import cv2
import numpy as np
import pytest

from app.layout import _scene_changed, _summarize_scene, camera_tiles, classify_layout
from app.media import _podcast_duo_regions


def _grid():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (10, 10), (310, 180), (160, 160, 160), -1)
    cv2.rectangle(frame, (330, 10), (630, 180), (210, 210, 210), -1)
    faces = [(100, 40, 55, 55), (430, 40, 55, 55)]
    return frame, faces


def test_verified_camera_tiles_contain_distinct_simultaneous_people():
    frame, faces = _grid()
    result = classify_layout(frame, faces)
    assert result["composition"] == "duo"
    assert result["people"] == 2
    assert len(result["tiles"]) == 2


def test_one_speaker_never_creates_a_background_pane():
    frame, faces = _grid()
    assert camera_tiles(frame, faces[:1]) == []
    assert classify_layout(frame, faces[:1])["composition"] != "duo"


def test_two_people_in_a_shared_shot_preserve_composition():
    frame = np.full((360, 640, 3), 100, dtype=np.uint8)
    result = classify_layout(frame, [(100, 50, 75, 75), (450, 50, 75, 75)])
    assert result["kind"] == "shared_camera"
    assert result["composition"] == "source"


def test_faces_from_alternating_shots_never_become_a_grid():
    samples = [dict(kind="single_speaker", confidence=0.8, tiles=[], people=1,
                    composition="single") for _ in range(4)]
    assert _summarize_scene(samples, 0, 4)["composition"] == "single"


def test_uncertain_or_disappearing_tiles_fall_back_to_full_frame():
    frame, faces = _grid()
    grid = classify_layout(frame, faces)
    uncertain = dict(kind="scene_or_graphics", composition="source", people=0,
                     confidence=0.4, tiles=[])
    assert _summarize_scene([grid, uncertain, uncertain], 0, 3)["composition"] == "source"


def test_moving_between_closeups_registers_a_camera_cut():
    dark = np.zeros((180, 320, 3), dtype=np.uint8)
    light = np.full((180, 320, 3), 180, dtype=np.uint8)
    assert _scene_changed(dark, light)
    assert not _scene_changed(dark, dark)


def test_duo_cannot_run_without_a_verified_layout(tmp_path):
    assert _podcast_duo_regions(tmp_path / "unused.mp4", 0, 10) is None


@pytest.mark.asyncio
async def test_failed_duo_verification_falls_back_to_filled_crop(tmp_path, monkeypatch):
    from app import media

    monkeypatch.setattr(media, "_podcast_duo_regions", lambda *_: None)
    report = {"scenes": [
        {"start": 0, "end": 3, "composition": "duo", "tiles": [[0, 0, 300, 170]]},
    ]}
    filters = await media._layout_framing(
        tmp_path / "unused.mp4", 0, 3, media.PLATFORM_PROFILES["tiktok"], report, "auto", "0"
    )
    assert "pad=" not in filters
    assert "force_original_aspect_ratio=decrease" not in filters
    assert "[camera" not in filters
    assert "crop=1080:1920" in filters
