"""SubQ Decisions API provider for Mellea Noul, Choice, and Score contracts."""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from typing import Any

import httpx2

from ..contracts import ChoiceCriteria, NoulCriteria
from ..criteria import (
    _json_value,
    normalize_choice_criteria,
    normalize_noul_criteria,
    normalize_score_criteria,
    probability,
)
from ..results import ChoiceResult, NoulResult, ScoreResult, UsageMetadata
from ._http import _DefaultBaseURL, _http_client

BASE_URL = "https://api.subq.ai"
MODEL = "subq-snap-preview"
QUESTION_ID = "decision"


class SubQProviderError(RuntimeError):
    """A transport or API-contract failure; no decision was returned."""


class SubQHTTPError(SubQProviderError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"SubQ returned HTTP {status_code}; decision did not complete.")


class SubQProtocolError(SubQProviderError):
    """The SubQ response does not satisfy the requested decision contract."""


def _question_text(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonempty text.")
    return question


def _usage(value: object) -> UsageMetadata | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"input_tokens", "output_tokens"}:
        raise ValueError("Expected a valid SubQ usage object.")
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    for count in (input_tokens, output_tokens):
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("Invalid token usage.")
    if input_tokens is None and output_tokens is None:
        return None
    return UsageMetadata(input_tokens, output_tokens)


class SubQProvider:
    """Synchronous adapter for SubQ's `/v1/systemone` Decisions endpoint.

    The default model is `subq-snap-preview`. Configure `base_url` for a gateway
    root or `endpoint_url` for an exact operation URL. Requests use Bearer auth,
    ignore environment proxies, do not follow redirects, and are not retried.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = MODEL,
        base_url: str = _DefaultBaseURL(BASE_URL),
        endpoint_url: str | None = None,
        timeout: float = 10.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        key = os.environ.get("SUBQ_API_KEY", "") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Set SUBQ_API_KEY or supply api_key.")
        if any(ch.isspace() for ch in key) or not key.isascii():
            raise ValueError("API key must be ASCII without whitespace.")
        if model != MODEL:
            raise ValueError(f"SubQ Decisions currently supports only {MODEL!r}.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive.")
        self.model = model
        self._base_url, self._client = _http_client(
            base_url=base_url,
            endpoint_url=endpoint_url,
            operation_path="/v1/systemone",
            timeout=timeout,
            transport=transport,
        )
        self._api_key = key

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResult:
        normalized = normalize_noul_criteria(criteria)
        answer, model, request_id, usage = self._request(
            state,
            self._question("noul", question, normalized),
        )
        if answer.get("type") != "noul":
            raise SubQProtocolError("Expected a Noul answer.")
        try:
            return NoulResult(probability(answer["noul"]), model, request_id, usage)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise SubQProtocolError(
                "Malformed SubQ Noul response; refusing to return a decision."
            ) from None

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
    ) -> ChoiceResult:
        normalized = normalize_choice_criteria(criteria)
        if not 2 <= len(normalized) <= 255:
            raise ValueError("SubQ Choice requires between 2 and 255 options.")
        answer, model, request_id, usage = self._request(
            state,
            self._question("choice", question, normalized),
        )
        if answer.get("type") != "choice":
            raise SubQProtocolError("Expected a Choice answer.")
        try:
            probabilities = answer["probabilities"]
            if not isinstance(probabilities, dict) or set(probabilities) != set(normalized):
                raise ValueError("Choice labels do not match the request.")
            return ChoiceResult(
                answer["choice"],
                probability(answer["confidence"]),
                {label: probability(value) for label, value in probabilities.items()},
                model,
                request_id,
                usage,
            )
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise SubQProtocolError(
                "Malformed SubQ Choice response; refusing to return a decision."
            ) from None

    def score(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Sequence[str],
    ) -> ScoreResult:
        normalized = normalize_score_criteria(criteria)
        if len(normalized) > 10:
            raise ValueError("SubQ Score requires between 2 and 10 levels.")
        answer, model, request_id, usage = self._request(
            state,
            self._question("score", question, normalized),
        )
        if answer.get("type") != "score":
            raise SubQProtocolError("Expected a Score answer.")
        try:
            expected_keys = {str(level) for level in range(len(normalized))}
            raw_probabilities = answer["probabilities"]
            raw_legend = answer["legend"]
            if (
                not isinstance(raw_probabilities, dict)
                or set(raw_probabilities) != expected_keys
                or not isinstance(raw_legend, dict)
                or set(raw_legend) != expected_keys
            ):
                raise ValueError("Score keys do not match the request.")
            probabilities = {
                level: probability(raw_probabilities[str(level)])
                for level in range(len(normalized))
            }
            legend = {level: raw_legend[str(level)] for level in range(len(normalized))}
            if legend != dict(enumerate(normalized)):
                raise ValueError("Score legend does not match the request.")
            return ScoreResult(
                answer["score"],
                probability(answer["confidence"]),
                probabilities,
                legend,
                model,
                request_id,
                usage,
            )
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise SubQProtocolError(
                "Malformed SubQ Score response; refusing to return a decision."
            ) from None

    @staticmethod
    def _question(kind: str, instructions: str, criteria: object | None) -> dict[str, Any]:
        question: dict[str, Any] = {"type": kind, "instructions": _question_text(instructions)}
        if criteria is not None:
            question["criteria"] = criteria
        return question

    def _request(
        self, state: dict[str, Any], question: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str | None, UsageMetadata | None]:
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        try:
            response = self._client.post(
                self._endpoint_url(),
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "state": _json_value(state),
                    "questions": {QUESTION_ID: question},
                },
            )
        except (TypeError, ValueError):
            raise ValueError("state must contain JSON-compatible values.") from None
        except httpx2.HTTPError:
            raise SubQProviderError("SubQ transport failed; decision did not complete.") from None
        if response.status_code >= 300:
            raise SubQHTTPError(response.status_code)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Expected a response object.")
            model = payload.get("model")
            answers = payload.get("answers")
            if (
                model != self.model
                or not isinstance(answers, dict)
                or set(answers) != {QUESTION_ID}
            ):
                raise ValueError("Model or answer keys do not match the request.")
            answer = answers[QUESTION_ID]
            if not isinstance(answer, dict):
                raise ValueError("Expected one answer object.")
            request_id = response.headers.get("x-request-id") or response.headers.get(
                "x-subq-request-id"
            )
            return answer, model, request_id, _usage(payload.get("usage"))
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise SubQProtocolError(
                "Malformed SubQ response; refusing to return a decision."
            ) from None

    def _endpoint_url(self) -> str:
        return self._base_url.rstrip("/") + "/v1/systemone"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SubQProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
