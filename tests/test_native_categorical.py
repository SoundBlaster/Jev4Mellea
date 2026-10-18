"""Native wrappers use real SDK serialization with one mocked HTTP request."""

import json
from unittest.mock import Mock

import httpx2
import pytest
from test_openai_choice import choice_wire

from mellea_jev import (
    CapabilityMismatchError,
    CategoricalProvider,
    CategoricalTask,
    ChoiceQuestion,
    ChoiceResult,
    JevClassifier,
    JevHTTPError,
    JevProtocolError,
    OpenAICategoricalProvider,
    OpenAIHTTPError,
    OpenAIProtocolError,
    OpenAIProvider,
    TypeSafeCategoricalProvider,
    TypeSafeProvider,
    UsageMetadata,
)


def task(batch=False):
    questions = {
        "task-original-id": ChoiceQuestion(
            "Which team handles the supplied ticket?",
            {"billing": {"examples": ["Refund", "Счёт"]}, "technical": ["Crashes", None]},
        )
    }
    if batch:
        questions["second"] = ChoiceQuestion("Second?", {"x": None, "y": None})
    return CategoricalTask(
        state={"source": {"ticket": "Charged twice"}, "candidate": ["typed", {"fact": False}]},
        questions=questions,
    )


def wire(family, name="task-original-id"):
    if family == "typesafe":
        return {
            "model": "actual-native-model",
            "answers": {
                name: {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.82,
                    "probabilities": {"billing": 0.88, "technical": 0.12},
                }
            },
            "usage": {"input_tokens": 42, "output_tokens": 0},
        }
    body = choice_wire(
        name=name,
        confidence=0.82,
        probabilities=[
            {"value": "billing", "probability": 0.88},
            {"value": "technical", "probability": 0.12},
        ],
    )
    body["model"] = "actual-native-model"
    return body


@pytest.fixture(params=["typesafe", "openai"])
def family(request):
    return request.param


def wrap(family, transport):
    provider_type = TypeSafeProvider if family == "typesafe" else OpenAIProvider
    wrapper_type = (
        TypeSafeCategoricalProvider if family == "typesafe" else OpenAICategoricalProvider
    )
    provider = provider_type(
        "fixture-key",
        model="requested-alias",
        endpoint_url="https://proxy.example/custom/native-operation",
        transport=transport,
    )
    return provider, wrapper_type(provider)


def test_one_request_preserves_task_ids_order_and_native_evidence(family, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            200,
            json=wire(family),
            headers={"x-typesafe-request-id": "request-native", "x-request-id": "request-native"},
        )

    provider, adapter = wrap(family, httpx2.MockTransport(handler))
    native_calls = []
    method = "system_one" if family == "typesafe" else "_choice_with_name"
    original = getattr(provider, method)

    def capture(**kwargs):
        value = original(**kwargs)
        native_calls.append(value)
        return value

    monkeypatch.setattr(provider, method, capture)
    closed = Mock(wraps=provider.close)
    monkeypatch.setattr(provider, "close", closed)
    with provider:
        assert calls == []
        categorical: CategoricalProvider = adapter
        value = task()
        snapshot = value.to_dict()
        result = categorical.classify(value)
        assert len(calls) == len(native_calls) == 1
        assert str(calls[0].url) == "https://proxy.example/custom/native-operation"
        assert calls[0].headers["authorization"] == "Bearer fixture-key"
        submitted = json.loads(calls[0].content)
        assert submitted["model"] == result.requested_model == "requested-alias"
        if family == "typesafe":
            assert submitted["state"] == value.state
            assert submitted["questions"] == {
                "task-original-id": value.questions["task-original-id"].to_payload()
            }
            native = native_calls[0].answers["task-original-id"]
        else:
            assert json.loads(submitted["input"]) == value.state
            question = submitted["questions"][0]
            assert question["name"] == "task-original-id"
            assert question["instructions"] == value.questions["task-original-id"].instructions
            assert [c["value"] for c in question["choices"]] == ["billing", "technical"]
            assert [json.loads(c["description"]) for c in question["choices"]] == [
                {"examples": ["Refund", "Счёт"]},
                ["Crashes", None],
            ]
            native = native_calls[0]
        assert result.native_results["task-original-id"] is native
        assert native.confidence == 0.82 and native.probabilities["billing"] == 0.88
        assert result.answers == {"task-original-id": "billing"}
        assert result.returned_model == "actual-native-model"
        assert result.request_id == "request-native" and result.usage == UsageMetadata(42, 0)
        assert result.evidence is None and result.settings is None
        assert not hasattr(result, "confidence") and not hasattr(result, "probabilities")
        assert adapter.capabilities.native_distribution
        assert not adapter.capabilities.shared_state_batch
        assert not adapter.capabilities.strict_schema
        assert snapshot == value.to_dict()
        closed.assert_not_called()
    closed.assert_called_once()


