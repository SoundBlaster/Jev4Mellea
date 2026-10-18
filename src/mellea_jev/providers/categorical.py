"""Borrow native providers for one-question categorical tasks; never own their lifetime."""

from __future__ import annotations

from dataclasses import replace

from ..categorical import (
    CapabilityMismatchError,
    CategoricalCapabilities,
    CategoricalResult,
    CategoricalTask,
    project_choice_results,
)
from ..results import ChoiceResult
from .openai import OpenAIProvider
from .typesafe import ChoiceQuestion, JevProtocolError, TypeSafeProvider


def _single_question(task: CategoricalTask) -> tuple[str, ChoiceQuestion]:
    if not isinstance(task, CategoricalTask):
        raise TypeError("classify requires a CategoricalTask.")
    questions = task.questions
    if len(questions) != 1:
        raise CapabilityMismatchError("This native categorical wrapper requires one question.")
    return next(iter(questions.items()))


class TypeSafeCategoricalProvider:
    """Compose an existing TypeSafe provider; one task issues one System One request.

    The caller owns and closes the borrowed provider. Native System One batching
    remains available separately; this wrapper deliberately rejects batches.
    """

    capabilities = CategoricalCapabilities(False, False, True)

    def __init__(self, provider: TypeSafeProvider) -> None:
        if not isinstance(provider, TypeSafeProvider):
            raise TypeError("Supply a TypeSafeProvider.")
        self.provider = provider

    def classify(self, task: CategoricalTask) -> CategoricalResult:
        name, question = _single_question(task)
        requested_model = self.provider.model
        response = self.provider.system_one(state=task.state, questions={name: question})
        result = response.answers[name]
        if not isinstance(result, ChoiceResult):
            raise JevProtocolError("Expected a native Choice result; no classification.")
        return replace(
            project_choice_results(
                task,
                {name: result},
                requested_model=requested_model,
                request_id=response.request_id,
                usage=response.usage,
            ),
            adapter_revision="typesafe-categorical-choice-v1",
        )


class OpenAICategoricalProvider:
    """Compose an OpenAI Decisions provider; preserve the caller's question name.

    The caller owns and closes the borrowed provider. Responses generation uses
    ResponsesChoiceProvider instead; no protocol/model fallback is performed.
    """

    capabilities = CategoricalCapabilities(False, False, True)

    def __init__(self, provider: OpenAIProvider) -> None:
        if not isinstance(provider, OpenAIProvider):
            raise TypeError("Supply an OpenAIProvider.")
        self.provider = provider

    def classify(self, task: CategoricalTask) -> CategoricalResult:
        name, question = _single_question(task)
        requested_model = self.provider.model
        result = self.provider._choice_with_name(
            name=name,
            state=task.state,
            question=question.instructions,
            criteria=question.criteria,
        )
        # This result comes from exactly one request with exactly one answer;
        # its metadata was copied from that request, never aggregated.
        return replace(
            project_choice_results(
                task,
                {name: result},
                requested_model=requested_model,
                request_id=result.request_id,
                usage=result.usage,
            ),
            adapter_revision="openai-categorical-choice-v1",
        )
