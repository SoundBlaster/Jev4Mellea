"""Build or check the procedural crosswalk reference, without model inference.

This is a fixture generator, not a general image loader. Labels follow the
explicit rectangle geometry. The visual evaluation runner is a separate step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).parent / "evaluation" / "visual"
SIZE = 512
CROSSWALK = (120, 224, 392, 288)
VERSION = "1.0.0"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
Color = tuple[int, int, int]
Bounds = tuple[int, int, int, int]


@dataclass(frozen=True)
class Car:
    bounds: Bounds
    color: Color


@dataclass(frozen=True)
class Scene:
    id: str
    pair: str
    crossing: bool
    cars: tuple[Car, ...]


RED = (190, 45, 45)
BLUE = (40, 100, 210)
ORANGE = (225, 130, 25)
GREEN = (40, 150, 100)
SCENES = (
    Scene("v01", "left-lane", True, (Car((168, 208, 216, 288), RED),)),
    Scene("v02", "left-lane", True, (Car((168, 112, 216, 192), RED),)),
    Scene("v03", "right-lane", True, (Car((304, 320, 352, 400), BLUE),)),
    Scene("v04", "right-lane", True, (Car((304, 224, 352, 304), BLUE),)),
    Scene("v05", "partial-overlap", True, (Car((168, 160, 216, 240), ORANGE),)),
    Scene("v06", "partial-overlap", True, (Car((168, 128, 216, 208), ORANGE),)),
    Scene(
        "v07",
        "two-cars",
        True,
        (Car((168, 320, 216, 400), RED), Car((304, 112, 352, 192), BLUE)),
    ),
    Scene(
        "v08",
        "two-cars",
        True,
        (Car((168, 320, 216, 400), RED), Car((304, 200, 352, 280), BLUE)),
    ),
    Scene("v09", "crossing-presence", False, (Car((168, 208, 216, 288), GREEN),)),
    Scene("v10", "crossing-presence", True, (Car((168, 208, 216, 288), GREEN),)),
    Scene("v11", "car-presence", True, (Car((304, 248, 352, 328), ORANGE),)),
    Scene("v12", "car-presence", True, ()),
)


def intersection_area(first: Bounds, second: Bounds) -> int:
    """Positive area excludes merely touching the crossing boundary."""
    return max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1])
    )


def overlap_areas(scene: Scene) -> tuple[int, ...]:
    return tuple(
        intersection_area(car.bounds, CROSSWALK) if scene.crossing else 0 for car in scene.cars
    )


def rectangle(pixels: bytearray, bounds: Bounds, color: Color) -> None:
    x0, y0, x1, y1 = bounds
    row = bytes(color) * (x1 - x0)
    for y in range(y0, y1):
        offset = (y * SIZE + x0) * 3
        pixels[offset : offset + len(row)] = row


def render(scene: Scene) -> bytes:
    """Draw a top-down diagram; car body rectangles define the labeled footprint."""
    pixels = bytearray(bytes((90, 135, 80)) * SIZE * SIZE)
    rectangle(pixels, (80, 0, 432, SIZE), (178, 178, 178))
    rectangle(pixels, (112, 0, 400, SIZE), (65, 68, 72))
    for y in range(16, SIZE, 56):
        if y + 28 <= CROSSWALK[1] or y >= CROSSWALK[3]:
            rectangle(pixels, (254, y, 258, min(y + 28, SIZE)), (225, 225, 225))
    if scene.crossing:
        for x in range(CROSSWALK[0], CROSSWALK[2], 36):
            rectangle(pixels, (x, CROSSWALK[1], x + 20, CROSSWALK[3]), (250, 250, 250))
    for car in scene.cars:
        x0, y0, x1, y1 = car.bounds
        rectangle(pixels, car.bounds, car.color)
        for wheel_y in (y0 + 12, y1 - 24):
            rectangle(pixels, (x0, wheel_y, x0 + 5, wheel_y + 12), (15, 15, 15))
            rectangle(pixels, (x1 - 5, wheel_y, x1, wheel_y + 12), (15, 15, 15))
        for window_y in (y0 + 16, y1 - 28):
            rectangle(pixels, (x0 + 8, window_y, x1 - 8, window_y + 12), (155, 205, 220))
    return bytes(pixels)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(pixels: bytes, width: int, height: int) -> bytes:
    rows = b"".join(b"\0" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows, level=9))
        + _chunk(b"IEND", b"")
    )


def check_png(content: bytes, pixels: bytes, width: int, height: int) -> None:
    """Check this generator's RGB/filter-0 PNG layout and decoded pixels.

    Compare pixels, not freshly compressed bytes: zlib versions may encode the
    same image differently. The manifest separately binds exact file bytes.
    """
    if not content.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid generated PNG signature.")
    offset = len(PNG_SIGNATURE)
    chunks = []
    while offset < len(content):
        if offset + 12 > len(content):
            raise ValueError("Truncated PNG chunk.")
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(content):
            raise ValueError("Truncated PNG data.")
        kind, data = content[offset + 4 : offset + 8], content[offset + 8 : end - 4]
        if struct.unpack(">I", content[end - 4 : end])[0] != zlib.crc32(kind + data):
            raise ValueError("PNG checksum mismatch.")
        chunks.append((kind, data))
        offset = end
    if [kind for kind, _ in chunks] != [b"IHDR", b"IDAT", b"IEND"]:
        raise ValueError("Unexpected generated PNG chunks.")
    if chunks[0][1] != struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0) or chunks[2][1]:
        raise ValueError("Unexpected generated PNG dimensions or encoding.")
    expected = b"".join(b"\0" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(chunks[1][1], len(expected) + 1)
    if decoded != expected or not decoder.eof or decoder.unused_data:
        raise ValueError("PNG pixels do not match the labeled scene geometry.")


def overview(images: Sequence[bytes]) -> tuple[bytes, int, int]:
    width, height, tile, gap = 1040, 784, 256, 4
    pixels = bytearray(bytes((245, 245, 245)) * width * height)
    for index, source in enumerate(images):
        left, top = gap + (index % 4) * (tile + gap), gap + (index // 4) * (tile + gap)
        for y in range(tile):
            row = b"".join(
                source[((y * 2) * SIZE + x * 2) * 3 : ((y * 2) * SIZE + x * 2) * 3 + 3]
                for x in range(tile)
            )
            offset = ((top + y) * width + left) * 3
            pixels[offset : offset + len(row)] = row
    return bytes(pixels), width, height


def reference(assets: dict[str, bytes]) -> bytes:
    header = {
        "type": "visual_dataset",
        "format_version": 1,
        "name": "crosswalk-overlap-synthetic",
        "version": VERSION,
        "requirement": "The candidate is supported by the top-down diagram in `images.scene`.",
        "criteria": {
            "true": "At least one car body overlaps the marked pedestrian-crossing band with positive area. The band includes gaps between the white zebra stripes.",
            "false": "All cars are outside the marked crossing band, or no car or marked crossing is present. Merely touching its boundary does not count.",
        },
        "provenance": {
            "source": "Procedural diagrams generated by examples/visual_reference.py.",
            "license": "MIT",
            "annotation_method": "rectangle-intersection",
            "human_adjudicated": False,
            "scope": "Synthetic spatial-overlap fixtures; not photographs or parking-law labels.",
        },
    }
    records = [header]
    for scene in SCENES:
        areas = overlap_areas(scene)
        records.append(
            {
                "type": "visual_example",
                "id": scene.id,
                "candidate": "At least one car overlaps the marked pedestrian crossing.",
                "expected": "accept" if any(areas) else "reject",
                "images": {
                    "scene": {
                        "path": f"assets/{scene.id}.png",
                        "sha256": hashlib.sha256(assets[scene.id]).hexdigest(),
                        "media_type": "image/png",
                        "width": SIZE,
                        "height": SIZE,
                    }
                },
                "annotation": {
                    "pair": scene.pair,
                    "crossing_bounds": CROSSWALK if scene.crossing else None,
                    "cars": [asdict(car) for car in scene.cars],
                    "overlap_areas_px2": areas,
                },
            }
        )
    return (
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n"
    ).encode()


def build(output: Path, *, check: bool) -> dict[str, object]:
    assets = {}
    rendered = [render(scene) for scene in SCENES]
    if not check:
        (output / "assets").mkdir(parents=True, exist_ok=True)
    for scene, pixels in zip(SCENES, rendered, strict=True):
        path = output / "assets" / f"{scene.id}.png"
        if check:
            assets[scene.id] = path.read_bytes()
            check_png(assets[scene.id], pixels, SIZE, SIZE)
        else:
            assets[scene.id] = png(pixels, SIZE, SIZE)
            path.write_bytes(assets[scene.id])
    pixels, width, height = overview(rendered)
    overview_path = output / "overview.png"
    expected_reference = reference(assets)
    reference_path = output / "reference.jsonl"
    if check:
        check_png(overview_path.read_bytes(), pixels, width, height)
        if reference_path.read_bytes() != expected_reference:
            raise ValueError(
                "Reference labels, geometry, or image hashes differ from the fixture definition."
            )
    else:
        overview_path.write_bytes(png(pixels, width, height))
        reference_path.write_bytes(expected_reference)
    positive_count = sum(any(overlap_areas(scene)) for scene in SCENES)
    return {
        "name": "crosswalk-overlap-synthetic",
        "version": VERSION,
        "examples": len(SCENES),
        "accept": positive_count,
        "reject": len(SCENES) - positive_count,
        "reference_sha256": hashlib.sha256(expected_reference).hexdigest(),
        "mode": "check" if check else "write",
        "provider_requests": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate committed artifacts offline")
    mode.add_argument("--write", action="store_true", help="Explicitly regenerate fixtures")
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = build(args.output, check=args.check)
    except (OSError, ValueError, zlib.error) as error:
        print(f"visual reference failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
