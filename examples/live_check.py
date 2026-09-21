"""One potentially billable Jev check, without installing or running Mellea."""

import argparse
import json
import os
import sys
from pathlib import Path

from mellea_jev import JevClient, JevError, JevVerifier


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="Hello! Thank you for your message.")
    parser.add_argument("--requirement", default="The candidate contains a polite greeting.")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--model", default=os.environ.get("JEV_MODEL", "jev-latest"))
    parser.add_argument("--accept-at", type=float, default=0.90)
    parser.add_argument("--reject-at", type=float, default=0.10)
    args = parser.parse_args()
    try:
        reference = args.reference_file.read_text(encoding="utf-8") if args.reference_file else None
        with JevClient(model=args.model) as client:
            verifier = JevVerifier(
                client,
                args.requirement,
                reference=reference,
                accept_at=args.accept_at,
                reject_at=args.reject_at,
            )
            verdict = verifier.evaluate(args.candidate)
        print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
        return {"pass": 0, "fail": 1, "uncertain": 2}[verdict.outcome]
    except (JevError, ValueError, OSError) as exc:
        print(f"Check did not complete: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
