"""CLI smoke configuration through real SDKs with mocked HTTP only."""

import json

import httpx2
import pytest
from test_client import wire as jev_wire
from test_openai_provider import wire as openai_wire

from examples import live_check
from mellea_jev import JevClient, OpenAIProvider


@pytest.mark.parametrize("provider", ["typesafe", "openai"])
@pytest.mark.parametrize("url_option", [None, "--base-url", "--endpoint-url"])
def test_smoke_routes_one_request(monkeypatch, capsys, provider, url_option):
    key_env = "TYPESAFE_API_KEY" if provider == "typesafe" else "OPENAI_API_KEY"
    monkeypatch.setenv(key_env, "official-key")
    monkeypatch.setenv("PROXY_API_KEY", "proxy-key")
    monkeypatch.setenv("JEV_MODEL", "jev-env-model")
    default_url = (
        "https://api.typesafe.ai/v1/systemone"
        if provider == "typesafe"
        else "https://api.openai.com/v1/decisions"
    )
    custom_url = "https://proxy.example:8443/tenant/a%2Fb/evaluate/"
    expected_url = default_url
    args = ["--provider", provider]
    if url_option is not None:
        args += [
            url_option,
            custom_url,
            "--api-key-env",
            "PROXY_API_KEY",
            "--model",
            "custom-model",
        ]
        suffix = "/v1/systemone" if provider == "typesafe" else "/decisions"
        expected_url = custom_url.rstrip("/") + suffix if url_option == "--base-url" else custom_url
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == expected_url
        assert request.headers["authorization"] == "Bearer " + (
            "proxy-key" if url_option else "official-key"
        )
        payload = json.loads(request.content)
        assert payload["model"] == (
            "custom-model"
            if url_option
            else "jev-env-model"
            if provider == "typesafe"
            else "gpt-6-luna"
        )
        body = jev_wire(0.98) if provider == "typesafe" else openai_wire(0.98)
        return httpx2.Response(
            200,
            json=body,
            headers={"x-request-id": "smoke-42", "x-typesafe-request-id": "smoke-42"},
        )

    real_provider = JevClient if provider == "typesafe" else OpenAIProvider
    monkeypatch.setattr(
        live_check,
        "JevClient" if provider == "typesafe" else "OpenAIProvider",
        lambda **kwargs: real_provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    assert live_check.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["outcome"] == "pass" and report["request_id"] == "smoke-42"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "options",
    [
        ["--base-url", "https://proxy.example"],
        ["--endpoint-url", "https://proxy.example/decide"],
        ["--base-url", "https://proxy.example", "--endpoint-url", "https://proxy.example/decide"],
    ],
)
def test_smoke_invalid_arguments_construct_no_provider(monkeypatch, options):
    monkeypatch.setattr(
        live_check, "JevClient", lambda **_: pytest.fail("Must not construct provider")
    )
    with pytest.raises(SystemExit) as captured:
        live_check.main(options)
    assert captured.value.code == 2


@pytest.mark.parametrize("provider", ["typesafe", "openai"])
def test_selected_key_never_falls_back(monkeypatch, capsys, provider):
    monkeypatch.setenv("TYPESAFE_API_KEY", "official-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "official-secret")
    monkeypatch.delenv("PROXY_API_KEY", raising=False)
    assert (
        live_check.main(
            [
                "--provider",
                provider,
                "--endpoint-url",
                "https://proxy.example/decide",
                "--api-key-env",
                "PROXY_API_KEY",
            ]
        )
        == 3
    )
    output = capsys.readouterr()
    assert not output.out and "official-secret" not in output.err


@pytest.mark.parametrize("provider", ["typesafe", "openai"])
def test_smoke_http_errors_are_safe_and_not_retried(monkeypatch, capsys, provider):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(429, json={"error": {"message": "secret-key response-body"}})

    real_provider = JevClient if provider == "typesafe" else OpenAIProvider
    monkeypatch.setenv("PROXY_API_KEY", "secret-key")
    monkeypatch.setattr(
        live_check,
        "JevClient" if provider == "typesafe" else "OpenAIProvider",
        lambda **kwargs: real_provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    assert (
        live_check.main(
            [
                "--provider",
                provider,
                "--endpoint-url",
                "https://proxy.example/decide",
                "--api-key-env",
                "PROXY_API_KEY",
            ]
        )
        == 3
    )
    output = capsys.readouterr()
    assert not output.out and "secret-key" not in output.err and "response-body" not in output.err
    assert len(calls) == 1
