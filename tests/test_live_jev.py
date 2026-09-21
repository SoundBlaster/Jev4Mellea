"""Optional, potentially billable smoke tests. Never run just because a key exists."""

import os

import pytest

from mellea_jev import JevClassifier, JevClient, JevVerifier


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_JEV") != "1" or not os.environ.get("TYPESAFE_API_KEY"),
    reason="Requires TYPESAFE_API_KEY and explicit RUN_LIVE_JEV=1 (billable).",
)
def test_live_noul_contract():
    with JevClient(model=os.environ.get("JEV_MODEL", "jev-latest")) as client:
        verdict = JevVerifier(client, "The candidate is a greeting.").evaluate("Hello!")
    assert verdict.p_yes is not None and 0 <= verdict.p_yes <= 1
    assert verdict.model
    # No flaky assertion that the model MUST pick a particular outcome.


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_JEV") != "1" or not os.environ.get("TYPESAFE_API_KEY"),
    reason="Requires TYPESAFE_API_KEY and explicit RUN_LIVE_JEV=1 (billable).",
)
def test_live_choice_contract():
    criteria = {
        "billing": "Payments, invoices, or refunds",
        "technical": "Product errors or usage problems",
        "other": "Anything outside the other categories",
    }
    with JevClient(model=os.environ.get("JEV_MODEL", "jev-latest")) as client:
        result = JevClassifier(
            client,
            "Choose the support category for the candidate.",
            criteria=criteria,
        ).classify("I was charged twice for my subscription.")
    assert result.choice in criteria
    assert set(result.probabilities) == set(criteria)
    assert 0 <= result.confidence <= 1
