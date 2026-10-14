"""ScaleDown Decisions API provider for Mellea Noul, Choice, and Score contracts."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from typing import Any

import httpx2

from ..contracts import ChoiceCriteria, ChoiceDescription, NoulCriteria
from ..criteria import (
    _json_value,
    normalize_choice_criteria,
    normalize_noul_criteria,
    normalize_score_criteria,
    probability,
)
from ..results import ChoiceResult, NoulResult, ScoreResult, UsageMetadata
from ._http import _DefaultBaseURL, _http_client

BASE_URL = "https://api.scaledown.xyz"
MODEL = "classify-1"
QUESTION_ID = "decision"


class ScaleDownProviderError(RuntimeError):
    """A transport or API-contract failure; no decision was returned."""


class ScaleDownHTTPError(ScaleDownProviderError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"ScaleDown returned HTTP {status_code}; decision did not complete.")


class ScaleDownProtocolError(ScaleDownProviderError):
    """The ScaleDown response does not satisfy the requested decision contract."""


def _question_text(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonempty text.")
    return question


def _description_text(description: ChoiceDescription | None) -> str:
    if description is None:
        return ""
    if isinstance(description, str):
        return description
    return json.dumps(_json_value(description), ensure_ascii=False, allow_nan=False)


def _usage(value: object) -> UsageMetadata | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Expected a usage object.")
    allowed = {"input_tokens", "output_tokens", "cost"}
    if set(value) - allowed:
        raise ValueError("Unexpected usage fields.")
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    cost = value.get("cost")
    for count in (input_tokens, output_tokens):
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("Invalid token usage.")
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ValueError("Invalid cost usage.")
    if input_tokens is None and output_tokens is None and cost is None:
        return None
    return UsageMetadata(input_tokens, output_tokens, cost)


class ScaleDownProvider:
    """Synchronous adapter for ScaleDown's Jev-shaped `/v1/scaledown` endpoint.

    ScaleDown reads only `state.text` and `state.document`. This provider serializes
    the complete Mellea state dictionary into JSON text so fields such as candidate
    and reference remain available. It pins the only model exposed by the OpenAPI
    schema (`classify-1`). Noul criteria become explicit instruction text; Choice
    descriptions are serialized to strings, and Score levels stay ordered strings.

    Configure `base_url` for a gateway root or `endpoint_url` for the exact operation
    URL. The endpoint defaults to `https://api.scaledown.xyz/v1/scaledown`. Environment
    proxies and redirects are disabled and requests are not retried automatically.
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
        key = os.environ.get("SCALEDOWN_API_KEY", "") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Set SCALEDOWN_API_KEY or supply api_key.")
        if any(ch.isspace() for ch in key) or not key.isascii():
            raise ValueError("API key must be ASCII without whitespace.")
        if model != MODEL:
            raise ValueError(f"ScaleDown Decisions currently supports only {MODEL!r}.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive.")
        self.model = model
        base_url, self._client = _http_client(
            base_url=base_url,
            endpoint_url=endpoint_url,
            operation_path="/v1/scaledown",
            timeout=timeout,
            transport=transport,
        )
        self._base_url = base_url
        self._api_key = key

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResult:
        instructions = _question_text(question)
        normalized = normalize_noul_criteria(criteria)
        if normalized:
            instructions += (
                "\n\nOutcome criteria (JSON; true means the condition holds):\n"
                + json.dumps(_json_value(normalized), ensure_ascii=False, allow_nan=False)
            )
        answer, model, request_id, usage = self._request(
            state,
            {"type": "noul", "instructions": instructions},
        )
        if answer.get("type") != "noul":
            raise ScaleDownProtocolError("Expected a Noul answer.")
        try:
            return NoulResult(probability(answer["noul"]), model, request_id, usage)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise ScaleDownProtocolError(
                "Malformed ScaleDown Noul response; refusing to return a decision."
            ) from None

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
    ) -> ChoiceResult:
        normalized = normalize_choice_criteria(criteria)
        labels = {
            label: _description_text(description) for label, description in normalized.items()
        }
        answer, model, request_id, usage = self._request(
            state,
            {"type": "choice", "instructions": _question_text(question), "criteria": labels},
        )
        if answer.get("type") != "choice":
            raise ScaleDownProtocolError("Expected a Choice answer.")
        try:
            choice = answer["choice"]
            probabilities = answer["probabilities"]
            if not isinstance(probabilities, dict) or set(probabilities) != set(labels):
                raise ValueError("Choice labels do not match the request.")
            probabilities = {label: probability(value) for label, value in probabilities.items()}
            confidence = probability(answer["confidence"])
            if choice not in probabilities or confidence != probabilities[choice]:
                raise ValueError("Choice confidence does not match its selected probability.")
            return ChoiceResult(choice, confidence, probabilities, model, request_id, usage)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise ScaleDownProtocolError(
                "Malformed ScaleDown Choice response; refusing to return a decision."
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
            raise ValueError("ScaleDown Score requires between 2 and 10 levels.")
        answer, model, request_id, usage = self._request(
            state,
            {"type": "score", "instructions": _question_text(question), "criteria": normalized},
        )
        if answer.get("type") != "score":
            raise ScaleDownProtocolError("Expected a Score answer.")
        try:
            expected_keys = {str(level) for level in range(len(normalized))}
            raw_probabilities = answer["probabilities"]
            legend = answer["legend"]
            if (
                not isinstance(raw_probabilities, dict)
                or set(raw_probabilities) != expected_keys
                or not isinstance(legend, dict)
                or set(legend) != expected_keys
            ):
                raise ValueError("Score keys do not match the request.")
            probabilities = {
                level: probability(raw_probabilities[str(level)])
                for level in range(len(normalized))
            }
            normalized_legend = {level: legend[str(level)] for level in range(len(normalized))}
            if normalized_legend != dict(enumerate(normalized)):
                raise ValueError("Score legend does not match the request.")
            confidence = probability(answer["confidence"])
            if confidence != max(probabilities.values()):
                raise ValueError("Score confidence does not match the probability distribution.")
            return ScoreResult(
                answer["score"],
                confidence,
                probabilities,
                normalized_legend,
                model,
                request_id,
                usage,
            )
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise ScaleDownProtocolError(
                "Malformed ScaleDown Score response; refusing to return a decision."
            ) from None

    def _request(
        self, state: dict[str, Any], question: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str | None, UsageMetadata | None]:
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        if (
            not isinstance(question.get("instructions"), str)
            or not question["instructions"].strip()
        ):
            raise ValueError("question must be nonempty text.")
        try:
            state_text = json.dumps(_json_value(state), ensure_ascii=False, allow_nan=False)
            response = self._client.post(
                self._endpoint_url(),
                headers={"x-api-key": self._api_key, "content-type": "application/json"},
                json={
                    "model": self.model,
                    "state": {"text": state_text},
                    "questions": {QUESTION_ID: question},
                },
            )
        except (TypeError, ValueError):
            raise ValueError("state must contain JSON-compatible values.") from None
        except httpx2.HTTPError:
            raise ScaleDownProviderError(
                "ScaleDown transport failed; decision did not complete."
            ) from None
        if response.status_code >= 300:
            raise ScaleDownHTTPError(response.status_code)
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
            return (
                answer,
                model,
                response.headers.get("x-request-id"),
                _usage(payload.get("usage")),
            )
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise ScaleDownProtocolError(
                "Malformed ScaleDown response; refusing to return a decision."
            ) from None

    def _endpoint_url(self) -> str:
        return self._base_url.rstrip("/") + "/v1/scaledown"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ScaleDownProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
