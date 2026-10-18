"""Caller-owned categorical policy with a lazy optional Mellea Requirement bridge."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .categorical import (
    CapabilityMismatchError,
    CategoricalProvider,
    CategoricalResult,
    CategoricalTask,
    project_choice_results,
)

if TYPE_CHECKING:
    from mellea.core import Context, Requirement, ValidationResult


class CategoricalProtocolError(ValueError):
    """A provider result violates the bound task; not a semantic rejection."""


@dataclass(frozen=True)
class CategoricalDecision:
    """Application policy, distinct from category labels and native confidence.

    A score is optional and may only be used with actual native evidence.
    The caller chooses its meaning; the bridge does not generate a score.
    """

    outcome: Literal["accept", "reject", "review"]
    reason: str = field(repr=False)
    score: float | None = None

    def __post_init__(self) -> None:
        if self.outcome not in ("accept", "reject", "review"):
            raise ValueError("Policy outcome must be accept, reject, or review.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Policy reason must be nonempty text.")
        if self.score is not None and (
            type(self.score) not in (int, float) or not math.isfinite(self.score)
        ):
            raise ValueError("Policy score must be finite numeric native evidence or None.")


@dataclass(frozen=True)
class CategoricalEvaluation:
    """Explicit task/result/policy binding; never automatically logged or stored."""

    task: CategoricalTask = field(repr=False)
    result: CategoricalResult = field(repr=False)
    decision: CategoricalDecision = field(repr=False)


class CategoricalReviewRequired(RuntimeError):
    """Explicit review signal retaining the full evaluation without printing it."""

    def __init__(self, evaluation: CategoricalEvaluation) -> None:
        self.evaluation = evaluation
        super().__init__("Categorical policy requires explicit review.")


class CategoricalRequirement:
    """Compose task binding, one classification, and a caller-supplied policy.

    Construction/evaluate do not import Mellea. Only as_requirement needs it.
    The task builder owns source/candidate/context binding; no state is inferred,
    rewritten, or recovered from arbitrary prompts by this bridge.
    """

    def __init__(
        self,
        provider: CategoricalProvider,
        *,
        task_builder: Callable[[Context], CategoricalTask],
        policy: Callable[[CategoricalResult], CategoricalDecision],
        description: str,
        on_evaluated: Callable[[CategoricalEvaluation], None] | None = None,
    ) -> None:
        if not callable(getattr(provider, "classify", None)):
            raise CapabilityMismatchError("Supply a categorical provider with classify(task).")
        if not callable(task_builder) or not callable(policy):
            raise TypeError("task_builder and policy must be callable.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be nonempty text.")
        if on_evaluated is not None and not callable(on_evaluated):
            raise TypeError("on_evaluated must be callable or None.")
        self.provider = provider
        self.task_builder = task_builder
        self.policy = policy
        self.description = description
        self.on_evaluated = on_evaluated

    def evaluate(self, ctx: Context) -> CategoricalEvaluation:
        """One explicit classification, with review represented as data here.

        Provider, builder, policy and observer exceptions propagate unchanged.
        No judge, logging, repair, fallback, retry or persistence is added.
        """
        task = self.task_builder(ctx)
        if not isinstance(task, CategoricalTask):
            raise TypeError("task_builder must return a CategoricalTask.")
        result = self.provider.classify(task)
        if not isinstance(result, CategoricalResult):
            raise TypeError("Provider must return a CategoricalResult.")
        questions = task.questions
        if set(result.answers) != set(questions) or any(
            label not in questions[name].criteria for name, label in result.answers.items()
        ):
            raise CategoricalProtocolError("Categorical answer IDs/labels do not match the task.")
        if result.native_results is not None:
            # Reuse native validation without replacing the original evidence.
            project_choice_results(task, result.native_results)
        decision = self.policy(result)
        if not isinstance(decision, CategoricalDecision):
            raise TypeError("policy must return a CategoricalDecision.")
        if decision.score is not None and result.native_results is None:
            raise CapabilityMismatchError("A policy score requires actual native Choice evidence.")
        evaluation = CategoricalEvaluation(task, result, decision)
        if self.on_evaluated is not None:
            self.on_evaluated(evaluation)
        return evaluation

    def as_requirement(self, *, check_only: bool = True) -> Requirement:
        """Create a real Mellea Requirement; validation guidance is hidden by default.

        At Requirement.validate, review raises CategoricalReviewRequired and
        operational exceptions propagate. Sampling strategies can catch errors;
        consumers needing guaranteed routing should call evaluate explicitly.
        """
        from mellea.core import Requirement, ValidationResult

        def validate(ctx: Context) -> ValidationResult:
            evaluation = self.evaluate(ctx)
            decision = evaluation.decision
            if decision.outcome == "review":
                raise CategoricalReviewRequired(evaluation)
            return ValidationResult(
                decision.outcome == "accept", reason=decision.reason, score=decision.score
            )

        return Requirement(self.description, validation_fn=validate, check_only=check_only)
