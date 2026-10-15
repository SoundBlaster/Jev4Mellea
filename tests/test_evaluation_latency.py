"""Response timing and offline statistics, with deterministic clocks and no paid calls."""

import json
import math
from dataclasses import asdict

import pytest

import examples.evaluate as runner
from mellea_jev import NoulResult

DATASET = "examples/evaluation/museum_opening.jsonl"


def predictions(durations, *, provider="fixture", model="model"):
    return [
        runner.Prediction(f"case-{index}", provider, model, 0.5, elapsed_ms)
        for index, elapsed_ms in enumerate(durations)
    ]


def test_latency_distribution_uses_linear_percentiles_and_population_stddev():
    row = runner.summarize_latency(predictions([40, 10, 30, 20]))[0]
    assert (row.measured_count, row.missing_count) == (4, 0)
    assert row.min_ms == 10
    assert row.max_ms == 40
    assert row.mean_ms == row.median_ms == 25
    assert row.stddev_ms == pytest.approx(math.sqrt(125))
    assert row.p90_ms == pytest.approx(37)
    assert row.p95_ms == pytest.approx(38.5)
    assert row.p99_ms == pytest.approx(39.7)


def test_latency_groups_by_provider_and_returned_model():
    rows = runner.summarize_latency(
        [
            *predictions([10, None], provider="a", model="one"),
            *predictions([20], provider="a", model="two"),
            *predictions([30], provider="b", model="one"),
        ]
    )
    assert [(row.provider, row.model, row.mean_ms) for row in rows] == [
        ("a", "one", 10),
        ("a", "two", 20),
        ("b", "one", 30),
    ]
    assert rows[0].measured_count == rows[0].missing_count == 1
    assert rows[0].stddev_ms == 0


def test_missing_timings_are_unknown_and_single_zero_is_a_valid_measurement():
    missing = runner.summarize_latency(predictions([None, None]))[0]
    assert (missing.measured_count, missing.missing_count) == (0, 2)
    assert all(value is None for key, value in asdict(missing).items() if key.endswith("_ms"))
    measured = runner.summarize_latency(predictions([0]))[0]
    assert (measured.measured_count, measured.missing_count) == (1, 0)
    assert all(value == 0 for key, value in asdict(measured).items() if key.endswith("_ms"))
    assert runner.summarize_latency([]) == []


def test_large_finite_durations_do_not_overflow_summary():
    row = runner.summarize_latency(predictions([1e308, 1e308]))[0]
    assert row.mean_ms == row.median_ms == row.p95_ms == 1e308
    assert row.stddev_ms == 0


@pytest.mark.parametrize(
    "duration", [-1, True, False, "10", float("nan"), float("inf"), float("-inf"), 10**400]
)
def test_invalid_durations_fail_validation(duration):
    with pytest.raises(ValueError, match="elapsed_ms"):
        predictions([duration])


def test_snapshot_v2_roundtrip_preserves_measured_and_missing_latency(tmp_path):
    dataset = runner.load_dataset(DATASET)
    items = [
        runner.Prediction(example.id, "fixture", "model", 0.5, duration)
        for example, duration in zip(dataset.examples, [10.5, None, 0, 99], strict=True)
    ]
    snapshot = tmp_path / "predictions.jsonl"
    runner.save_predictions(snapshot, dataset, items)
    records = [json.loads(line) for line in snapshot.read_text().splitlines()]
    assert records[0]["format_version"] == 2
    assert records[1]["elapsed_ms"] == 10.5
    assert "elapsed_ms" not in records[2]
    assert runner.load_predictions(snapshot, dataset) == items


def test_legacy_snapshots_load_without_fabricating_latency():
    dataset = runner.load_dataset(DATASET)
    items = runner.load_predictions(
        "examples/evaluation/live-predictions-2026-09-21.jsonl", dataset
    )
    assert len(items) == 8
    assert all(item.elapsed_ms is None for item in items)
    rows = runner.summarize_latency(items)
    assert all(row.measured_count == 0 and row.missing_count == 4 for row in rows)


@pytest.mark.parametrize("duration", [-1, True, "secret-invalid", float("nan"), float("inf")])
def test_snapshot_rejects_invalid_timing_without_echoing_contents(tmp_path, duration):
    dataset = runner.load_dataset(DATASET)
    snapshot = tmp_path / "predictions.jsonl"
    runner.save_predictions(snapshot, dataset, [runner.Prediction("correct-time", "a", "m", 0.5)])
    records = [json.loads(line) for line in snapshot.read_text().splitlines()]
    records[1]["elapsed_ms"] = duration
    snapshot.write_text("\n".join(json.dumps(record) for record in records))
    with pytest.raises(runner.EvaluationFormatError, match="invalid prediction") as error:
        runner.load_predictions(snapshot, dataset)
    assert "secret-invalid" not in str(error.value)


@pytest.mark.parametrize("version", [1, 3, True])
def test_timed_snapshots_require_supported_version(tmp_path, version):
    dataset = runner.load_dataset(DATASET)
    snapshot = tmp_path / "predictions.jsonl"
    runner.save_predictions(
        snapshot, dataset, [runner.Prediction("correct-time", "a", "m", 0.5, 10)]
    )
    records = [json.loads(line) for line in snapshot.read_text().splitlines()]
    records[0]["format_version"] = version
    snapshot.write_text("\n".join(json.dumps(record) for record in records))
    with pytest.raises(runner.EvaluationFormatError):
        runner.load_predictions(snapshot, dataset)


def test_cli_measures_calls_once_and_replays_identical_latency_report(
    monkeypatch, tmp_path, capsys
):
    events = []
    ticks = iter(
        [
            0,
            10_000_000,
            100_000_000,
            130_000_000,
            200_000_000,
            250_000_000,
            300_000_000,
            370_000_000,
        ]
    )

    def clock():
        events.append("clock")
        return next(ticks)

    class Provider:
        def noul(self, *, state, question, criteria=None):
            events.append("provider")
            return NoulResult(0.5, "fixture-model")

    def collect(provider_name, model, dataset, **options):
        return runner.collect_predictions(dataset, Provider(), provider_name=provider_name)

    monkeypatch.setattr(runner, "perf_counter_ns", clock)
    monkeypatch.setattr(runner, "_run_live", collect)
    snapshot = tmp_path / "predictions.jsonl"
    thresholds = ["--threshold", "0.10,0.90", "--threshold", "0.20,0.80"]
    assert runner.main([DATASET, "--live", "--save-predictions", str(snapshot), *thresholds]) == 0
    live = json.loads(capsys.readouterr().out)
    assert events == ["clock", "provider", "clock"] * 4
    assert len(live["results"]) == 2
    assert len(live["latency"]["results"]) == 1
    row = live["latency"]["results"][0]
    assert row["measured_count"] == 4 and row["missing_count"] == 0
    assert row["mean_ms"] == row["median_ms"] == 40
    assert row["p95_ms"] == pytest.approx(67)
    assert live["latency"]["unit"] == "ms"
    assert live["latency"]["stddev_method"] == "population"
    assert runner.main([DATASET, "--predictions", str(snapshot), *thresholds]) == 0
    assert json.loads(capsys.readouterr().out) == live
    assert len(events) == 12
