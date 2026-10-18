"""Categorical task snapshots and explicit native projections, without inference."""

from collections.abc import Mapping

import pytest

from mellea_jev import (
    CategoricalResult,
    CategoricalTask,
    ChoiceQuestion,
    ChoiceResult,
    NoulQuestion,
    UsageMetadata,
    project_choice_results,
)


def task():
    return CategoricalTask(
        state={"source": ["Пример", {"nested": True}]},
        questions={
            "role": ChoiceQuestion("Role?", {"a": {"examples": ["policy"]}, "b": None}),
            "support": ChoiceQuestion("Supported?", {"yes": "Supported", "unknown": []}),
        },
    )


def test_task_preserves_order_and_structured_descriptions_with_detached_views():
    state = {"source": ["original"]}
    question = ChoiceQuestion("Role?", {"a": {"examples": ["policy"]}, "b": None})
    questions = {"role": question}
    value = CategoricalTask(state=state, questions=questions)
    state["source"].append("changed")
    question.criteria["a"]["examples"].append("changed")
    questions.clear()
    value.state["source"].append("changed")
    value.questions["role"].criteria["a"]["examples"].append("changed")
    assert value.to_dict() == {
        "state": {"source": ["original"]},
        "questions": {
            "role": {
                "instructions": "Role?",
                "criteria": {
                    "a": {"examples": ["policy"]},
                    "b": None,
                },
            }
        },
    }
    assert list(task().questions) == ["role", "support"]
    assert list(task().questions["support"].criteria) == ["yes", "unknown"]
    assert "original" not in repr(value)


@pytest.mark.parametrize(
    "state", [[], "text", {1: "value"}, {"bad": float("nan")}, {"file": b"bytes"}]
)
def test_invalid_state(state):
    with pytest.raises((ValueError, TypeError)):
        CategoricalTask(state=state, questions=task().questions)


@pytest.mark.parametrize(
    "questions", [{}, [], {"": ChoiceQuestion("Q?", {"a": None})}, {"id": NoulQuestion("Q?")}]
)
def test_invalid_questions(questions):
    with pytest.raises((ValueError, TypeError)):
        CategoricalTask(state={}, questions=questions)


def test_duplicate_ids_in_a_custom_mapping_are_rejected():
    class Duplicates(Mapping):
        def __iter__(self):
            return iter(["role", "role"])

        def __len__(self):
            return 2

        def __getitem__(self, key):
            return ChoiceQuestion("Q?", {"a": None})

    with pytest.raises(ValueError, match="unique"):
        CategoricalTask(state={}, questions=Duplicates())


def test_native_projection_keeps_evidence_without_inventing_batch_metadata():
    role = ChoiceResult("a", 0.8, {"a": 0.8, "b": 0.2}, "native-model", "r1", UsageMetadata(10, 0))
    support = ChoiceResult("unknown", 0.9, {"yes": 0.1, "unknown": 0.9}, "native-model", "r2")
    value = project_choice_results(task(), {"support": support, "role": role})
    assert dict(value.answers) == {"role": "a", "support": "unknown"}
    assert list(value.answers) == ["role", "support"]
    assert value.requested_model is None
    assert value.returned_model == "native-model"
    assert value.request_id is None and value.usage is None
    assert value.settings is None and value.adapter_revision is None and value.evidence is None
    assert value.native_results["role"] is role
    assert value.native_results["support"] is support
    assert not hasattr(value, "confidence") and not hasattr(value, "probabilities")
    with pytest.raises(TypeError):
        value.answers["role"] = "b"
    mixed = project_choice_results(
        task(),
        {
            "role": role,
            "support": ChoiceResult("yes", 1, {"yes": 1, "unknown": 0}, "another-model"),
        },
    )
    assert mixed.returned_model is None


def test_projection_accepts_explicit_actual_batch_metadata():
    native = {"q": ChoiceResult("a", 1, {"a": 1}, "actual")}
    value = project_choice_results(
        CategoricalTask(state={}, questions={"q": ChoiceQuestion("Q?", {"a": None})}),
        native,
        requested_model="alias",
        request_id="batch-request",
        usage=UsageMetadata(10, 1),
    )
    assert value.requested_model == "alias" and value.returned_model == "actual"
    assert value.request_id == "batch-request" and value.usage == UsageMetadata(10, 1)


@pytest.mark.parametrize(
    "results",
    [
        {},
        {"role": object(), "support": object()},
        {"extra": object()},
        {"role": ChoiceResult("c", 1, {"c": 1}, "m"), "support": object()},
    ],
)
def test_projection_rejects_mismatched_or_non_choice_native_results(results):
    with pytest.raises(ValueError):
        project_choice_results(task(), results)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"answers": {}},
        {"answers": {"q": ""}},
        {"answers": {"": "a"}},
        {"answers": {"q": "a"}, "returned_model": ""},
        {"answers": {"q": "a"}, "requested_model": 1},
        {"answers": {"q": "a"}, "usage": {}},
    ],
)
def test_result_metadata_validation(kwargs):
    with pytest.raises((ValueError, TypeError)):
        CategoricalResult(**kwargs)


def test_projection_revalidates_mutated_native_distributions():
    value = ChoiceResult("a", 1, {"a": 1, "b": 0}, "actual")
    value.probabilities["a"] = 0
    with pytest.raises(ValueError, match="sum"):
        project_choice_results(
            CategoricalTask(
                state={}, questions={"q": ChoiceQuestion("Q?", {"a": None, "b": None})}
            ),
            {"q": value},
        )


def test_result_rejects_mismatched_native_evidence():
    with pytest.raises(ValueError, match="Native results"):
        CategoricalResult(
            answers={"q": "a"}, native_results={"other": ChoiceResult("a", 1, {"a": 1}, "m")}
        )
