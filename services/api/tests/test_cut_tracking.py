import subprocess

import cv2
import numpy as np
import pytest

from app import media


def write_source(path, cut_frame=14, fps=10, frames=40):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (640, 360))
    assert writer.isOpened()
    for index in range(frames):
        after = index >= cut_frame
        frame = np.full((360, 640, 3), 120 if after else 25, dtype=np.uint8)
        x = 530 if after else 60
        frame[90:150, x:x + 50] = 255
        writer.write(frame)
    writer.release()


class MarkerCascade:
    """Deterministic head markers isolate timing from face-model accuracy."""

    def __init__(self, name):
        self.enabled = "frontalface" in name

    def detectMultiScale(self, gray, *args, **kwargs):
        if not self.enabled:
            return []
        rows, columns = np.where(gray > 235)
        if not len(rows):
            return []
        return [(int(columns.min()), int(rows.min()),
                 int(columns.max() - columns.min() + 1), int(rows.max() - rows.min() + 1))]


@pytest.mark.parametrize("positions", [[40] * 121, [20 if i % 2 else 80 for i in range(121)]])
def test_long_tracking_expressions_fit_the_ffmpeg_parser(positions):
    expression = media._interpolated_crop_expression(positions, 1)
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=320x180:r=1:d=1",
        "-vf", f"crop=100:180:x='{expression}':y=0", "-frames:v", "1", "-f", "null", "-",
    ], capture_output=True)
    assert result.returncode == 0, "FFmpeg rejected the tracking expression"


def test_balancing_preserves_crop_timing_and_easing():
    positions = [40, 40, 80, 80, 20, 20, 60]
    cuts = {4}
    expression = media._interpolated_crop_expression(positions, 1, cuts).replace("\\,", ",")
    expression = expression.replace("if(", "choose(")
    for timestamp in [0, 1.54, 1.7, 2, 2.8, 3.49, 3.5, 3.8, 5.7, 6.1]:
        expected = positions[-1]
        for index in range(len(positions) - 1):
            hard = index + 1 in cuts
            boundary = index + (0.5 if hard else 1)
            if timestamp >= boundary:
                continue
            expected = positions[index]
            if not hard and timestamp >= boundary - 0.45:
                progress = (timestamp - (boundary - 0.45)) / 0.45
                delta = positions[index + 1] - positions[index]
                expected += delta * progress**2 * (3 - 2 * progress)
            break
        actual = eval(expression, {"__builtins__": {}}, {
            "t": timestamp, "lt": lambda a, b: a < b,
            "choose": lambda condition, yes, no: yes if condition else no,
        })
        assert actual == pytest.approx(expected)


def test_many_shots_also_fit_the_ffmpeg_parser():
    expression = media._piecewise_crop_expression(
        list(range(1, 121)), [str(20 + i % 2 * 60) for i in range(121)]
    )
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=320x180:r=1:d=1",
        "-vf", f"crop=100:180:x='{expression}':y=0", "-frames:v", "1", "-f", "null", "-",
    ], capture_output=True)
    assert result.returncode == 0, "FFmpeg rejected the shot selector"


def test_cut_between_motion_windows_is_found_on_the_frame_clock(tmp_path):
    source = tmp_path / "shots.avi"
    write_source(source)
    assert media._tracking_shot_boundaries(source, 0, 4) == pytest.approx([1.4])
    assert media._tracking_shot_boundaries(source, 1, 3) == pytest.approx([0.4])


def test_no_cut_keeps_existing_tracking_path(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_tracking_shot_boundaries", lambda *_: [])
    calls = []

    def segment(*args):
        calls.append(args)
        return "unchanged", 7

    monkeypatch.setattr(media, "_speaker_crop_segment", segment)
    source = tmp_path / "unused.mp4"
    assert media._speaker_crop_expression(source, 2, 8, 100, 200) == ("unchanged", 7)
    assert calls == [(source, 2, 8, 100, 200)]


def test_scene_targets_are_ready_before_the_cut_is_rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_tracking_shot_boundaries", lambda *_: [1.4])
    calls = []

    def segment(source, start, end, *_):
        calls.append((start, end))
        return ("100" if len(calls) == 1 else "900+t"), 1

    monkeypatch.setattr(media, "_speaker_crop_segment", segment)
    expression, count = media._speaker_crop_expression(tmp_path / "unused.mp4", 10, 14)
    assert calls == [(10, 11.4), (11.4, 14)]
    assert expression == "if(lt(t\\,1.4)\\,100\\,900+(t-1.400000))"
    assert count == 2


def test_tracking_motion_samples_never_read_the_next_shot(tmp_path):
    source = tmp_path / "shots.avi"
    write_source(source)
    capture = cv2.VideoCapture(str(source))
    try:
        sampled = media._sample_motion_frames(capture, 1.35, 10, 0, 1.4)
        if sampled:
            assert all(float(frame[0, 0].mean()) < 60 for frame in sampled[:3])
        assert media._sample_motion_frames(capture, 1.8, 10, 0, 1.4) is None
    finally:
        capture.release()


@pytest.mark.parametrize("cut_frame", [2, 14])
def test_render_has_the_head_from_the_first_frame_of_each_shot(tmp_path, monkeypatch, cut_frame):
    source = tmp_path / "shots.avi"
    output = tmp_path / "cropped.avi"
    write_source(source, cut_frame=cut_frame)
    monkeypatch.setattr(media.cv2, "CascadeClassifier", MarkerCascade)
    expression, detections = media._speaker_crop_expression(source, 0, 4, 180, 360)
    assert detections > 0
    subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(source), "-vf",
        f"crop=180:360:x='{expression}':y=0", "-c:v", "mjpeg", str(output),
    ], check=True)
    capture = cv2.VideoCapture(str(output))
    frames = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        capture.release()
    assert len(frames) == 40
    for index, frame in enumerate(frames):
        assert np.count_nonzero(frame[:, :, 0] > 230) > 1000, index
    assert frames[cut_frame - 1][0, 0, 0] < 60
    assert frames[cut_frame][0, 0, 0] > 80
