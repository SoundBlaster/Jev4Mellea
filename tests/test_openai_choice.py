import json
import traceback

import httpx2
import pytest
from test_openai_provider import wire

from mellea_jev import (
    ChoiceProvider,
    ChoiceResult,
    JevClassifier,
    OpenAIHTTPError,
    OpenAIProtocolError,
    OpenAIProvider,
    OpenAIRefusalError,
    UsageMetadata,
)


def choice_wire(**changes):
    answer = {
        "type": "choice",
        "name": "classification",
        "choice": "billing",
        "confidence": 0.93,
        "probabilities": [
            {"value": "billing", "probability": 0.95},
            {"value": "technical", "probability": 0.05},
        ],
        **changes,
    }
    return {**wire(), "answers": [answer]}


def test_choice_sdk_payload_metadata_and_classifier():
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://proxy.example/core/openai/v1/decisions"
        assert json.loads(request.content) == {
            "model": "gpt-6-luna",
            "input": '{"candidate": "Charged twice", "reference": "Refund duplicate charges"}',
            "questions": [
                {
                    "type": "choice",
                    "name": "classification",
                    "instructions": "Which team?",
                    "choices": [
                        {"value": "billing", "description": "Payments"},
                        {"value": "technical"},
                    ],
                }
            ],
        }
        return httpx2.Response(200, json=choice_wire(), headers={"x-request-id": "choice-42"})

    with OpenAIProvider(
        "test-key",
        base_url="https://proxy.example/core/openai/v1/",
        transport=httpx2.MockTransport(handler),
    ) as client:
        provider: ChoiceProvider = client
        result = JevClassifier(
            provider,
            "Which team?",
            criteria={"billing": "Payments", "technical": None},
        ).classify("Charged twice", reference="Refund duplicate charges")
    assert result == ChoiceResult(
        "billing",
        0.93,
        {"billing": 0.95, "technical": 0.05},
        "gpt-6-luna",
        "choice-42",
        UsageMetadata(42, 0),
    )
    assert len(requests) == 1


def test_structured_choice_descriptions_are_json_text():
    def handler(request):
        choices = json.loads(request.content)["questions"][0]["choices"]
        assert choices == [
            {"value": "billing", "description": '{"examples": ["Refund", "Счёт"]}'},
            {"value": "technical", "description": '["Crashes", null]'},
        ]
        return httpx2.Response(200, json=choice_wire())

    with OpenAIProvider("test", transport=httpx2.MockTransport(handler)) as client:
        client.choice(
            state={},
            question="Which team?",
            criteria={"billing": {"examples": ["Refund", "Счёт"]}, "technical": ["Crashes", None]},
        )


@pytest.mark.parametrize(
    "change",
    [
        {"choice": True},
        {"choice": "unknown"},
        {"choice": "technical"},
        {"confidence": True},
        {"confidence": "0.9"},
        {"confidence": -1},
        {"confidence": 1.1},
        {"name": "wrong"},
        {"probabilities": []},
        {"probabilities": [{"value": "billing", "probability": 1}]},
        {"probabilities": [{"value": "billing", "probability": 0.5}] * 2},
        {
            "probabilities": [
                {"value": True, "probability": 0.5},
                {"value": "technical", "probability": 0.5},
            ]
        },
        {
            "probabilities": [
                {"value": "unknown", "probability": 0.5},
                {"value": "technical", "probability": 0.5},
            ]
        },
        {
            "probabilities": [
                {"value": "billing", "probability": 0.5},
                {"value": "technical", "probability": 0.1},
            ]
        },
        {
            "probabilities": [
                {"value": "billing", "probability": True},
                {"value": "technical", "probability": 0},
            ]
        },
        {
            "probabilities": [
                {"value": "billing", "probability": "0.95"},
                {"value": "technical", "probability": 0.05},
            ]
        },
        {
            "probabilities": [
                {"value": "billing", "probability": -0.1},
                {"value": "technical", "probability": 1.1},
            ]
        },
    ],
)
def test_choice_invalid_response_is_safe(change):
    with OpenAIProvider(
        "secret-key",
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=choice_wire(**change))),
    ) as client:
        with pytest.raises(OpenAIProtocolError) as captured:
            client.choice(
                state={}, question="Which team?", criteria={"billing": None, "technical": None}
            )
    assert "secret-key" not in "".join(traceback.format_exception(captured.value))


def test_choice_refusal_does_not_become_classification():
    body = {**wire(), "answers": [{"type": "refusal", "name": "classification"}]}
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(OpenAIRefusalError):
            client.choice(state={}, question="Which team?", criteria={"billing": None})


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_choice_http_errors_no_retries_or_redirects(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            status, text="secret-body secret-key", headers={"location": "https://other.example"}
        )

    with OpenAIProvider("secret-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(OpenAIHTTPError) as captured:
            client.choice(state={}, question="Which team?", criteria={"billing": None})
    assert len(calls) == 1
    assert "secret" not in "".join(traceback.format_exception(captured.value))


@pytest.mark.parametrize(
    "criteria,error", [({}, ValueError), ({" ": None}, ValueError), ({"billing": 3}, TypeError)]
)
def test_invalid_criteria_fail_before_http(criteria, error):
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: pytest.fail("No request expected"))
    ) as client:
        with pytest.raises(error):
            client.choice(state={}, question="Which team?", criteria=criteria)
