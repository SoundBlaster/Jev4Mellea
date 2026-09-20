"""Adapter from Laya-MLX's local System One interface to provider contracts.

The optional ``laya-mlx`` package is never imported here. Pass an already loaded
agent, which also keeps tests independent of MLX and model checkpoint downloads.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, Sequence

from ..contracts import ChoiceCriteria, NoulCriteria
from ..criteria import (
    normalize_choice_criteria,
    normalize_noul_criteria,
    normalize_score_criteria,
    probability,
)
from ..results import (
    ChoiceResult,
    NoulResult,
    ScoreResult,
    UsageMetadata,
)

_ANSWER_ID = "mellea"


class LayaAgent(Protocol):
    """The small part of a loaded Laya agent used by this provider."""

    def system_one(
        self,
        state: dict[str, Any],
        questions: dict[str, dict[str, Any]],
    ) -> Mapping[str, Any]: ...


class LayaProtocolError(RuntimeError):
    """Laya returned a response that does not match the decision contract."""


class LayaProvider:
    """Expose a loaded Laya-MLX agent through the Noul, Choice, and Score APIs."""

    def __init__(self, agent: LayaAgent) -> None:
        if not callable(getattr(agent, "system_one", None)):
            raise TypeError("agent must expose a callable system_one(state, questions).")
        self.agent = agent

    def _evaluate(
        self,
        *,
        kind: str,
        state: dict[str, Any],
        question: str,
        criteria: object = None,
    ) -> tuple[Mapping[str, Any], str, UsageMetadata | None]:
        if not isinstance(state, dict):
            raise TypeError("state must be a dictionary.")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be nonempty text.")

        definition: dict[str, Any] = {"type": kind, "instructions": question}
        if criteria is not None:
            definition["criteria"] = criteria
        response = self.agent.system_one(state, {_ANSWER_ID: definition})
        if not isinstance(response, Mapping):
            raise LayaProtocolError("Laya returned a malformed response envelope.")
        model = response.get("model")
        answers = response.get("answers")
        if not isinstance(model, str) or not model.strip():
            raise LayaProtocolError("Laya response is missing its model name.")
        if not isinstance(answers, Mapping) or set(answers) != {_ANSWER_ID}:
            raise LayaProtocolError("Laya answer IDs do not match the request.")
        answer = answers[_ANSWER_ID]
        if not isinstance(answer, Mapping) or answer.get("type") != kind:
            raise LayaProtocolError(f"Laya returned a malformed {kind} answer.")
        return answer, model, self._usage(response.get("usage"))

    @staticmethod
    def _usage(value: object) -> UsageMetadata | None:
        if not isinstance(value, Mapping):
            return None
        try:
            return UsageMetadata(
                input_tokens=value.get("input_tokens"),
                output_tokens=value.get("output_tokens"),
            )
        except ValueError:
            # Usage is informational; malformed metadata must not alter a decision.
            return None

    @staticmethod
    def _probabilities(value: object, labels: Sequence[str]) -> dict[str, float]:
        if not isinstance(value, Mapping) or set(value) != set(labels):
            raise LayaProtocolError("Laya probability labels do not match the criteria.")
        probabilities = {label: probability(value[label]) for label in labels}
        total = sum(probabilities.values())
        if total <= 0:
            raise LayaProtocolError("Laya returned an empty probability distribution.")
        # Laya rounds probabilities to four decimal places; normalize rounding drift.
        return {label: value / total for label, value in probabilities.items()}

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResult:
        normalized = normalize_noul_criteria(criteria)
        answer, model, usage = self._evaluate(
            kind="noul", state=state, question=question, criteria=normalized
        )
        try:
            return NoulResult(
                p_yes=probability(answer["noul"]), model=model, usage=usage
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise LayaProtocolError("Laya returned a malformed Noul probability.") from None

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
    ) -> ChoiceResult:
        normalized = normalize_choice_criteria(criteria)
        answer, model, usage = self._evaluate(
            kind="choice", state=state, question=question, criteria=normalized
        )
        try:
            choice = answer["choice"]
            if choice not in normalized:
                raise ValueError
            probabilities = self._probabilities(answer["probabilities"], list(normalized))
            return ChoiceResult(
                choice=choice,
                confidence=probability(answer["confidence"]),
                probabilities=probabilities,
                model=model,
                usage=usage,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise LayaProtocolError("Laya returned a malformed Choice result.") from None

    def score(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Sequence[str],
    ) -> ScoreResult:
        normalized = normalize_score_criteria(criteria)
        answer, model, usage = self._evaluate(
            kind="score", state=state, question=question, criteria=normalized
        )
        expected_keys = {str(level) for level in range(len(normalized))}
        try:
            raw_probabilities = answer["probabilities"]
            raw_legend = answer["legend"]
            if not isinstance(raw_probabilities, Mapping) or set(raw_probabilities) != expected_keys:
                raise ValueError
            if not isinstance(raw_legend, Mapping) or set(raw_legend) != expected_keys:
                raise ValueError
            probabilities_by_key = self._probabilities(
                raw_probabilities,
                [str(level) for level in range(len(normalized))],
            )
            probabilities = {
                int(level): value for level, value in probabilities_by_key.items()
            }
            legend = {int(level): raw_legend[level] for level in raw_legend}
            if legend != dict(enumerate(normalized)):
                raise ValueError
            return ScoreResult(
                score=answer["score"],
                confidence=probability(answer["confidence"]),
                probabilities=probabilities,
                legend=legend,
                model=model,
                usage=usage,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise LayaProtocolError("Laya returned a malformed Score result.") from None
