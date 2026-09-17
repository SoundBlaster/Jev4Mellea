"""Local Ollama generation + real Jev validation. Jev calls may be billable.

Requires .[mellea], an already-running Ollama server and an installed model.
This end-to-end example was not executed in the build environment.
"""
import os
import sys

from mellea import MelleaSession
from mellea.backends.ollama import OllamaModelBackend
from mellea.core import Requirement
from mellea.stdlib.requirements import simple_validate
from mellea.stdlib.sampling import RepairTemplateStrategy

from mellea_jev import (
    GenerationRejected, JevClient, JevError, JevVerifier, ReviewRequired, accepted_text,
)


def main() -> int:
    model = os.environ.get("OLLAMA_MODEL")
    if not model:
        print("Set OLLAMA_MODEL to an already-installed Ollama model tag.", file=sys.stderr)
        return 3
    source = "The museum opens at 10:00 and closes at 18:00."
    m = MelleaSession(backend=OllamaModelBackend(model_id=model))
    try:
        with JevClient(model=os.environ.get("JEV_MODEL", "jev-latest")) as client:
            verifier = JevVerifier(
                client,
                "The museum opening time stated in the candidate matches the reference.",
                reference=source,
                repair_hint="State only the opening time supported by the reference.",
            )
            sampled = m.instruct(
                "State the museum's opening time in one short sentence, using this source: {{source}}",
                user_variables={"source": source},
                requirements=[
                    Requirement(
                        "Use no more than 25 words.",
                        validation_fn=simple_validate(
                            lambda text: (len(text.split()) <= 25, "Shorten the answer to 25 words.")
                        ),
                    ),
                    verifier.as_requirement(),
                ],
                # Unlike bare rejection sampling, this strategy incorporates repair reasons.
                strategy=RepairTemplateStrategy(loop_budget=3, concurrency_budget=1),
                return_sampling_results=True,
            )
            print(accepted_text(sampled))  # Never print an unvalidated fallback.
        return 0
    except ReviewRequired as exc:
        print(f"Review needed; Jev P(yes)={exc.verdict.p_yes}. No answer accepted.", file=sys.stderr)
        # Optional: send exc.candidate and the trusted source to another verifier.
        # This example deliberately does not make a hidden second-model call.
        return 2
    except GenerationRejected as exc:
        # Mellea may return failure instead of re-raising a later validation error.
        # This branch also needs review/fallback in an application controller.
        print(str(exc), file=sys.stderr)
        return 1
    except (JevError, ValueError) as exc:
        print(f"Validation did not complete: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
