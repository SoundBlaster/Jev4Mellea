"""Actual Mellea image inputs and Requirements, with local SDK HTTP transports."""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest
from test_choice import CRITERIA, choice_wire
from test_client import wire
from test_images import PNG, assert_image
from test_score import LEVELS, score_wire

pytest.importorskip("mellea")
from mellea.core import Context, ImageBlock, ImageUrlBlock, Requirement, ValidationResult

from mellea_jev import (
    ImageInput,
    JevClassifier,
    JevClient,
    JevScorer,
    JevVerifier,
    ReviewRequired,
    WithImages,
)
from mellea_jev.images import MAX_IMAGE_BYTES

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("prefix", ["", "data:image/png;base64,"])
def test_image_block_conversion_preserves_bytes_and_supports_mellea_padding(prefix):
    block = ImageBlock(prefix + base64.b64encode(PNG).decode().rstrip("="))
    assert ImageInput.from_mellea(block).data == PNG


def test_image_url_blocks_are_not_fetched():
    with pytest.raises(TypeError, match="resolve URL images explicitly"):
        ImageInput.from_mellea(ImageUrlBlock("https://private.example/image.png"))


@pytest.mark.parametrize(
    "value", [None, "private invalid image", "data:image/jpeg;base64,eA==", "eA=="]
)
def test_mutated_mellea_image_blocks_fail_without_echoing_data(value):
    block = ImageBlock(base64.b64encode(PNG).decode())
    block.value = value
    with pytest.raises(ValueError) as captured:
        ImageInput.from_mellea(block)
    assert "private invalid image" not in str(captured.value)


def test_oversized_mellea_base64_is_rejected_before_decoding():
    block = ImageBlock(base64.b64encode(PNG).decode())
    block.value = "A" * (4 * ((MAX_IMAGE_BYTES + 2) // 3) + 1)
    with pytest.raises(ValueError, match="16 MiB"):
        ImageInput.from_mellea(block)


@pytest.mark.parametrize("primitive", ["noul", "choice", "score"])
def test_real_requirements_keep_text_and_explicit_visual_reference(primitive):
    block = ImageBlock(base64.b64encode(PNG).decode())
    context = Mock(spec=Context)
    context.last_output.return_value = SimpleNamespace(value="The picture shows a billing form.")
    calls = []
    bodies = {"noul": wire(0.98), "choice": choice_wire(), "score": score_wire()}

    def handler(request):
        calls.append(request)
        payload = assert_image(request)
        assert payload["state"]["candidate"] == "The picture shows a billing form."
        assert set(payload["state"]) == {"candidate", "images"}
        return httpx2.Response(200, json=bodies[primitive])

    with JevClient("test", transport=httpx2.MockTransport(handler)) as client:
        bound = WithImages(client, {"scene": ImageInput.from_mellea(block)})
        if primitive == "noul":
            requirement = JevVerifier(
                bound, "The candidate describes `images.scene` correctly."
            ).as_requirement()
        elif primitive == "choice":
            requirement = JevClassifier(
                bound,
                "Which department is shown in `images.scene`?",
                criteria=CRITERIA,
            ).as_requirement("billing")
        else:
            requirement = JevScorer(bound, "Rate `images.scene`.", criteria=LEVELS).as_requirement(
                maximum_score=1.0
            )
        result = asyncio.run(requirement.validate(backend=None, ctx=context))
    assert isinstance(requirement, Requirement)
    assert isinstance(result, ValidationResult)
    assert bool(result) is True
    assert len(calls) == 1


@pytest.mark.parametrize("p_yes,expected", [(0.02, False), (0.5, None)])
def test_visual_verifier_retains_rejection_and_uncertainty_policy(p_yes, expected):
    context = Mock(spec=Context)
    context.last_output.return_value = SimpleNamespace(value="A candidate.")
    transport = httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire(p_yes)))
    with JevClient("test", transport=transport) as client:
        requirement = JevVerifier(
            WithImages(client, {"scene": ImageInput(PNG)}),
            "The candidate describes `images.scene`.",
        ).as_requirement()
        if expected is None:
            with pytest.raises(ReviewRequired):
                asyncio.run(requirement.validate(backend=None, ctx=context))
        else:
            assert bool(asyncio.run(requirement.validate(backend=None, ctx=context))) is expected
