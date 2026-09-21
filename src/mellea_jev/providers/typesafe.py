"""TypeSafe HTTP provider implementing the package's primitive contracts."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, cast

import httpx2
from pydantic import ConfigDict, Field
from typesafe_sdk import (
    Choice as SDKChoice,
)
from typesafe_sdk import (
    ChoiceAnswer as SDKChoiceAnswer,
)
from typesafe_sdk import (
    Noul as SDKNoul,
)
from typesafe_sdk import (
    NoulAnswer as SDKNoulAnswer,
)
from typesafe_sdk import (
    NoulCriteria as SDKNoulCriteria,
)
from typesafe_sdk import (
    RetryPolicy,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeError,
)
from typesafe_sdk import (
    Score as SDKScore,
)
from typesafe_sdk import (
    ScoreAnswer as SDKScoreAnswer,
)
from typesafe_sdk import (
    SystemOneResponse as SDKSystemOneResponse,
)
from typesafe_sdk import (
    TypeSafeClient as SDKTypeSafeClient,
)
from typesafe_sdk import (
    Usage as SDKUsage,
)

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
from ..results import (
    ChoiceResult,
    NoulResult,
    ScoreResult,
    TypeSafeUsage,
    _validate_usage,
)

BASE_URL = "https://api.typesafe.ai"
ENDPOINT = f"{BASE_URL}/v1/systemone"
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


class _AdapterScoreAnswer(SDKScoreAnswer):
    """Keep wire score keys as strings so noncanonical aliases fail closed."""

    probabilities: dict[str, float]  # type: ignore[assignment]
    legend: dict[str, str]  # type: ignore[assignment]


_AdapterAnswer = Annotated[
    SDKNoulAnswer | SDKChoiceAnswer | _AdapterScoreAnswer,
    Field(discriminator="type"),
]


class _AdapterSystemOneResponse(SDKSystemOneResponse):
    """Preserve the adapter's optional usage and strict score-key contracts."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    answers: dict[str, _AdapterAnswer] = Field(default_factory=dict)  # type: ignore[assignment]
    # Preserve the adapter's optional usage contract; SDK 0.7.0 marks it required.
    usage: SDKUsage | None = None  # type: ignore[assignment]


def _parse_answer(
    question: TypeSafeQuestion,
    answer: object,
    *,
    model: str,
    request_id: str | None,
    usage: TypeSafeUsage | None,
) -> TypeSafeAnswer:
    if isinstance(question, NoulQuestion):
        if not isinstance(answer, SDKNoulAnswer):
            raise ValueError("Expected a Noul answer.")
        return NoulResult(
            p_yes=probability(answer.noul),
            model=model,
            request_id=request_id,
            usage=usage,
        )
    if isinstance(question, ChoiceQuestion):
        if not isinstance(answer, SDKChoiceAnswer):
            raise ValueError("Expected a Choice answer.")
        choice_result = ChoiceResult(
            choice=answer.choice,
            confidence=probability(answer.confidence),
            probabilities=answer.probabilities,
            model=model,
            request_id=request_id,
            usage=usage,
        )
        if (
            set(choice_result.probabilities) != set(question.criteria)
            or choice_result.choice not in question.criteria
        ):
            raise ValueError("Choice answer labels do not match the requested criteria.")
        return choice_result
    if isinstance(question, ScoreQuestion):
        if not isinstance(answer, _AdapterScoreAnswer):
            raise ValueError("Expected a Score answer.")
        probabilities = _score_answer_map(answer.probabilities, len(question.criteria))
        legend = _score_answer_map(answer.legend, len(question.criteria))
        score_result = ScoreResult(
            score=answer.score,
            confidence=probability(answer.confidence),
            probabilities=probabilities,
            legend=legend,
            model=model,
            request_id=request_id,
            usage=usage,
        )
        if score_result.legend != dict(enumerate(question.criteria)):
            raise ValueError("Score legend does not match the requested criteria.")
        return score_result
    raise TypeError("Unsupported TypeSafe question.")


def _score_answer_map(value: Mapping[str, Any], level_count: int) -> dict[int, Any]:
    expected_keys = {str(level) for level in range(level_count)}
    if set(value) != expected_keys:
        raise ValueError("Score response keys do not match the configured levels.")
    return {level: value[str(level)] for level in range(level_count)}


def _to_sdk_question(question: TypeSafeQuestion) -> SDKNoul | SDKChoice | SDKScore:
    if isinstance(question, NoulQuestion):
        return SDKNoul(
            instructions=question.instructions,
            criteria=cast(SDKNoulCriteria | None, question.criteria),
        )
    if isinstance(question, ChoiceQuestion):
        return SDKChoice(instructions=question.instructions, criteria=question.criteria)
    if isinstance(question, ScoreQuestion):
        return SDKScore(instructions=question.instructions, criteria=list(question.criteria))
    raise TypeError("Unsupported TypeSafe question.")


class TypeSafeProvider:
    """Synchronous TypeSafe provider with single and batched question methods.

    Only the official HTTPS endpoint is used. ``transport`` is the SDK's
    synchronous transport seam, primarily for tests rather than untrusted
    per-request configuration.
    There are no hidden retries. HTTP timeout is per operation, not an
    end-to-end wall-clock deadline. Close with a context manager.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "jev-latest",
        timeout: float = 10.0,
        transport: httpx2.BaseTransport | None = None,
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
        http_client = httpx2.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._client = SDKTypeSafeClient(
            api_key=key,
            model=model,
            retry=RetryPolicy(max_retries=0),
            timeout=timeout,
            base_url=BASE_URL,
            http_client=http_client,
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
                raise TypeError(
                    "questions must contain NoulQuestion, ChoiceQuestion, or ScoreQuestion values."
                )
            normalized_questions[question_id] = question

        sdk_questions = {
            question_id: _to_sdk_question(question)
            for question_id, question in normalized_questions.items()
        }
        try:
            response = self._client.system_one(
                state=state,
                questions=sdk_questions,
                response_model=_AdapterSystemOneResponse,
            )
        except TypeSafeAPIResponseValidationError:
            raise JevProtocolError(
                "Malformed TypeSafe response; refusing to return answers."
            ) from None
        except TypeSafeAPIError as exc:
            raise JevHTTPError(exc.status) from None
        except TypeSafeAPIConnectionError:
            raise JevError("TypeSafe transport failed; validation did not complete.") from None
        except TypeSafeError:
            raise JevError("TypeSafe SDK failed; validation did not complete.") from None

        try:
            if set(response.answers) != set(normalized_questions):
                raise ValueError("Answer IDs do not match the request.")
            if response.usage is None:
                usage = None
            else:
                usage = TypeSafeUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            request_id = response.raw_http_response.headers.get("x-typesafe-request-id")
            answers = {
                question_id: _parse_answer(
                    question,
                    response.answers[question_id],
                    model=response.model,
                    request_id=request_id,
                    usage=usage,
                )
                for question_id, question in normalized_questions.items()
            }
            return SystemOneResult(answers, response.model, request_id, usage)
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            raise JevProtocolError(
                "Malformed TypeSafe response; refusing to return answers."
            ) from None

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
        self._client.close()

    def __enter__(self) -> TypeSafeProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# Keep the established name as an exact alias for existing integrations.
JevClient = TypeSafeProvider
