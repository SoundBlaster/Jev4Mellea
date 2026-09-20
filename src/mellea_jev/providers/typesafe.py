"""TypeSafe HTTP provider implementing the package's primitive contracts."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

from ..contracts import (
    ChoiceCriteria,
    ChoiceDescription,
    NoulCriteria,
)
from ..criteria import (
    normalize_choice_criteria,
    normalize_noul_criteria,
    normalize_score_criteria,
    probability,
)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
QUESTION_ID = "requirement"
CHOICE_QUESTION_ID = "classification"
SCORE_QUESTION_ID = "rating"

class JevError(RuntimeError):
    """A transport or API-contract failure, not a semantic rejection."""


class JevHTTPError(JevError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"TypeSafe returned HTTP {status_code}; validation did not complete.")


class JevProtocolError(JevError):
    """The server response does not satisfy the expected TypeSafe contract."""


@dataclass(frozen=True)
class TypeSafeUsage:
    """Optional request usage metadata reported by TypeSafe."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None.")


def _validate_usage(value: TypeSafeUsage | None) -> None:
    if value is not None and not isinstance(value, TypeSafeUsage):
        raise ValueError("usage must be TypeSafeUsage or None.")


@dataclass(frozen=True)
class NoulResult:
    p_yes: float
    model: str
    request_id: str | None = None
    usage: TypeSafeUsage | None = None

    def __post_init__(self) -> None:
        probability(self.p_yes)
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Expected a nonempty response model name.")
        _validate_usage(self.usage)


@dataclass(frozen=True)
class ChoiceResult:
    choice: str
    confidence: float
    probabilities: dict[str, float]
    model: str
    request_id: str | None = None
    usage: TypeSafeUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.choice, str) or not self.choice.strip():
            raise ValueError("Expected a nonempty selected choice.")
        confidence = probability(self.confidence)
        if not isinstance(self.probabilities, dict) or not self.probabilities:
            raise ValueError("Expected a nonempty choice probability map.")
        probabilities = {
            label: probability(value) for label, value in self.probabilities.items()
        }
        if any(not isinstance(label, str) or not label.strip() for label in probabilities):
            raise ValueError("Choice probability labels must be nonempty strings.")
        if self.choice not in probabilities:
            raise ValueError("Selected choice is missing from its probability map.")
        if not math.isclose(sum(probabilities.values()), 1.0, rel_tol=0.0, abs_tol=1e-3):
            raise ValueError("Choice probabilities must sum to 1.")
        if probabilities[self.choice] != max(probabilities.values()):
            raise ValueError("Selected choice must have the highest probability.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Expected a nonempty response model name.")
        _validate_usage(self.usage)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "probabilities", probabilities)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    confidence: float
    probabilities: dict[int, float]
    legend: dict[int, str]
    model: str
    request_id: str | None = None
    usage: TypeSafeUsage | None = None

    def __post_init__(self) -> None:
        if type(self.score) not in (int, float) or not math.isfinite(self.score):
            raise ValueError("Expected a finite numeric score.")
        probability(self.confidence)
        if not isinstance(self.probabilities, dict) or len(self.probabilities) < 2:
            raise ValueError("Expected a nonempty score probability map.")
        probabilities = {
            level: probability(value) for level, value in self.probabilities.items()
        }
        if any(type(level) is not int or level < 0 for level in probabilities):
            raise ValueError("Score levels must be nonnegative integers.")
        if set(probabilities) != set(range(len(probabilities))):
            raise ValueError("Score levels must be contiguous and start at zero.")
        if not 0 <= self.score <= len(probabilities) - 1:
            raise ValueError("Score must fall within the configured level range.")
        if not math.isclose(sum(probabilities.values()), 1.0, rel_tol=0.0, abs_tol=1e-3):
            raise ValueError("Score probabilities must sum to 1.")
        expected_score = sum(level * value for level, value in probabilities.items())
        if not math.isclose(float(self.score), expected_score, rel_tol=0.0, abs_tol=0.02):
            raise ValueError("Score must match the probability-weighted level average.")
        if not isinstance(self.legend, dict) or set(self.legend) != set(probabilities):
            raise ValueError("Score legend must describe every configured level.")
        if any(not isinstance(text, str) or not text.strip() for text in self.legend.values()):
            raise ValueError("Score legend descriptions must be nonempty strings.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Expected a nonempty response model name.")
        _validate_usage(self.usage)
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "probabilities", probabilities)


