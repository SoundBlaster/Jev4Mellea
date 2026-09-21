"""Real Mellea Requirement.validate hook, fake context, mocked Jev HTTP.

No generator and no paid calls. This is a bridge integration test, NOT an
end-to-end Mellea generation/repair test. Missing Mellea skips this module.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest

pytest.importorskip("mellea", reason="Install .[mellea,dev] to test the real bridge.")
from mellea.core import Context, Requirement, ValidationResult

from mellea_jev import JevClassifier, JevClient, JevScorer, JevVerifier, ReviewRequired

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("p,expected", [(0.98, True), (0.02, False), (0.5, None)])
def test_real_requirement_validate_hook(p, expected):
    context = Mock(spec=Context)
    context.last_output.return_value = SimpleNamespace(value="Hello")
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            json={
                "model": "jev-integration-fixture",
                "answers": {"requirement": {"type": "noul", "noul": p}},
                "usage": {"input_tokens": 20, "output_tokens": 2},
            },
        )
    )
    with JevClient("test", transport=transport) as client:
        req = JevVerifier(client, "The answer is polite.").as_requirement()
        assert isinstance(req, Requirement)
        if expected is None:
            with pytest.raises(ReviewRequired):
                asyncio.run(req.validate(backend=None, ctx=context))
        else:
            result = asyncio.run(req.validate(backend=None, ctx=context))
            assert isinstance(result, ValidationResult)
            assert bool(result) is expected
            assert result.score == p


@pytest.mark.parametrize("choice,expected", [("billing", True), ("technical", False)])
def test_real_choice_requirement_validate_hook(choice, expected):
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            json={
                "model": "jev-choice-integration-fixture",
                "answers": {
                    "classification": {
                        "type": "choice",
                        "choice": choice,
                        "confidence": 0.8,
                        "probabilities": {"billing": 0.8, "technical": 0.2}
                        if choice == "billing"
                        else {"billing": 0.2, "technical": 0.8},
                    }
                },
            },
        )
    )
    with JevClient("test", transport=transport) as client:
        classifier = JevClassifier(
            client,
            "Classify the customer request.",
            criteria={"billing": "Payments and refunds", "technical": "Product errors"},
        )
        req = classifier.as_requirement("billing")
        ctx = Mock(spec=Context)
        ctx.last_output.return_value = SimpleNamespace(value="I was charged twice.")
        result = asyncio.run(req.validate(backend=None, ctx=ctx))
    assert isinstance(req, Requirement)
    assert isinstance(result, ValidationResult)
    assert bool(result) is expected
    assert result.score == (0.8 if choice == "billing" else 0.2)


@pytest.mark.parametrize("score,expected", [(0.7, True), (1.5, False)])
def test_real_score_requirement_validate_hook(score, expected):
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200,
            json={
                "model": "jev-score-integration-fixture",
                "answers": {
                    "rating": {
                        "type": "score",
                        "score": score,
                        "confidence": 0.8,
                        "probabilities": {"0": 0.5, "1": 0.3, "2": 0.2}
                        if score == 0.7
                        else {"0": 0.0, "1": 0.5, "2": 0.5},
                        "legend": {"0": "Low", "1": "Medium", "2": "High"},
                    }
                },
            },
        )
    )
    with JevClient("test", transport=transport) as client:
        scorer = JevScorer(
            client,
            "How severe is the issue?",
            criteria=["Low", "Medium", "High"],
        )
        req = scorer.as_requirement(maximum_score=1.0, minimum_confidence=0.7)
        context = Mock(spec=Context)
        context.last_output.return_value = SimpleNamespace(value="The button fails.")
        result = asyncio.run(req.validate(backend=None, ctx=context))
    assert isinstance(req, Requirement)
    assert isinstance(result, ValidationResult)
    assert bool(result) is expected
    assert result.score == score
