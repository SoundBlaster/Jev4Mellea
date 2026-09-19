"""Isolated contract doubles, NOT proof of compatibility with installed Mellea.

The separate test_mellea_integration.py imports and exercises the real package.
These tests test our wiring even in environments without that dependency.
"""
import sys
from types import ModuleType, SimpleNamespace

import pytest

from mellea_jev import (
    ChoiceResult, JevClassifier, JevError, JevVerifier, NoulResult, ReviewRequired,
)


@pytest.fixture
def contract_module(monkeypatch):
    core = ModuleType("mellea.core")

    class RequirementDouble:
        def __init__(self, description=None, validation_fn=None, *, check_only=False):
            self.description = description
            self.validation_fn = validation_fn
            self.check_only = check_only

    class ValidationResultDouble:
        def __init__(self, result, reason=None, score=None):
            self.result, self.reason, self.score = result, reason, score
        def __bool__(self):
            return self.result

    core.Requirement = RequirementDouble
    core.ValidationResult = ValidationResultDouble
    parent = ModuleType("mellea")
    parent.core = core
    monkeypatch.setitem(sys.modules, "mellea", parent)
    monkeypatch.setitem(sys.modules, "mellea.core", core)
    return core


class Client:
    def __init__(self, p):
        self.p = p
    def noul(self, **_):
        return NoulResult(self.p, "jev-contract-double")


def context(text):
    return SimpleNamespace(last_output=lambda: SimpleNamespace(value=text))


@pytest.mark.parametrize("p,expected", [(0.99, True), (0.01, False)])
def test_sync_validation_callback(contract_module, p, expected):
    requirement = JevVerifier(Client(p), "Be polite.").as_requirement(check_only=True)
    assert isinstance(requirement, contract_module.Requirement)
    assert requirement.check_only is True
    assert requirement.description == "Be polite."
    result = requirement.validation_fn(context("Hello"))
    assert isinstance(result, contract_module.ValidationResult)
    assert bool(result) is expected
    assert result.score == p


def test_uncertainty_aborts_callback_instead_of_triggering_repair(contract_module):
    requirement = JevVerifier(Client(0.5), "Be polite.").as_requirement()
    with pytest.raises(ReviewRequired) as exc:
        requirement.validation_fn(context("Hello"))
    assert exc.value.verdict.outcome == "uncertain"
    assert exc.value.candidate == "Hello"


def test_no_last_output_is_repairable(contract_module):
    requirement = JevVerifier(Client(0.99), "Be polite.").as_requirement()
    result = requirement.validation_fn(SimpleNamespace(last_output=lambda: None))
    assert not result
    assert result.score is None


def test_api_error_propagates_through_callback(contract_module):
    class BrokenClient:
        def noul(self, **_):
            raise JevError("not available")
    requirement = JevVerifier(BrokenClient(), "Be polite.").as_requirement()
    with pytest.raises(JevError):
        requirement.validation_fn(context("Hello"))


def test_choice_requirement_accepts_expected_class(contract_module):
    class ClassifierClient:
        def choice(self, **_):
            return ChoiceResult(
                "billing", 0.8,
                {"billing": 0.8, "technical": 0.2},
                "jev-contract-double",
            )

    classifier = JevClassifier(
        ClassifierClient(), "Choose a category.",
        criteria={"billing": "Payment issues", "technical": "Product issues"},
    )
    requirement = classifier.as_requirement("billing", minimum_confidence=0.7)
    result = requirement.validation_fn(context("I was charged twice."))
    assert isinstance(requirement, contract_module.Requirement)
    assert isinstance(result, contract_module.ValidationResult)
    assert bool(result)
    assert result.score == 0.8


def test_choice_requirement_fails_for_other_class_and_bad_expected_class(contract_module):
    class ClassifierClient:
        def choice(self, **_):
            return ChoiceResult(
                "technical", 0.8,
                {"billing": 0.2, "technical": 0.8},
                "jev-contract-double",
            )

    classifier = JevClassifier(
        ClassifierClient(), "Choose a category.",
        criteria={"billing": "Payment issues", "technical": "Product issues"},
    )
    with pytest.raises(ValueError, match="configured criteria"):
        classifier.as_requirement("other")
    result = classifier.as_requirement("billing").validation_fn(context("Broken app."))
    assert not result
    assert result.score == 0.2
    assert "Expected class 'billing'" in result.reason


def test_choice_requirement_can_reject_low_confidence(contract_module):
    class ClassifierClient:
        def choice(self, **_):
            return ChoiceResult(
                "billing", 0.6,
                {"billing": 0.6, "technical": 0.4},
                "jev-contract-double",
            )

    classifier = JevClassifier(
        ClassifierClient(), "Choose a category.",
        criteria={"billing": "Payment issues", "technical": "Product issues"},
    )
    result = classifier.as_requirement("billing", minimum_confidence=0.8).validation_fn(
        context("I might have been charged twice.")
    )
    assert not result
    assert result.score == 0.6
    assert "below the configured minimum" in result.reason
