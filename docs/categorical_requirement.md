# Native categorical providers and the optional Mellea bridge

Implemented for proposal [#66](https://github.com/SoundBlaster/Jev4Mellea/issues/66).
These additions are available starting with version 0.9.0. Install with
`pip install 'mellea-jev-adapter[mellea,openai]>=0.9.0'`. The
underlying categorical/Responses API is available in 0.8.0.
No dependencies or existing primitive signatures are changed.

## Choose an interface

| Interface | Output | Questions per request | Existing native Mellea helpers |
| --- | --- | --- | --- |
| `TypeSafeProvider` / `OpenAIProvider` | Native Noul/Choice/Score results | Existing primitive APIs | Supported |
| `TypeSafeCategoricalProvider(native)` | Labels plus original native Choice evidence | Exactly one | Use the categorical bridge |
| `OpenAICategoricalProvider(native)` | Labels plus original native Choice evidence | Exactly one | Use the categorical bridge |
| `ResponsesChoiceProvider` | Labels; no native probabilities/confidence | One or several over shared state | Use the categorical bridge |

Both native wrappers declare `CategoricalCapabilities(False, False, True)`:
no ordinary-generation strict JSON Schema, no shared-state batch support in
these wrappers, and actual native distributions. A multi-question task raises
`CapabilityMismatchError` before dispatch, even though native System One has a
separate batch API. No wrapper loops over questions or falls back to another API.
The existing Responses batch contract is unchanged.

## Compose a native provider

The following example sends one potentially billable request. Configure
credentials outside source code.

```python
from mellea_jev import (
    CategoricalTask,
    ChoiceQuestion,
    TypeSafeProvider,
    TypeSafeCategoricalProvider,
)

task = CategoricalTask(
    state={"source": "The museum opens at 10:00.", "candidate": {"opens_at": "12:00"}},
    questions={
        "support": ChoiceQuestion(
            "Does the candidate agree with the source?",
            {
                "supported": "The source supports the candidate.",
                "unsupported": "The candidate contradicts the source.",
                "unknown": "The available facts do not settle the question.",
            },
        )
    },
)
with TypeSafeProvider(model="jev-latest") as native:
    provider = TypeSafeCategoricalProvider(native)
    result = provider.classify(task)
    label = result.answers["support"]
    original_choice = result.native_results["support"]
```

For native OpenAI Decisions, compose `OpenAICategoricalProvider(native)` inside
`with OpenAIProvider(model="gpt-6-luna") as native:`. Existing `base_url`,
`endpoint_url`, auth, timeout, HTTP transport and no-retry behavior come from the
borrowed provider. The caller owns its lifetime: wrappers do not close it.

The original task's ID, JSON state, instructions and category ordering are
preserved. OpenAI's existing mapping encodes structured descriptions as JSON
text; it is reused without flattening their meaning. Native results retain their
original confidence and distributions, separately from categorical labels.
Requested/returned model are distinct. One-request usage is copied, never summed
from per-answer counts; absent metadata stays absent when the underlying native
contract permits it. Native adapters still reject malformed required SDK fields.
The wrappers do not add sensitive raw payload capture; `evidence` remains
`None`, while `native_results` contains the original validated `ChoiceResult`.

## Bind candidate/context explicitly

`CategoricalRequirement` composes a provider, a `task_builder(ctx)`, a
`policy(result)`, and an optional `on_evaluated(evaluation)` observer.
It does not infer source context, parse arbitrary prompts, change task state,
add reference/gold answers to input, or create a generation backend.

```python
from mellea_jev import CategoricalDecision, CategoricalRequirement


def task_builder(ctx):
    output = ctx.last_output()
    if output is None:
        raise ValueError("No candidate to classify.")
    return CategoricalTask(
        state={"source": task.state["source"], "candidate": {"text": output.value}},
        questions=task.questions,
    )


def policy(result):
    # Application acceptance policy, not a per-case reference label.
    label = result.answers["support"]
    if label == "unknown":
        return CategoricalDecision("review", "The application needs more evidence.")
    if label == "unsupported":
        return CategoricalDecision("reject", "Revise the unsupported fact.")
    return CategoricalDecision("accept", "The application accepts this category.")


# provider is a caller-owned categorical provider; classification happens only
# when evaluate() or the resulting Mellea Requirement is validated.
evaluations = []
bridge = CategoricalRequirement(
    provider,
    task_builder=task_builder,
    policy=policy,
    description="The candidate must satisfy the application's acceptance policy.",
    on_evaluated=evaluations.append,  # Optional application-owned in-memory capture.
)
requirement = bridge.as_requirement()  # Requires the optional Mellea dependency.
```

`as_requirement(check_only=True)` is the default: Mellea excludes the
description from the generation instruction's requirements. Explicit
`check_only=False` opts into normal prompt guidance. Check-only does not disable
Mellea's own logs or caller-selected repair strategies: a rejection reason may
be used as repair feedback. Keep source/target data out of reasons/descriptions
unless the application intends to disclose it.

The task builder receives the actual Mellea validation context and decides how
to bind it. It may preserve a typed candidate instead of using the textual
example above. Missing output or invalid binding is an error, not an invented
semantic rejection. It must return a `CategoricalTask`; results are checked
against that task's exact IDs and configured labels before policy execution.

## Keep outcomes separate

| Policy/operation | `bridge.evaluate(ctx)` | Real `Requirement.validate(...)` |
| --- | --- | --- |
| `accept` | `CategoricalEvaluation` | Successful `ValidationResult` |
| `reject` | `CategoricalEvaluation` | Failed `ValidationResult` with caller reason |
| `review` | `CategoricalEvaluation` | Raises `CategoricalReviewRequired` |
| Provider, binding, policy or observer failure | Original exception propagates | Original exception propagates |
| Mismatched categorical IDs/labels | `CategoricalProtocolError` | Same error propagates |

A model label such as `indeterminate` is just a category. Only the supplied
policy assigns acceptance/rejection/review meaning. A label-only decision's
score stays `None`. A policy may explicitly select a meaningful finite score
from actual `native_results` (for example, a native confidence or selected-label
probability). A policy score without native evidence raises
`CapabilityMismatchError`; no 1.0 confidence or one-hot distribution is invented.
The library does not validate a caller's calibration or semantic score meaning.

`CategoricalEvaluation` retains the exact bound task, original result and policy
decision. A review exception retains it as `error.evaluation`. Observers run
once after a successful classification/policy evaluation, including review.
They are synchronous application code; their exceptions are not swallowed.
Transport failures produce no completed evaluation and keep their original
exception/evidence contract. Nothing is automatically logged, archived or sent
to another provider by this bridge.

The signal guarantee is at `Requirement.validate`. Mellea sampling strategies
may catch exceptions after earlier failed attempts or combine concurrent
branches. For deterministic classification escalation, use explicit
`evaluate(ctx)` or direct `classify(task)` in consumer code. Do not infer
rejection from a generic unsuccessful sampling result or reuse a fallback
candidate as accepted output. The offline tests exercise both real hooks and
a bounded deterministic generation/validation flow on supported Mellea versions.

## Consumer-controlled escalation with a total call budget

This example is direct classification: the budget covers **all provider calls**
in the example, including a failed or unknown-outcome attempt. There is no
generation call. Applications adding generation, verifiers, retries, concurrency
or time/spend limits must account for those operations in their own global
budget too. The example confidence threshold is application policy, not a
recommended universal setting.

```python
from dataclasses import dataclass
from mellea_jev import CategoricalEvaluation, CategoricalReviewRequired


@dataclass
class CallBudget:
    limit: int
    reserved: int = 0

    def classify(self, provider, task):
        if self.reserved >= self.limit:
            raise RuntimeError("Classification call budget exhausted.")
        self.reserved += 1  # Reserve before dispatch, including timeout/error.
        return provider.classify(task)


def escalation_policy(result):
    native = result.native_results
    if native is not None and native["support"].confidence < 0.90:
        return CategoricalDecision("review", "Caller requires another source.")
    return policy(result)  # Same category policy defined above.


# primary/secondary are explicit caller-owned categorical providers.
# Both receive this same task; no generation history or expected answer is added.
budget = CallBudget(limit=2)
evaluations = []
result = budget.classify(primary, task)
decision = escalation_policy(result)
evaluations.append(CategoricalEvaluation(task, result, decision))
if decision.outcome == "review":
    result = budget.classify(secondary, task)
    decision = escalation_policy(result)
    evaluations.append(CategoricalEvaluation(task, result, decision))
if decision.outcome == "review":
    raise CategoricalReviewRequired(evaluations[-1])
```

Operational errors propagate immediately: this code does not spend the second
call after a transport failure. A final reject stays reject; budget exhaustion
or unresolved review never becomes acceptance. The application owns these
reservations, provider order, policy, optional captures and any later routing.

SOFAI remains outside this adapter: classifier providers are not Mellea text
generation `Backend` instances. A typed categorical action/backend, async
cancellation and general routing framework are separate proposals.

References: [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice),
[Python SDK](https://docs.typesafe.ai/sdk/python), and the
[Responses categorical contract](categorical.md).