@dataclass(frozen=True)
class NoulQuestion:
    instructions: str
    criteria: NoulCriteria | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be nonempty text.")
        object.__setattr__(self, "criteria", _noul_criteria(self.criteria))

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": "noul", "instructions": self.instructions}
        if self.criteria is not None:
            payload["criteria"] = _noul_criteria(self.criteria)
        return payload


@dataclass(frozen=True)
class ChoiceQuestion:
    instructions: str
    criteria: ChoiceCriteria

    def __post_init__(self) -> None:
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be nonempty text.")
        object.__setattr__(self, "criteria", _choice_criteria(self.criteria))

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": _choice_criteria(self.criteria),
        }


@dataclass(frozen=True)
class ScoreQuestion:
    instructions: str
    criteria: Sequence[str]

    def __post_init__(self) -> None:
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be nonempty text.")
        object.__setattr__(self, "criteria", tuple(_score_criteria(self.criteria)))

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "score",
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


TypeSafeQuestion = NoulQuestion | ChoiceQuestion | ScoreQuestion
TypeSafeAnswer = NoulResult | ChoiceResult | ScoreResult


@dataclass(frozen=True)
class SystemOneResult:
    answers: Mapping[str, TypeSafeAnswer]
    model: str
    request_id: str | None = None
    usage: TypeSafeUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.answers, Mapping) or not self.answers:
            raise ValueError("Expected at least one TypeSafe answer.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Expected a nonempty response model name.")
        _validate_usage(self.usage)
        object.__setattr__(self, "answers", dict(self.answers))


def _choice_criteria(criteria: ChoiceCriteria) -> dict[str, ChoiceDescription | None]:
    normalized = normalize_choice_criteria(criteria)
    if len(normalized) > 255:
        raise ValueError("TypeSafe Choice supports at most 255 options.")
    return normalized


def _noul_criteria(criteria: NoulCriteria | None) -> NoulCriteria | None:
    return normalize_noul_criteria(criteria)


def _score_criteria(criteria: Sequence[str]) -> list[str]:
    normalized = normalize_score_criteria(criteria)
    if len(normalized) > 10:
        raise ValueError("TypeSafe Score requires between 2 and 10 levels.")
    return normalized


def _score_response_map(value: object, level_count: int) -> dict[int, Any]:
    expected_keys = {str(level) for level in range(level_count)}
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError("Score response keys must exactly match the configured levels.")
    return {level: value[str(level)] for level in range(level_count)}


def _parse_answer(
    question: TypeSafeQuestion,
    answer: object,
    *,
    model: str,
    request_id: str | None,
    usage: TypeSafeUsage | None,
) -> TypeSafeAnswer:
    if not isinstance(answer, dict):
        raise ValueError("Each answer must be an object.")
    if isinstance(question, NoulQuestion):
        if answer.get("type") != "noul":
            raise ValueError("Expected a Noul answer.")
        return NoulResult(
            p_yes=probability(answer["noul"]), model=model, request_id=request_id,
            usage=usage,
        )
    if isinstance(question, ChoiceQuestion):
        if answer.get("type") != "choice":
            raise ValueError("Expected a Choice answer.")
        result = ChoiceResult(
            choice=answer["choice"],
            confidence=probability(answer["confidence"]),
            probabilities=answer["probabilities"],
            model=model,
            request_id=request_id,
            usage=usage,
        )
        if set(result.probabilities) != set(question.criteria) or result.choice not in question.criteria:
            raise ValueError("Choice answer labels do not match the requested criteria.")
        return result
    if isinstance(question, ScoreQuestion):
        if answer.get("type") != "score":
            raise ValueError("Expected a Score answer.")
        probabilities = _score_response_map(answer["probabilities"], len(question.criteria))
        legend = _score_response_map(answer["legend"], len(question.criteria))
        result = ScoreResult(
            score=answer["score"],
            confidence=probability(answer["confidence"]),
            probabilities=probabilities,
            legend=legend,
            model=model,
            request_id=request_id,
            usage=usage,
        )
        if result.legend != dict(enumerate(question.criteria)):
            raise ValueError("Score legend does not match the requested criteria.")
        return result
    raise TypeError("Unsupported TypeSafe question.")


