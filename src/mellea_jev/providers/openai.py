"""Optional synchronous Decisions API provider for Noul and Choice."""

from __future__ import annotations

import json
import math
import os
from typing import TYPE_CHECKING, Any

import httpx2

from ..contracts import ChoiceCriteria, NoulCriteria
from ..criteria import _json_value, normalize_choice_criteria, normalize_noul_criteria, probability
from ..results import ChoiceResult, NoulResult, UsageMetadata

if TYPE_CHECKING:
    from openai.types.decision import Answer
    from openai.types.decision_create_params import Question, QuestionQuestionParamChoiceChoice

BASE_URL = "https://api.openai.com/v1"
QUESTION_NAME = "requirement"
CHOICE_QUESTION_NAME = "classification"


class OpenAIProviderError(RuntimeError):
    """A Decisions API failure; the requirement has not been validated."""


class OpenAIHTTPError(OpenAIProviderError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"OpenAI returned HTTP {status_code}; validation did not complete.")


class OpenAIProtocolError(OpenAIProviderError):
    """A response does not satisfy the requested decision contract."""


class OpenAIRefusalError(OpenAIProtocolError):
    """OpenAI refused to evaluate the requested decision."""


class OpenAIProvider:
    """Adapt one Decisions question without exposing SDK response types.

    Install the ``openai`` extra before construction. Imports do not load the
    SDK or send requests. State is serialized as JSON text, and optional outcome
    criteria are appended to the predicate instructions as JSON. Choice labels
    remain strings; structured descriptions are serialized as JSON text.
    Image input, batching, and Score are outside the current interface.

    The official endpoint is the default. ``base_url`` explicitly selects a
    compatible gateway; OPENAI_BASE_URL is not read. Environment proxies and
    redirects are disabled. Requests are never automatically retried. Timeout is per HTTP
    operation, not an end-to-end deadline. Close with a context manager.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "gpt-6-luna",
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        key = os.environ.get("OPENAI_API_KEY", "") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Set OPENAI_API_KEY or supply api_key.")
        if any(ch.isspace() for ch in key) or not key.isascii():
            raise ValueError("API key must be ASCII without whitespace.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonempty string.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive.")
        if not isinstance(base_url, str) or any(ch.isspace() for ch in base_url):
            raise ValueError(
                "base_url must be an absolute HTTP(S) URL without credentials or query."
            )
        try:
            url = httpx2.URL(base_url)
        except httpx2.InvalidURL:
            raise ValueError("base_url must be a valid HTTP(S) URL.") from None
        if (
            not url.is_absolute_url
            or url.scheme not in ("http", "https")
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "base_url must be an absolute HTTP(S) URL without credentials or query."
            )
        try:
            from openai import OpenAI, OpenAIError
        except ImportError:
            raise OpenAIProviderError(
                "Install mellea-jev-adapter[openai] to use OpenAIProvider."
            ) from None

        self.model = model
        http_client = httpx2.Client(
            timeout=timeout, follow_redirects=False, trust_env=False, transport=transport
        )
        try:
            self._client = OpenAI(
                api_key=key,
                base_url=base_url,
                timeout=timeout,
                max_retries=0,
                http_client=http_client,
            )
        except OpenAIError:
            http_client.close()
            raise OpenAIProviderError("OpenAI SDK initialization failed.") from None

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResult:
        """Return a predicate's P(true); refusals and invalid responses raise."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be nonempty text.")
        normalized = normalize_noul_criteria(criteria)
        instructions = question
        if normalized:
            instructions += (
                "\n\nOutcome criteria (JSON; true means the condition holds):\n"
                + json.dumps(normalized, ensure_ascii=False, allow_nan=False)
            )
        answer, model, request_id, usage = self._request(
            state=state,
            question={"type": "predicate", "name": QUESTION_NAME, "instructions": instructions},
        )
        if answer.type != "predicate":
            raise OpenAIProtocolError("Expected a predicate answer.")
        try:
            return NoulResult(probability(answer.probability), model, request_id, usage)
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise OpenAIProtocolError(
                "Malformed OpenAI predicate response; refusing to accept."
            ) from None

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
    ) -> ChoiceResult:
        """Classify into the caller's string labels; reject incomplete distributions."""
        normalized = normalize_choice_criteria(criteria)
        choices: list[QuestionQuestionParamChoiceChoice] = []
        for label, description in normalized.items():
            option: QuestionQuestionParamChoiceChoice = {"value": label}
            if description is not None:
                option["description"] = (
                    description
                    if isinstance(description, str)
                    else json.dumps(description, ensure_ascii=False, allow_nan=False)
                )
            choices.append(option)
        answer, model, request_id, usage = self._request(
            state=state,
            question={
                "type": "choice",
                "name": CHOICE_QUESTION_NAME,
                "instructions": question,
                "choices": choices,
            },
        )
        if answer.type != "choice":
            raise OpenAIProtocolError("Expected a choice answer.")
        try:
            probabilities: dict[str, float] = {}
            for entry in answer.probabilities:
                if not isinstance(entry.value, str) or entry.value in probabilities:
                    raise ValueError("Expected unique string choice labels.")
                probabilities[entry.value] = probability(entry.probability)
            if set(probabilities) != set(normalized) or not isinstance(answer.choice, str):
                raise ValueError("Choice labels do not match the request.")
            return ChoiceResult(
                answer.choice, answer.confidence, probabilities, model, request_id, usage
            )
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise OpenAIProtocolError(
                "Malformed OpenAI choice response; refusing to accept."
            ) from None

    def _request(
        self, *, state: dict[str, Any], question: Question
    ) -> tuple[Answer, str, str | None, UsageMetadata]:
        from openai import APIConnectionError, APIStatusError, OpenAIError
        from openai.types.decision import Decision

        if not isinstance(state, dict):
            raise TypeError("state must be a JSON-serializable dictionary.")
        if not isinstance(question["instructions"], str) or not question["instructions"].strip():
            raise ValueError("question must be nonempty text.")
        input_text = json.dumps(_json_value(state), ensure_ascii=False, allow_nan=False)
        try:
            raw = self._client.decisions.with_raw_response.create(
                model=self.model,
                input=input_text,
                questions=[question],
            )
        except APIStatusError as exc:
            raise OpenAIHTTPError(exc.status_code) from None
        except APIConnectionError:
            raise OpenAIProviderError(
                "OpenAI transport failed; validation did not complete."
            ) from None
        except OpenAIError:
            raise OpenAIProviderError("OpenAI SDK failed; validation did not complete.") from None

        try:
            # SDK parsing defaults to permissive construction. Validate wire data
            # with the official SDK model, without coercing strings or booleans.
            response = Decision.model_validate_json(raw.content, strict=True)
            if len(response.answers) != 1 or response.answers[0].name != question["name"]:
                raise ValueError("Answer count or name does not match the request.")
            answer = response.answers[0]
            if answer.type == "refusal":
                raise OpenAIRefusalError(
                    "OpenAI refused the decision; validation did not complete."
                )
            if answer.type != question["type"] or not response.model.strip():
                raise ValueError("Response type or model does not match the contract.")
            return (
                answer,
                response.model,
                raw.request_id,
                UsageMetadata(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                ),
            )
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise OpenAIProtocolError(
                "Malformed OpenAI decision response; refusing to accept."
            ) from None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenAIProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
