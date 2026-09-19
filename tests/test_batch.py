import json

import httpx
import pytest

from mellea_jev import (
    ChoiceQuestion,
    ChoiceResult,
    JevClient,
    JevProtocolError,
    NoulQuestion,
    NoulResult,
    ScoreQuestion,
    ScoreResult,
)
from mellea_jev.client import ENDPOINT


def test_system_one_sends_mixed_questions_in_one_request():
    calls = []
    questions = {
        "urgent": NoulQuestion("Is this urgent?"),
        "team": ChoiceQuestion(
            "Which team owns this?",
            {"support": "Customer help", "engineering": "Product issues"},
        ),
        "severity": ScoreQuestion(
            "Rate the impact.", ["Cosmetic", "Workaround exists", "Blocking"]
        ),
    }

    def handler(request):
        calls.append(request)
        assert request.url == httpx.URL(ENDPOINT)
        assert json.loads(request.content) == {
            "model": "jev-latest",
            "state": {"candidate": "The outage blocks all users."},
            "questions": {
                "urgent": {"type": "noul", "instructions": "Is this urgent?"},
                "team": {
                    "type": "choice",
                    "instructions": "Which team owns this?",
                    "criteria": {"support": "Customer help", "engineering": "Product issues"},
                },
                "severity": {
                    "type": "score",
                    "instructions": "Rate the impact.",
                    "criteria": ["Cosmetic", "Workaround exists", "Blocking"],
                },
            },
        }
        return httpx.Response(200, json={
            "model": "jev-batch-fixture",
            "answers": {
                "urgent": {"type": "noul", "noul": 0.9},
                "team": {
                    "type": "choice",
                    "choice": "engineering",
                    "confidence": 0.8,
                    "probabilities": {"support": 0.2, "engineering": 0.8},
                },
                "severity": {
                    "type": "score",
                    "score": 1.5,
                    "confidence": 0.6,
                    "probabilities": {"0": 0.0, "1": 0.5, "2": 0.5},
                    "legend": {"0": "Cosmetic", "1": "Workaround exists", "2": "Blocking"},
                },
            },
        }, headers={"x-typesafe-request-id": "batch-1"})

    with JevClient("test-key", transport=httpx.MockTransport(handler)) as client:
        result = client.system_one(
            state={"candidate": "The outage blocks all users."}, questions=questions
        )

    assert len(calls) == 1
    assert result.model == "jev-batch-fixture"
    assert result.request_id == "batch-1"
    assert isinstance(result.answers["urgent"], NoulResult)
    assert result.answers["urgent"].p_yes == 0.9
    assert isinstance(result.answers["team"], ChoiceResult)
    assert result.answers["team"].choice == "engineering"
    assert isinstance(result.answers["severity"], ScoreResult)
    assert result.answers["severity"].score == 1.5
    assert all(answer.request_id == "batch-1" for answer in result.answers.values())


def test_system_one_rejects_missing_answers():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "model": "jev",
        "answers": {"first": {"type": "noul", "noul": 0.9}},
    }))
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(JevProtocolError):
            client.system_one(
                state={},
                questions={
                    "first": NoulQuestion("First?"),
                    "second": NoulQuestion("Second?"),
                },
            )


@pytest.mark.parametrize("questions,error", [
    ({}, ValueError),
    ({" ": NoulQuestion("Question?")}, ValueError),
    ({"unknown": object()}, TypeError),
])
def test_system_one_validates_question_collection_before_request(questions, error):
    transport = httpx.MockTransport(lambda _: pytest.fail("Must reject before HTTP."))
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(error):
            client.system_one(state={}, questions=questions)


def test_question_types_validate_and_copy_criteria():
    choice_criteria = {"billing": "Payments", "other": None}
    choice = ChoiceQuestion("Choose a class.", choice_criteria)
    choice_criteria["later"] = "Should not mutate the question"
    assert "later" not in choice.criteria

    score_levels = ["low", "high"]
    score = ScoreQuestion("Rate it.", score_levels)
    score_levels[0] = "mutated"
    assert score.criteria == ("low", "high")

    with pytest.raises(ValueError):
        NoulQuestion(" ")
