"""Image inputs and real SDK multipart serialization through local HTTP transports."""

import base64
import json
from email import policy
from email.parser import BytesParser

import httpx2
import pytest
from test_choice import CRITERIA, choice_wire
from test_client import wire
from test_score import LEVELS, score_wire

from mellea_jev import (
    ChoiceQuestion,
    ImageInput,
    JevClient,
    JevHTTPError,
    JevProtocolError,
    NoulQuestion,
    ScoreQuestion,
    WithImages,
)
from mellea_jev.images import MAX_IMAGE_BYTES

# A PNG transport fixture; image dimensions/decoding are upstream API validation.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX1cAAAAASUVORK5CYII="
)


def multipart(request):
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.read()
    )
    parts = {
        part.get_param("name", header="content-disposition"): part for part in message.iter_parts()
    }
    return json.loads(parts.pop("request").get_payload(decode=True)), parts


def assert_image(request, name="scene"):
    assert request.headers["typesafe-danger-zone-images"] == "true"
    assert "content-encoding" not in request.headers
    payload, parts = multipart(request)
    reference = payload["state"]["images"][name]
    assert set(payload["assets"]) == {reference}
    image_part = parts[payload["assets"][reference]["part"]]
    assert image_part.get_content_type() == "image/png"
    assert image_part.get_payload(decode=True) == PNG
    assert len(parts) == 1
    return payload


@pytest.mark.parametrize(
    "data,error",
    [
        (b"", ValueError),
        (b"private image text", ValueError),
        (bytearray(PNG), TypeError),
        ("https://example.com/photo.jpg", TypeError),
        (PNG + bytes(MAX_IMAGE_BYTES), ValueError),
    ],
)
def test_image_input_rejects_invalid_bytes_without_exposing_contents(data, error):
    with pytest.raises(error) as captured:
        ImageInput(data)
    assert "private image text" not in str(captured.value)


def test_image_input_is_immutable_and_file_reads_are_explicit(tmp_path):
    image = ImageInput(PNG)
    assert repr(image) == "ImageInput()"
    path = tmp_path / "fixture.png"
    path.write_bytes(PNG)
    assert ImageInput.from_file(path) == image
    assert ImageInput(b"\xff\xd8\xffjpeg").data.startswith(b"\xff\xd8\xff")
    path.write_bytes(PNG + bytes(MAX_IMAGE_BYTES))
    with pytest.raises(ValueError, match="16 MiB"):
        ImageInput.from_file(path)