class TypeSafeProvider:
    """Synchronous TypeSafe provider with single and batched question methods.

    Only the official HTTPS endpoint is used. ``transport`` is a trusted
    dependency-injection hook for tests, not an untrusted per-request option.
    There are no hidden retries. HTTP timeout is per operation, not an
    end-to-end wall-clock deadline. Close with a context manager.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "jev-latest",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = os.environ.get("TYPESAFE_API_KEY", "") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Set TYPESAFE_API_KEY or supply api_key.")
        if any(ch.isspace() for ch in key) or not key.isascii():
            raise ValueError("API key must be ASCII without whitespace.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonempty string.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive.")
        self.model = model
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: Mapping[str, TypeSafeQuestion],
    ) -> SystemOneResult:
        """Evaluate one or more named primitive questions in a single HTTP request."""
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        if not isinstance(questions, Mapping) or not questions:
            raise ValueError("questions must be a nonempty mapping of IDs to question types.")
        normalized_questions: dict[str, TypeSafeQuestion] = {}
        for question_id, question in questions.items():
            if not isinstance(question_id, str) or not question_id.strip():
                raise ValueError("Question IDs must be nonempty strings.")
            if not isinstance(question, (NoulQuestion, ChoiceQuestion, ScoreQuestion)):
                raise TypeError("questions must contain NoulQuestion, ChoiceQuestion, or ScoreQuestion values.")
            normalized_questions[question_id] = question

        try:
            response = self._http.post(
                ENDPOINT,
                json={
                    "model": self.model,
                    "state": state,
                    "questions": {
                        question_id: question.to_payload()
                        for question_id, question in normalized_questions.items()
                    },
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JevHTTPError(exc.response.status_code) from None
        except httpx.RequestError:
            raise JevError("TypeSafe transport failed; validation did not complete.") from None

        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                raise ValueError
            raw_answers = data["answers"]
            if set(raw_answers) != set(normalized_questions):
                raise ValueError("Answer IDs do not match the request.")
            model = data["model"]
            raw_usage = data.get("usage")
            if raw_usage is None:
                usage = None
            elif isinstance(raw_usage, dict):
                usage = TypeSafeUsage(
                    input_tokens=raw_usage.get("input_tokens"),
                    output_tokens=raw_usage.get("output_tokens"),
                )
            else:
                raise ValueError("Usage metadata must be an object or null.")
            request_id = response.headers.get("x-typesafe-request-id")
            answers = {
                question_id: _parse_answer(
                    question,
                    raw_answers[question_id],
                    model=model,
                    request_id=request_id,
                    usage=usage,
                )
                for question_id, question in normalized_questions.items()
            }
            return SystemOneResult(answers, model, request_id, usage)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise JevProtocolError("Malformed TypeSafe response; refusing to return answers.") from None

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResult:
        """Return P(yes). Exceptions never include the response body or API key."""
        result = self.system_one(
            state=state, questions={QUESTION_ID: NoulQuestion(question, criteria)}
        ).answers[QUESTION_ID]
        if not isinstance(result, NoulResult):
            raise JevProtocolError("Malformed TypeSafe Noul response; refusing to accept.")
        return result

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
    ) -> ChoiceResult:
        """Select one configured class and return its distribution and confidence."""
        result = self.system_one(
            state=state,
            questions={CHOICE_QUESTION_ID: ChoiceQuestion(question, criteria)},
        ).answers[CHOICE_QUESTION_ID]
        if not isinstance(result, ChoiceResult):
            raise JevProtocolError("Malformed TypeSafe Choice response; refusing to classify.")
        return result

    def score(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Sequence[str],
    ) -> ScoreResult:
        """Rate the state against ordered levels and return the full distribution."""
        result = self.system_one(
            state=state,
            questions={SCORE_QUESTION_ID: ScoreQuestion(question, criteria)},
        ).answers[SCORE_QUESTION_ID]
        if not isinstance(result, ScoreResult):
            raise JevProtocolError("Malformed TypeSafe Score response; refusing to score.")
        return result

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TypeSafeProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# Keep the established name as an exact alias for existing integrations.
JevClient = TypeSafeProvider
