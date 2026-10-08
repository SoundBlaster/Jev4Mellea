import copy
import json
import traceback

import httpx2
import pytest
from test_openai_provider import wire

from mellea_jev import (
    JevScorer,
    OpenAIHTTPError,
    OpenAIProtocolError,
    OpenAIProvider,
    OpenAIRefusalError,
    PrimitiveProvider,
    ScoreProvider,
    ScoreResult,
    UsageMetadata,
)

RUBRIC = ["Low", "Medium", "High"]


def score_wire(**changes):
    return {
        **wire(),
        "answers": [
            {
                "type": "score",
                "name": "rating",
                "score": 0.7,
                "confidence": 0.8,
                "probabilities": [
                    {"value": 0, "label": "Low", "probability": 0.5},
                    {"value": 1, "label": "Medium", "probability": 0.3},
                    {"value": 2, "label": "High", "probability": 0.2},
                ],
                **changes,
            }
        ],
    }


def test_score_sdk_payload_metadata_and_scorer():
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://proxy.example/nested/v1/decisions"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "gpt-6-luna",
            "input": '{"candidate": "A minor issue", "reference": "Severity rubric"}',
            "questions": [
                {
                    "type": "score",
                    "name": "rating",
                    "instructions": "Rate severity.",
                    "levels": [{"label": description} for description in RUBRIC],
                }
            ],
        }
        return httpx2.Response(200, json=score_wire(), headers={"x-request-id": "score-42"})

    with OpenAIProvider(
        "test-key",
        base_url="https://proxy.example/nested/v1",
        transport=httpx2.MockTransport(handler),
    ) as client:
        provider: ScoreProvider = client
        complete_provider: PrimitiveProvider = client
        assert complete_provider is provider
        result = JevScorer(provider, "Rate severity.", criteria=RUBRIC).evaluate(
            "A minor issue", reference="Severity rubric"
        )
    assert result == ScoreResult(
        0.7,
        0.8,
        {0: 0.5, 1: 0.3, 2: 0.2},
        dict(enumerate(RUBRIC)),
        "gpt-6-luna",
        "score-42",
        UsageMetadata(42, 0),
    )
    assert len(requests) == 1


def test_score_distribution_order_is_irrelevant():
    entries = list(reversed(score_wire()["answers"][0]["probabilities"]))
    with OpenAIProvider(
        "test",
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(200, json=score_wire(probabilities=entries))
        ),
    ) as client:
        result = client.score(state={}, question="Rate severity.", criteria=RUBRIC)
    assert result.legend == dict(enumerate(RUBRIC))
    assert result.score == 0.7


@pytest.mark.parametrize(
    "change",
    [
        {"score": True},
        {"score": "0.7"},
        {"score": -0.1},
        {"score": 2.1},
        {"score": 1.0},
        {"confidence": True},
        {"confidence": "0.8"},
        {"confidence": 1.1},
        {"name": "wrong"},
        {"probabilities": []},
        {"probabilities": score_wire()["answers"][0]["probabilities"][:2]},
    ],
)
def test_invalid_score_response_is_safe(change):
    with OpenAIProvider(
        "secret-key",
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=score_wire(**change))),
    ) as client:
        with pytest.raises(OpenAIProtocolError) as captured:
            client.score(state={}, question="Rate severity.", criteria=RUBRIC)
    assert "secret-key" not in "".join(traceback.format_exception(captured.value))


@pytest.mark.parametrize(
    "entry_change",
    [
        {"value": True},
        {"value": "0"},
        {"value": -1},
        {"value": 3},
        {"value": 1},
        {"label": "Wrong"},
        {"label": True},
        {"probability": True},
        {"probability": "0.5"},
        {"probability": -0.1},
        {"probability": 1.1},
        {"probability": 0.4},
    ],
)
def test_invalid_score_level_is_rejected(entry_change):
    body = copy.deepcopy(score_wire())
    body["answers"][0]["probabilities"][0].update(entry_change)
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(OpenAIProtocolError):
            client.score(state={}, question="Rate severity.", criteria=RUBRIC)


def test_score_refusal_is_not_a_rating():
    body = {**wire(), "answers": [{"type": "refusal", "name": "rating"}]}
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(OpenAIRefusalError):
            client.score(state={}, question="Rate severity.", criteria=RUBRIC)


@pytest.mark.parametrize("status", [302, 429, 500])
def test_score_http_errors_no_retries_or_redirects(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            status, text="secret-key secret-body", headers={"location": "https://other.example"}
        )

    with OpenAIProvider("secret-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(OpenAIHTTPError) as captured:
            client.score(state={}, question="Rate severity.", criteria=RUBRIC)
    assert len(calls) == 1
    assert "secret" not in "".join(traceback.format_exception(captured.value))


@pytest.mark.parametrize(
    "criteria,error",
    [([], ValueError), (["Low"], ValueError), (["Low", " "], ValueError), ("Low", TypeError)],
)
def test_invalid_score_criteria_fail_before_http(criteria, error):
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: pytest.fail("No request expected"))
    ) as client:
        with pytest.raises(error):
            client.score(state={}, question="Rate severity.", criteria=criteria)
