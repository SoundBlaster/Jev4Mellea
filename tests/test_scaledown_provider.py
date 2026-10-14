"""ScaleDown Decisions API requests through a local transport; no paid calls."""

import json
import traceback

import httpx2
import pytest

from mellea_jev import (
    ChoiceProvider,
    ChoiceResult,
    NoulProvider,
    NoulResult,
    ScaleDownHTTPError,
    ScaleDownProtocolError,
    ScaleDownProvider,
    ScaleDownProviderError,
    ScoreProvider,
    ScoreResult,
    UsageMetadata,
)


def wire(answer, *, model="classify-1", usage=None):
    result = {"model": model, "answers": {"decision": answer}}
    if usage is not None:
        result["usage"] = usage
    return result


def test_noul_request_preserves_full_state_and_usage(monkeypatch):
    monkeypatch.setenv("SCALEDOWN_BASE_URL", "https://untrusted.example")
    states = []

    def handler(request):
        assert str(request.url) == "https://api.scaledown.xyz/v1/scaledown"
        assert request.method == "POST"
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["content-type"] == "application/json"
        payload = json.loads(request.content)
        assert payload["model"] == "classify-1"
        assert set(payload) == {"model", "state", "questions"}
        state = payload["state"]
        assert set(state) == {"text"}
        states.append(json.loads(state["text"]))
        assert payload["questions"] == {
            "decision": {"type": "noul", "instructions": "Is it correct?"}
        }
        return httpx2.Response(
            200,
            json=wire(
                {"type": "noul", "noul": 0.98},
                usage={"input_tokens": 24, "output_tokens": 0, "cost": 0.0002},
            ),
            headers={"x-request-id": "request-123"},
        )

    with ScaleDownProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: NoulProvider = client
        result = provider.noul(
            state={"candidate": "10:00", "reference": "10:00", "extra": {"x": [1, 2]}},
            question="Is it correct?",
        )
    assert states == [{"candidate": "10:00", "reference": "10:00", "extra": {"x": [1, 2]}}]
    assert result == NoulResult(0.98, "classify-1", "request-123", UsageMetadata(24, 0, 0.0002))


def test_noul_criteria_are_forwarded_as_explicit_instruction_text():
    def handler(request):
        question = json.loads(request.content)["questions"]["decision"]
        assert question["instructions"] == (
            "Urgent?\n\nOutcome criteria (JSON; true means the condition holds):\n"
            '{"true": {"examples": ["Blocks launch"]}, "false": ["Can wait"]}'
        )
        return httpx2.Response(200, json=wire({"type": "noul", "noul": 0.7}))

    with ScaleDownProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        assert (
            client.noul(
                state={},
                question="Urgent?",
                criteria={"true": {"examples": ["Blocks launch"]}, "false": ["Can wait"]},
            ).p_yes
            == 0.7
        )


def test_choice_converts_json_descriptions_and_checks_confidence():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["questions"]["decision"] == {
            "type": "choice",
            "instructions": "Which team?",
            "criteria": {"billing": "Payments", "other": '{"examples": ["misc"]}'},
        }
        return httpx2.Response(
            200,
            json=wire(
                {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.75,
                    "probabilities": {"billing": 0.75, "other": 0.25},
                }
            ),
        )

    with ScaleDownProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: ChoiceProvider = client
        result = provider.choice(
            state={"ticket": "refund"},
            question="Which team?",
            criteria={"billing": "Payments", "other": {"examples": ["misc"]}},
        )
    assert result == ChoiceResult("billing", 0.75, {"billing": 0.75, "other": 0.25}, "classify-1")


def test_score_preserves_order_and_validates_legend_confidence_and_weighted_value():
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

    with ScaleDownProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        provider: ScoreProvider = client
        result = provider.score(state={}, question="Severity?", criteria=["low", "medium", "high"])
    assert result == ScoreResult(
        1.2,
        0.6,
        {0: 0.1, 1: 0.6, 2: 0.3},
        {0: "low", 1: "medium", 2: "high"},
        "classify-1",
    )


