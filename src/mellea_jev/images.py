"""Explicit image inputs and composition over the existing primitive contracts."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .contracts import (
    ChoiceCriteria,
    ChoiceResponse,
    NoulCriteria,
    NoulResponse,
    PrimitiveProvider,
    ScoreResponse,
)

if TYPE_CHECKING:
    from mellea.core import ImageBlock

MAX_IMAGE_BYTES = 16 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


@dataclass(frozen=True)
class ImageInput:
    """Immutable PNG/JPEG bytes; no downloading, resizing, or SDK types.

    File signatures and the per-image byte limit are checked locally. Full
    decoding, dimensions, and aggregate request limits are checked by the API.
    Prepare correctly oriented, appropriately sized images before construction.
    """

    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise TypeError("ImageInput requires immutable image bytes.")
        if not self.data or len(self.data) > MAX_IMAGE_BYTES:
            raise ValueError("ImageInput must contain between 1 byte and 16 MiB.")
        if not self.data.startswith((PNG_SIGNATURE, JPEG_SIGNATURE)):
            raise ValueError("ImageInput requires PNG or JPEG file bytes.")

    @property
    def media_type(self) -> Literal["image/png", "image/jpeg"]:
        """MIME type inferred from the validated file signature."""
        return "image/png" if self.data.startswith(PNG_SIGNATURE) else "image/jpeg"

    @classmethod
    def from_file(cls, path: str | PathLike[str]) -> ImageInput:
        """Read a local file explicitly, with bounded allocation; URLs are not fetched."""
        with Path(path).open("rb") as stream:
            return cls(stream.read(MAX_IMAGE_BYTES + 1))

    @classmethod
    def from_mellea(cls, image: ImageBlock) -> ImageInput:
        """Copy a Mellea ImageBlock's base64 PNG without fetching URL images."""
        from mellea.core import ImageBlock

        if not isinstance(image, ImageBlock):
            raise TypeError("Expected a Mellea ImageBlock; resolve URL images explicitly first.")
        if not isinstance(image.value, str):
            raise ValueError("ImageBlock must contain base64 PNG text.")
        encoded = image.value.strip().removeprefix("data:image/png;base64,")
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError("ImageBlock exceeds the 16 MiB image limit.")
        encoded += "=" * (-len(encoded) % 4)
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise ValueError("ImageBlock must contain valid base64 PNG text.") from None
        if not data.startswith(PNG_SIGNATURE):
            raise ValueError("ImageBlock must contain PNG file bytes.")
        return cls(data)


def _normalize_images(images: Mapping[str, ImageInput]) -> dict[str, ImageInput]:
    if not isinstance(images, Mapping) or not images:
        raise ValueError("images must be a nonempty mapping of names to ImageInput values.")
    normalized = {}
    for name, image in images.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Image names must be nonempty text.")
        if not isinstance(image, ImageInput):
            raise TypeError("images must contain ImageInput values.")
        normalized[name] = image
    return normalized


class ImageProvider(PrimitiveProvider, Protocol):
    """Optional image capability; text-only providers need not implement it.

    Images are exposed as named fields under state['images']. The image-aware
    provider owns transport encoding and opt-in to its upstream image API.
    """

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
        images: Mapping[str, ImageInput] | None = None,
    ) -> NoulResponse: ...

    def choice(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: ChoiceCriteria,
        images: Mapping[str, ImageInput] | None = None,
    ) -> ChoiceResponse: ...

    def score(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: Sequence[str],
        images: Mapping[str, ImageInput] | None = None,
    ) -> ScoreResponse: ...


class WithImages:
    """Bind selected images to an image provider, exposing ordinary primitives.

    Compose this view with JevVerifier, JevClassifier, or JevScorer and their
    Mellea Requirements. It does not read conversation history or own/close the
    underlying provider. The caller's image mapping is copied at construction.
    """

    def __init__(self, provider: ImageProvider, images: Mapping[str, ImageInput]) -> None:
        self.provider = provider
        self._images = _normalize_images(images)

    def noul(
        self, *, state: dict[str, Any], question: str, criteria: NoulCriteria | None = None
    ) -> NoulResponse:
        return self.provider.noul(
            state=state, question=question, criteria=criteria, images=self._images
        )

    def choice(
        self, *, state: dict[str, Any], question: str, criteria: ChoiceCriteria
    ) -> ChoiceResponse:
        return self.provider.choice(
            state=state, question=question, criteria=criteria, images=self._images
        )

    def score(
        self, *, state: dict[str, Any], question: str, criteria: Sequence[str]
    ) -> ScoreResponse:
        return self.provider.score(
            state=state, question=question, criteria=criteria, images=self._images
        )
