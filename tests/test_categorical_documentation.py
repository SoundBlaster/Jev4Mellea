"""Execute the documented consumer policy/budget with deterministic providers only."""

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mellea_jev import (
    CategoricalDecision,
    CategoricalResult,
    CategoricalReviewRequired,
    CategoricalTask,
    ChoiceQuestion,
    JevHTTPError,
)

GUIDE = Path(__file__).resolve().parents[1] / "docs/categorical_requirement.md"


def blocks():
    return re.findall(r"```python\n(.*?)\n```", GUIDE.read_text(), re.DOTALL)


def scenario(first="unknown", second="supported"):
    task = CategoricalTask(
        state={"source": "immutable"},
        questions={
            "support": ChoiceQuestion(
                "Supported?", {"supported": None, "unsupported": None, "unknown": None}
            )
        },
    )

    def policy(result):
        label = result.answers["support"]
        outcome = {"supported": "accept", "unsupported": "reject", "unknown": "review"}[label]
        return CategoricalDecision(outcome, "Caller policy.")

    return {
        "task": task,
        "policy": policy,
        "primary": SimpleNamespace(
            classify=Mock(return_value=CategoricalResult({"support": first}))
        ),
        "secondary": SimpleNamespace(
            classify=Mock(return_value=CategoricalResult({"support": second}))
        ),
    }


def test_documented_python_snippets_are_syntactically_valid():
    assert len(blocks()) == 3
    for block in blocks():
        ast.parse(block)


@pytest.mark.parametrize("first", ["supported", "unsupported", "unknown"])
@pytest.mark.parametrize("second", ["supported", "unsupported", "unknown"])
def test_documented_escalation_obeys_policy_and_two_call_budget(first, second):
    namespace = scenario(first, second)
    if first == second == "unknown":
        with pytest.raises(CategoricalReviewRequired) as captured:
            exec(blocks()[-1], namespace)
        assert captured.value.evaluation is namespace["evaluations"][-1]
    else:
        exec(blocks()[-1], namespace)
        expected_label = second if first == "unknown" else first
        assert namespace["decision"].outcome == (
            "accept" if expected_label == "supported" else "reject"
        )
    budget = namespace["budget"]
    primary, secondary = namespace["primary"], namespace["secondary"]
    assert budget.reserved == len(namespace["evaluations"]) == (2 if first == "unknown" else 1)
    primary.classify.assert_called_once_with(namespace["task"])
    if first == "unknown":
        secondary.classify.assert_called_once_with(namespace["task"])
    else:
        secondary.classify.assert_not_called()
    budget.reserved = 2
    with pytest.raises(RuntimeError, match="budget exhausted"):
        budget.classify(secondary, namespace["task"])
    assert secondary.classify.call_count == (1 if first == "unknown" else 0)


def test_documented_escalation_retains_unknown_outcome_reservation_without_fallback():
    namespace = scenario()
    error = JevHTTPError(503)
    namespace["primary"].classify.side_effect = error
    with pytest.raises(JevHTTPError) as captured:
        exec(blocks()[-1], namespace)
    assert captured.value is error and namespace["budget"].reserved == 1
    namespace["primary"].classify.assert_called_once()
    namespace["secondary"].classify.assert_not_called()
