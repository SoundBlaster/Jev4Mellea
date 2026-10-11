"""Exact gateway URLs through both official SDKs; HTTP stays in process."""

import json
from unittest.mock import Mock

import httpx2
import pytest
from test_choice import choice_wire as typesafe_choice_wire
from test_client import wire as typesafe_wire
from test_openai_choice import choice_wire as openai_choice_wire
from test_openai_provider import wire as openai_wire
from test_openai_score import score_wire as openai_score_wire
from test_score import score_wire as typesafe_score_wire

from mellea_jev import (
    ChoiceQuestion,
    JevClient,
    JevHTTPError,
    JevProtocolError,
    NoulQuestion,
    OpenAIHTTPError,
    OpenAIProtocolError,
    OpenAIProvider,
    ScoreQuestion,
)
from mellea_jev.providers._http import _EndpointTransport


@pytest.fixture(params=[JevClient, OpenAIProvider])
def provider(request):
    return request.param


def response_body(provider, primitive="noul"):
    if provider is OpenAIProvider:
        return {"noul": openai_wire, "choice": openai_choice_wire, "score": openai_score_wire}[
            primitive
        ]()
    bodies = {
        "noul": typesafe_wire(0.98),
        "choice": typesafe_choice_wire(probabilities={"billing": 0.8, "technical": 0.2}),
        "score": typesafe_score_wire(legend={"0": "Low", "1": "Medium", "2": "High"}),
    }
    return bodies[primitive]


@pytest.mark.parametrize("primitive", ["noul", "choice", "score"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://proxy.example/models/luna/decide",
        "https://proxy.example/prefix/v42/custom/",
        "https://proxy.example:8443/tenant/a%2Fb/evaluate",
        "http://[::1]:8080/custom",
    ],
)
def test_exact_endpoint_for_every_primitive(provider, primitive, endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.example")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://untrusted.example")
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.example:9999")
    state = {"candidate": "Привет"}
    body = response_body(provider, primitive)
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == endpoint
        assert request.method == "POST"
        assert request.headers["host"] == httpx2.URL(endpoint).netloc.decode("ascii")
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.extensions["timeout"] == dict.fromkeys(
            ["connect", "read", "write", "pool"], 2.5
        )
        payload = json.loads(request.content)
        assert payload["model"] == "model-fixture"
        if provider is OpenAIProvider:
            assert payload["input"] == json.dumps(state, ensure_ascii=False)
            (question,) = payload["questions"]
            assert question["type"] == ("predicate" if primitive == "noul" else primitive)
        else:
            assert payload["state"] == state
            (question,) = payload["questions"].values()
            assert question["type"] == primitive
        assert question["instructions"] == "Evaluate."
        return httpx2.Response(
            200,
            json=body,
            headers={"x-request-id": "endpoint-42", "x-typesafe-request-id": "endpoint-42"},
        )

    options = {
        "noul": {},
        "choice": {"criteria": {"billing": "Payments", "technical": "Bugs"}},
        "score": {"criteria": ["Low", "Medium", "High"]},
    }
    transport = httpx2.MockTransport(handler)
    transport.close = Mock()
    with provider(
        "test-key", model="model-fixture", endpoint_url=endpoint, timeout=2.5, transport=transport
    ) as client:
        result = getattr(client, primitive)(state=state, question="Evaluate.", **options[primitive])
    assert result.model == body["model"] and result.request_id == "endpoint-42"
    if primitive == "noul":
        assert result.p_yes == 0.98
        assert result.usage.input_tokens == body["usage"]["input_tokens"]
    elif primitive == "choice":
        assert result.choice == "billing"
    else:
        assert result.score == 0.7 and result.legend == dict(
            enumerate(options[primitive]["criteria"])
        )
    assert len(requests) == 1
    transport.close.assert_called_once()


