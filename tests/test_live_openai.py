"""Opt-in Decisions smoke tests: one request per primitive, no accuracy claims."""

import os

import pytest

from mellea_jev import JevClassifier, JevScorer, JevVerifier, OpenAIProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_OPENAI") != "1" or not os.environ.get("OPENAI_API_KEY"),
        reason="Requires OPENAI_API_KEY and explicit RUN_LIVE_OPENAI=1 (billable).",
    ),
]


def test_live_openai_noul_contract():
    with OpenAIProvider() as provider:
        verdict = JevVerifier(provider, "The candidate is a greeting.").evaluate("Hello!")
    assert verdict.p_yes is not None and 0 <= verdict.p_yes <= 1
    assert verdict.model
    assert verdict.request_id


def test_live_openai_choice_contract():
    criteria = {
        "billing": "Payments, invoices, or refunds",
        "technical": "Product errors or usage problems",
        "other": "Anything outside the other categories",
    }
    with OpenAIProvider() as provider:
        result = JevClassifier(
            provider,
            "Choose the support category for the candidate.",
            criteria=criteria,
        ).classify("I was charged twice for my subscription.")
    assert result.choice in criteria
    assert set(result.probabilities) == set(criteria)
    assert all(0 <= p <= 1 for p in result.probabilities.values())
    assert sum(result.probabilities.values()) == pytest.approx(1, abs=1e-3)
    assert 0 <= result.confidence <= 1
    assert result.model
    assert result.request_id
    assert result.usage is not None
    assert result.usage.input_tokens is not None and result.usage.input_tokens >= 0
    assert result.usage.output_tokens is not None and result.usage.output_tokens >= 0


def test_live_openai_score_contract():
    criteria = [
        "Low: cosmetic issue; the product remains usable",
        "Medium: impaired functionality with a workaround",
        "High: core functionality is completely blocked",
    ]
    with OpenAIProvider() as provider:
        result = JevScorer(
            provider,
            "Rate the severity of the candidate issue using the ordered rubric.",
            criteria=criteria,
        ).evaluate("A button is slightly misaligned, but all actions still work.")
    assert 0 <= result.score <= len(criteria) - 1
    assert set(result.probabilities) == set(range(len(criteria)))
    assert result.legend == dict(enumerate(criteria))
    assert all(0 <= p <= 1 for p in result.probabilities.values())
    assert sum(result.probabilities.values()) == pytest.approx(1, abs=1e-3)
    expected_score = sum(level * p for level, p in result.probabilities.items())
    assert result.score == pytest.approx(expected_score, abs=0.02)
    assert 0 <= result.confidence <= 1
    assert result.model
    assert result.request_id
    assert result.usage is not None
    assert result.usage.input_tokens is not None and result.usage.input_tokens >= 0
    assert result.usage.output_tokens is not None and result.usage.output_tokens >= 0
