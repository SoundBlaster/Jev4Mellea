"""Minimal synchronous client for TypeSafe's documented Noul HTTP API."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

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


def probability(value: object) -> float:
    """Reject bools, numeric strings, NaN, infinity and out-of-range values."""
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError("Expected a finite number in [0, 1], not a boolean.")
    return float(value)


@dataclass(frozen=True)
class NoulResult:
    p_yes: float
    model: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        probability(self.p_yes)
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Expected a nonempty response model name.")


@dataclass(frozen=True)
class ChoiceResult:
    choice: str
    confidence: float
    probabilities: dict[str, float]
    model: str
    request_id: str | None = None

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
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "probabilities", probabilities)


def _choice_criteria(criteria: Mapping[str, str | None]) -> dict[str, str | None]:
    if not isinstance(criteria, Mapping) or not criteria:
        raise ValueError("criteria must be a nonempty mapping of labels to descriptions.")
    if len(criteria) > 255:
        raise ValueError("TypeSafe Choice supports at most 255 options.")
    normalized: dict[str, str | None] = {}
    for label, description in criteria.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Choice labels must be nonempty strings.")
        if description is not None and not isinstance(description, str):
            raise TypeError("Choice descriptions must be strings or None.")
        if isinstance(description, str) and not description.strip():
            raise ValueError("Choice descriptions must be nonempty strings or None.")
        normalized[label] = description
    return normalized


def _score_criteria(criteria: Sequence[str]) -> list[str]:
    if isinstance(criteria, (str, bytes)) or not isinstance(criteria, Sequence):
        raise TypeError("Score criteria must be an ordered sequence of descriptions.")
    if not 2 <= len(criteria) <= 10:
        raise ValueError("TypeSafe Score requires between 2 and 10 levels.")
    normalized = list(criteria)
    if any(not isinstance(level, str) or not level.strip() for level in normalized):
        raise ValueError("Score levels must be nonempty descriptions.")
    return normalized


class JevClient:
    """One Noul, Choice, or Score question per request. No hidden retries; close with a context manager.

    Only the official HTTPS endpoint is used. ``transport`` is a trusted
    dependency-injection hook for tests, not an untrusted per-request option.
    HTTP timeout is per operation, not an end-to-end wall-clock deadline.
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

    def noul(self, *, state: dict[str, Any], question: str) -> NoulResult:
        """Return P(yes). Exceptions never include the response body or API key."""
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string.")
        try:
            response = self._http.post(
                ENDPOINT,
                json={
                    "model": self.model,
                    "state": state,
                    "questions": {
                        QUESTION_ID: {"type": "noul", "instructions": question}
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
            if not isinstance(data, dict):
                raise ValueError
            answer = data["answers"][QUESTION_ID]
            if not isinstance(answer, dict) or answer.get("type") != "noul":
                raise ValueError
            return NoulResult(
                p_yes=probability(answer["noul"]),
                model=data["model"],
                request_id=response.headers.get("x-typesafe-request-id"),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise JevProtocolError("Malformed TypeSafe Noul response; refusing to accept.") from None

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Mapping[str, str | None],
    ) -> ChoiceResult:
        """Select one configured class and return its distribution and confidence."""
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string.")
        choices = _choice_criteria(criteria)
        try:
            response = self._http.post(
                ENDPOINT,
                json={
                    "model": self.model,
                    "state": state,
                    "questions": {
                        CHOICE_QUESTION_ID: {
                            "type": "choice",
                            "instructions": question,
                            "criteria": choices,
                        }
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
            if not isinstance(data, dict):
                raise ValueError
            answer = data["answers"][CHOICE_QUESTION_ID]
            if not isinstance(answer, dict) or answer.get("type") != "choice":
                raise ValueError
            result = ChoiceResult(
                choice=answer["choice"],
                confidence=probability(answer["confidence"]),
                probabilities=answer["probabilities"],
                model=data["model"],
                request_id=response.headers.get("x-typesafe-request-id"),
            )
            if set(result.probabilities) != set(choices) or result.choice not in choices:
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, OverflowError):
            raise JevProtocolError("Malformed TypeSafe Choice response; refusing to classify.") from None

    def score(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Sequence[str],
    ) -> ScoreResult:
        """Rate the state against ordered levels and return the full distribution."""
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string.")
        levels = _score_criteria(criteria)
        try:
            response = self._http.post(
                ENDPOINT,
                json={
                    "model": self.model,
                    "state": state,
                    "questions": {
                        SCORE_QUESTION_ID: {
                            "type": "score",
                            "instructions": question,
                            "criteria": levels,
                        }
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
            if not isinstance(data, dict):
                raise ValueError
            answer = data["answers"][SCORE_QUESTION_ID]
            if not isinstance(answer, dict) or answer.get("type") != "score":
                raise ValueError
            if not isinstance(answer["probabilities"], dict) or not isinstance(answer["legend"], dict):
                raise ValueError
            probabilities = {int(level): value for level, value in answer["probabilities"].items()}
            legend = {int(level): value for level, value in answer["legend"].items()}
            result = ScoreResult(
                score=answer["score"],
                confidence=probability(answer["confidence"]),
                probabilities=probabilities,
                legend=legend,
                model=data["model"],
                request_id=response.headers.get("x-typesafe-request-id"),
            )
            if len(result.probabilities) != len(levels) or result.legend != dict(enumerate(levels)):
                raise ValueError
            if not 0 <= result.score <= len(levels) - 1:
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, OverflowError):
            raise JevProtocolError("Malformed TypeSafe Score response; refusing to score.") from None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> JevClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
