"""Unofficial Mellea–Jev adapter. No paid request runs on import."""
from .client import (
    ChoiceCriteria,
    ChoiceDescription,
    ChoiceQuestion,
    ChoiceResult,
    JevClient,
    JevError,
    JevHTTPError,
    JevProtocolError,
    NoulCriteria,
    NoulQuestion,
    NoulResult,
    ScoreQuestion,
    ScoreResult,
    SystemOneResult,
    TypeSafeAnswer,
    TypeSafeQuestion,
    TypeSafeUsage,
    JsonValue,
)
from .verifier import (
    GenerationRejected,
    JevClassifier,
    JevScorer,
    JevVerifier,
    ReviewRequired,
    Verdict,
    accepted_text,
)
from .contracts import (
    ChoiceProvider,
    ChoiceResponse,
    NoulProvider,
    NoulResponse,
    PrimitiveProvider,
    ScoreProvider,
    ScoreResponse,
)
from .providers import TypeSafeProvider

__all__ = [
    "ChoiceCriteria",
    "ChoiceDescription",
    "ChoiceQuestion",
    "ChoiceResult",
    "JevClient",
    "JevError",
    "JevHTTPError",
    "JevProtocolError",
    "NoulCriteria",
    "NoulQuestion",
    "NoulResult",
    "ScoreQuestion",
    "ScoreResult",
    "SystemOneResult", "TypeSafeAnswer", "TypeSafeQuestion", "TypeSafeUsage", "GenerationRejected",
    "JsonValue",
    "JevClassifier", "JevScorer", "JevVerifier",
    "ReviewRequired", "Verdict", "accepted_text",
    "ChoiceProvider", "ChoiceResponse", "NoulProvider", "NoulResponse",
    "PrimitiveProvider", "ScoreProvider", "ScoreResponse",
    "TypeSafeProvider",
]
__version__ = "0.1.0"
