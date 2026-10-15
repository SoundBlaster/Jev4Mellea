"""Actual Decisions SDK image payloads, common results, and Mellea composition."""

import asyncio
import base64
import json
from types import SimpleNamespace

import httpx2
import pytest
from test_images import PNG
from test_openai_choice import choice_wire
from test_openai_provider import wire
from test_openai_score import RUBRIC, score_wire

from mellea_jev import (
    ImageInput,
    JevClassifier,
    JevScorer,
    JevVerifier,
    OpenAIHTTPError,
    OpenAIProtocolError,
    OpenAIProvider,
    WithImages,
)

JPEG = b"\xff\xd8\xffjpeg-transport-fixture"
IMAGES = {"scene": ImageInput(PNG), "detail": ImageInput(JPEG)}
BODIES = {"noul": wire(), "choice": choice_wire(), "score": score_wire()}
OPTIONS = {
    "noul": {},
    "choice": {"criteria": {"billing": "Payments", "technical": "Bugs"}},
    "score": {"criteria": RUBRIC},
}


def assert_images(payload):
    (message,) = payload["input"]
    assert message["role"] == "user"
    parts = message["content"]
    assert json.loads(parts[0]["text"]) == {
        "candidate": "A street.",
        "reference": "Описание",
        "images": {"scene": "images.scene", "detail": "images.detail"},
    }
    for offset, (name, image) in zip((1, 3), IMAGES.items(), strict=True):
        assert parts[offset] == {"type": "input_text", "text": f"Image reference: `images.{name}`"}
        assert parts[offset + 1] == {
            "type": "input_image",
            "image_url": f"data:{image.media_type};base64,{base64.b64encode(image.data).decode()}",
        }
    assert len(parts) == 5


@pytest.mark.parametrize("primitive", ["noul", "choice", "score"])
@pytest.mark.parametrize("endpoint", [None, "https://hub.coreinfra.ai/openai/api/v1/decisions"])
def test_all_primitives_send_named_images_and_keep_results(primitive, endpoint):
    calls = []
    state = {"candidate": "A street.", "reference": "Описание"}

    def handler(request):
        calls.append(request)
        assert str(request.url) == (endpoint or "https://api.openai.com/v1/decisions")
        assert request.headers["authorization"] == "Bearer private-key"
        assert "typesafe-danger-zone-images" not in request.headers
        payload = json.loads(request.content)
        assert_images(payload)
        assert payload["questions"][0]["instructions"] == "Evaluate `images.scene`."
        return httpx2.Response(200, json=BODIES[primitive], headers={"x-request-id": "vision-1"})

    with OpenAIProvider(
        "private-key", endpoint_url=endpoint, transport=httpx2.MockTransport(handler)
    ) as client:
        result = getattr(client, primitive)(
            state=state, question="Evaluate `images.scene`.", images=IMAGES, **OPTIONS[primitive]
        )
    assert result.model == "gpt-6-luna" and result.request_id == "vision-1"
    assert result.usage.input_tokens == 42 and len(calls) == 1
    assert state == {"candidate": "A street.", "reference": "Описание"}
    assert ImageInput(PNG).media_type == "image/png"
    assert ImageInput(JPEG).media_type == "image/jpeg"


@pytest.mark.parametrize("primitive", ["noul", "choice", "score"])
def test_real_mellea_requirements_accept_bound_decisions_images(primitive):
    pytest.importorskip("mellea")
    from mellea.core import Requirement, ValidationResult

    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        parts = payload["input"][0]["content"]
        assert json.loads(parts[0]["text"])["candidate"] == "A street."
        assert parts[2]["type"] == "input_image"
        return httpx2.Response(200, json=BODIES[primitive])

    with OpenAIProvider("test", transport=httpx2.MockTransport(handler)) as provider:
        bound = WithImages(provider, {"scene": ImageInput(PNG)})
        if primitive == "noul":
            requirement = JevVerifier(
                bound, "The candidate matches `images.scene`."
            ).as_requirement()
        elif primitive == "choice":
            requirement = JevClassifier(
                bound, "Classify `images.scene`.", **OPTIONS[primitive]
            ).as_requirement("billing")
        else:
            requirement = JevScorer(
                bound, "Rate `images.scene`.", **OPTIONS[primitive]
            ).as_requirement(maximum_score=1)
        context = SimpleNamespace(last_output=lambda: SimpleNamespace(value="A street."))
        result = asyncio.run(requirement.validate(backend=None, ctx=context))
    assert isinstance(requirement, Requirement) and isinstance(result, ValidationResult)
    assert bool(result) and len(calls) == 1


@pytest.mark.parametrize("images", [{}, {"scene": PNG}, {"scene": "https://example.com/photo.png"}])
def test_invalid_images_fail_before_http(images):
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as provider:
        with pytest.raises((TypeError, ValueError)):
            provider.noul(state={}, question="Valid?", images=images)


def test_reserved_state_images_are_not_overwritten():
    state = {"images": "caller context"}
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: pytest.fail())
    ) as provider:
        with pytest.raises(ValueError, match="reserved"):
            provider.noul(state=state, question="Valid?", images=IMAGES)
    assert state == {"images": "caller context"}


def test_text_call_after_image_call_keeps_the_original_json_string_input():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        if calls:
            assert payload["input"] == '{"candidate": "Text only"}'
        else:
            assert isinstance(payload["input"], list)
        calls.append(request)
        return httpx2.Response(200, json=wire())

    with OpenAIProvider("test", transport=httpx2.MockTransport(handler)) as provider:
        provider.noul(state={}, question="Image?", images=IMAGES)
        provider.noul(state={"candidate": "Text only"}, question="Text?")
    assert len(calls) == 2


@pytest.mark.parametrize("status", [302, 400, 429, 502])
def test_image_failure_is_safe_without_route_fallback_or_retries(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(
            status, text="private-key image-body", headers={"location": "https://elsewhere.example"}
        )

    with OpenAIProvider("private-key", transport=httpx2.MockTransport(handler)) as provider:
        with pytest.raises(OpenAIHTTPError) as error:
            provider.noul(state={}, question="Valid?", images=IMAGES)
    assert "private" not in str(error.value) and "image-body" not in str(error.value)
    assert error.value.status_code == status and len(calls) == 1


def test_visual_answer_uses_the_existing_strict_response_checks():
    with OpenAIProvider(
        "test", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire("0.99")))
    ) as provider:
        with pytest.raises(OpenAIProtocolError):
            provider.noul(state={}, question="Valid?", images=IMAGES)
