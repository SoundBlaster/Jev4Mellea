"""Provider-independent normalization for primitive criteria and probabilities."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

from .contracts import (
    ChoiceCriteria,
    ChoiceDescription,
    JsonValue,
    NoulCriteria,
)


def probability(value: object) -> float:
    """Reject bools, numeric strings, NaN, infinity and out-of-range values."""
    if type(value) not in (int, float):
        raise ValueError("Expected a finite number in [0, 1], not a boolean.")
    number = cast(int | float, value)
    if not 0 <= number <= 1 or not math.isfinite(number):
        raise ValueError("Expected a finite number in [0, 1], not a boolean.")
    return float(number)


def _json_value(value: object, ancestors: frozenset[int] = frozenset()) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Descriptions cannot contain non-finite numbers.")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("Descriptions cannot contain circular references.")
        nested_ancestors = ancestors | {identity}
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Choice description object keys must be strings.")
            normalized[key] = _json_value(item, nested_ancestors)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("Descriptions cannot contain circular references.")
        nested_ancestors = ancestors | {identity}
        return [_json_value(item, nested_ancestors) for item in value]
    raise TypeError("Descriptions must contain only JSON-compatible values.")


def _json_description(description: object, primitive: str) -> ChoiceDescription | None:
    if description is None:
        return None
    if isinstance(description, str):
        if not description.strip():
            raise ValueError(
                f"{primitive} descriptions must be nonempty strings or structured JSON."
            )
        return description
    if isinstance(description, Mapping) or (
        isinstance(description, Sequence) and not isinstance(description, (str, bytes, bytearray))
    ):
        return cast(ChoiceDescription, _json_value(description))
    raise TypeError(f"{primitive} descriptions must be strings, objects, arrays, or None.")


def normalize_choice_criteria(criteria: ChoiceCriteria) -> dict[str, ChoiceDescription | None]:
    """Validate and copy category labels/descriptions without provider limits."""
    if not isinstance(criteria, Mapping) or not criteria:
        raise ValueError("criteria must be a nonempty mapping of labels to descriptions.")
    normalized: dict[str, ChoiceDescription | None] = {}
    for label, description in criteria.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Choice labels must be nonempty strings.")
        normalized[label] = _json_description(description, "Choice")
    return normalized


def normalize_noul_criteria(criteria: NoulCriteria | None) -> NoulCriteria | None:
    """Validate and copy optional true/false descriptions."""
    if criteria is None:
        return None
    if not isinstance(criteria, Mapping):
        raise TypeError("Noul criteria must be a mapping with 'true' and/or 'false' keys.")
    normalized: dict[str, ChoiceDescription | None] = {}
    for outcome, description in criteria.items():
        if outcome not in ("true", "false"):
            raise ValueError("Noul criteria keys must be 'true' or 'false'.")
        normalized[outcome] = _json_description(description, "Noul")
    return cast(NoulCriteria, normalized)


def normalize_score_criteria(criteria: object) -> list[str]:
    """Validate an ordered rubric; providers can enforce their own level limits."""
    if isinstance(criteria, (str, bytes, bytearray)) or not isinstance(criteria, Sequence):
        raise TypeError("Score criteria must be an ordered sequence of descriptions.")
    if len(criteria) < 2:
        raise ValueError("Score criteria require at least 2 levels.")
    normalized = list(criteria)
    if any(not isinstance(level, str) or not level.strip() for level in normalized):
        raise ValueError("Score levels must be nonempty descriptions.")
    return cast(list[str], normalized)
