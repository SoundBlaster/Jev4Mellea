"""Backward-compatible imports for the original Jev client module.

New code can import :class:`TypeSafeProvider` from ``mellea_jev.providers``.
"""
from .contracts import (
    ChoiceCriteria,
    ChoiceDescription,
    JsonValue,
    NoulCriteria,
)
from .criteria import _json_description, _json_value, probability
from .providers.typesafe import (
    CHOICE_QUESTION_ID,
    ENDPOINT,
    QUESTION_ID,
    SCORE_QUESTION_ID,
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
    TypeSafeProvider,
    TypeSafeQuestion,
    TypeSafeUsage,
    _choice_criteria,
    _noul_criteria,
    _parse_answer,
    _score_criteria,
    _score_response_map,
)

__all__ = [
    "CHOICE_QUESTION_ID",
    "ENDPOINT",
    "QUESTION_ID",
    "SCORE_QUESTION_ID",
    "ChoiceCriteria",
    "ChoiceDescription",
    "ChoiceQuestion",
    "ChoiceResult",
    "JevClient",
    "JevError",
    "JevHTTPError",
    "JevProtocolError",
    "JsonValue",
    "NoulCriteria",
    "NoulQuestion",
    "NoulResult",
    "ScoreQuestion",
    "ScoreResult",
    "SystemOneResult",
    "TypeSafeAnswer",
    "TypeSafeProvider",
    "TypeSafeQuestion",
    "TypeSafeUsage",
    "probability",
]
