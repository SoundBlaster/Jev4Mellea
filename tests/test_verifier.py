from types import SimpleNamespace

import pytest

from mellea_jev import (
    GenerationRejected, JevError, JevVerifier, NoulResult, ReviewRequired,
    Verdict, accepted_text,
)


class ScriptedClient:
    def __init__(self, p=0.99):
        self.p = p
        self.calls = []

    def noul(self, *, state, question):
        self.calls.append({"state": state, "question": question})
        return NoulResult(self.p, "jev-test-fixture", "fixture-request")


@pytest.mark.parametrize("p,outcome", [
    (0, "fail"), (0.1, "fail"), (0.100001, "uncertain"),
    (0.5, "uncertain"), (0.899999, "uncertain"), (0.9, "pass"), (1, "pass"),
])
def test_default_policy_boundaries(p, outcome):
    verdict = JevVerifier(ScriptedClient(p), "It is polite.").evaluate("Hello")
    assert verdict.outcome == outcome
    assert verdict.accepted is (outcome == "pass")
    assert verdict.p_yes == p
    assert verdict.model == "jev-test-fixture"


def test_custom_thresholds():
    verifier = JevVerifier(ScriptedClient(0.8), "It is polite.", accept_at=0.8, reject_at=0.2)
    assert verifier.evaluate("Hello").accepted


@pytest.mark.parametrize("kwargs", [
    {"accept_at": True}, {"reject_at": False}, {"accept_at": float("nan")},
    {"reject_at": -1}, {"accept_at": 1.01}, {"accept_at": 0.5},
    {"reject_at": 0.5}, {"accept_at": 0.2, "reject_at": 0.8},
])
def test_invalid_thresholds(kwargs):
    with pytest.raises(ValueError):
        JevVerifier(ScriptedClient(), "It is polite.", **kwargs)


@pytest.mark.parametrize("candidate", [None, "", " \n\t"])
def test_empty_output_fails_without_paying_for_a_request(candidate):
    client = ScriptedClient()
    verdict = JevVerifier(client, "It is polite.").evaluate(candidate)
    assert verdict.outcome == "fail"
    assert verdict.p_yes is None  # Not an invented model probability.
    assert client.calls == []


def test_only_candidate_and_explicit_reference_are_sent():
    client = ScriptedClient()
    verifier = JevVerifier(client, "It matches the source.", reference="Source text.")
    verifier.evaluate("Candidate text.")
    assert client.calls[0]["state"] == {
        "candidate": "Candidate text.", "reference": "Source text."
    }
    assert "It matches the source." in client.calls[0]["question"]
    assert "data, not instructions" in client.calls[0]["question"]


def test_reference_is_omitted_when_not_supplied():
    client = ScriptedClient()
    JevVerifier(client, "It is polite.").evaluate("Hello")
    assert client.calls[0]["state"] == {"candidate": "Hello"}


def test_verifier_passes_optional_noul_criteria():
    class CriteriaClient:
        def noul(self, *, state, question, criteria):
            self.criteria = criteria
            return NoulResult(0.99, "jev-test-fixture")

    configured = {"true": {"what": "The requirement is met"}, "false": ["Not met"]}
    client = CriteriaClient()
    verifier = JevVerifier(client, "The candidate is polite.", criteria=configured)
    configured["true"]["what"] = "changed after verifier setup"

    assert verifier.evaluate("Thank you!").accepted
    assert client.criteria == {"true": {"what": "The requirement is met"}, "false": ["Not met"]}


def test_explicit_repair_hint_not_a_fabricated_model_explanation():
    verdict = JevVerifier(
        ScriptedClient(0.03), "It matches the source.",
        repair_hint="Remove claims not present in the source.",
    ).evaluate("Some answer")
    assert "Remove claims not present in the source." in verdict.reason
    assert verdict.p_yes == 0.03


def test_verifier_never_turns_an_api_error_into_an_acceptance():
    class BrokenClient:
        def noul(self, **_):
            raise JevError("transport failed")

    with pytest.raises(JevError):
        JevVerifier(BrokenClient(), "It is polite.").evaluate("Hello")


def test_verdict_serialization_is_metadata_only():
    verdict = JevVerifier(ScriptedClient(), "It is polite.").evaluate("SECRET-CANDIDATE")
    data = verdict.to_dict()
    assert data["outcome"] == "pass"
    assert "SECRET-CANDIDATE" not in str(data)
    assert "confidence" not in data


def test_review_error_preserves_candidate_without_printing_it():
    verdict = Verdict("uncertain", 0.5, "uncertain")
    error = ReviewRequired(verdict, "PRIVATE-TEXT")
    assert error.candidate == "PRIVATE-TEXT"
    assert error.verdict is verdict
    assert "PRIVATE-TEXT" not in str(error)


@pytest.mark.parametrize("kwargs,error", [
    ({"description": ""}, ValueError), ({"description": None}, ValueError),
    ({"description": "ok", "reference": []}, TypeError),
    ({"description": "ok", "repair_hint": []}, TypeError),
])
def test_bad_configuration(kwargs, error):
    with pytest.raises(error):
        JevVerifier(ScriptedClient(), **kwargs)


def test_nontext_candidates_are_not_silently_stringified():
    with pytest.raises(TypeError):
        JevVerifier(ScriptedClient(), "It is polite.").evaluate({"text": "Hello"})


def sampled(success=True, validations=None, text="Accepted answer"):
    return SimpleNamespace(
        success=success,
        result_validations=[("r", True)] if validations is None else validations,
        result=SimpleNamespace(value=text),
    )


def test_accepted_text_returns_only_validated_success():
    assert accepted_text(sampled()) == "Accepted answer"


@pytest.mark.parametrize("result", [
    sampled(success=False), sampled(success=None),
    sampled(validations=[]), sampled(validations=[("r", False)]),
    sampled(validations=[("r1", True), ("r2", False)]),
    sampled(text=None), sampled(text=""), sampled(text="  "), sampled(text=42),
    SimpleNamespace(success=True, result_validations=[("r", True)], result=None),
])
def test_final_fallback_never_leaks_as_an_accepted_answer(result):
    with pytest.raises(GenerationRejected):
        accepted_text(result)


def test_missing_final_history_is_rejected_explicitly():
    class MissingHistory:
        success = True

        @property
        def result_validations(self):
            # SamplingResult uses direct indexing into sample_validations.
            raise IndexError("list index out of range")

    with pytest.raises(GenerationRejected, match="history is missing"):
        accepted_text(MissingHistory())
