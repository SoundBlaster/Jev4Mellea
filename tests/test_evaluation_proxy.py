import json

import httpx2
import pytest

import mellea_jev
from examples.evaluate import (
    LabeledDataset,
    LabeledExample,
    Prediction,
    ThresholdPair,
    _run_live,
    load_predictions,
    main,
    save_predictions,
    score_predictions,
)


def dataset():
    return LabeledDataset(
        name="proxy-fixture",
        version="1",
        requirement="The candidate matches the reference.",
        examples=(
            LabeledExample("positive", "10:00", "accept", "Opens at 10:00."),
            LabeledExample("negative", "09:00", "reject", "Opens at 10:00."),
        ),
        content_sha256="fixture-hash",
    )


@pytest.mark.parametrize(
    "options,endpoint,key,label",
    [
        ({}, "https://api.typesafe.ai/v1/systemone", "official-test-key", "typesafe"),
        (
            {"base_url": "https://proxy.example/typesafe/api", "api_key_env": "PROXY_API_KEY"},
            "https://proxy.example/typesafe/api/v1/systemone",
            "proxy-test-key",
            "typesafe-proxy",
        ),
        (
            {
                "base_url": "https://proxy.example/typesafe/api",
                "api_key_env": "PROXY_API_KEY",
                "provider_label": "typesafe-proxy-a",
            },
            "https://proxy.example/typesafe/api/v1/systemone",
            "proxy-test-key",
            "typesafe-proxy-a",
        ),
    ],
)
def test_live_configuration_and_snapshot_roundtrip(
    monkeypatch, tmp_path, options, endpoint, key, label
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "official-test-key")
    monkeypatch.setenv("PROXY_API_KEY", "proxy-test-key")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://untrusted.example")
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == endpoint
        assert request.headers["authorization"] == "Bearer " + key
        payload = json.loads(request.content)
        assert payload["model"] == "jev-requested"
        assert payload["state"]["reference"] == "Opens at 10:00."
        return httpx2.Response(
            200,
            json={
                "model": "jev-returned",
                "answers": {
                    "requirement": {
                        "type": "noul",
                        "noul": 0.98 if payload["state"]["candidate"] == "10:00" else 0.02,
                    }
                },
            },
        )

    real_client = mellea_jev.JevClient
    monkeypatch.setattr(
        mellea_jev,
        "JevClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    labeled = dataset()
    predictions = _run_live("typesafe", "jev-requested", labeled, **options)
    assert len(requests) == 2
    assert {p.provider for p in predictions} == {label}
    assert {p.model for p in predictions} == {"jev-returned"}
    snapshot = tmp_path / "predictions.jsonl"
    save_predictions(snapshot, labeled, predictions)
    assert load_predictions(snapshot, labeled) == predictions
    assert key not in snapshot.read_text()
    assert "https://" not in snapshot.read_text()
    rows = score_predictions(
        labeled,
        predictions,
        [ThresholdPair(0.10, 0.90), ThresholdPair(0.20, 0.80)],
    )
    assert len(rows) == 2
    assert all(row.provider == label and row.false_acceptance_count == 0 for row in rows)
    assert len(requests) == 2  # Threshold sweeps do not repeat inference.


@pytest.mark.parametrize(
    "mode,options",
    [
        (["--predictions", "unused.jsonl"], ["--base-url", "https://proxy.example"]),
        (["--predictions", "unused.jsonl"], ["--api-key-env", "PROXY_API_KEY"]),
        (["--predictions", "unused.jsonl"], ["--provider-label", "proxy-a"]),
        (["--live", "--provider", "laya"], ["--base-url", "https://proxy.example"]),
        (["--live", "--provider", "laya"], ["--api-key-env", "PROXY_API_KEY"]),
        (["--live"], ["--base-url", "https://proxy.example"]),
        (["--live"], ["--provider-label", " "]),
        (["--live"], ["--api-key-env", ""]),
    ],
)
def test_invalid_cli_configuration_fails_before_loading_or_inference(mode, options):
    with pytest.raises(SystemExit) as exc:
        main(["nonexistent-dataset.jsonl", *mode, *options])
    assert exc.value.code == 2


def test_missing_selected_key_does_not_fall_back_to_official_key(monkeypatch):
    monkeypatch.delenv("PROXY_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "official-test-key")
    with pytest.raises(ValueError, match="selected by --api-key-env"):
        _run_live(
            "typesafe",
            None,
            dataset(),
            base_url="https://proxy.example/typesafe/api",
            api_key_env="PROXY_API_KEY",
        )


def test_sources_with_same_model_remain_separate():
    predictions = [
        Prediction(example.id, source, "same-model", 0.98 if example.expected == "accept" else 0.02)
        for source in ("typesafe", "typesafe-proxy-a", "typesafe-proxy-b")
        for example in dataset().examples
    ]
    rows = score_predictions(dataset(), predictions, [ThresholdPair(0.10, 0.90)])
    assert {row.provider for row in rows} == {"typesafe", "typesafe-proxy-a", "typesafe-proxy-b"}


def test_cli_forwards_proxy_options_and_offline_scoring_reuses_snapshot(
    monkeypatch, tmp_path, capsys
):
    import examples.evaluate as runner

    calls = []

    def collect(provider_name, model, dataset, **options):
        calls.append((provider_name, model, options))
        return [
            Prediction(
                example.id,
                options["provider_label"],
                "jev-returned",
                0.98 if example.expected == "accept" else 0.02,
            )
            for example in dataset.examples
        ]

    monkeypatch.setattr(runner, "_run_live", collect)
    source = "examples/evaluation/museum_opening.jsonl"
    snapshot = tmp_path / "proxy-predictions.jsonl"
    thresholds = ["--threshold", "0.10,0.90", "--threshold", "0.20,0.80"]
    assert (
        main(
            [
                source,
                "--live",
                "--provider",
                "typesafe",
                "--model",
                "jev-requested",
                "--base-url",
                "https://proxy.example/typesafe/api",
                "--api-key-env",
                "PROXY_API_KEY",
                "--provider-label",
                "proxy-a",
                "--save-predictions",
                str(snapshot),
                *thresholds,
            ]
        )
        == 0
    )
    live_report = json.loads(capsys.readouterr().out)
    assert calls == [
        (
            "typesafe",
            "jev-requested",
            {
                "base_url": "https://proxy.example/typesafe/api",
                "api_key_env": "PROXY_API_KEY",
                "provider_label": "proxy-a",
            },
        )
    ]
    assert main([source, "--predictions", str(snapshot), *thresholds]) == 0
    assert json.loads(capsys.readouterr().out) == live_report
    assert len(calls) == 1