@pytest.mark.parametrize("primitive", ["noul", "choice", "score"])
@pytest.mark.parametrize("endpoint", [None, "https://proxy.example/tenant/images/run"])
def test_images_multipart_all_primitives_and_exact_endpoints(primitive, endpoint):
    calls = []
    state = {"candidate": "Hello"}
    bodies = {"noul": wire(), "choice": choice_wire(), "score": score_wire()}
    bodies["score"]["usage"] = {"input_tokens": 42, "output_tokens": 8}
    options = {
        "noul": {},
        "choice": {"criteria": CRITERIA},
        "score": {"criteria": LEVELS},
    }

    def handler(request):
        calls.append(request)
        assert str(request.url) == (endpoint or "https://api.typesafe.ai/v1/systemone")
        assert request.headers["authorization"] == "Bearer test-key"
        payload = assert_image(request)
        assert payload["state"]["candidate"] == "Hello"
        assert payload["model"] == "jev-1.14.0"
        (question,) = payload["questions"].values()
        assert question["type"] == primitive
        assert question["instructions"] == "Evaluate `images.scene`."
        return httpx2.Response(
            200, json=bodies[primitive], headers={"x-typesafe-request-id": "img-1"}
        )

    with JevClient(
        "test-key",
        model="jev-1.14.0",
        endpoint_url=endpoint,
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = getattr(client, primitive)(
            state=state,
            question="Evaluate `images.scene`.",
            images={"scene": ImageInput(PNG)},
            **options[primitive],
        )
    assert state == {"candidate": "Hello"}
    assert result.model == bodies[primitive]["model"] and result.request_id == "img-1"
    assert result.usage.input_tokens == bodies[primitive]["usage"]["input_tokens"]
    assert result.usage.output_tokens == bodies[primitive]["usage"]["output_tokens"]
    assert len(calls) == 1


def test_one_image_is_uploaded_once_for_mixed_questions():
    calls = []
    questions = {
        "requirement": NoulQuestion("A valid scene?"),
        "classification": ChoiceQuestion("Classify.", CRITERIA),
        "rating": ScoreQuestion("Rate.", LEVELS),
    }
    body = wire()
    body["answers"].update(choice_wire()["answers"])
    body["answers"].update(score_wire()["answers"])

    def handler(request):
        calls.append(request)
        payload = assert_image(request)
        assert set(payload["questions"]) == set(questions)
        return httpx2.Response(200, json=body)

    with JevClient("test", transport=httpx2.MockTransport(handler)) as client:
        result = client.system_one(state={}, images={"scene": ImageInput(PNG)}, questions=questions)
    assert set(result.answers) == set(questions)
    assert len(calls) == 1


def test_named_png_and_jpeg_attachments_keep_their_mime_types():
    # As with PNG, only signature/transport validation is exercised by these bytes.
    jpeg = b"\xff\xd8\xffjpeg"

    def handler(request):
        payload, parts = multipart(request)
        for name, mime, content in [("before", "image/png", PNG), ("after", "image/jpeg", jpeg)]:
            reference = payload["state"]["images"][name]
            part = parts[payload["assets"][reference]["part"]]
            assert part.get_content_type() == mime
            assert part.get_payload(decode=True) == content
        assert len(parts) == 2
        return httpx2.Response(200, json=wire())

    with JevClient("test", transport=httpx2.MockTransport(handler)) as client:
        assert (
            client.noul(
                state={},
                question="Do `images.before` and `images.after` show the same scene?",
                images={"before": ImageInput(PNG), "after": ImageInput(jpeg)},
            ).p_yes
            == 0.97
        )


def test_image_opt_in_is_per_request_and_text_stays_uncompressed_json():
    calls = []

    def handler(request):
        if not calls:
            assert_image(request)
        else:
            assert "typesafe-danger-zone-images" not in request.headers
            assert "content-encoding" not in request.headers
            assert request.headers["content-type"].startswith("application/json")
            assert json.loads(request.content)["state"] == {"text": "x" * 10_000}
        calls.append(request)
        return httpx2.Response(200, json=wire())

    with JevClient("test", transport=httpx2.MockTransport(handler)) as client:
        client.noul(state={}, question="Valid?", images={"scene": ImageInput(PNG)})
        client.noul(state={"text": "x" * 10_000}, question="Valid?")
    assert len(calls) == 2


@pytest.mark.parametrize(
    "images,error",
    [
        ({}, ValueError),
        ([], ValueError),
        ({"": ImageInput(PNG)}, ValueError),
        ({"scene": PNG}, TypeError),
        ({1: ImageInput(PNG)}, ValueError),
    ],
)
def test_invalid_attachments_fail_before_transport(images, error):
    transport = httpx2.MockTransport(lambda _: pytest.fail("No request expected"))
    with JevClient("test", transport=transport) as client:
        with pytest.raises(error):
            client.noul(state={}, question="Valid?", images=images)
        with pytest.raises(error):
            WithImages(client, images)


def test_image_state_name_collision_does_not_silently_overwrite_context():
    state = {"images": "caller value"}
    with JevClient(
        "test", transport=httpx2.MockTransport(lambda _: pytest.fail("No request expected"))
    ) as client:
        with pytest.raises(ValueError, match="reserved"):
            client.noul(state=state, question="Valid?", images={"scene": ImageInput(PNG)})
    assert state == {"images": "caller value"}


@pytest.mark.parametrize("status", [302, 429, 500])
def test_image_errors_are_safe_and_are_not_retried_or_redirected(status):
    calls = []

    def handler(request):
        calls.append(request)
        assert_image(request)
        return httpx2.Response(
            status, text="private image response", headers={"location": "https://elsewhere.example"}
        )

    with JevClient("private-key", transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(JevHTTPError) as captured:
            client.noul(state={}, question="Valid?", images={"scene": ImageInput(PNG)})
    assert captured.value.status_code == status
    assert "private" not in str(captured.value)
    assert len(calls) == 1


def test_malformed_visual_answer_fails_closed():
    with JevClient(
        "test", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire("0.98")))
    ) as client:
        with pytest.raises(JevProtocolError):
            client.noul(state={}, question="Valid?", images={"scene": ImageInput(PNG)})


def test_bound_view_copies_image_mapping_and_keeps_provider_lifetime_external():
    images = {"scene": ImageInput(PNG)}
    calls = []

    def handler(request):
        calls.append(request)
        assert_image(request)
        return httpx2.Response(200, json=wire())

    with JevClient("test", transport=httpx2.MockTransport(handler)) as client:
        bound = WithImages(client, images)
        images.clear()
        assert bound.noul(state={}, question="Valid?").p_yes == 0.97
        assert bound.noul(state={}, question="Valid?").p_yes == 0.97
    assert len(calls) == 2
