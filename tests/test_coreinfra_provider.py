"""Both CoreInfra routes reuse SDK providers, without a Hub-specific wire layer."""

import json

import httpx2
import pytest
from test_client import wire as systemone_wire
from test_openai_provider import wire as decisions_wire

from mellea_jev import OpenAIProvider, TypeSafeProvider, coreinfra_provider
from mellea_jev.providers.coreinfra import DECISIONS_ENDPOINT, SYSTEM_ONE_ENDPOINT


@pytest.mark.parametrize("protocol", ["systemone", "decisions"])
@pytest.mark.parametrize("model", ["jev-latest", "gpt-6-luna"])
def test_protocol_and_model_are_independent_and_key_is_explicit(monkeypatch, protocol, model):
    monkeypatch.setenv("COREINFRA_API_KEY", "hub-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "wrong-typesafe-key")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-openai-key")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://wrong.example")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.example")
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == (
            SYSTEM_ONE_ENDPOINT if protocol == "systemone" else DECISIONS_ENDPOINT
        )
        assert request.headers["authorization"] == "Bearer hub-key"
        payload = json.loads(request.content)
        assert payload["model"] == model
        if protocol == "systemone":
            assert payload["state"] == {"candidate": "Paid"}
            body = systemone_wire(0.98)
        else:
            assert json.loads(payload["input"]) == {"candidate": "Paid"}
            body = decisions_wire(0.98)
        body["model"] = model
        return httpx2.Response(
            200,
            json=body,
            headers={"x-typesafe-request-id": "hub-receipt", "x-request-id": "hub-receipt"},
        )

    with coreinfra_provider(
        protocol=protocol, model=model, transport=httpx2.MockTransport(handler)
    ) as provider:
        assert type(provider) is (TypeSafeProvider if protocol == "systemone" else OpenAIProvider)
        answer = provider.noul(state={"candidate": "Paid"}, question="Is the invoice paid?")
    assert answer.p_yes == 0.98 and answer.model == model
    assert answer.request_id == "hub-receipt"
    assert answer.usage.input_tokens == (50 if protocol == "systemone" else 42)
    assert len(calls) == 1


@pytest.mark.parametrize("protocol", ["systemone", "decisions"])
@pytest.mark.parametrize("key", [None, "", " "])
def test_hub_key_never_falls_back_to_other_provider_credentials(monkeypatch, protocol, key):
    monkeypatch.delenv("COREINFRA_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "official-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "official-secret")
    with pytest.raises(ValueError, match="COREINFRA_API_KEY"):
        coreinfra_provider(api_key=key, protocol=protocol)


def test_explicit_key_and_default_route(monkeypatch):
    monkeypatch.setenv("COREINFRA_API_KEY", "wrong-key")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer explicit-key"
        return httpx2.Response(200, json=systemone_wire())

    with coreinfra_provider(
        api_key="explicit-key",
        transport=httpx2.MockTransport(handler),
    ) as provider:
        assert type(provider) is TypeSafeProvider
        assert provider.model == "jev-latest"
        assert not calls
        provider.noul(state={}, question="Valid?")
    assert len(calls) == 1


def test_invalid_protocol_is_rejected_before_sdk_construction():
    with pytest.raises(ValueError, match="protocol"):
        coreinfra_provider(api_key="test", protocol="chat")
