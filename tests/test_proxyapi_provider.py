"""Exercise the temporary bridge through the actual SDK, without live requests."""

import copy
import json

import httpx2
import pytest

from mellea_jev import (
    ChoiceQuestion,
    JevClassifier,
    JevError,
    JevHTTPError,
    JevProtocolError,
    JevScorer,
    JevVerifier,
    NoulQuestion,
    ScoreQuestion,
    UsageMetadata,
)
from mellea_jev.providers.proxyapi import DEFAULT_MODEL, ENDPOINT, ProxyAPIProvider


def questions():
    return {
        "bug": NoulQuestion("Is this a bug?", {"true": "Broken", "false": "Expected"}),
        "team": ChoiceQuestion("Which team?", {"payments": "Billing", "frontend": "UI"}),
        "urgency": ScoreQuestion("Rate urgency.", ["Can wait", "Today"]),
    }


def wire():
    return {
        "id": "gen-dec-fixture",
        "model": "openai/gpt-6-luna-decisions-fixture",
        "usage": {"input_tokens": 503, "output_tokens": 0},
        "answers": {
            "bug": {"type": "noul", "noul": 0.98},
            "team": {
                "type": "choice",
                "choice": "payments",
                "confidence": 0.8,
                "probabilities": {"payments": 0.9, "frontend": 0.1},
            },
            "urgency": {
                "type": "score",
                "score": 0.75,
                "confidence": 0.5,
                "probabilities": {"0": 0.25, "1": 0.75},
                "legend": {"0": "Can wait", "1": "Today"},
            },
        },
    }


def test_mixed_questions_preserve_payload_and_normalize_metadata(monkeypatch):
    calls = []
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://wrong.invalid")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "http://wrong.invalid")

    def handler(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer mock-key"
        assert request.headers["content-type"].startswith("application/json")
        assert json.loads(request.content) == {
            "model": DEFAULT_MODEL,
            "state": {"ticket": "Checkout broke."},
            "questions": {name: question.to_payload() for name, question in questions().items()},
        }
        assert "timeout" in request.extensions
        return httpx2.Response(200, json=wire(), headers={"x-typesafe-request-id": "wrong-id"})

    with ProxyAPIProvider("mock-key", transport=httpx2.MockTransport(handler)) as provider:
        result = provider.system_one(state={"ticket": "Checkout broke."}, questions=questions())
        assert provider.model == DEFAULT_MODEL

    assert len(calls) == 1
    assert result.request_id == "gen-dec-fixture"
    assert result.usage == UsageMetadata(503, 0)
    assert result.answers["bug"].p_yes == 0.98
    assert result.answers["team"].choice == "payments"
    assert result.answers["urgency"].score == 0.75
    assert all(answer.request_id == result.request_id for answer in result.answers.values())


@pytest.mark.parametrize("primitive", ["noul", "choice", "score"])
def test_existing_mellea_adapters_consume_the_provider(primitive):
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["state"]["candidate"] == "Checkout broke."
        name, question = next(iter(payload["questions"].items()))
        assert question["type"] == primitive
        source = {"noul": "bug", "choice": "team", "score": "urgency"}[primitive]
        body = wire()
        body["answers"] = {name: body["answers"][source]}
        return httpx2.Response(200, json=body)

    with ProxyAPIProvider("mock-key", transport=httpx2.MockTransport(handler)) as provider:
        if primitive == "noul":
            result = JevVerifier(provider, "Is this a bug?").evaluate("Checkout broke.")
            assert result.p_yes == 0.98
        elif primitive == "choice":
            result = JevClassifier(
                provider, "Which team?", criteria={"payments": "Billing", "frontend": "UI"}
            ).classify("Checkout broke.")
            assert result.choice == "payments"
        else:
            result = JevScorer(provider, "Rate urgency.", criteria=["Can wait", "Today"]).evaluate(
                "Checkout broke."
            )
            assert result.score == 0.75
    assert result.request_id == "gen-dec-fixture"
    assert len(calls) == 1


@pytest.mark.parametrize("request_id", [None, "", True, 123, "bad\nid", "id\x00", "ид"])
def test_invalid_response_id_fails_safely(request_id):
    body = {**wire(), "id": request_id}
    with ProxyAPIProvider(
        "mock-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as provider:
        with pytest.raises(JevProtocolError, match="response ID"):
            provider.system_one(state={}, questions=questions())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.pop("id"),
        lambda b: b.update(model=""),
        lambda b: b["answers"]["bug"].update(noul="0.98"),
        lambda b: b["answers"]["bug"].update(noul=True),
        lambda b: b["answers"]["team"].update(probabilities={"other": 1.0}),
        lambda b: b["answers"]["team"].update(probabilities={"payments": 0.1, "frontend": 0.9}),
        lambda b: b["answers"]["urgency"].update(score=0.1),
        lambda b: b["answers"]["urgency"].update(probabilities={"00": 0.25, "1": 0.75}),
        lambda b: b["answers"]["urgency"].update(legend={"0": "Wrong", "1": "Today"}),
        lambda b: b["usage"].update(input_tokens=True),
    ],
)
def test_shared_validation_rejects_malformed_answers(mutation):
    body = copy.deepcopy(wire())
    mutation(body)
    with ProxyAPIProvider(
        "mock-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as provider:
        with pytest.raises(JevProtocolError):
            provider.system_one(state={}, questions=questions())


def test_malformed_json_is_rejected_without_echoing_body():
    with ProxyAPIProvider(
        "mock-key",
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=b"private body")),
    ) as provider:
        with pytest.raises(JevProtocolError) as error:
            provider.system_one(state={}, questions=questions())
    assert "private body" not in str(error.value)


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_failures_are_safe_and_never_retried_or_redirected(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            status, text="private body mock-key", headers={"location": "https://wrong.invalid"}
        )

    with ProxyAPIProvider("mock-key", transport=httpx2.MockTransport(handler)) as provider:
        with pytest.raises(JevHTTPError) as error:
            provider.noul(state={}, question="Valid?")
    assert error.value.status_code == status
    assert "mock-key" not in str(error.value) and "private body" not in str(error.value)
    assert error.value.__suppress_context__
    assert len(calls) == 1


