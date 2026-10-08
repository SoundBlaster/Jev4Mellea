"""The parked branch's ProxyAPI runner path is offline-testable and explicit."""

import json

import httpx2
import pytest
from test_evaluation_proxy import dataset

from examples.evaluate import (
    ThresholdPair,
    _run_live,
    load_predictions,
    main,
    save_predictions,
    score_predictions,
)
from mellea_jev.providers import proxyapi


@pytest.mark.parametrize(
    "options,key,label",
    [
        ({}, "proxyapi-key", "proxyapi"),
        (
            {"api_key_env": "SELECTED_PROXY_KEY", "provider_label": "proxyapi-luna"},
            "selected-key",
            "proxyapi-luna",
        ),
    ],
)
@pytest.mark.parametrize("model", [None, "requested-model"])
def test_configuration_snapshot_and_offline_threshold_reuse(
    monkeypatch, tmp_path, options, key, label, model
):
    monkeypatch.setenv("PROXYAPI_API_KEY", "proxyapi-key")
    monkeypatch.setenv("SELECTED_PROXY_KEY", "selected-key")
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == proxyapi.ENDPOINT
        assert request.headers["authorization"] == "Bearer " + key
        payload = json.loads(request.content)
        assert payload["model"] == (model or proxyapi.DEFAULT_MODEL)
        assert payload["state"]["reference"] == "Opens at 10:00."
        assert payload["questions"]["requirement"]["type"] == "noul"
        return httpx2.Response(
            200,
            json={
                "id": "fixture-id",
                "model": "openai/gpt-6-luna-decisions-fixture",
                "answers": {
                    "requirement": {
                        "type": "noul",
                        "noul": 0.98 if payload["state"]["candidate"] == "10:00" else 0.02,
                    }
                },
                "usage": {"input_tokens": 30, "output_tokens": 0},
            },
        )

    real_provider = proxyapi.ProxyAPIProvider
    monkeypatch.setattr(
        proxyapi,
        "ProxyAPIProvider",
        lambda **kwargs: real_provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    predictions = _run_live("proxyapi", model, dataset(), **options)
    snapshot = tmp_path / "predictions.jsonl"
    save_predictions(snapshot, dataset(), predictions)
    assert load_predictions(snapshot, dataset()) == predictions
    assert {p.provider for p in predictions} == {label}
    assert {p.model for p in predictions} == {"openai/gpt-6-luna-decisions-fixture"}
    assert key not in snapshot.read_text()
    rows = score_predictions(
        dataset(), predictions, [ThresholdPair(0.1, 0.9), ThresholdPair(0.2, 0.8)]
    )
    assert len(rows) == 2 and len(calls) == 2
    assert all(
        row.false_acceptance_rate == row.false_rejection_rate == row.uncertain_rate == 0
        for row in rows
    )


@pytest.mark.parametrize("api_key_env", [None, "SELECTED_PROXY_KEY"])
def test_missing_own_or_selected_key_never_falls_back(monkeypatch, api_key_env):
    monkeypatch.delenv("PROXYAPI_API_KEY", raising=False)
    monkeypatch.delenv("SELECTED_PROXY_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("TYPESAFE_API_KEY", "must-not-be-used")
    if api_key_env:
        monkeypatch.setenv("PROXYAPI_API_KEY", "must-not-be-used")
    monkeypatch.setattr(
        proxyapi, "ProxyAPIProvider", lambda **_: pytest.fail("No provider expected")
    )
    with pytest.raises(ValueError, match="selected ProxyAPI key"):
        _run_live("proxyapi", None, dataset(), api_key_env=api_key_env)


def test_fixed_endpoint_rejects_overrides_before_inference(monkeypatch):
    monkeypatch.setattr(
        proxyapi, "ProxyAPIProvider", lambda **_: pytest.fail("No provider expected")
    )
    with pytest.raises(ValueError, match="fixed endpoint"):
        _run_live("proxyapi", None, dataset(), base_url="https://wrong.invalid")
    with pytest.raises(SystemExit) as error:
        main(["unused", "--live", "--provider", "proxyapi", "--base-url", "https://wrong.invalid"])
    assert error.value.code == 2


def test_offline_metrics_do_not_construct_proxyapi_provider(monkeypatch, tmp_path, capsys):
    from examples.evaluate import Prediction, load_dataset

    labeled = load_dataset("examples/evaluation/museum_opening.jsonl")
    snapshot = tmp_path / "snapshot.jsonl"
    save_predictions(
        snapshot,
        labeled,
        [
            Prediction(
                example.id, "proxyapi", "fixture", 0.98 if example.expected == "accept" else 0.02
            )
            for example in labeled.examples
        ],
    )
    monkeypatch.setattr(proxyapi, "ProxyAPIProvider", lambda **_: pytest.fail("Offline only"))
    assert (
        main(
            [
                "examples/evaluation/museum_opening.jsonl",
                "--provider",
                "proxyapi",
                "--predictions",
                str(snapshot),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["results"][0]["uncertain_rate"] == 0


def test_live_cli_stops_at_first_http_failure_without_saving_partial_snapshot(
    monkeypatch, tmp_path, capsys
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(500, text="private body proxyapi-key")

    real_provider = proxyapi.ProxyAPIProvider
    monkeypatch.setenv("PROXYAPI_API_KEY", "proxyapi-key")
    monkeypatch.setattr(
        proxyapi,
        "ProxyAPIProvider",
        lambda **kwargs: real_provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    snapshot = tmp_path / "snapshot.jsonl"
    assert (
        main(
            [
                "examples/evaluation/museum_opening.jsonl",
                "--live",
                "--provider",
                "proxyapi",
                "--save-predictions",
                str(snapshot),
            ]
        )
        == 2
    )
    assert len(calls) == 1 and not snapshot.exists()
    error = capsys.readouterr().err
    assert "proxyapi-key" not in error and "private body" not in error
