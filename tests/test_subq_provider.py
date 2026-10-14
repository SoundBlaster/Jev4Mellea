"""SubQ Decisions API requests through local transport; no paid calls."""

import json
import traceback

import httpx2
import pytest

from mellea_jev import (
    ChoiceProvider,
    ChoiceResult,
    NoulProvider,
    NoulResult,
    ScoreProvider,
    ScoreResult,
    SubQHTTPError,
    SubQProtocolError,
    SubQProvider,
    SubQProviderError,
    UsageMetadata,
)


def wire(answer, *, model="subq-snap-preview", usage=None):
    result = {"model": model, "answers": {"decision": answer}}
    if usage is not None:
        result["usage"] = usage
    return result


def test_noul_uses_bearer_auth_and_preserves_state_response_metadata(monkeypatch):
    monkeypatch.setenv("SUBQ_BASE_URL", "https://untrusted.example")

    def handler(request):
        assert str(request.url) == "https://api.subq.ai/v1/systemone"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "subq-snap-preview",
            "state": {"candidate": "10:00", "reference": "10:00"},
            "questions": {
                "decision": {
                    "type": "noul",
                    "instructions": "Is it correct?",
                    "criteria": {"true": "matches", "false": "differs"},
                }
            },
        }
        return httpx2.Response(
            200,
            json=wire(
                {"type": "noul", "noul": 0.975},
                usage={"input_tokens": 146, "output_tokens": 0},
            ),
            headers={"x-request-id": "request-123"},
        )

    with SubQProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: NoulProvider = client
        result = provider.noul(
            state={"candidate": "10:00", "reference": "10:00"},
            question="Is it correct?",
            criteria={"true": "matches", "false": "differs"},
        )
    assert result == NoulResult(0.975, "subq-snap-preview", "request-123", UsageMetadata(146, 0))


def test_choice_sends_structured_criteria_and_maps_distribution():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["questions"]["decision"] == {
            "type": "choice",
            "instructions": "Which team?",
            "criteria": {"billing": "Payments", "account": {"examples": ["login"]}},
        }
        return httpx2.Response(
            200,
            json=wire(
                {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.82,
                    "probabilities": {"billing": 0.82, "account": 0.18},
                }
            ),
        )

    with SubQProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: ChoiceProvider = client
        result = provider.choice(
            state={"ticket": "duplicate charge"},
            question="Which team?",
            criteria={"billing": "Payments", "account": {"examples": ["login"]}},
        )
    assert result == ChoiceResult(
        "billing", 0.82, {"billing": 0.82, "account": 0.18}, "subq-snap-preview"
    )


def test_score_sends_ordered_levels_and_maps_weighted_score():
    def handler(request):
        assert json.loads(request.content)["questions"]["decision"]["criteria"] == [
            "low",
            "medium",
            "high",
        ]
        return httpx2.Response(
            200,
            json=wire(
                {
                    "type": "score",
                    "score": 1.2,
                    "confidence": 0.6,
                    "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
                    "legend": {"0": "low", "1": "medium", "2": "high"},
                }
            ),
        )

    with SubQProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: ScoreProvider = client
        result = provider.score(state={}, question="Severity?", criteria=["low", "medium", "high"])
    assert result == ScoreResult(
        1.2,
        0.6,
        {0: 0.1, 1: 0.6, 2: 0.3},
        {0: "low", 1: "medium", 2: "high"},
        "subq-snap-preview",
    )


@pytest.mark.parametrize(
    "answer,primitive,criteria",
    [
        ({"type": "noul", "noul": True}, "noul", None),
        ({"type": "noul", "noul": 1.01}, "noul", None),
        (
            {
                "type": "choice",
                "choice": "missing",
                "confidence": 0.7,
                "probabilities": {"a": 0.7, "b": 0.3},
            },
            "choice",
            {"a": "A", "b": "B"},
        ),
        (
            {
                "type": "score",
                "score": 0.2,
                "confidence": 0.8,
                "probabilities": {"0": 0.8, "01": 0.2},
                "legend": {"0": "low", "1": "high"},
            },
            "score",
            ["low", "high"],
        ),
    ],
)
def test_malformed_answers_fail_closed(answer, primitive, criteria):
    with SubQProvider(
        "test-key",
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire(answer))),
    ) as client:
        with pytest.raises(SubQProtocolError):
            if primitive == "noul":
                client.noul(state={}, question="Valid?")
            elif primitive == "choice":
                client.choice(state={}, question="Pick?", criteria=criteria)
            else:
                client.score(state={}, question="Rate?", criteria=criteria)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"model": "subq-snap-preview", "answers": {}},
        {"model": "other", "answers": {"decision": {"type": "noul", "noul": 1}}},
        {
            "model": "subq-snap-preview",
            "answers": {"decision": {"type": "noul", "noul": 1}, "other": {}},
        },
    ],
)
def test_invalid_envelopes_fail_closed(body):
    with SubQProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(SubQProtocolError):
            client.noul(state={}, question="Valid?")


@pytest.mark.parametrize("status", [302, 401, 402, 403, 422, 429, 503])
def test_http_errors_are_safe_and_not_retried(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            status,
            json={"detail": {"message": "secret-body test-key"}},
            headers={"location": "https://untrusted.example", "retry-after": "0"},
        )

    with SubQProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(SubQHTTPError) as captured:
            client.noul(state={}, question="Valid?")
    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.status_code == status
    assert "secret-body" not in rendered and "test-key" not in rendered
    assert len(requests) == 1


def test_transport_errors_are_sanitized():
    def handler(request):
        raise httpx2.ConnectError("secret-body test-key", request=request)

    with SubQProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(SubQProviderError) as captured:
            client.noul(state={}, question="Valid?")
    assert "secret-body" not in str(captured.value) and "test-key" not in str(captured.value)
    assert captured.value.__suppress_context__


def test_exact_endpoint_url_and_environment_key(monkeypatch):
    monkeypatch.setenv("SUBQ_API_KEY", "environment-key")

    def handler(request):
        assert str(request.url) == "https://proxy.example/tenant/decision/run"
        assert request.headers["authorization"] == "Bearer environment-key"
        return httpx2.Response(200, json=wire({"type": "noul", "noul": 0.5}))

    with SubQProvider(
        endpoint_url="https://proxy.example/tenant/decision/run",
        transport=httpx2.MockTransport(handler),
    ) as client:
        assert client.noul(state={}, question="Valid?").p_yes == 0.5


@pytest.mark.parametrize("model", ["subq-preview", "jev-latest", ""])
def test_unsupported_models_fail_before_request(model):
    with pytest.raises(ValueError, match="only 'subq-snap-preview'"):
        SubQProvider(
            "test-key", model=model, transport=httpx2.MockTransport(lambda _: pytest.fail())
        )


@pytest.mark.parametrize("criteria", [["one"], [str(index) for index in range(11)]])
def test_score_requires_two_to_ten_levels(criteria):
    with SubQProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as client:
        with pytest.raises(ValueError):
            client.score(state={}, question="Rate?", criteria=criteria)


def test_choice_requires_two_to_255_labels():
    with SubQProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as client:
        with pytest.raises(ValueError):
            client.choice(state={}, question="Pick?", criteria={"only": "one"})


def test_bad_state_is_rejected_before_network():
    with SubQProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as client:
        with pytest.raises(ValueError, match="JSON-compatible"):
            client.noul(state={"bad": float("nan")}, question="Valid?")
