"""Opt-in CoreInfra contract smoke matrix: at most 12 text + 1 image requests."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from mellea_jev import ImageInput, JevError, OpenAIProviderError, coreinfra_provider

STATE = {
    "candidate": "I was charged twice for my subscription. Refund the duplicate payment today."
}
CHECKS = {
    "noul": {
        "question": "Does the customer report a duplicate charge in `candidate`?",
        "criteria": {
            "true": "A duplicate charge is reported.",
            "false": "No duplicate charge is reported.",
        },
    },
    "choice": {
        "question": "Which team should handle `candidate`?",
        "criteria": {"billing": "Charges and refunds.", "technical": "Software bugs and outages."},
    },
    "score": {
        "question": "How urgent is the issue in `candidate`?",
        "criteria": ["No action needed.", "Needs attention this week.", "Needs attention today."],
    },
}


def _record(results, provider, *, model, protocol, primitive, image=None):
    row = {
        "requested_model": model,
        "protocol": protocol,
        "primitive": primitive,
        "input_kind": "image" if image is not None else "text",
    }
    results.append(row)
    started = time.perf_counter()
    try:
        if image is not None:
            result = provider.noul(
                state={},
                images={"scene": image},
                question="Is a marked pedestrian crossing visible in `images.scene`?",
            )
        else:
            result = getattr(provider, primitive)(state=STATE.copy(), **CHECKS[primitive])
        row.update(status="pass", result=asdict(result))
    except (JevError, OpenAIProviderError) as error:
        row.update(status="error", error=str(error))
        raise
    finally:
        row["elapsed_seconds"] = time.perf_counter() - started


def collect(results, *, jev_model, image):
    for model in (jev_model, "gpt-6-luna"):
        for protocol in ("systemone", "decisions"):
            with coreinfra_provider(model=model, protocol=protocol, timeout=30.0) as provider:
                for primitive in CHECKS:
                    _record(results, provider, model=model, protocol=protocol, primitive=primitive)
    if image is not None:
        with coreinfra_provider(model="gpt-6-luna", protocol="decisions", timeout=30.0) as provider:
            _record(
                results,
                provider,
                model="gpt-6-luna",
                protocol="decisions",
                primitive="noul",
                image=image,
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow potentially billable Hub requests"
    )
    parser.add_argument("--jev-model", default="jev-latest", help="Explicit Jev model or Hub alias")
    parser.add_argument(
        "--image", type=Path, help="Optional prepared PNG/JPEG; uploaded once to Luna Decisions"
    )
    parser.add_argument(
        "--report", type=Path, help="Save the JSON report; may contain partial results"
    )
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Pass --live to allow at most 12 text requests (13 with --image).")
    if not args.jev_model.strip():
        parser.error("--jev-model must be nonempty.")
    # Load the file before the first provider is constructed or request is sent.
    results = []
    report = {
        "format_version": 1,
        "kind": "coreinfra-compatibility",
        "outcome": "pass",
        "planned_calls": 12 + int(args.image is not None),
        "results": results,
    }
    output = None
    try:
        image = None if args.image is None else ImageInput.from_file(args.image)
        if args.report is not None:
            # Refuse an existing/unwritable capture before any billable request.
            output = args.report.open("x", encoding="utf-8")
        collect(results, jev_model=args.jev_model, image=image)
    except (JevError, OpenAIProviderError, OSError, TypeError, ValueError) as error:
        report.update(outcome="error", error=str(error))
    report["attempted_calls"] = len(results)
    report["completed_calls"] = sum(row.get("status") == "pass" for row in results)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(encoded, end="")
    if output is not None:
        try:
            output.write(encoded)
            output.flush()
        except OSError as error:
            print(f"Cannot save compatibility report: {error}", file=sys.stderr)
            return 2
        finally:
            output.close()
    return 0 if report["outcome"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