def test_connection_failure_does_not_leak_credentials_or_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx2.ConnectError("private body mock-key", request=request)

    with ProxyAPIProvider("mock-key", transport=httpx2.MockTransport(handler)) as provider:
        with pytest.raises(JevError, match="transport failed") as error:
            provider.noul(state={}, question="Valid?")
    assert "mock-key" not in str(error.value)
    assert len(calls) == 1


def test_http_client_disables_environment_and_redirects(monkeypatch):
    real_client = httpx2.Client
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx2, "Client", client)
    with ProxyAPIProvider("mock-key", transport=httpx2.MockTransport(lambda _: None)):
        pass
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False


@pytest.mark.parametrize("key", [None, "", "white space", "кириллица"])
def test_invalid_explicit_key_never_falls_back_to_environment(key, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "must-not-be-used")
    with (
        pytest.raises(ValueError),
        ProxyAPIProvider(
            key, transport=httpx2.MockTransport(lambda _: pytest.fail("No request expected"))
        ),
    ):
        pass


def test_close_reaches_inner_transport_even_when_initialization_fails():
    closed = []

    class TrackingTransport(httpx2.MockTransport):
        def close(self):
            closed.append(True)

    transport = TrackingTransport(lambda _: None)
    with ProxyAPIProvider("mock-key", transport=transport):
        pass
    assert closed == [True]
    with pytest.raises(ValueError):
        ProxyAPIProvider("", transport=transport)
    assert closed == [True, True]


def test_bridge_rejects_unexpected_routes_before_forwarding():
    from mellea_jev.providers.proxyapi import _DecisionsTransport

    transport = _DecisionsTransport(
        httpx2.MockTransport(lambda _: pytest.fail("Unexpected request must not be forwarded"))
    )
    with pytest.raises(httpx2.UnsupportedProtocol):
        transport.handle_request(httpx2.Request("POST", "https://wrong.invalid/v1/systemone"))


@pytest.mark.parametrize("args,key", [([], "mock-key"), (["--live"], "")])
def test_smoke_requires_explicit_opt_in_and_own_key(args, key, monkeypatch):
    from examples import live_proxyapi_check as smoke

    monkeypatch.setattr("sys.argv", ["smoke", *args])
    monkeypatch.setenv("PROXYAPI_API_KEY", key)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("TYPESAFE_API_KEY", "must-not-be-used")
    monkeypatch.setattr(smoke, "ProxyAPIProvider", lambda **_: pytest.fail("No provider expected"))
    with pytest.raises(SystemExit) as error:
        smoke.main()
    assert error.value.code == 2


def test_smoke_runs_one_mixed_request_and_prints_no_key(monkeypatch, capsys):
    from examples import live_proxyapi_check as smoke

    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        answers = {}
        for name, question in payload["questions"].items():
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 0.98}
            elif question["type"] == "choice":
                labels = list(question["criteria"])
                answers[name] = {
                    "type": "choice",
                    "choice": labels[0],
                    "confidence": 0.5,
                    "probabilities": {label: 1 / len(labels) for label in labels},
                }
            else:
                levels = question["criteria"]
                answers[name] = {
                    "type": "score",
                    "score": 0.0,
                    "confidence": 1.0,
                    "probabilities": {str(i): float(i == 0) for i in range(len(levels))},
                    "legend": {str(i): label for i, label in enumerate(levels)},
                }
        return httpx2.Response(200, json={**wire(), "answers": answers})

    monkeypatch.setattr("sys.argv", ["smoke", "--live"])
    monkeypatch.setenv("PROXYAPI_API_KEY", "mock-key")
    monkeypatch.setattr(
        smoke,
        "ProxyAPIProvider",
        lambda **kwargs: ProxyAPIProvider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    assert smoke.main() == 0
    output = capsys.readouterr().out
    assert "mock-key" not in output
    report = json.loads(output)
    assert report["outcome"] == "pass" and len(calls) == 1
    assert set(report["answers"]) == {"is_bug", "team", "urgency"}
