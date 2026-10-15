"""Bounded opt-in matrix using both actual SDKs and mocked Hub HTTP."""

import json

import httpx2
import pytest
from test_choice import choice_wire as systemone_choice
from test_client import wire as systemone_noul
from test_images import PNG
from test_openai_choice import choice_wire as decisions_choice
from test_openai_provider import wire as decisions_noul
from test_openai_score import score_wire as decisions_score
from test_score import score_wire as systemone_score

from examples import coreinfra_check as check
from mellea_jev import coreinfra_provider


def reply(request):
    payload = json.loads(request.content)
    if "systemone" in request.url.path:
        question = next(iter(payload["questions"].values()))
        if question["type"] == "noul":
            assert question["criteria"] == check.CHECKS["noul"]["criteria"]
            body = systemone_noul()
        elif question["type"] == "choice":
            body = systemone_choice(probabilities={"billing": 0.8, "technical": 0.2})
        else:
            body = systemone_score(
                legend={str(i): label for i, label in enumerate(question["criteria"])}
            )
    else:
        (question,) = payload["questions"]
        if question["type"] == "predicate":
            body = decisions_noul()
        elif question["type"] == "choice":
            body = decisions_choice()
        else:
            body = decisions_score()
            for row, level in zip(
                body["answers"][0]["probabilities"], question["levels"], strict=True
            ):
                row["label"] = level["label"]
    body["model"] = payload["model"]
    return httpx2.Response(
        200, json=body, headers={"x-request-id": "receipt", "x-typesafe-request-id": "receipt"}
    )


@pytest.mark.parametrize("with_image", [False, True])
def test_matrix_uses_each_route_and_primitive_once(monkeypatch, tmp_path, capsys, with_image):
    calls = []
    monkeypatch.setenv("COREINFRA_API_KEY", "hub-secret-key")

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer hub-secret-key"
        payload = json.loads(request.content)
        if len(calls) == 13:
            assert payload["model"] == "gpt-6-luna" and "decisions" in request.url.path
            assert payload["input"][0]["content"][2]["type"] == "input_image"
        return reply(request)

    monkeypatch.setattr(
        check,
        "coreinfra_provider",
        lambda **kwargs: coreinfra_provider(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    capture = tmp_path / "capture.json"
    args = ["--live", "--report", str(capture), "--jev-model", "jev-preview"]
    if with_image:
        path = tmp_path / "image.png"
        path.write_bytes(PNG)
        args += ["--image", str(path)]
    assert check.main(args) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report == json.loads(capture.read_text())
    assert report["outcome"] == "pass"
    assert (
        report["planned_calls"]
        == report["attempted_calls"]
        == report["completed_calls"]
        == 12 + int(with_image)
    )
    assert len(calls) == report["completed_calls"]
    text_cases = {
        (row["requested_model"], row["protocol"], row["primitive"])
        for row in report["results"][:12]
    }
    assert text_cases == {
        (model, protocol, primitive)
        for model in ("jev-preview", "gpt-6-luna")
        for protocol in ("systemone", "decisions")
        for primitive in check.CHECKS
    }
    assert all(
        row["elapsed_seconds"] >= 0 and row["result"]["request_id"] == "receipt"
        for row in report["results"]
    )
    assert "hub-secret-key" not in output.out and "iVBOR" not in output.out
    assert "hub.coreinfra.ai" not in output.out


@pytest.mark.parametrize("failure_index", [1, 3])
def test_http_failure_keeps_partial_receipts_and_stops_without_retries(
    monkeypatch, tmp_path, capsys, failure_index
):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == failure_index:
            return httpx2.Response(502, text="private-key private-body")
        return reply(request)

    monkeypatch.setattr(
        check,
        "coreinfra_provider",
        lambda **kwargs: coreinfra_provider(
            api_key="private-key", **kwargs, transport=httpx2.MockTransport(handler)
        ),
    )
    assert check.main(["--live", "--report", str(tmp_path / "partial.json")]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["outcome"] == "error" and report["completed_calls"] == failure_index - 1
    assert report["attempted_calls"] == len(calls) == failure_index
    assert report["results"][-1]["status"] == "error"
    assert "private" not in json.dumps(report)


def test_no_live_flag_constructs_no_provider(monkeypatch):
    monkeypatch.setattr(check, "coreinfra_provider", lambda **_: pytest.fail("No opt-in"))
    with pytest.raises(SystemExit) as error:
        check.main([])
    assert error.value.code == 2


@pytest.mark.parametrize("failure", ["missing-image", "existing-report"])
def test_invalid_local_artifacts_fail_before_billable_calls(monkeypatch, tmp_path, capsys, failure):
    monkeypatch.setattr(check, "coreinfra_provider", lambda **_: pytest.fail("No request expected"))
    path = tmp_path / "artifact"
    if failure == "existing-report":
        path.write_text("preserve-existing-capture")
    args = ["--live", "--image" if failure == "missing-image" else "--report", str(path)]
    assert check.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["attempted_calls"] == report["completed_calls"] == 0
    if failure == "existing-report":
        assert path.read_text() == "preserve-existing-capture"
