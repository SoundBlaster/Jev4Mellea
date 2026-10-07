"""Opt-in Decisions smoke test; keys alone never enable a paid request."""

import os

import pytest

from mellea_jev import JevVerifier, OpenAIProvider


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_OPENAI") != "1" or not os.environ.get("OPENAI_API_KEY"),
    reason="Requires OPENAI_API_KEY and explicit RUN_LIVE_OPENAI=1 (billable).",
)
def test_live_openai_noul_contract():
    with OpenAIProvider() as provider:
        verdict = JevVerifier(provider, "The candidate is a greeting.").evaluate("Hello!")
    assert verdict.p_yes is not None and 0 <= verdict.p_yes <= 1
    assert verdict.model
    assert verdict.request_id
