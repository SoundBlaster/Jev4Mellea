"""One opt-in, potentially billable image request using Jev Noul, Choice, and Score."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from mellea_jev import (
    ChoiceQuestion,
    ImageInput,
    JevClient,
    JevError,
    NoulQuestion,
    ScoreQuestion,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Prepared PNG/JPEG file to upload")
    parser.add_argument("--model", default="jev-1.14.0")
    args = parser.parse_args(argv)
    try:
        image = ImageInput.from_file(args.image)
        with JevClient(model=args.model) as provider:
            result = provider.system_one(
                state={},
                images={"scene": image},
                questions={
                    "vehicle_visible": NoulQuestion("Is a vehicle visible in `images.scene`?"),
                    "scene_type": ChoiceQuestion(
                        "What kind of scene is shown in `images.scene`?",
                        {"road": "A road or street.", "document": "A document.", "other": "Other."},
                    ),
                    "legibility": ScoreQuestion(
                        "How clearly can the main objects in `images.scene` be distinguished?",
                        [
                            "Indistinguishable.",
                            "Partly distinguishable.",
                            "Clearly distinguishable.",
                        ],
                    ),
                },
            )
    except (JevError, OSError, TypeError, ValueError) as error:
        print(f"image check failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
