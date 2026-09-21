import json

import httpx2
import pytest

from mellea_jev import JevClient, JevProtocolError, ScoreResult
from mellea_jev.client import ENDPOINT

LEVELS = ["Cosmetic", "Workaround exists", "Blocking"]


def score_wire(*, score=0.7, confidence=0.6, probabilities=None, legend=None):
    return {
        "model": "jev-score-fixture",
        "answers": {
            "rating": {
                "type": "score",
                "score": score,
                "confidence": confidence,
                "probabilities": probabilities or {"0": 0.5, "1": 0.3, "2": 0.2},
                "legend": legend or {"0": LEVELS[0], "1": LEVELS[1], "2": LEVELS[2]},
            }
        },
    }


def test_score_serializes_ordered_levels_and_parses_weighted_result():
    def handler(request):
        assert request.url == httpx2.URL(ENDPOINT)
        assert json.loads(request.content) == {
            "model": "jev-latest",
            "state": {"candidate": "The export button crashes in Safari."},
            "questions": {
                "rating": {
                    "type": "score",
                    "instructions": "How severe is the bug?",
                    "criteria": LEVELS,
                }
            },
        }
        return httpx2.Response(
            200, json=score_wire(), headers={"x-typesafe-request-id": "score-42"}
        )

    with JevClient("test-key", transport=httpx2.MockTransport(handler)) as client:
        result = client.score(
            state={"candidate": "The export button crashes in Safari."},
            question="How severe is the bug?",
            criteria=LEVELS,
        )

    assert result == ScoreResult(
        0.7,
        0.6,
        {0: 0.5, 1: 0.3, 2: 0.2},
        {0: "Cosmetic", 1: "Workaround exists", 2: "Blocking"},
        "jev-score-fixture",
        "score-42",
    )


@pytest.mark.parametrize(
    "criteria,error",
    [
        ("not an ordered list", TypeError),
        (["only one level"], ValueError),
        (["", "blocking"], ValueError),
        ([f"level {i}" for i in range(11)], ValueError),
    ],
)
def test_invalid_score_criteria(criteria, error):
    with JevClient(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(500))
    ) as client:
        with pytest.raises(error):
            client.score(state={}, question="Rate severity.", criteria=criteria)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"model": "jev", "answers": {"rating": {"type": "choice"}}},
        score_wire(score=0.5),
        score_wire(probabilities={"0": 0.5, "1": 0.3, "2": 0.1}),
        score_wire(probabilities={"0": 1.0, "1": 0.0, "2": 0.0}, score=0.5),
        score_wire(legend={"0": "Cosmetic", "1": "Changed", "2": "Blocking"}),
        score_wire(confidence=True),
        score_wire(score=float("nan")),
    ],
)
def test_malformed_score_response_fails_closed(body):
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            content=json.dumps(body, allow_nan=True).encode(),
            headers={"content-type": "application/json"},
        )
    )
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(JevProtocolError):
            client.score(state={"candidate": "text"}, question="Rate.", criteria=LEVELS)


def test_integer_equivalent_wire_keys_fail_before_conversion():
    body = score_wire(
        score=0.5,
        probabilities={"0": 2, "00": 0.5, "1": 0.5},
        legend={"0": "Low", "1": "High"},
    )
    transport = httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(JevProtocolError):
            client.score(
                state={"candidate": "text"},
                question="Rate.",
                criteria=["Low", "High"],
            )
