# Mellea × Jev

A small Python adapter that brings TypeSafe Jev's semantic checks into
[Mellea](https://github.com/generative-computing/mellea). Use Jev to verify
generated text, classify it into your labels, or rate it on a scale. Mellea
continues to manage generation and repair.

- **Verify requirements** with Jev Noul and configurable accept/reject thresholds.
- **Classify text** with TypeSafe Choice and caller-defined categories.
- **Score text** on an ordered scale with TypeSafe Score.
- **Ask several questions in one request** and inspect returned token usage.
- **Connect checks to Mellea `Requirement`s** so they can participate in sampling.

This is an unofficial, synchronous adapter. Jev evaluates text; it does not
generate or repair it.

## Quick start

Install from a checkout and set an API key from the
[TypeSafe console](https://console.typesafe.ai/). Live requests may incur
charges.

```bash
git clone https://github.com/SoundBlaster/Jev4Mellea.git
cd Jev4Mellea
make install
export TYPESAFE_API_KEY='your-key'
```

The Makefile defaults to Python 3.13. To use another supported interpreter,
run `make install PYTHON=python3.11` (or set `PYTHON` to your installed version).

Ask whether a candidate meets a positive requirement:

```python
from mellea_jev import JevClient, JevVerifier

with JevClient() as jev:
    verifier = JevVerifier(
        jev,
        "The answer gives the museum's opening time from the reference.",
        reference="The museum opens at 10:00 and closes at 18:00.",
    )
    verdict = verifier.evaluate("The museum opens at 10:00.")
    print(verdict.outcome, verdict.p_yes)
```

`outcome` is `pass`, `fail`, or `uncertain`. Use `verifier.as_requirement()` to
attach the same check to a Mellea generation flow. Once the project dependencies
are installed, `make demo` runs without a key or network access using a mocked
Jev response.

## Examples

### Verify a requirement with Noul

Noul returns `p_yes`, the probability that a positively phrased requirement is
satisfied. The adapter uses two configurable thresholds; the space between
them is uncertain and is never silently accepted.

```python
from mellea_jev import JevClient, JevVerifier

with JevClient() as jev:
    verifier = JevVerifier(
        jev,
        "The candidate states the opening time supported by the reference.",
        reference="The museum opens at 10:00.",
        criteria={
            "true": "The candidate gives 10:00 as the opening time.",
            "false": "The candidate omits or contradicts the opening time.",
        },
        accept_at=0.90,
        reject_at=0.10,
        repair_hint="Use the opening time stated in the reference.",
    )
    verdict = verifier.evaluate("The museum opens at 10:00.")

    if verdict.outcome == "uncertain":
        print("Route for another check or human review")
```

The threshold values are application policy, not accuracy guarantees. Noul does
not return a separate confidence field or a textual explanation.

To use the verifier as a Mellea requirement:

```python
requirement = verifier.as_requirement()
```

For generation and repair with a real Mellea session, see
[`examples/mellea_ollama.py`](examples/mellea_ollama.py). That example uses
Ollama for generation and Jev for verification.

### Classify into configured categories with Choice

Choice selects one label from the supplied criteria and returns its confidence
and the probability of every label. Descriptions may be strings, JSON objects,
arrays, or `None`.

```python
from mellea_jev import JevClient, JevClassifier

criteria = {
    "billing": {"what": "Payments, invoices, or refunds", "examples": ["duplicate charge"]},
    "technical": "Product errors or problems using the service",
    "other": None,
}

with JevClient() as jev:
    classifier = JevClassifier(
        jev,
        "Choose the best category for this support message.",
        criteria=criteria,
    )
    result = classifier.classify("I was charged twice for my subscription.")
    print(result.choice, result.confidence, result.probabilities)
```

To require a Mellea candidate to be assigned to a particular category:

```python
requirement = classifier.as_requirement(
    "billing",
    minimum_confidence=0.75,
)
```

Confidence thresholds are caller policy. TypeSafe supports up to 255 Choice
labels.

### Rate text on an ordered scale with Score

Score returns a probability-weighted position on an ordered scale. The result
can fall between two levels.

```python
from mellea_jev import JevClient, JevScorer

levels = ["Cosmetic", "Workaround exists", "Blocking"]

with JevClient() as jev:
    scorer = JevScorer(
        jev,
        "How severe is the reported issue?",
        criteria=levels,
    )
    result = scorer.evaluate("The export button crashes and there is no workaround.")
    print(result.score, result.confidence, result.probabilities)
```

The result can also become a Mellea requirement with inclusive score bounds:

```python
requirement = scorer.as_requirement(
    minimum_score=1.0,
    maximum_score=2.0,
    minimum_confidence=0.6,
)
```

Score supports 2–10 ordered string descriptions.

### Batch questions and read usage metadata

`JevClient.system_one()` sends named Noul, Choice, and Score questions in one
request. Each answer remains a typed result. The returned usage counts are
informational and do not affect validation.

```python
from mellea_jev import ChoiceQuestion, JevClient, NoulQuestion

with JevClient() as jev:
    result = jev.system_one(
        state={"candidate": "I was charged twice and cannot log in."},
        questions={
            "urgent": NoulQuestion("Does the message convey urgency?"),
            "team": ChoiceQuestion(
                "Which team should handle this?",
                {"billing": "Payments and invoices", "technical": "Product errors"},
            ),
        },
    )

    print(result.answers["urgent"].p_yes)
    print(result.answers["team"].choice)
    if result.usage is not None:
        print(result.usage.input_tokens, result.usage.output_tokens)
```

For one-off checks without the Mellea helper classes, call the client methods
directly. Each method sends its own request:

```python
with JevClient() as jev:
    yes_no = jev.noul(
        state={"candidate": "The museum opens at 10:00."},
        question="Does the candidate state the opening time?",
    )
    category = jev.choice(
        state={"candidate": "I was charged twice."},
        question="Choose a category.",
        criteria={"billing": "Payments", "technical": "Product errors"},
    )
    rating = jev.score(
        state={"candidate": "The export is broken."},
        question="Rate the impact.",
        criteria=["minor", "major"],
    )
```

The single-question result objects also expose optional usage metadata.

### Use a check during Mellea generation

For an existing Mellea session `m`, pass the adapter's requirement to
`instruct()`. Keep the Jev client open until sampling finishes because the
requirement calls it during validation:

```python
from mellea.stdlib.sampling import RepairTemplateStrategy
from mellea_jev import JevClient, JevVerifier, accepted_text

with JevClient() as jev:
    verifier = JevVerifier(
        jev,
        "The candidate states the opening time supported by the source.",
        reference="The museum opens at 10:00.",
    )
    sampled = m.instruct(
        "State the museum's opening time using this source: {{source}}",
        user_variables={"source": "The museum opens at 10:00."},
        requirements=[verifier.as_requirement()],
        strategy=RepairTemplateStrategy(loop_budget=3, concurrency_budget=1),
        return_sampling_results=True,
    )
    answer = accepted_text(sampled)
```

`accepted_text()` checks the final validation state before returning text. Do
not return `sampled.result` directly after failed or incomplete sampling.

## Requirements and compatibility

- Python **3.11 or newer**.
- Mellea **0.7.0** for the `Requirement` integration.
- TypeSafe API access and `TYPESAFE_API_KEY` for live Jev requests. Mocked tests and `make demo` need no key.
- The adapter uses TypeSafe's HTTPS API through HTTPX; the official TypeSafe Python SDK is not required.

The Mellea requirement callback is synchronous, so a Jev request can block the
event loop. This package does not provide an async client. If sampling has
already seen a failed candidate, Mellea may return a failed sampling result
instead of propagating a later Jev error or uncertain verdict; inspect the
final result with `accepted_text()`. See [API notes](API_NOTES.md) for external
contracts and [test report](TEST_REPORT.md) for the evidence behind the current
prototype status.

The Mellea helpers depend on small structural protocols: `NoulProvider`,
`ChoiceProvider`, and `ScoreProvider` (or the combined `PrimitiveProvider`). A
custom backend can implement only the primitive it needs; it does not need to
inherit from a package class. Its response must expose the fields in
`NoulResponse`, `ChoiceResponse`, or `ScoreResponse`. The current criteria
shapes follow the TypeSafe request model, and each provider may impose its own
limits. Batched requests remain a TypeSafe feature. Use `JevClient` as the
existing compatible name, or import `TypeSafeProvider` explicitly from
`mellea_jev.providers`. See [provider contracts](src/mellea_jev/contracts.py).

## Development and further reading

```bash
make help    # list the repository commands
make check   # run the local test suite and whitespace check
make demo    # run without API keys or network access
```

- [API notes and source references](API_NOTES.md)
- [Test report and validation limits](TEST_REPORT.md)
- [Development commands](Makefile)
- [Roadmap](roadmap.md)
- [Offline demo](examples/offline_demo.py)
- [Live Jev example](examples/live_check.py)

Before using the adapter with private data, account for the fact that candidate
text and any supplied reference are sent to TypeSafe. The adapter does not log
request bodies or API keys, and it does not follow redirects or retry requests
automatically. See the [API notes](API_NOTES.md) for details.

Licensed under MIT. This project is unofficial and is not affiliated with Mellea, IBM, or TypeSafe.
