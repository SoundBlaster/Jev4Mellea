import json

import httpx2
import pytest

from mellea_jev import (
    ChoiceResult,
    JevClassifier,
    JevClient,
    JevProtocolError,
    TypeSafeUsage,
)
from mellea_jev.client import ENDPOINT

CRITERIA = {
    "billing": "Questions about payments, invoices, or refunds.",
    "technical": "Errors or problems using the product.",
    "other": "Anything that fits neither category.",
}


def choice_wire(choice="billing", probabilities=None):
    return {
        "model": "jev-choice-fixture",
        "answers": {
            "classification": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.8,
                "probabilities": probabilities
                or {
                    "billing": 0.8,
                    "technical": 0.1,
                    "other": 0.1,
                },
            }
        },
        "usage": {"input_tokens": 30, "output_tokens": 5},
    }


def test_choice_serializes_schema_and_parses_selected_class():
    def handler(request):
        assert request.url == httpx2.URL(ENDPOINT)
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "jev-latest",
            "state": {"candidate": "I was charged twice."},
            "questions": {
                "classification": {
                    "type": "choice",
                    "instructions": "Choose the support category.",
                    "criteria": CRITERIA,
                }
            },
        }
        return httpx2.Response(
            200, json=choice_wire(), headers={"x-typesafe-request-id": "choice-42"}
        )

    with JevClient("test-key", transport=httpx2.MockTransport(handler)) as client:
        result = client.choice(
            state={"candidate": "I was charged twice."},
            question="Choose the support category.",
            criteria=CRITERIA,
        )

    assert result == ChoiceResult(
        "billing",
        0.8,
        {"billing": 0.8, "technical": 0.1, "other": 0.1},
        "jev-choice-fixture",
        "choice-42",
        TypeSafeUsage(30, 5),
    )


def test_choice_serializes_structured_json_descriptions():
    criteria = {
        "billing": {
            "what": "Payment issues",
            "not_for": "Product defects",
            "examples": ["duplicate charge", {"kind": "refund", "active": True}],
        },
        "technical": ["Errors", "Product usage problems"],
        "other": None,
    }

    def handler(request):
        payload = json.loads(request.content)
        assert payload["questions"]["classification"]["criteria"] == criteria
        return httpx2.Response(200, json=choice_wire())

    with JevClient("test-key", transport=httpx2.MockTransport(handler)) as client:
        result = client.choice(
            state={"candidate": "I was charged twice."},
            question="Choose a support category.",
            criteria=criteria,
        )

    assert result.choice == "billing"


@pytest.mark.parametrize(
    "criteria,error",
    [
        ({"billing": b"not JSON"}, TypeError),
        ({"billing": {1: "non-string object key"}}, TypeError),
        ({"billing": {"confidence": float("nan")}}, ValueError),
        ({"billing": ["valid", {"invalid": {"set"}}]}, TypeError),
    ],
)
def test_invalid_nested_choice_criteria(criteria, error):
    with JevClient(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(500))
    ) as client:
        with pytest.raises(error):
            client.choice(state={}, question="Classify.", criteria=criteria)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"model": "jev", "answers": {"classification": {"type": "noul", "noul": 0.9}}},
        {"model": "jev", "answers": {"classification": {"type": "choice", "choice": "billing"}}},
        choice_wire(choice="unknown"),
        choice_wire(probabilities={"billing": 0.8, "unknown": 0.2}),
        choice_wire(probabilities={"billing": 0.8, "technical": 0.8, "other": 0.1}),
        choice_wire(probabilities={"billing": float("nan"), "technical": 0.0, "other": 0.0}),
    ],
)
def test_malformed_choice_response_fails_closed(body):
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            content=json.dumps(body, allow_nan=True).encode(),
            headers={"content-type": "application/json"},
        )
    )
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(JevProtocolError):
            client.choice(state={"candidate": "text"}, question="Classify.", criteria=CRITERIA)


@pytest.mark.parametrize(
    "criteria,error",
    [
        ({}, ValueError),
        ({" ": "empty label"}, ValueError),
        ({"billing": 3}, TypeError),
        ({"billing": " "}, ValueError),
    ],
)
def test_invalid_choice_criteria(criteria, error):
    with JevClient(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(500))
    ) as client:
        with pytest.raises(error):
            client.choice(state={}, question="Classify.", criteria=criteria)


def test_choice_supports_at_most_255_options():
    options = {f"class_{index}": None for index in range(256)}
    with JevClient(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(500))
    ) as client:
        with pytest.raises(ValueError, match="255"):
            client.choice(state={}, question="Classify.", criteria=options)


def test_classifier_sends_candidate_reference_and_returns_choice():
    class Client:
        def choice(self, **kwargs):
            assert kwargs == {
                "state": {"candidate": "I was charged twice.", "reference": "Support ticket"},
                "question": "Choose the support category.",
                "criteria": CRITERIA,
            }
            return ChoiceResult(
                "billing",
                0.8,
                {"billing": 0.8, "technical": 0.1, "other": 0.1},
                "jev-fixture",
            )

    classifier = JevClassifier(Client(), "Choose the support category.", criteria=CRITERIA)
    result = classifier.classify("I was charged twice.", reference="Support ticket")
    assert result.choice == "billing"
    assert result.probabilities["billing"] == 0.8


def test_classifier_rejects_empty_candidate_without_calling_client():
    class Client:
        def choice(self, **_):
            pytest.fail("The API must not be called for empty candidate text.")

    classifier = JevClassifier(Client(), "Choose a category.", criteria=CRITERIA)
    with pytest.raises(ValueError, match="nonempty"):
        classifier.classify("  ")
