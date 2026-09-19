"""Unofficial Mellea–Jev adapter. No paid request runs on import."""
from .client import (
    ChoiceQuestion,
    ChoiceResult,
    JevClient,
    JevError,
    JevHTTPError,
    JevProtocolError,
    NoulQuestion,
    NoulResult,
    ScoreQuestion,
    ScoreResult,
    SystemOneResult,
    TypeSafeAnswer,
    TypeSafeQuestion,
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

__all__ = [
    "ChoiceQuestion", "ChoiceResult", "JevClient", "JevError", "JevHTTPError",
    "JevProtocolError", "NoulQuestion", "NoulResult", "ScoreQuestion", "ScoreResult",
    "SystemOneResult", "TypeSafeAnswer", "TypeSafeQuestion", "GenerationRejected",
    "JevClassifier", "JevScorer", "JevVerifier",
    "ReviewRequired", "Verdict", "accepted_text",
]
__version__ = "0.1.0"
