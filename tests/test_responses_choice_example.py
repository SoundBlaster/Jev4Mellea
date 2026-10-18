"""The example opts into exactly one SDK call; HTTP remains mocked here."""

import json

import httpx2
import pytest

from examples import responses_choice
from mellea_jev import ResponsesChoiceProvider


def test_example_requires_live_before_provider_construction(monkeypatch):
    monkeypatch.setattr(responses_choice, "ResponsesChoiceProvider", lambda **_: pytest.fail())
    with pytest.raises(SystemExit) as captured:
        responses_choice.main(["--model", "m"])
    assert captured.value.code == 2


@pytest.mark.parametrize("status", [200, 429])
def test_one_call_example_with_labels_metadata_and_safe_failure(monkeypatch, capsys, status):
    calls = []

    def handler(request):
        calls.append(request)
        if status != 200:
            return httpx2.Response(status, json={"error": {"message": "private fixture-key"}})
        schema = json.loads(request.content)["text"]["format"]["schema"]
        assert schema["properties"]["answers"]["required"] == ["team", "kind"]
        return httpx2.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"answers":{"team":"frontend","kind":"bug"}}',
                            }
                        ],
                    }
                ],
            },
        )

    def provider(**options):
        return ResponsesChoiceProvider(
            "fixture-key", transport=httpx2.MockTransport(handler), **options
        )

    monkeypatch.setattr(responses_choice, "ResponsesChoiceProvider", provider)
    code = responses_choice.main(["--live", "--model", "alias"])
    captured = capsys.readouterr()
    assert len(calls) == 1
    assert "fixture-key" not in captured.out + captured.err
    if status == 200:
        assert code == 0
        report = json.loads(captured.out)
        assert report["answers"] == {"team": "frontend", "kind": "bug"}
        assert report["returned_model"] is None and report["usage"] is None
        assert "evidence" not in report
    else:
        assert code == 2 and not captured.out
        assert "429" in captured.err and "private" not in captured.err
