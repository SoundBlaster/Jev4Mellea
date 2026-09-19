"""Unofficial Mellea–Jev adapter. No paid request runs on import."""
from .client import (
    ChoiceResult,
    JevClient,
    JevError,
    JevHTTPError,
    JevProtocolError,
    NoulResult,
    ScoreResult,
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
    "ChoiceResult", "JevClient", "JevError", "JevHTTPError", "JevProtocolError",
    "NoulResult", "ScoreResult", "GenerationRejected", "JevClassifier", "JevScorer", "JevVerifier",
    "ReviewRequired", "Verdict", "accepted_text",
]
__version__ = "0.1.0"