@pytest.mark.parametrize(
    "answer,primitive,criteria",
    [
        ({"type": "noul", "noul": True}, "noul", None),
        ({"type": "noul", "noul": 1.01}, "noul", None),
        (
            {
                "type": "choice",
                "choice": "a",
                "confidence": 0.7,
                "probabilities": {"a": 0.6, "b": 0.4},
            },
            "choice",
            {"a": "A", "b": "B"},
        ),
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
                "confidence": 0.9,
                "probabilities": {"0": 0.8, "1": 0.2},
                "legend": {"0": "low", "1": "high"},
            },
            "score",
            ["low", "high"],
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
def test_malformed_primitive_answers_fail_closed(answer, primitive, criteria):
    with ScaleDownProvider(
        "test-key",
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire(answer))),
    ) as client:
        with pytest.raises(ScaleDownProtocolError):
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
        {"model": "classify-1", "answers": {}},
        {"model": "other", "answers": {"decision": {"type": "noul", "noul": 1}}},
        {"model": "classify-1", "answers": {"decision": {"type": "noul", "noul": 1}, "other": {}}},
    ],
)
def test_invalid_envelopes_fail_closed(body):
    with ScaleDownProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    ) as client:
        with pytest.raises(ScaleDownProtocolError):
            client.noul(state={}, question="Valid?")


@pytest.mark.parametrize("model", ["classify", "jev-latest", ""])
def test_unsupported_model_fails_before_request(model):
    with pytest.raises(ValueError, match="only 'classify-1'"):
        ScaleDownProvider(
            "test-key", model=model, transport=httpx2.MockTransport(lambda _: pytest.fail())
        )


@pytest.mark.parametrize("criteria", [["one"], [str(i) for i in range(11)]])
def test_score_requires_two_to_ten_levels(criteria):
    with ScaleDownProvider(
        "test-key", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as client:
        with pytest.raises(ValueError):
            client.score(state={}, question="Rate?", criteria=criteria)


@pytest.mark.parametrize("status", [302, 401, 402, 422, 429, 502, 504])
def test_http_errors_are_safe_and_not_retried(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            status,
            json={"error": {"message": "secret-body test-key"}},
            headers={"location": "https://untrusted.example", "retry-after": "0"},
        )

    with ScaleDownProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ScaleDownHTTPError) as captured:
            client.noul(state={}, question="Valid?")
    assert captured.value.status_code == status
    assert "secret-body" not in "".join(traceback.format_exception(captured.value))
    assert "test-key" not in "".join(traceback.format_exception(captured.value))
    assert len(requests) == 1


def test_transport_failure_is_safe():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx2.ConnectError("secret-body test-key", request=request)

    with ScaleDownProvider("test-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ScaleDownProviderError) as captured:
            client.noul(state={}, question="Valid?")
    assert "secret-body" not in str(captured.value) and "test-key" not in str(captured.value)
    assert captured.value.__suppress_context__
    assert len(requests) == 1


def test_exact_endpoint_url_and_environment_key(monkeypatch):
    monkeypatch.setenv("SCALEDOWN_API_KEY", "environment-key")

    def handler(request):
        assert str(request.url) == "https://proxy.example/tenant/v1/decide"
        assert request.headers["x-api-key"] == "environment-key"
        return httpx2.Response(200, json=wire({"type": "noul", "noul": 0.5}))

    with ScaleDownProvider(
        endpoint_url="https://proxy.example/tenant/v1/decide",
        transport=httpx2.MockTransport(handler),
    ) as client:
        assert client.noul(state={}, question="Valid?").p_yes == 0.5


def test_usage_metadata_validates_cost():
    with pytest.raises(ValueError, match="cost_usd"):
        UsageMetadata(cost_usd=float("nan"))
    with pytest.raises(ValueError, match="cost_usd"):
        UsageMetadata(cost_usd=-0.01)
