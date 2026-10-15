"""Integrity and semantic checks for the offline procedural visual reference."""

import hashlib
import json

import pytest

from examples import evaluate
from examples import visual_reference as visual


def test_committed_visual_reference_matches_geometry_and_exact_asset_hashes():
    report = visual.build(visual.ROOT, check=True)
    assert report["examples"] == 12
    assert report["accept"] == report["reject"] == 6
    assert report["provider_requests"] == 0
    rows = [json.loads(line) for line in (visual.ROOT / "reference.jsonl").read_text().splitlines()]
    assert rows[0]["provenance"]["human_adjudicated"] is False
    pairs = {}
    for row in rows[1:]:
        pairs.setdefault(row["annotation"]["pair"], []).append(row["expected"])
        image = row["images"]["scene"]
        assert (
            image["sha256"]
            == hashlib.sha256((visual.ROOT / image["path"]).read_bytes()).hexdigest()
        )
    assert len(pairs) == 6
    assert all(sorted(labels) == ["accept", "reject"] for labels in pairs.values())


@pytest.mark.parametrize(
    "bounds,area",
    [
        ((168, 160, 216, 224), 0),  # Just touches the top boundary.
        ((168, 288, 216, 368), 0),  # Just touches the bottom boundary.
        ((72, 224, 120, 288), 0),  # Just touches the left boundary.
        ((168, 160, 216, 240), 768),  # A visible 16-pixel partial overlap.
        ((168, 224, 216, 288), 3072),
    ],
)
def test_overlap_definition_excludes_touching_and_counts_partial_area(bounds, area):
    assert visual.intersection_area(bounds, visual.CROSSWALK) == area


def test_geometry_requires_both_crossing_and_car():
    car = visual.Car((168, 224, 216, 288), visual.RED)
    assert visual.overlap_areas(visual.Scene("absent", "pair", False, (car,))) == (0,)
    assert visual.overlap_areas(visual.Scene("empty", "pair", True, ())) == ()


def test_changing_pixels_and_updating_hash_still_fails_geometry_check(tmp_path):
    visual.build(tmp_path, check=False)
    path = tmp_path / "assets" / "v01.png"
    # Replace a positive scene with its negative counterpart, with valid PNG CRCs.
    changed = (tmp_path / "assets" / "v02.png").read_bytes()
    path.write_bytes(changed)
    reference = tmp_path / "reference.jsonl"
    rows = [json.loads(line) for line in reference.read_text().splitlines()]
    rows[1]["images"]["scene"]["sha256"] = hashlib.sha256(changed).hexdigest()
    reference.write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n")
    with pytest.raises(ValueError, match="pixels do not match"):
        visual.build(tmp_path, check=True)


def test_changed_label_is_rejected_without_rewriting_reference(tmp_path):
    visual.build(tmp_path, check=False)
    path = tmp_path / "reference.jsonl"
    changed = path.read_bytes().replace(b'"expected":"accept"', b'"expected":"reject"', 1)
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="Reference labels"):
        visual.build(tmp_path, check=True)
    assert path.read_bytes() == changed


def test_check_is_read_only_and_missing_files_fail(tmp_path, capsys):
    assert visual.main(["--check", "--output", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []
    assert "visual reference failed" in capsys.readouterr().err


def test_cli_requires_explicit_mode():
    with pytest.raises(SystemExit) as result:
        visual.main([])
    assert result.value.code == 2


def test_text_evaluator_cannot_silently_run_a_visual_reference(monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "_run_live", lambda *args, **kwargs: pytest.fail("No inference"))
    assert evaluate.main([str(visual.ROOT / "reference.jsonl"), "--live"]) == 2
    assert "evaluation failed" in capsys.readouterr().err
