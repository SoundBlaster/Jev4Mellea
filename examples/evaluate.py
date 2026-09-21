"""Evaluate saved Noul predictions offline or opt in to model inference.

The default path reads a labeled JSONL dataset and a prediction snapshot. It
never constructs a provider or makes a request. Pass ``--live`` to run the
dataset through a provider explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from mellea_jev.contracts import NoulCriteria, NoulProvider
from mellea_jev.criteria import normalize_noul_criteria, probability
from mellea_jev.verifier import JevVerifier

FORMAT_VERSION = 1
DEFAULT_THRESHOLD = (0.10, 0.90)  # reject_at, accept_at
ExpectedOutcome = Literal["accept", "reject"]


class EvaluationFormatError(ValueError):
    """A dataset or prediction file does not match the documented JSONL format."""


@dataclass(frozen=True)
class LabeledExample:
    id: str
    candidate: str
    expected: ExpectedOutcome
    reference: str | None = None


@dataclass(frozen=True)
class LabeledDataset:
    name: str
    version: str
    requirement: str
    examples: tuple[LabeledExample, ...]
    content_sha256: str
    criteria: NoulCriteria | None = None


@dataclass(frozen=True)
class ThresholdPair:
    reject_at: float
    accept_at: float

    def __post_init__(self) -> None:
        reject_at = probability(self.reject_at)
        accept_at = probability(self.accept_at)
        if not reject_at < 0.5 < accept_at:
            raise ValueError("Thresholds must satisfy 0 <= reject_at < 0.5 < accept_at <= 1.")
        object.__setattr__(self, "reject_at", reject_at)
        object.__setattr__(self, "accept_at", accept_at)


@dataclass(frozen=True)
class Prediction:
    example_id: str
    provider: str
    model: str
    p_yes: float

    def __post_init__(self) -> None:
        for field in ("example_id", "provider", "model"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be nonempty text.")
        object.__setattr__(self, "p_yes", probability(self.p_yes))


@dataclass(frozen=True)
class MetricRow:
    provider: str
    model: str
    threshold: ThresholdPair
    sample_count: int
    positive_count: int
    negative_count: int
    false_acceptance_count: int
    false_acceptance_rate: float | None
    false_rejection_count: int
    false_rejection_rate: float | None
    uncertain_count: int
    uncertain_rate: float


def _object(line: str, line_number: int, path: Path) -> dict[str, object]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EvaluationFormatError(f"{path}:{line_number}: invalid JSON.") from exc
    if not isinstance(value, dict):
        raise EvaluationFormatError(f"{path}:{line_number}: each record must be a JSON object.")
    return value


def _keys(
    record: dict[str, object], required: set[str], optional: set[str], path: Path, line: int
) -> None:
    if not required <= record.keys() or record.keys() - required - optional:
        raise EvaluationFormatError(f"{path}:{line}: record fields do not match the format.")


def _text(record: dict[str, object], key: str, path: Path, line: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationFormatError(f"{path}:{line}: '{key}' must be nonempty text.")
    return value


def load_dataset(path: str | Path) -> LabeledDataset:
    """Load a versioned JSONL dataset; fail with line context, never row contents."""
    source = Path(path)
    content = source.read_bytes()
    records = [
        (number, raw)
        for number, raw in enumerate(content.decode("utf-8").splitlines(), start=1)
        if raw.strip()
    ]
    if not records:
        raise EvaluationFormatError(f"{source}: dataset is empty.")
    header_line, header_raw = records[0]
    header = _object(header_raw, header_line, source)
    _keys(
        header,
        {"type", "format_version", "name", "version", "requirement"},
        {"criteria"},
        source,
        header_line,
    )
    if (
        header.get("type") != "dataset"
        or type(header.get("format_version")) is not int
        or header.get("format_version") != FORMAT_VERSION
    ):
        raise EvaluationFormatError(f"{source}:{header_line}: unsupported dataset format version.")
    name = _text(header, "name", source, header_line)
    version = _text(header, "version", source, header_line)
    requirement = _text(header, "requirement", source, header_line)
    criteria: NoulCriteria | None = None
    if "criteria" in header:
        try:
            normalized = normalize_noul_criteria(header["criteria"])
        except (TypeError, ValueError) as exc:
            raise EvaluationFormatError(f"{source}:{header_line}: invalid Noul criteria.") from exc
        if normalized is None:
            raise EvaluationFormatError(f"{source}:{header_line}: criteria must not be empty.")
        criteria = normalized

    examples: list[LabeledExample] = []
    ids: set[str] = set()
    for line_number, raw in records[1:]:
        record = _object(raw, line_number, source)
        _keys(
            record,
            {"type", "id", "candidate", "expected"},
            {"reference"},
            source,
            line_number,
        )
        if record.get("type") != "example":
            raise EvaluationFormatError(f"{source}:{line_number}: expected an example record.")
        example_id = _text(record, "id", source, line_number)
        if example_id in ids:
            raise EvaluationFormatError(f"{source}:{line_number}: duplicate example id.")
        ids.add(example_id)
        candidate = _text(record, "candidate", source, line_number)
        expected = record.get("expected")
        if expected not in ("accept", "reject"):
            raise EvaluationFormatError(
                f"{source}:{line_number}: expected must be accept or reject."
            )
        reference: str | None = None
        if "reference" in record:
            reference = record["reference"]  # type: ignore[assignment]
            if not isinstance(reference, str):
                raise EvaluationFormatError(f"{source}:{line_number}: reference must be text.")
        examples.append(LabeledExample(example_id, candidate, expected, reference))
    if not examples:
        raise EvaluationFormatError(f"{source}: dataset must contain at least one example.")
    if not any(example.expected == "accept" for example in examples):
        raise EvaluationFormatError(f"{source}: dataset needs at least one expected accept.")
    if not any(example.expected == "reject" for example in examples):
        raise EvaluationFormatError(f"{source}: dataset needs at least one expected reject.")
    return LabeledDataset(
        name,
        version,
        requirement,
        tuple(examples),
        hashlib.sha256(content).hexdigest(),
        criteria,
    )


def collect_predictions(
    dataset: LabeledDataset,
    provider: NoulProvider,
    *,
    provider_name: str,
) -> list[Prediction]:
    """Call a provider once per example and retain raw P(yes) for threshold sweeps."""
    predictions: list[Prediction] = []
    for example in dataset.examples:
        verifier = JevVerifier(
            provider,
            dataset.requirement,
            reference=example.reference,
            criteria=dataset.criteria,
        )
        verdict = verifier.evaluate(example.candidate)
        if verdict.p_yes is None or verdict.model is None:
            raise RuntimeError(f"Provider returned no judgment for example '{example.id}'.")
        predictions.append(Prediction(example.id, provider_name, verdict.model, verdict.p_yes))
    return predictions


def score_predictions(
    dataset: LabeledDataset,
    predictions: Sequence[Prediction],
    thresholds: Sequence[ThresholdPair],
) -> list[MetricRow]:
    """Compute FAR, FRR, and uncertainty by provider, returned model, and threshold pair."""
    if not thresholds:
        raise ValueError("At least one threshold pair is required.")
    expected_ids = {example.id for example in dataset.examples}
    positive_count = sum(example.expected == "accept" for example in dataset.examples)
    negative_count = sum(example.expected == "reject" for example in dataset.examples)
    if not expected_ids or not positive_count or not negative_count:
        raise EvaluationFormatError("Dataset must contain positive and negative examples.")
    grouped: dict[tuple[str, str], dict[str, Prediction]] = defaultdict(dict)
    for prediction in predictions:
        key = (prediction.provider, prediction.model)
        if prediction.example_id not in expected_ids:
            raise EvaluationFormatError(
                f"Prediction references unknown example '{prediction.example_id}'."
            )
        if prediction.example_id in grouped[key]:
            raise EvaluationFormatError(
                f"Duplicate prediction for {prediction.provider}/{prediction.model}: "
                f"'{prediction.example_id}'."
            )
        grouped[key][prediction.example_id] = prediction
    if not grouped:
        raise EvaluationFormatError("No predictions were supplied.")

    rows: list[MetricRow] = []
    for (provider, model), by_id in sorted(grouped.items()):
        if set(by_id) != expected_ids:
            raise EvaluationFormatError(
                f"Predictions for {provider}/{model} must contain every dataset example exactly once."
            )
        for threshold in thresholds:
            false_acceptance = false_rejection = uncertain = 0
            for example in dataset.examples:
                p_yes = by_id[example.id].p_yes
                if p_yes >= threshold.accept_at:
                    observed: ExpectedOutcome | Literal["uncertain"] = "accept"
                elif p_yes <= threshold.reject_at:
                    observed = "reject"
                else:
                    observed = "uncertain"
                false_acceptance += example.expected == "reject" and observed == "accept"
                false_rejection += example.expected == "accept" and observed == "reject"
                uncertain += observed == "uncertain"
            rows.append(
                MetricRow(
                    provider=provider,
                    model=model,
                    threshold=threshold,
                    sample_count=len(dataset.examples),
                    positive_count=positive_count,
                    negative_count=negative_count,
                    false_acceptance_count=false_acceptance,
                    false_acceptance_rate=(false_acceptance / negative_count),
                    false_rejection_count=false_rejection,
                    false_rejection_rate=(false_rejection / positive_count),
                    uncertain_count=uncertain,
                    uncertain_rate=uncertain / len(dataset.examples),
                )
            )
    return rows


def load_predictions(path: str | Path, dataset: LabeledDataset) -> list[Prediction]:
    """Load a saved prediction set so thresholds can be compared without new calls."""
    source = Path(path)
    records = [
        (number, raw)
        for number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1)
        if raw.strip()
    ]
    if not records:
        raise EvaluationFormatError(f"{source}: prediction file is empty.")
    header_line, header_raw = records[0]
    header = _object(header_raw, header_line, source)
    _keys(
        header,
        {"type", "format_version", "dataset", "dataset_version", "dataset_sha256"},
        set(),
        source,
        header_line,
    )
    if (
        header.get("type") != "prediction_set"
        or type(header.get("format_version")) is not int
        or header.get("format_version") != FORMAT_VERSION
        or header.get("dataset") != dataset.name
        or header.get("dataset_version") != dataset.version
        or header.get("dataset_sha256") != dataset.content_sha256
    ):
        raise EvaluationFormatError(
            f"{source}:{header_line}: prediction set does not match the dataset."
        )
    predictions: list[Prediction] = []
    for line_number, raw in records[1:]:
        record = _object(raw, line_number, source)
        _keys(record, {"type", "id", "provider", "model", "p_yes"}, set(), source, line_number)
        if record.get("type") != "prediction":
            raise EvaluationFormatError(f"{source}:{line_number}: expected a prediction record.")
        try:
            predictions.append(
                Prediction(
                    example_id=_text(record, "id", source, line_number),
                    provider=_text(record, "provider", source, line_number),
                    model=_text(record, "model", source, line_number),
                    p_yes=record["p_yes"],  # type: ignore[arg-type]
                )
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationFormatError(f"{source}:{line_number}: invalid prediction.") from exc
    return predictions


def save_predictions(
    path: str | Path, dataset: LabeledDataset, predictions: Sequence[Prediction]
) -> None:
    """Persist predictions for offline threshold tuning and reproducible reports."""
    destination = Path(path)
    records = [
        {
            "type": "prediction_set",
            "format_version": FORMAT_VERSION,
            "dataset": dataset.name,
            "dataset_version": dataset.version,
            "dataset_sha256": dataset.content_sha256,
        },
        *(
            {
                "type": "prediction",
                "id": prediction.example_id,
                "provider": prediction.provider,
                "model": prediction.model,
                "p_yes": prediction.p_yes,
            }
            for prediction in predictions
        ),
    ]
    destination.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        ),
        encoding="utf-8",
    )


def _threshold(value: str) -> ThresholdPair:
    try:
        reject, accept = (float(part) for part in value.split(","))
        return ThresholdPair(reject, accept)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("use REJECT_AT,ACCEPT_AT, for example 0.10,0.90") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Versioned labeled-example JSONL file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--predictions", type=Path, help="Score a saved prediction JSONL file offline"
    )
    mode.add_argument("--live", action="store_true", help="Explicitly run model inference")
    parser.add_argument("--provider", choices=("typesafe", "laya"), default="typesafe")
    parser.add_argument("--model", help="Requested model/checkpoint (defaults depend on provider)")
    parser.add_argument(
        "--threshold",
        action="append",
        type=_threshold,
        help="REJECT_AT,ACCEPT_AT; repeat to compare thresholds without repeating inference",
    )
    parser.add_argument(
        "--save-predictions", type=Path, help="Save live raw outputs for offline reuse"
    )
    return parser


def _run_live(provider_name: str, model: str | None, dataset: LabeledDataset) -> list[Prediction]:
    if provider_name == "typesafe":
        from mellea_jev import JevClient

        with JevClient(model=model or "jev-latest") as provider:
            return collect_predictions(dataset, provider, provider_name=provider_name)
    try:
        import laya_mlx
    except ImportError as exc:
        raise RuntimeError("Install the optional backend with `pip install -e '.[laya]'`.") from exc
    from mellea_jev.providers import LayaProvider

    checkpoint = model or "aac6fef/laya-mlx"
    return collect_predictions(
        dataset, LayaProvider(laya_mlx.load(checkpoint)), provider_name=provider_name
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.save_predictions and not args.live:
        parser.error("--save-predictions can only be used with --live.")
    try:
        dataset = load_dataset(args.dataset)
        if args.live:
            predictions = _run_live(args.provider, args.model, dataset)
            if args.save_predictions:
                save_predictions(args.save_predictions, dataset, predictions)
        else:
            predictions = load_predictions(args.predictions, dataset)
        rows = score_predictions(
            dataset, predictions, args.threshold or [ThresholdPair(*DEFAULT_THRESHOLD)]
        )
    except (OSError, UnicodeError, EvaluationFormatError, RuntimeError, ValueError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    report = {
        "dataset": {
            "name": dataset.name,
            "version": dataset.version,
            "sha256": dataset.content_sha256,
        },
        "sample_count": len(dataset.examples),
        "rates": {
            "false_acceptance": "false accepts / expected rejects",
            "false_rejection": "false rejects / expected accepts",
            "uncertain": "uncertain predictions / all examples",
        },
        "results": [asdict(row) for row in rows],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
