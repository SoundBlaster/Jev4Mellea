"""Decisions SDK requests through a local transport; no paid calls."""

import json
import subprocess
import sys
import traceback

import httpx2
import pytest

from mellea_jev import (
    JevVerifier,
    NoulProvider,
    NoulResult,
    OpenAIHTTPError,
    OpenAIProtocolError,
    OpenAIProvider,
    OpenAIProviderError,
    OpenAIRefusalError,
    UsageMetadata,
)


def wire(p=0.98):
    return {
        "model": "gpt-6-luna",
        "answers": [{"type": "predicate", "name": "requirement", "probability": p}],
        "usage": {
            "input_tokens": 42,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 42,
        },
    }


def test_sdk_request_metadata_and_provider_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.example")
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.openai.com/v1/decisions"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "gpt-6-luna",
            "input": '{"candidate": "Привет", "reference": "Hello"}',
            "questions": [
                {"type": "predicate", "name": "requirement", "instructions": "Greeting?"}
            ],
        }
        return httpx2.Response(200, json=wire(), headers={"x-request-id": "request-fixture"})

    with OpenAIProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: NoulProvider = client
        result = provider.noul(
            state={"candidate": "Привет", "reference": "Hello"}, question="Greeting?"
        )
    assert result == NoulResult(0.98, "gpt-6-luna", "request-fixture", UsageMetadata(42, 0))
    assert len(requests) == 1


def test_outcome_criteria_are_explicit_instruction_data():
    criteria = {"true": {"examples": ["ASAP"]}, "false": ["No time pressure", None]}

    def handler(request):
        question = json.loads(request.content)["questions"][0]
        assert question["instructions"] == (
            "Urgent?\n\nOutcome criteria (JSON; true means the condition holds):\n"
            '{"true": {"examples": ["ASAP"]}, "false": ["No time pressure", null]}'
        )
        assert "criteria" not in question
        return httpx2.Response(200, json=wire())

    with OpenAIProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        assert client.noul(state={}, question="Urgent?", criteria=criteria).p_yes == 0.98


@pytest.mark.parametrize("p,outcome", [(0, "fail"), (0.5, "uncertain"), (1, "pass")])
def test_verifier_outcomes(p, outcome):
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire(p)))
    ) as client:
        assert JevVerifier(client, "Greeting?").evaluate("Hello").outcome == outcome


@pytest.mark.parametrize("p", [True, False, "0.99", None, -0.1, 1.1])
def test_strict_wire_probability(p):
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire(p)))
    ) as client:
        with pytest.raises(OpenAIProtocolError):
            client.noul(state={}, question="Valid?")


@pytest.mark.parametrize(
    "change",
    [
        {"answers": []},
        {"answers": [wire()["answers"][0]] * 2},
        {"answers": [{"type": "predicate", "name": "wrong", "probability": 1}]},
        {"answers": [{"type": "predicate", "probability": 1}]},
        {"answers": [{"type": "predicate", "name": "requirement"}]},
        {"answers": [{"type": "unknown", "name": "requirement", "probability": 1}]},
        {
            "answers": [
                {
                    "type": "choice",
                    "name": "requirement",
                    "choice": "a",
                    "confidence": 1,
                    "probabilities": [{"value": "a", "probability": 1}],
                }
            ]
        },
        {"model": ""},
        {"model": 1},
        {"usage": None},
        {"usage": {**wire()["usage"], "input_tokens": True}},
        {"usage": {**wire()["usage"], "output_tokens": -1}},
    ],
)
def test_invalid_response_rejected(change):
    body = {**wire(), **change}
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(OpenAIProtocolError):
            client.noul(state={}, question="Valid?")


@pytest.mark.parametrize("content", [b"not JSON", b"null", b"[]", b"{}"])
def test_invalid_envelope(content):
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=content))
    ) as client:
        with pytest.raises(OpenAIProtocolError):
            client.noul(state={}, question="Valid?")


def test_nonfinite_probability():
    content = json.dumps(wire()).replace('"probability": 0.98', '"probability": NaN').encode()
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=content))
    ) as client:
        with pytest.raises(OpenAIProtocolError):
            client.noul(state={}, question="Valid?")


