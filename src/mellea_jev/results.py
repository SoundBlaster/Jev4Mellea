"""Normalized primitive responses shared by provider implementations."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .criteria import probability


@dataclass(frozen=True)
class UsageMetadata:
    """Optional token counts as reported by a provider."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None.")


# Compatibility name retained for the original TypeSafe usage object.
TypeSafeUsage = UsageMetadata


def _validate_usage(value: UsageMetadata | None) -> None:
    if value is not None and not isinstance(value, UsageMetadata):
        raise ValueError("usage must be UsageMetadata or None.")


@dataclass(frozen=True)
class NoulResult:
    p_yes: float
    model: str
    request_id: str | None = None
    usage: UsageMetadata | None = None

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
    usage: UsageMetadata | None = None

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
    usage: UsageMetadata | None = None

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
