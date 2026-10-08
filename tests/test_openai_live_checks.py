"""Exercise the live smoke checks offline, including their opt-in guard."""

import json
import os
import subprocess
import sys

import httpx2
import pytest
import test_live_openai as live_checks
from test_openai_provider import wire

from mellea_jev import OpenAIProvider


@pytest.mark.parametrize(
    "check_name,primitive",
    [
        ("test_live_openai_noul_contract", "predicate"),
        ("test_live_openai_choice_contract", "choice"),
        ("test_live_openai_score_contract", "score"),
    ],
)
def test_live_check_body_uses_one_mocked_sdk_request(monkeypatch, check_name, primitive):
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.openai.com/v1/decisions"
        assert request.headers["authorization"] == "Bearer mock-key"
        payload = json.loads(request.content)
        question = payload["questions"][0]
        assert question["type"] == primitive
        body = wire()
        if primitive == "choice":
            labels = [choice["value"] for choice in question["choices"]]
            body["answers"] = [
                {
                    "type": "choice",
                    "name": question["name"],
                    "choice": labels[0],
                    "confidence": 0.8,
                    "probabilities": [
                        {"value": label, "probability": 1 / len(labels)} for label in labels
                    ],
                }
            ]
        elif primitive == "score":
            labels = [level["label"] for level in question["levels"]]
            body["answers"] = [
                {
                    "type": "score",
                    "name": question["name"],
                    "score": (len(labels) - 1) / 2,
                    "confidence": 0.8,
                    "probabilities": [
                        {"value": index, "label": label, "probability": 1 / len(labels)}
                        for index, label in enumerate(labels)
                    ],
                }
            ]
        return httpx2.Response(200, json=body, headers={"x-request-id": "mock-request-id"})

    monkeypatch.setattr(
        live_checks,
        "OpenAIProvider",
        lambda: OpenAIProvider("mock-key", transport=httpx2.MockTransport(handler)),
    )
    # Invoke the same function body used by live pytest, with a mock transport.
    getattr(live_checks, check_name)()
    assert len(requests) == 1


@pytest.mark.parametrize(
    "key_present,opt_in", [(False, False), (True, False), (False, True), (True, True)]
)
def test_live_checks_require_both_key_and_opt_in(key_present, opt_in):
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("RUN_LIVE_OPENAI", None)
    if key_present:
        environment["OPENAI_API_KEY"] = "mock-key"
    if opt_in:
        environment["RUN_LIVE_OPENAI"] = "1"
    code = """
import mellea_jev
import pytest

# Even a broken opt-in guard cannot contact a real endpoint in this regression test.
mellea_jev.OpenAIProvider = lambda: pytest.fail("Provider must not be constructed")
raise SystemExit(pytest.main(["-q", "--override-ini", "addopts=", "tests/test_live_openai.py"]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], env=environment, capture_output=True, text=True, timeout=30
    )
    if key_present and opt_in:
        # Both flags enable all three bodies; the deliberate constructor failure
        # proves they ran while still preventing any external request.
        assert result.returncode == 1, result.stdout + result.stderr
        assert "3 failed" in result.stdout
        assert "Provider must not be constructed" in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "3 skipped" in result.stdout
