"""Evaluate the synthetic visual reference, offline or with explicit live uploads.

Use --live --save-predictions NEW_FILE for one bounded capture. Replay one or
more complete captures with --predictions FILE; replay never constructs a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns
from typing import TextIO

import mellea_jev
from mellea_jev import ImageInput, JevVerifier, WithImages

if __package__:
    from . import evaluate as metrics
    from . import visual_reference as reference
else:
    import evaluate as metrics
    import visual_reference as reference


@dataclass(frozen=True)
class VisualReference:
    dataset: metrics.LabeledDataset
    images: dict[str, dict[str, ImageInput]]


def load_reference(directory: Path) -> VisualReference:
    """Validate the entire generated bundle, then freeze the exact upload bytes.

    This runner deliberately supports the versioned procedural reference only.
    The generator validates pixels, labels, geometry, and hashes independently
    of predictions; no generic user-photo labeling is inferred here.
    """
    receipt = reference.build(directory, check=True)
    content = (directory / "reference.jsonl").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != receipt["reference_sha256"]:
        raise metrics.EvaluationFormatError("Reference changed during validation.")
    header, *records = [json.loads(line) for line in content.decode().splitlines()]
    examples = []
    images = {}
    for record in records:
        examples.append(
            metrics.LabeledExample(record["id"], record["candidate"], record["expected"])
        )
        attachments = {}
        for name, asset in record["images"].items():
            image = ImageInput.from_file(directory / asset["path"])
            if hashlib.sha256(image.data).hexdigest() != asset["sha256"]:
                raise metrics.EvaluationFormatError("Image changed during validation.")
            attachments[name] = image
        images[record["id"]] = attachments
    return VisualReference(
        metrics.LabeledDataset(
            header["name"],
            header["version"],
            header["requirement"],
            tuple(examples),
            digest,
            header["criteria"],
        ),
        images,
    )


def _identity(dataset: metrics.LabeledDataset) -> dict[str, object]:
    return {
        "type": "visual_prediction_set",
        "format_version": 1,
        "dataset": dataset.name,
        "dataset_version": dataset.version,
        "dataset_sha256": dataset.content_sha256,
    }


def _write(stream: TextIO, record: dict[str, object]) -> None:
    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def _adapter_sources() -> dict[str, str]:
    root = Path(mellea_jev.__file__).parent
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }


def _provider(args: argparse.Namespace):
    # Custom URLs require their own explicitly selected key; no ambient key fallback.
    key = None if args.api_key_env is None else os.environ.get(args.api_key_env, "")
    if key == "":
        raise ValueError("The selected API key environment variable is empty.")
    options = {"timeout": args.timeout, "model": args.model, "api_key": key}
    for name in ("base_url", "endpoint_url"):
        if getattr(args, name) is not None:
            options[name] = getattr(args, name)
    if args.provider == "typesafe":
        from mellea_jev import JevClient

        return JevClient(**options)
    from mellea_jev import OpenAIProvider

    return OpenAIProvider(**options)


def capture(
    bundle: VisualReference, args: argparse.Namespace, thresholds: list[metrics.ThresholdPair]
) -> list[metrics.Prediction]:
    """One sequential call per image; flush successes and fail closed on any error."""
    if len(bundle.dataset.examples) > args.max_requests:
        raise ValueError("Reference exceeds --max-requests; no provider was constructed.")
    custom_url = args.base_url is not None or args.endpoint_url is not None
    label = args.provider_label or (f"{args.provider}-proxy" if custom_url else args.provider)
    header = {
        **_identity(bundle.dataset),
        "capture": {
            "provider": label,
            "protocol": "systemone" if args.provider == "typesafe" else "decisions",
            "requested_model": args.model,
            "started_at": datetime.now(UTC).isoformat(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "metrics_sha256": hashlib.sha256(Path(metrics.__file__).read_bytes()).hexdigest(),
            "adapter_sources": _adapter_sources(),
            "versions": {
                name: version(name)
                for name in (
                    "mellea-jev-adapter",
                    "typesafe-sdk",
                    "httpx2",
                    *(("openai",) if args.provider == "openai" else ()),
                )
            },
        },
    }
    predictions = []
    # Reserve the destination before the first billable call. Never overwrite a receipt.
    with args.save_predictions.open("x", encoding="utf-8") as stream:
        _write(stream, header)
        try:
            with _provider(args) as provider:
                for example in bundle.dataset.examples:
                    verifier = JevVerifier(
                        WithImages(provider, bundle.images[example.id]),
                        bundle.dataset.requirement,
                        criteria=bundle.dataset.criteria,
                    )
                    started = perf_counter_ns()
                    verdict = verifier.evaluate(example.candidate)
                    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
                    prediction = metrics.Prediction(
                        example.id, label, verdict.model, verdict.p_yes, elapsed_ms
                    )
                    predictions.append(prediction)
                    _write(
                        stream,
                        {
                            "type": "visual_prediction",
                            **asdict(prediction),
                            "request_id": verdict.request_id,
                        },
                    )
            # A model change mid-capture must not produce a misleading complete group.
            metrics.score_predictions(bundle.dataset, predictions, thresholds)
        except (Exception, KeyboardInterrupt) as error:
            _write(
                stream,
                {
                    "type": "visual_run",
                    "status": "failed",
                    "count": len(predictions),
                    "error_type": type(error).__name__,
                },
            )
            raise RuntimeError(
                "Capture failed; partial receipt saved. No quality report was produced."
            ) from None
        _write(stream, {"type": "visual_run", "status": "complete", "count": len(predictions)})
    return predictions


def load_capture(path: Path, dataset: metrics.LabeledDataset) -> list[metrics.Prediction]:
    """Accept complete visual captures bound to this exact reference revision only."""
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(records) < 3 or not all(isinstance(record, dict) for record in records):
        raise metrics.EvaluationFormatError("Invalid visual capture records.")
    header, *rows, footer = records
    if (
        type(header.get("format_version")) is not int
        or set(header) != {*_identity(dataset), "capture"}
        or any(header[key] != value for key, value in _identity(dataset).items())
    ):
        raise metrics.EvaluationFormatError("Visual capture does not match the reference.")
    if footer != {"type": "visual_run", "status": "complete", "count": len(rows)}:
        raise metrics.EvaluationFormatError("Visual capture is incomplete; no metrics available.")
    if not isinstance(header["capture"], dict):
        raise metrics.EvaluationFormatError("Missing capture provenance.")
    predictions = []
    for row in rows:
        if (
            set(row)
            != {"type", "example_id", "provider", "model", "p_yes", "elapsed_ms", "request_id"}
            or row["type"] != "visual_prediction"
        ):
            raise metrics.EvaluationFormatError("Invalid visual prediction fields.")
        if row["request_id"] is not None and not isinstance(row["request_id"], str):
            raise metrics.EvaluationFormatError("Invalid request ID.")
        if row["elapsed_ms"] is None:
            raise metrics.EvaluationFormatError("Visual capture requires measured latency.")
        if row["provider"] != header["capture"].get("provider"):
            raise metrics.EvaluationFormatError("Prediction provider differs from capture.")
        predictions.append(
            metrics.Prediction(
                **{key: value for key, value in row.items() if key not in ("type", "request_id")}
            )
        )
    metrics.score_predictions(
        dataset, predictions, [metrics.ThresholdPair(*metrics.DEFAULT_THRESHOLD)]
    )
    return predictions


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, nargs="?", default=reference.ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Opt into billable image uploads")
    mode.add_argument("--predictions", type=Path, action="append", help="Replay complete captures")
    parser.add_argument(
        "--save-predictions", type=Path, help="Required NEW receipt file for --live"
    )
    parser.add_argument("--provider", choices=("typesafe", "openai"))
    parser.add_argument("--model", type=metrics._nonempty_argument)
    connection = parser.add_mutually_exclusive_group()
    for name in ("base-url", "endpoint-url"):
        connection.add_argument(f"--{name}", type=metrics._nonempty_argument)
    parser.add_argument("--api-key-env", type=metrics._nonempty_argument)
    parser.add_argument("--provider-label", type=metrics._nonempty_argument)
    parser.add_argument("--max-requests", type=_positive, default=12)
    parser.add_argument("--timeout", type=_positive, default=30, help="Per-call timeout in seconds")
    parser.add_argument("--threshold", action="append", type=metrics._threshold)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.live and args.save_predictions is None:
        parser.error("--live requires --save-predictions to a new file.")
    if not args.live and any(
        getattr(args, name) is not None
        for name in (
            "save_predictions",
            "provider",
            "model",
            "base_url",
            "endpoint_url",
            "api_key_env",
            "provider_label",
        )
    ):
        parser.error("Provider connection options and --save-predictions require --live.")
    if (args.base_url is not None or args.endpoint_url is not None) and args.api_key_env is None:
        parser.error("Custom URLs require an explicit --api-key-env.")
    thresholds = args.threshold or [metrics.ThresholdPair(*metrics.DEFAULT_THRESHOLD)]
    try:
        bundle = load_reference(args.reference)
        args.provider = args.provider or "typesafe"
        args.model = args.model or ("jev-1.14.0" if args.provider == "typesafe" else "gpt-6-luna")
        predictions = (
            capture(bundle, args, thresholds)
            if args.live
            else [
                prediction
                for path in args.predictions
                for prediction in load_capture(path, bundle.dataset)
            ]
        )
        report = metrics.build_report(bundle.dataset, predictions, thresholds)
        report["mode"] = "live" if args.live else "offline"
        report["provider_requests"] = len(predictions) if args.live else 0
        report["visual_reference"] = {
            "annotation_method": "rectangle-intersection",
            "human_adjudicated": False,
            "scope": "12 correlated synthetic diagrams; not photographs or parking-law labels.",
            "assets_validated": True,
        }
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, ImportError) as error:
        # Never print provider response bodies, URLs, or credential-bearing exceptions.
        print(
            f"visual evaluation failed ({type(error).__name__}); check inputs/receipt.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
