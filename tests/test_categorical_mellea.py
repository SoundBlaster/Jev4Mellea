"""Real Mellea hooks and sampling; deterministic generation, provider HTTP mocked."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest

pytest.importorskip("mellea", reason="Install .[mellea,dev] for the optional bridge.")
from mellea import MelleaSession
from mellea.backends.dummy import DummyBackend
from mellea.core import Context, Requirement, ValidationResult
from mellea.core.base import GenerateLog
from mellea.stdlib.components import Instruction
from mellea.stdlib.sampling import RepairTemplateStrategy

from mellea_jev import (
    CategoricalDecision,
    CategoricalRequirement,
    CategoricalResult,
    CategoricalReviewRequired,
    CategoricalTask,
    ChoiceQuestion,
    ChoiceResult,
    JevHTTPError,
    TypeSafeCategoricalProvider,
    TypeSafeProvider,
    accepted_text,
    project_choice_results,
)

pytestmark = pytest.mark.integration
DESCRIPTION = "PRIVATE_TARGET_LABEL_FOR_ACCEPTANCE"
SOURCE = "The museum opens at 10:00."
QUESTIONS = {
    "support": ChoiceQuestion(
        "Does the candidate agree with the source?",
        {"supported": "Agrees", "unsupported": "Contradicts", "unknown": "Insufficient facts"},
    )
}


def build_task(ctx):
    return CategoricalTask(
        state={"source": SOURCE, "typed_candidate": {"text": ctx.last_output().value}},
        questions=QUESTIONS,
    )


def context():
    ctx = Mock(spec=Context)
    ctx.last_output.return_value = SimpleNamespace(value="Candidate text")
    return ctx


@pytest.mark.parametrize("outcome", ["accept", "reject", "review"])
def test_real_requirement_maps_policy_without_collapsing_review(outcome):
    observed = []
    categorical = CategoricalResult({"support": "unknown"})
    provider = SimpleNamespace(classify=Mock(return_value=categorical))
    bridge = CategoricalRequirement(
        provider,
        task_builder=build_task,
        policy=lambda _: CategoricalDecision(outcome, "Caller reason"),
        description=DESCRIPTION,
        on_evaluated=observed.append,
    )
    requirement = bridge.as_requirement()
    assert isinstance(requirement, Requirement) and requirement.check_only is True
    ctx = context()
    if outcome == "review":
        with pytest.raises(CategoricalReviewRequired) as captured:
            asyncio.run(requirement.validate(backend=None, ctx=ctx))
        assert captured.value.evaluation is observed[0]
        assert captured.value.evaluation.result is categorical
        assert "Candidate text" not in str(captured.value)
    else:
        value = asyncio.run(requirement.validate(backend=None, ctx=ctx))
        assert isinstance(value, ValidationResult)
        assert bool(value) is (outcome == "accept")
        assert value.score is None and value.reason == "Caller reason"
    assert len(observed) == 1 and provider.classify.call_count == 1
    assert observed[0].task.state == {
        "source": SOURCE,
        "typed_candidate": {"text": "Candidate text"},
    }


def test_real_requirement_preserves_operational_error():
    error = JevHTTPError(401)
    provider = SimpleNamespace(classify=Mock(side_effect=error))
    bridge = CategoricalRequirement(
        provider,
        task_builder=build_task,
        policy=Mock(),
        description=DESCRIPTION,
    )
    with pytest.raises(JevHTTPError) as captured:
        asyncio.run(bridge.as_requirement().validate(backend=None, ctx=context()))
    assert captured.value is error
    bridge.policy.assert_not_called()
    provider.classify.assert_called_once()


def test_check_only_omits_target_description_from_real_instruction():
    bridge = CategoricalRequirement(
        SimpleNamespace(classify=Mock()),
        task_builder=build_task,
        policy=Mock(),
        description=DESCRIPTION,
    )
    hidden = Instruction("Generate a candidate.", requirements=[bridge.as_requirement()])
    visible = Instruction(
        "Generate a candidate.", requirements=[bridge.as_requirement(check_only=False)]
    )
    assert hidden.format_for_llm().args["requirements"] == []
    assert visible.format_for_llm().args["requirements"] == [DESCRIPTION]


def test_real_requirement_score_is_selected_from_native_evidence():
    native = ChoiceResult(
        "supported", 0.82, {"supported": 0.88, "unsupported": 0.10, "unknown": 0.02}, "actual"
    )
    result = project_choice_results(build_task(context()), {"support": native})
    bridge = CategoricalRequirement(
        SimpleNamespace(classify=lambda _: result),
        task_builder=build_task,
        policy=lambda value: CategoricalDecision(
            "accept", "Caller policy", value.native_results["support"].confidence
        ),
        description=DESCRIPTION,
    )
    validated = asyncio.run(bridge.as_requirement().validate(backend=None, ctx=context()))
    assert bool(validated) and validated.score == 0.82


def test_real_sampling_with_explicit_two_attempt_budget_preserves_source_binding():
    requests, observations, prompts = [], [], []

    class RecordingBackend(DummyBackend):
        async def _generate_from_context(self, action, ctx, **kwargs):
            prompts.append(action.format_for_llm().args)
            output, result_ctx = await super()._generate_from_context(action, ctx, **kwargs)
            # DummyBackend omits the log required by real sampling's final selection.
            output._generate_log = GenerateLog()
            return output, result_ctx

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        label = "unsupported" if len(requests) == 1 else "supported"
        return httpx2.Response(
            200,
            json={
                "model": "jev-fixture",
                "answers": {
                    "support": {
                        "type": "choice",
                        "choice": label,
                        "confidence": 0.82,
                        "probabilities": {
                            key: 0.9 if key == label else 0.05
                            for key in QUESTIONS["support"].criteria
                        },
                    }
                },
            },
        )

    def policy(result):
        accepted = result.answers["support"] == "supported"
        return CategoricalDecision(
            "accept" if accepted else "reject",
            "Caller accepted." if accepted else "Revise the unsupported fact.",
        )

    backend = RecordingBackend(responses=["It opens at 12:00.", "It opens at 10:00."])
    session = MelleaSession(backend=backend)
    with TypeSafeProvider("fixture-key", transport=httpx2.MockTransport(handler)) as native:
        bridge = CategoricalRequirement(
            TypeSafeCategoricalProvider(native),
            task_builder=build_task,
            policy=policy,
            description=DESCRIPTION,
            on_evaluated=observations.append,
        )
        sampled = session.instruct(
            "Summarize the opening time.",
            requirements=[bridge.as_requirement()],
            strategy=RepairTemplateStrategy(loop_budget=2, concurrency_budget=1),
            return_sampling_results=True,
        )
    assert accepted_text(sampled) == "It opens at 10:00."
    assert backend.idx == len(requests) == len(observations) == 2
    assert [value.decision.outcome for value in observations] == ["reject", "accept"]
    assert [p["state"] for p in requests] == [
        {"source": SOURCE, "typed_candidate": {"text": candidate}}
        for candidate in ["It opens at 12:00.", "It opens at 10:00."]
    ]
    assert all(p["questions"] == {"support": QUESTIONS["support"].to_payload()} for p in requests)
    assert DESCRIPTION not in json.dumps(requests)
    assert all(p["requirements"] == [] for p in prompts)


@pytest.mark.parametrize("review", [True, False])
def test_single_attempt_sampling_preserves_review_or_operational_error(review):
    provider = SimpleNamespace(
        classify=Mock(return_value=CategoricalResult({"support": "unknown"}))
    )
    if not review:
        provider.classify.side_effect = JevHTTPError(401)
    bridge = CategoricalRequirement(
        provider,
        task_builder=build_task,
        policy=lambda _: CategoricalDecision("review", "Caller policy"),
        description=DESCRIPTION,
    )
    session = MelleaSession(backend=DummyBackend(responses=["Candidate text"]))
    with pytest.raises(CategoricalReviewRequired if review else JevHTTPError):
        session.instruct(
            "Generate.",
            requirements=[bridge.as_requirement()],
            strategy=RepairTemplateStrategy(loop_budget=1, concurrency_budget=1),
            return_sampling_results=True,
        )
    provider.classify.assert_called_once()