def test_refusal_is_an_explicit_failure():
    body = {**wire(), "answers": [{"type": "refusal", "name": "requirement"}]}
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(OpenAIRefusalError):
            JevVerifier(client, "Valid?").evaluate("candidate")


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_errors_are_safe_no_retries_or_redirects(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            status,
            json={"error": {"message": "secret-body test-key"}},
            headers={"location": "https://untrusted.example", "x-should-retry": "true"},
        )

    with OpenAIProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(OpenAIHTTPError) as captured:
            client.noul(state={}, question="Valid?")
    assert captured.value.status_code == status
    error_text = "".join(traceback.format_exception(captured.value))
    assert "secret-body" not in error_text and "test-key" not in error_text
    assert captured.value.__suppress_context__
    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_transport_failure_is_safe_and_not_retried(error):
    requests = []

    def handler(request):
        requests.append(request)
        raise error("secret-body test-key", request=request)

    with OpenAIProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(OpenAIProviderError) as captured:
            client.noul(state={}, question="Valid?")
    assert "secret-body" not in str(captured.value) and "test-key" not in str(captured.value)
    assert captured.value.__suppress_context__
    assert len(requests) == 1


def test_sdk_error_is_safe(monkeypatch):
    from openai import OpenAIError

    def fail(**kwargs):
        raise OpenAIError("secret-body test-key")

    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as client:
        monkeypatch.setattr(client._client.decisions.with_raw_response, "create", fail)
        with pytest.raises(OpenAIProviderError, match="SDK failed") as captured:
            client.noul(state={}, question="Valid?")
    assert "test-key" not in str(captured.value)


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"state": [], "question": "Valid?"}, TypeError),
        ({"state": {}, "question": " "}, ValueError),
        ({"state": {}, "question": True}, ValueError),
        ({"state": {1: "text"}, "question": "Valid?"}, TypeError),
        ({"state": {"value": float("nan")}, "question": "Valid?"}, ValueError),
        ({"state": {"value": object()}, "question": "Valid?"}, TypeError),
        ({"state": {}, "question": "Valid?", "criteria": {"yes": "Invalid"}}, ValueError),
        ({"state": {}, "question": "Valid?", "criteria": {"true": 3}}, TypeError),
    ],
)
def test_invalid_inputs_never_send_a_request(kwargs, error):
    with OpenAIProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as client:
        with pytest.raises(error):
            client.noul(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": ""},
        {"api_key": " "},
        {"api_key": "bad key"},
        {"api_key": "ключ"},
        {"api_key": 1},
        {"api_key": "test", "model": " "},
        {"api_key": "test", "timeout": True},
        {"api_key": "test", "timeout": 0},
        {"api_key": "test", "timeout": float("inf")},
    ],
)
def test_constructor_validation(kwargs):
    with pytest.raises(ValueError):
        OpenAIProvider(**kwargs)


def test_environment_key_and_transport_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    options = []
    original = httpx2.Client

    class SpyClient(original):
        def __init__(self, **kwargs):
            options.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx2, "Client", SpyClient)
    with OpenAIProvider(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire()))
    ) as client:
        assert client._client.api_key == "env-key"
        assert client._client.max_retries == 0
        assert client.noul(state={}, question="Valid?").request_id is None
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert client._client.is_closed()


def test_missing_environment_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider()


def test_optional_sdk_import_and_actionable_install_error():
    code = """
import builtins
original = builtins.__import__
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name.split('.')[0] == 'openai':
        raise ImportError('blocked optional SDK')
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = guarded
from mellea_jev import OpenAIProvider, OpenAIProviderError
try:
    OpenAIProvider('test-key')
except OpenAIProviderError as exc:
    assert 'mellea-jev-adapter[openai]' in str(exc)
else:
    raise AssertionError('SDK dependency should be required only at construction')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_constructor_sdk_failure_closes_transport(monkeypatch):
    import openai

    closed = []

    class TrackingTransport(httpx2.MockTransport):
        def close(self):
            closed.append(True)

    def fail(**kwargs):
        raise openai.OpenAIError("secret-body test-key")

    monkeypatch.setattr(openai, "OpenAI", fail)
    with pytest.raises(OpenAIProviderError, match="initialization failed"):
        OpenAIProvider("test-key", transport=TrackingTransport(lambda _: pytest.fail()))
    assert closed == [True]
