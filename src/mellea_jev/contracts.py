"""Provider-neutral contracts consumed by the Mellea adapters.

Implementations are structural: a provider does not need to inherit these
protocols. The existing ``JevClient`` satisfies all three primitive protocols.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, TypeAlias, TypedDict

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
ChoiceDescription: TypeAlias = str | Mapping[str, JsonValue] | Sequence[JsonValue]
ChoiceCriteria: TypeAlias = Mapping[str, ChoiceDescription | None]


class NoulCriteria(TypedDict, total=False):
    """Optional descriptions of the true and false Noul outcomes."""

    true: ChoiceDescription | None
    false: ChoiceDescription | None


class NoulResponse(Protocol):
    """Normalized output needed by the Mellea Noul requirement adapter."""

    @property
    def p_yes(self) -> float: ...

    @property
    def model(self) -> str: ...

    @property
    def request_id(self) -> str | None: ...


class ChoiceResponse(Protocol):
    """Normalized class prediction and its distribution."""

    @property
    def choice(self) -> str: ...

    @property
    def confidence(self) -> float: ...

    @property
    def probabilities(self) -> dict[str, float]: ...

    @property
    def model(self) -> str: ...

    @property
    def request_id(self) -> str | None: ...


class ScoreResponse(Protocol):
    """Normalized ordinal score and its distribution."""

    @property
    def score(self) -> float: ...

    @property
    def confidence(self) -> float: ...

    @property
    def probabilities(self) -> dict[int, float]: ...

    @property
    def legend(self) -> dict[int, str]: ...

    @property
    def model(self) -> str: ...

    @property
    def request_id(self) -> str | None: ...


class NoulProvider(Protocol):
    """Provider for a yes/no semantic requirement check."""

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResponse: ...


class ChoiceProvider(Protocol):
    """Provider for classification into a configured set of labels."""

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
    ) -> ChoiceResponse: ...


class ScoreProvider(Protocol):
    """Provider for scoring against an ordered rubric."""

    def score(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Sequence[str],
    ) -> ScoreResponse: ...


class PrimitiveProvider(NoulProvider, ChoiceProvider, ScoreProvider, Protocol):
    """A provider exposing all three primitives; adapters also accept each separately."""
