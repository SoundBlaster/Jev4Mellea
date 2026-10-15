"""Exercise the image smoke CLI through the real SDK, without live inference."""

import json

import httpx2
import pytest
from test_images import PNG, assert_image
from test_score import score_wire

from examples import live_image_check
from mellea_jev import JevClient


def test_image_cli_batches_three_primitives_and_prints_only_results(monkeypatch, tmp_path, capsys):
    path = tmp_path / "private photo.png"
    path.write_bytes(PNG)
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-key")
    calls = []

    def handler(request):
        calls.append(request)
        payload = assert_image(request)
        assert payload["model"] == "jev-1.14.0"
        assert set(payload["questions"]) == {"vehicle_visible", "scene_type", "legibility"}
        answers = {
            "vehicle_visible": {"type": "noul", "noul": 0.98},
            "scene_type": {
                "type": "choice",
                "choice": "road",
                "confidence": 0.8,
                "probabilities": {"road": 0.8, "document": 0.1, "other": 0.1},
            },
            "legibility": score_wire()["answers"]["rating"],
        }
        answers["legibility"]["legend"] = {
            str(index): label
            for index, label in enumerate(payload["questions"]["legibility"]["criteria"])
        }
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.14.0",
                "answers": answers,
                "usage": {"input_tokens": 321, "output_tokens": 10},
            },
            headers={"x-typesafe-request-id": "image-smoke-1"},
        )

    monkeypatch.setattr(
        live_image_check,
        "JevClient",
        lambda **kwargs: JevClient(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    assert live_image_check.main([str(path)]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["request_id"] == "image-smoke-1"
    assert report["model"] == "jev-1.14.0"
    assert report["usage"] == {"input_tokens": 321, "output_tokens": 10, "cost_usd": None}
    assert report["answers"]["scene_type"]["choice"] == "road"
    assert len(calls) == 1 and not output.err
    assert "private" not in output.out and "iVBOR" not in output.out


@pytest.mark.parametrize("contents", [None, b"private invalid image"])
def test_image_cli_invalid_file_constructs_no_provider(monkeypatch, tmp_path, capsys, contents):
    path = tmp_path / "image.png"
    if contents is not None:
        path.write_bytes(contents)
    monkeypatch.setattr(
        live_image_check, "JevClient", lambda **_: pytest.fail("Must not construct provider")
    )
    assert live_image_check.main([str(path)]) == 2
    output = capsys.readouterr()
    assert not output.out and "image check failed" in output.err
    assert "private invalid image" not in output.err


def test_image_cli_http_error_is_safe_and_not_retried(monkeypatch, tmp_path, capsys):
    path = tmp_path / "image.png"
    path.write_bytes(PNG)
    calls = []
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-key")

    def handler(request):
        calls.append(request)
        return httpx2.Response(429, text="private response body")

    monkeypatch.setattr(
        live_image_check,
        "JevClient",
        lambda **kwargs: JevClient(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    assert live_image_check.main([str(path)]) == 2
    output = capsys.readouterr()
    assert not output.out and "429" in output.err
    assert "private" not in output.err and len(calls) == 1
