"""One potentially billable TypeSafe or OpenAI check, without running Mellea."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from mellea_jev import JevClient, JevError, JevVerifier, OpenAIProvider, OpenAIProviderError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="Hello! Thank you for your message.")
    parser.add_argument("--requirement", default="The candidate contains a polite greeting.")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--provider", choices=("typesafe", "openai"), default="typesafe")
    parser.add_argument("--model", help="Model name (defaults depend on provider)")
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument("--base-url", help="API root; the SDK appends its operation path")
    connection.add_argument("--endpoint-url", help="Complete operation URL; no path is appended")
    parser.add_argument("--api-key-env", help="Key variable (required for a custom URL)")
    parser.add_argument("--accept-at", type=float, default=0.90)
    parser.add_argument("--reject-at", type=float, default=0.10)
    args = parser.parse_args(argv)
    if (args.base_url is not None or args.endpoint_url is not None) and not args.api_key_env:
        parser.error("--base-url or --endpoint-url requires an explicit --api-key-env.")
    url_options = {
        name: value
        for name, value in (("base_url", args.base_url), ("endpoint_url", args.endpoint_url))
        if value is not None
    }
    provider_type = JevClient if args.provider == "typesafe" else OpenAIProvider
    default_key_env = "TYPESAFE_API_KEY" if args.provider == "typesafe" else "OPENAI_API_KEY"
    default_model = (
        os.environ.get("JEV_MODEL", "jev-latest") if args.provider == "typesafe" else "gpt-6-luna"
    )
    try:
        reference = args.reference_file.read_text(encoding="utf-8") if args.reference_file else None
        with provider_type(
            api_key=os.environ.get(
                default_key_env if args.api_key_env is None else args.api_key_env, ""
            ),
            model=args.model if args.model is not None else default_model,
            **url_options,
        ) as client:
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
    except (JevError, OpenAIProviderError, ValueError, OSError, ImportError) as exc:
        print(f"Check did not complete: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
