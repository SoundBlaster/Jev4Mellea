"""Optional, potentially billable smoke test. Never runs just because a key exists."""
import os

import pytest

from mellea_jev import JevClient, JevVerifier


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