@pytest.mark.parametrize("use_official_base", [True, False])
def test_endpoint_and_explicit_base_are_mutually_exclusive(provider, use_official_base):
    official = (
        "https://api.openai.com/v1" if provider is OpenAIProvider else "https://api.typesafe.ai"
    )
    base_url = official if use_official_base else "https://proxy.example/prefix"
    with pytest.raises(ValueError, match="only one of base_url or endpoint_url"):
        provider("test-key", base_url=base_url, endpoint_url="https://proxy.example/decide")


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        1,
        True,
        "/decide",
        "ftp://proxy.example/decide",
        "https://",
        "https://user:secret@proxy.example/decide",
        "https://proxy.example/decide?key=secret",
        "https://proxy.example/decide#secret",
        " https://proxy.example/decide",
        "https://proxy.example/with space",
        "https://proxy.example:bad/decide",
    ],
)
def test_invalid_endpoint_is_safe_and_creates_no_transport(provider, endpoint, monkeypatch):
    constructor = Mock(side_effect=AssertionError("Must validate before creating transport"))
    monkeypatch.setattr(httpx2, "HTTPTransport", constructor)
    with pytest.raises(ValueError) as captured:
        provider("test-key", endpoint_url=endpoint)
    assert "endpoint_url" in str(captured.value) and "secret" not in str(captured.value)
    constructor.assert_not_called()


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_exact_endpoint_never_retries_or_redirects(provider, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            status,
            json={"error": {"message": "secret test-key"}},
            headers={"location": "https://untrusted.example", "x-should-retry": "true"},
        )

    error = OpenAIHTTPError if provider is OpenAIProvider else JevHTTPError
    with provider(
        "test-key",
        endpoint_url="https://proxy.example/decide",
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(error) as captured:
            client.noul(state={}, question="Valid?")
    assert captured.value.status_code == status
    assert "secret" not in str(captured.value) and "test-key" not in str(captured.value)
    assert len(calls) == 1


def test_exact_endpoint_keeps_strict_response_validation(provider):
    error = OpenAIProtocolError if provider is OpenAIProvider else JevProtocolError
    with provider(
        "test-key",
        endpoint_url="https://proxy.example/decide",
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"answers": []})),
    ) as client:
        with pytest.raises(error):
            client.noul(state={}, question="Valid?")


def test_default_endpoint_transport_disables_retries_and_environment(provider, monkeypatch):
    handler = Mock(return_value=httpx2.Response(200, json=response_body(provider)))
    constructor = Mock(return_value=httpx2.MockTransport(handler))
    monkeypatch.setattr(httpx2, "HTTPTransport", constructor)
    with provider("test-key", endpoint_url="https://proxy.example/decide") as client:
        client.noul(state={}, question="Valid?")
    constructor.assert_called_once_with(retries=0, trust_env=False)
    handler.assert_called_once()


def test_typesafe_batch_uses_one_exact_endpoint_request():
    bodies = [response_body(JevClient, kind) for kind in ["noul", "choice", "score"]]
    body = {
        **bodies[0],
        "answers": {key: value for b in bodies for key, value in b["answers"].items()},
    }
    questions = {
        "requirement": NoulQuestion("Greeting?"),
        "classification": ChoiceQuestion("Team?", {"billing": "Payments", "technical": "Bugs"}),
        "rating": ScoreQuestion("Severity?", ["Low", "Medium", "High"]),
    }
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://proxy.example/models/jev/batch/"
        assert json.loads(request.content)["questions"] == {
            name: question.to_payload() for name, question in questions.items()
        }
        return httpx2.Response(200, json=body, headers={"x-typesafe-request-id": "batch-42"})

    with JevClient(
        "test-key",
        endpoint_url="https://proxy.example/models/jev/batch/",
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = client.system_one(state={"candidate": "Hello"}, questions=questions)
    assert set(result.answers) == set(questions)
    assert all(answer.request_id == "batch-42" for answer in result.answers.values())
    assert len(calls) == 1


@pytest.mark.parametrize("method,path", [("GET", "/decisions"), ("POST", "/models")])
def test_transport_rejects_unexpected_sdk_operations(method, path):
    handler = Mock()
    transport = _EndpointTransport(
        httpx2.MockTransport(handler),
        httpx2.URL("https://proxy.example/decisions"),
        httpx2.URL("https://proxy.example/custom"),
    )
    with transport, pytest.raises(httpx2.UnsupportedProtocol):
        transport.handle_request(httpx2.Request(method, "https://proxy.example" + path))
    handler.assert_not_called()
