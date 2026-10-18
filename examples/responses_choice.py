"""One opt-in Responses request containing two categorical questions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from mellea_jev import (
    CategoricalTask,
    ChoiceQuestion,
    ResponsesChoiceProvider,
    ResponsesProviderError,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow one potentially billable call")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    route = parser.add_mutually_exclusive_group()
    route.add_argument("--base-url")
    route.add_argument("--endpoint-url")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--max-output-tokens", type=int, default=512)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Pass --live to allow one potentially billable request.")
    task = CategoricalTask(
        state={"ticket": "The checkout page goes blank when I click Pay."},
        questions={
            "team": ChoiceQuestion(
                "Which team should handle this ticket?",
                {
                    "frontend": "Page rendering or browser behavior.",
                    "payments": "Payment processing or billing.",
                    "unknown": "The evidence does not establish a team.",
                },
            ),
            "kind": ChoiceQuestion(
                "What kind of request is this?",
                {
                    "bug": "Unexpected or broken behavior.",
                    "feature": "A request for new functionality.",
                    "unknown": "Insufficient evidence.",
                },
            ),
        },
    )
    options = {
        name: getattr(args, name)
        for name in ("base_url", "endpoint_url")
        if getattr(args, name) is not None
    }
    try:
        with ResponsesChoiceProvider(
            model=args.model,
            api_key_env=args.api_key_env,
            reasoning_effort=args.reasoning_effort,
            max_output_tokens=args.max_output_tokens,
            **options,
        ) as provider:
            result = provider.classify(task)
    except (ValueError, ResponsesProviderError) as error:
        print(f"categorical check failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "answers": dict(result.answers),
                "requested_model": result.requested_model,
                "returned_model": result.returned_model,
                "request_id": result.request_id,
                "usage": asdict(result.usage) if result.usage is not None else None,
                "adapter_revision": result.adapter_revision,
                "settings": dict(result.settings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
