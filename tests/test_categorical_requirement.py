"""Task binding/policy evaluation needs no Mellea, SDK, or inference service."""

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mellea_jev import (
    CapabilityMismatchError,
    CategoricalDecision,
    CategoricalProtocolError,
    CategoricalRequirement,
    CategoricalResult,
    CategoricalTask,
    ChoiceQuestion,
    ChoiceResult,
    JevHTTPError,
    project_choice_results,
)


def task():
    return CategoricalTask(
        state={"source": "SOURCE", "typed_candidate": {"paid": True}},
        questions={
            "compatibility": ChoiceQuestion(
                "Is the candidate compatible with the source?",
                {"compatible": None, "incompatible": None, "indeterminate": None},
            )
        },
    )


def bridge(result=None, **options):
    provider = SimpleNamespace(
        classify=Mock(return_value=result or CategoricalResult({"compatibility": "indeterminate"}))
    )
    return CategoricalRequirement(
        provider,
        task_builder=options.pop("task_builder", lambda _: task()),
        policy=options.pop("policy", lambda _: CategoricalDecision("review", "Caller policy")),
        description="Caller acceptance target; not evaluation gold",
        **options,
    )


@pytest.mark.parametrize("outcome", ["accept", "reject", "review"])
def test_category_is_independent_of_policy_and_full_evaluation_is_observable(outcome):
    observed = []
    bound = task()
    result = CategoricalResult({"compatibility": "indeterminate"}, returned_model="actual")
    policy = Mock(return_value=CategoricalDecision(outcome, "Caller reason"))
    requirement = bridge(
        result,
        task_builder=lambda _: bound,
        policy=policy,
        on_evaluated=observed.append,
    )
    evaluation = requirement.evaluate(object())
    assert evaluation.task is bound and evaluation.result is result
    assert evaluation.decision.outcome == outcome and evaluation.decision.score is None
    assert observed == [evaluation]
    requirement.provider.classify.assert_called_once_with(bound)
    policy.assert_called_once_with(result)
    assert "SOURCE" not in repr(evaluation)
    assert "Caller reason" not in repr(evaluation.decision)


def test_policy_can_select_native_score_without_generating_new_evidence():
    native = ChoiceResult(
        "compatible",
        0.82,
        {"compatible": 0.88, "incompatible": 0.10, "indeterminate": 0.02},
        "native-model",
    )
    result = project_choice_results(task(), {"compatibility": native})
    requirement = bridge(
        result,
        policy=lambda value: CategoricalDecision(
            "accept", "Caller native policy", value.native_results["compatibility"].confidence
        ),
    )
    evaluation = requirement.evaluate(object())
    assert evaluation.decision.score == 0.82
    assert evaluation.result.native_results["compatibility"] is native


def test_label_only_score_is_rejected_instead_of_inventing_confidence():
    requirement = bridge(policy=lambda _: CategoricalDecision("accept", "Bad policy", 1))
    with pytest.raises(CapabilityMismatchError, match="native"):
        requirement.evaluate(object())
    requirement.provider.classify.assert_called_once()


@pytest.mark.parametrize("score", [True, "1", float("nan"), float("inf"), object()])
def test_invalid_policy_scores(score):
    with pytest.raises(ValueError):
        CategoricalDecision("accept", "Reason", score)


@pytest.mark.parametrize("outcome,reason", [("indeterminate", "r"), (True, "r"), ("review", "")])
def test_invalid_policy_decisions(outcome, reason):
    with pytest.raises(ValueError):
        CategoricalDecision(outcome, reason)


@pytest.mark.parametrize(
    "result",
    [
        CategoricalResult({"wrong-id": "compatible"}),
        CategoricalResult({"compatibility": "not-configured"}),
        CategoricalResult({"compatibility": "compatible", "extra": "compatible"}),
    ],
)
def test_result_task_mismatch_never_reaches_policy(result):
    policy = Mock()
    requirement = bridge(result, policy=policy)
    with pytest.raises(CategoricalProtocolError):
        requirement.evaluate(object())
    policy.assert_not_called()
    requirement.provider.classify.assert_called_once()


def test_wrong_provider_return_type_and_policy_return_type_are_errors():
    requirement = bridge()
    requirement.provider.classify.return_value = "compatible"
    with pytest.raises(TypeError, match="CategoricalResult"):
        requirement.evaluate(object())
    requirement = bridge(policy=lambda _: True)
    with pytest.raises(TypeError, match="CategoricalDecision"):
        requirement.evaluate(object())


def test_builder_is_explicit_and_must_return_a_task_before_any_provider_call():
    requirement = bridge(task_builder=lambda _: {"candidate": "rewritten"})
    with pytest.raises(TypeError, match="CategoricalTask"):
        requirement.evaluate(object())
    requirement.provider.classify.assert_not_called()


@pytest.mark.parametrize("stage", ["task_builder", "provider", "policy", "observer"])
def test_operational_and_callback_errors_propagate_without_semantic_rejection(stage):
    error = JevHTTPError(401)
    failing = Mock(side_effect=error)
    options = {}
    if stage == "task_builder":
        options["task_builder"] = failing
    elif stage == "policy":
        options["policy"] = failing
    elif stage == "observer":
        options["on_evaluated"] = failing
    requirement = bridge(**options)
    if stage == "provider":
        requirement.provider.classify = failing
    with pytest.raises(JevHTTPError) as captured:
        requirement.evaluate(object())
    assert captured.value is error
    assert requirement.provider.classify.call_count == (0 if stage == "task_builder" else 1)


@pytest.mark.parametrize(
    "options",
    [
        {"provider": object()},
        {"task_builder": None},
        {"policy": None},
        {"description": ""},
        {"on_evaluated": False},
    ],
)
def test_invalid_composition_fails_on_construction(options):
    settings = {
        "provider": SimpleNamespace(classify=Mock()),
        "task_builder": lambda _: task(),
        "policy": lambda _: CategoricalDecision("accept", "r"),
        "description": "Description",
        **options,
    }
    with pytest.raises((ValueError, TypeError)):
        CategoricalRequirement(**settings)


def test_no_mellea_or_openai_import_is_required_for_basic_composition():
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mellea', 'openai'):
            raise ModuleNotFoundError('Blocked optional dependency')
sys.meta_path.insert(0, Block())
from types import SimpleNamespace
from mellea_jev import (
    CategoricalTask, ChoiceQuestion, CategoricalRequirement,
    CategoricalResult, CategoricalDecision,
)
task = CategoricalTask(state={}, questions={'q': ChoiceQuestion('Q?', {'a': None})})
bridge = CategoricalRequirement(
    SimpleNamespace(classify=lambda _: CategoricalResult({'q': 'a'})),
    task_builder=lambda ctx: task,
    policy=lambda result: CategoricalDecision('accept', 'Caller reason'),
    description='Private validation target',
)
assert bridge.evaluate(object()).decision.outcome == 'accept'
assert 'mellea' not in sys.modules and 'openai' not in sys.modules
try:
    bridge.as_requirement()
except ModuleNotFoundError:
    pass
else:
    raise AssertionError('Expected missing optional Mellea')
"""
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