def test_unsupported_batch_and_legacy_use_fail_before_dispatch(family):
    calls = []
    provider, adapter = wrap(family, httpx2.MockTransport(lambda request: calls.append(request)))
    with provider:
        with pytest.raises(CapabilityMismatchError):
            adapter.classify(task(batch=True))
        with pytest.raises(TypeError):
            adapter.classify({})
        with pytest.raises(CapabilityMismatchError):
            JevClassifier(adapter, "Q?", criteria={"a": None, "b": None})
    assert calls == []


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_operational_error_is_not_rejection_and_is_not_retried(family, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(status, text="fixture-key", headers={"location": "https://other"})

    provider, adapter = wrap(family, httpx2.MockTransport(handler))
    with provider:
        with pytest.raises(JevHTTPError if family == "typesafe" else OpenAIHTTPError):
            adapter.classify(task())
    assert len(calls) == 1


@pytest.mark.parametrize("malformation", ["wrong-id", "wrong-labels"])
def test_malformed_native_result_fails_without_projection_or_retry(family, malformation):
    body = wire(family, "wrong-id" if malformation == "wrong-id" else "task-original-id")
    if malformation == "wrong-labels":
        if family == "typesafe":
            body["answers"]["task-original-id"]["probabilities"] = {"other": 1}
        else:
            body["answers"][0]["probabilities"] = [{"value": "other", "probability": 1}]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json=body)

    provider, adapter = wrap(family, httpx2.MockTransport(handler))
    with provider:
        with pytest.raises(JevProtocolError if family == "typesafe" else OpenAIProtocolError):
            adapter.classify(task())
    assert len(calls) == 1


def test_single_request_metadata_is_not_invented_when_unavailable(family, monkeypatch):
    provider, adapter = wrap(family, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    native = ChoiceResult("billing", 0.8, {"billing": 0.9, "technical": 0.1}, "actual")
    if family == "typesafe":
        from mellea_jev import SystemOneResult

        monkeypatch.setattr(
            provider,
            "system_one",
            lambda **_: SystemOneResult({"task-original-id": native}, "actual"),
        )
    else:
        monkeypatch.setattr(provider, "_choice_with_name", lambda **_: native)
    with provider:
        result = adapter.classify(task())
    assert result.request_id is None and result.usage is None
    assert result.native_results["task-original-id"] is native


def test_typesafe_requested_model_tracks_the_actual_submitted_model():
    def handler(request):
        assert json.loads(request.content)["model"] == "updated-alias"
        return httpx2.Response(200, json=wire("typesafe"))

    provider, adapter = wrap("typesafe", httpx2.MockTransport(handler))
    with provider:
        provider.model = "updated-alias"
        assert adapter.classify(task()).requested_model == "updated-alias"


def test_typesafe_wrapper_does_not_project_a_non_choice_answer(monkeypatch):
    from mellea_jev import NoulResult, SystemOneResult

    provider, adapter = wrap("typesafe", httpx2.MockTransport(lambda _: httpx2.Response(500)))
    monkeypatch.setattr(
        provider,
        "system_one",
        lambda **_: SystemOneResult({"task-original-id": NoulResult(0.9, "actual")}, "actual"),
    )
    with provider, pytest.raises(JevProtocolError, match="Choice"):
        adapter.classify(task())


@pytest.mark.parametrize("wrapper", [TypeSafeCategoricalProvider, OpenAICategoricalProvider])
def test_wrapper_rejects_incompatible_provider_without_dispatch(wrapper):
    with pytest.raises(TypeError):
        wrapper(object())
