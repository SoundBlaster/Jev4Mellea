"""Exercise real HTTPX serialization/parsing with an in-process mock transport."""
import json

import httpx
import pytest

from mellea_jev import JevClient, JevError, JevHTTPError, JevProtocolError, NoulResult
from mellea_jev.client import ENDPOINT, probability


def wire(p=0.97):
    return {
        "model": "jev-test-fixture",
        "answers": {"requirement": {"type": "noul", "noul": p}},
        "usage": {"input_tokens": 50, "output_tokens": 2},
    }


def transport_for(body):
    return httpx.MockTransport(lambda _: httpx.Response(200, json=body))


def test_exact_request_and_response_contract():
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == ENDPOINT
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["content-type"].startswith("application/json")
        assert json.loads(request.content) == {
            "model": "jev-latest",
            "state": {"candidate": "Привет", "reference": "Hello"},
            "questions": {"requirement": {"type": "noul", "instructions": "Is it a greeting?"}},
        }
        return httpx.Response(200, json=wire(), headers={"x-typesafe-request-id": "fixture-42"})

    with JevClient("test-key", transport=httpx.MockTransport(handler)) as client:
        result = client.noul(
            state={"candidate": "Привет", "reference": "Hello"},
            question="Is it a greeting?",
        )
    assert result == NoulResult(0.97, "jev-test-fixture", "fixture-42")
    assert len(requests) == 1


def test_noul_serializes_optional_outcome_criteria():
    criteria = {
        "true": {"what": "Urgency is explicit", "examples": ["ASAP", "immediately"]},
        "false": ["No time pressure", {"example": "When you get a chance", "other": None}],
    }

    def handler(request):
        payload = json.loads(request.content)
        assert payload["questions"]["requirement"] == {
            "type": "noul",
            "instructions": "Is the message urgent?",
            "criteria": criteria,
        }
        return httpx.Response(200, json=wire())

    with JevClient("test-key", transport=httpx.MockTransport(handler)) as client:
        result = client.noul(
            state={"candidate": "Please do this ASAP."},
            question="Is the message urgent?",
            criteria=criteria,
        )

    assert result.p_yes == 0.97


@pytest.mark.parametrize("criteria,error", [
    ({"yes": "Invalid outcome key"}, ValueError),
    ({"true": 1}, TypeError),
    ({"false": " "}, ValueError),
])
def test_invalid_noul_criteria_rejected_before_request(criteria, error):
    with JevClient("test-key", transport=httpx.MockTransport(lambda _: pytest.fail("No request expected."))) as client:
        with pytest.raises(error):
            client.noul(state={}, question="Valid?", criteria=criteria)


@pytest.mark.parametrize("value", [None, True, False, "0.99", -0.1, 1.1, float("nan"), float("inf"), float("-inf"), [], {}])
def test_invalid_probabilities_rejected(value):
    with pytest.raises(ValueError):
        probability(value)


@pytest.mark.parametrize("value", [0, 1, 0.0, 0.5, 1.0])
def test_probability_boundaries(value):
    assert probability(value) == float(value)


@pytest.mark.parametrize("body", [
    None, [], {}, {"answers": {}},
    {"model": "jev-test", "answers": None},
    {"model": "jev-test", "answers": {"requirement": {"type": "choice", "noul": 0.99}}},
    {"model": "jev-test", "answers": {"requirement": {"type": "noul"}}},
    {"model": "jev-test", "answers": {"other_id": {"type": "noul", "noul": 0.99}}},
    wire(True), wire("0.99"), wire(-1), wire(2),
    {**wire(), "model": None}, {**wire(), "model": ""},
])
def test_malformed_response_fails_closed(body):
    with JevClient("test", transport=transport_for(body)) as client:
        with pytest.raises(JevProtocolError):
            client.noul(state={"candidate": "hi"}, question="Is it a greeting?")


@pytest.mark.parametrize("content", [b"not json", b"{", b'{"model":"jev-test","answers":{"requirement":{"type":"noul","noul":NaN}}}'])
def test_invalid_json_and_non_finite_response(content):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    with JevClient("test", transport=transport) as client:
        with pytest.raises(JevProtocolError):
            client.noul(state={}, question="Valid?")


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 422, 429, 500, 529])
def test_http_failures_are_not_semantic_failures_or_retried(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="SECRET-CANDIDATE and SECRET-API-KEY",
            headers={"location": "https://different-host.invalid"},
        )

    with JevClient("test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JevHTTPError) as exc:
            client.noul(state={}, question="Valid?")
    assert exc.value.status_code == status
    assert "SECRET" not in str(exc.value)
    assert len(calls) == 1  # No redirect following or automatic paid retries.


@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_errors_are_sanitized(exception):
    def handler(request):
        raise exception("SECRET-TRANSPORT-DIAGNOSTIC", request=request)

    with JevClient("test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JevError) as exc:
            client.noul(state={}, question="Valid?")
    assert "SECRET" not in str(exc.value)
    assert not isinstance(exc.value, JevHTTPError)


@pytest.mark.parametrize("timeout", [0, -1, True, "10", float("inf"), float("nan")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        JevClient("test", timeout=timeout)


@pytest.mark.parametrize("key", ["", " ", "key\nvalue", " key", "ключ"])
def test_invalid_keys(key):
    with pytest.raises(ValueError):
        JevClient(key)


def test_environment_key_and_explicit_override(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-env")
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json=wire())

    for key in (None, "explicit"):
        with JevClient(key, transport=httpx.MockTransport(handler)) as client:
            client.noul(state={}, question="Valid?")
    assert seen == ["Bearer from-env", "Bearer explicit"]


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        JevClient()


def test_model_override():
    def handler(request):
        assert json.loads(request.content)["model"] == "jev-account-version"
        return httpx.Response(200, json=wire())

    with JevClient("test", model="jev-account-version", transport=httpx.MockTransport(handler)) as client:
        client.noul(state={}, question="Valid?")


def test_client_closes_transport():
    class RecordingTransport(httpx.MockTransport):
        closed = False
        def close(self):
            self.closed = True

    transport = RecordingTransport(lambda _: httpx.Response(200, json=wire()))
    with JevClient("test", transport=transport):
        assert not transport.closed
    assert transport.closed


@pytest.mark.parametrize("kwargs,exception", [
    ({"state": [], "question": "valid?"}, TypeError),
    ({"state": {}, "question": ""}, ValueError),
    ({"state": {}, "question": None}, ValueError),
])
def test_invalid_call_inputs(kwargs, exception):
    with JevClient("test", transport=transport_for(wire())) as client:
        with pytest.raises(exception):
            client.noul(**kwargs)
