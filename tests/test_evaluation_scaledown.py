"""ScaleDown evaluation-runner tests through a local transport; no paid calls."""

import json

import httpx2
import pytest
from test_evaluation_proxy import dataset

import mellea_jev
from examples.evaluate import (
    ThresholdPair,
    _run_live,
    load_predictions,
    main,
    save_predictions,
    score_predictions,
)


def response(p_yes):
    return {
        "model": "classify-1",
        "answers": {"decision": {"type": "noul", "noul": p_yes}},
        "usage": {"input_tokens": 25, "output_tokens": 0, "cost": 0.0001},
    }


def test_scaledown_live_evaluation_saves_predictions_and_reuses_them_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("SCALEDOWN_API_KEY", "scaledown-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    requests = []

    def handler(request):
        assert str(request.url) == "https://api.scaledown.xyz/v1/scaledown"
        assert request.headers["x-api-key"] == "scaledown-test-key"
        payload = json.loads(request.content)
        state = json.loads(payload["state"]["text"])
        requests.append(state)
        assert payload["model"] == "classify-1"
        assert payload["questions"]["decision"]["type"] == "noul"
        return httpx2.Response(200, json=response(0.98 if state["candidate"] == "10:00" else 0.02))

    provider = mellea_jev.ScaleDownProvider
    monkeypatch.setattr(
        mellea_jev,
        "ScaleDownProvider",
        lambda **kwargs: provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    labeled = dataset()
    predictions = _run_live("scaledown", None, labeled)
    assert requests == [
        {"candidate": example.candidate, "reference": example.reference}
        for example in labeled.examples
    ]
    assert {item.provider for item in predictions} == {"scaledown"}
    assert {item.model for item in predictions} == {"classify-1"}

    snapshot = tmp_path / "scaledown-predictions.jsonl"
    save_predictions(snapshot, labeled, predictions)
    assert load_predictions(snapshot, labeled) == predictions
    saved_text = snapshot.read_text()
    assert "scaledown-test-key" not in saved_text
    assert "https://" not in saved_text

    rows = score_predictions(
        labeled, predictions, [ThresholdPair(0.1, 0.9), ThresholdPair(0.2, 0.8)]
    )
    assert len(rows) == 2
    assert all(
        row.provider == "scaledown"
        and row.false_acceptance_count == 0
        and row.false_rejection_count == 0
        and row.uncertain_count == 0
        for row in rows
    )
    assert len(requests) == len(labeled.examples)


def test_scaledown_cli_accepts_exact_proxy_url_with_explicit_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SCALEDOWN_PROXY_KEY", "proxy-key")
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://proxy.example/tenant/decisions/run"
        assert request.headers["x-api-key"] == "proxy-key"
        state = json.loads(json.loads(request.content)["state"]["text"])
        return httpx2.Response(
            200,
            json=response(0.98 if state["candidate"] == "10:00" else 0.02),
        )

    provider = mellea_jev.ScaleDownProvider
    monkeypatch.setattr(
        mellea_jev,
        "ScaleDownProvider",
        lambda **kwargs: provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    snapshot = tmp_path / "predictions.jsonl"
    assert (
        main(
            [
                "examples/evaluation/museum_opening.jsonl",
                "--live",
                "--provider",
                "scaledown",
                "--endpoint-url",
                "https://proxy.example/tenant/decisions/run",
                "--api-key-env",
                "SCALEDOWN_PROXY_KEY",
                "--provider-label",
                "scaledown-proxy",
                "--threshold",
                "0.1,0.9",
                "--save-predictions",
                str(snapshot),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["sample_count"] == 4
    assert report["results"][0]["provider"] == "scaledown-proxy"
    assert report["results"][0]["model"] == "classify-1"
    assert report["results"][0]["false_acceptance_rate"] == 0
    assert len(requests) == 4
    assert "proxy-key" not in snapshot.read_text()


def test_missing_selected_scaledown_key_never_uses_another_provider_key(monkeypatch):
    monkeypatch.delenv("SCALEDOWN_PROXY_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    with pytest.raises(ValueError, match="selected by --api-key-env"):
        _run_live(
            "scaledown",
            None,
            dataset(),
            endpoint_url="https://proxy.example/decisions",
            api_key_env="SCALEDOWN_PROXY_KEY",
        )
