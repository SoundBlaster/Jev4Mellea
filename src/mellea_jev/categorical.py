"""Label-only tasks and evidence, separate from native probability contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast

from .contracts import ChoiceCriteria, JsonValue
from .criteria import _json_value
from .results import ChoiceResult, UsageMetadata

if TYPE_CHECKING:
    from .providers.typesafe import ChoiceQuestion


class CapabilityMismatchError(TypeError):
    """A consumer requires a primitive that the supplied provider does not expose."""


def _require_primitive(provider: object, primitive: str) -> None:
    if not callable(getattr(provider, primitive, None)):
        raise CapabilityMismatchError(
            f"This consumer requires the probability-based {primitive} primitive; "
            "a categorical provider supplies labels through classify(task)."
        )


class CategoricalTask:
    """Snapshot shared JSON state and ordered Choice questions, without I/O.

    Public views are detached copies: caller mutation cannot change the task.
    Abstention is an ordinary caller-defined label, never added by the library.
    """

    def __init__(
        self, *, state: Mapping[str, JsonValue], questions: Mapping[str, ChoiceQuestion]
    ) -> None:
        from .providers.typesafe import ChoiceQuestion

        normalized = _json_value(state)
        if not isinstance(normalized, dict):
            raise TypeError("state must be a JSON-compatible object.")
        if not isinstance(questions, Mapping) or not questions:
            raise ValueError("questions must be a nonempty mapping of IDs to ChoiceQuestion.")
        prompts: dict[str, JsonValue] = {}
        for name, question in questions.items():
            if not isinstance(name, str) or not name.strip() or name in prompts:
                raise ValueError("Question IDs must be unique nonempty strings.")
            if not isinstance(question, ChoiceQuestion):
                raise TypeError("Categorical tasks accept only ChoiceQuestion values.")
            prompts[name] = {
                "instructions": question.instructions,
                "criteria": _json_value(question.to_payload()["criteria"]),
            }
        self._json = json.dumps(
            {"state": normalized, "questions": prompts},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Return the original semantic task, separate from any wire serialization."""
        return cast(dict[str, JsonValue], json.loads(self._json))

    @property
    def state(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self.to_dict()["state"])

    @property
    def questions(self) -> dict[str, ChoiceQuestion]:
        from .providers.typesafe import ChoiceQuestion

        prompts = cast(dict[str, dict[str, JsonValue]], self.to_dict()["questions"])
        return {
            name: ChoiceQuestion(
                cast(str, value["instructions"]), cast(ChoiceCriteria, value["criteria"])
            )
            for name, value in prompts.items()
        }


@dataclass(frozen=True)
class CategoricalCapabilities:
    """Configured behavior, not a live capability or semantic-quality attestation."""

    strict_schema: bool
    shared_state_batch: bool
    native_distribution: bool


@dataclass(frozen=True)
class CategoricalEvidence:
    """Explicitly accessible sensitive data; never logged or persisted automatically.

    Request JSON contains the submitted payload, without HTTP headers or URLs.
    Response bytes contain the bounded body. The configured API key is redacted
    from both. An unavailable body stays None (for example a transport failure).
    """

    request_json: str | None = field(default=None, repr=False)
    response_body: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CategoricalResult:
    """Selected labels, with no generated probability or confidence fields."""

    answers: Mapping[str, str] = field(repr=False)
    requested_model: str | None = None
    returned_model: str | None = None
    request_id: str | None = None
    usage: UsageMetadata | None = None
    adapter_revision: str | None = None
    settings: Mapping[str, JsonValue] | None = field(default=None, repr=False)
    evidence: CategoricalEvidence | None = field(default=None, repr=False)
    native_results: Mapping[str, ChoiceResult] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.answers, Mapping)
            or not self.answers
            or any(
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(value, str)
                or not value.strip()
                for key, value in self.answers.items()
            )
        ):
            raise ValueError("answers must map nonempty question IDs to nonempty labels.")
        for name in ("requested_model", "returned_model", "request_id", "adapter_revision"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Available categorical metadata must be nonempty text.")
        if self.usage is not None and not isinstance(self.usage, UsageMetadata):
            raise TypeError("usage must be UsageMetadata or None.")
        object.__setattr__(self, "answers", MappingProxyType(dict(self.answers)))
        if self.settings is not None:
            settings = cast(dict[str, JsonValue], _json_value(self.settings))
            object.__setattr__(self, "settings", MappingProxyType(settings))
        if self.native_results is not None:
            if set(self.native_results) != set(self.answers) or any(
                not isinstance(value, ChoiceResult) or value.choice != self.answers[name]
                for name, value in self.native_results.items()
            ):
                raise ValueError(
                    "Native results must match the categorical IDs and selected labels."
                )
            object.__setattr__(self, "native_results", MappingProxyType(dict(self.native_results)))


class CategoricalProvider(Protocol):
    """One task is one explicit shared-state inference request, including a batch."""

    def classify(self, task: CategoricalTask) -> CategoricalResult: ...


def project_choice_results(
    task: CategoricalTask,
    results: Mapping[str, ChoiceResult],
    *,
    requested_model: str | None = None,
    request_id: str | None = None,
    usage: UsageMetadata | None = None,
) -> CategoricalResult:
    """Project already-collected native choices; never dispatch or invent evidence.

    Retain the original results and distributions separately. Request ID/usage
    must be supplied from actual request metadata; they are not inferred or
    summed from per-answer fields. This view does not attest batch execution.
    """
    questions = task.questions
    if set(results) != set(questions):
        raise ValueError("Native result IDs must match all task question IDs.")
    for name, question in questions.items():
        result = results[name]
        if not isinstance(result, ChoiceResult) or set(result.probabilities) != set(
            question.criteria
        ):
            raise ValueError("Native ChoiceResult labels must match the corresponding question.")
        # Re-check mutable native maps without replacing or inventing their evidence.
        ChoiceResult(
            result.choice,
            result.confidence,
            result.probabilities,
            result.model,
            result.request_id,
            result.usage,
        )
    models = {result.model for result in results.values()}
    return CategoricalResult(
        answers={name: results[name].choice for name in questions},
        requested_model=requested_model,
        returned_model=next(iter(models)) if len(models) == 1 else None,
        request_id=request_id,
        usage=usage,
        native_results=results,
    )
