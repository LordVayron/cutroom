import json
import subprocess

import cv2
import pytest

from app.media import render_vertical


@pytest.mark.asyncio
@pytest.mark.parametrize("fps", [24, 60])
async def test_silence_edits_preserve_source_speed(tmp_path, fps):
    source = tmp_path / "source.mp4"
    output = tmp_path / "render.mp4"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate={fps}:duration=4",
        "-f", "lavfi", "-i",
        "aevalsrc=if(between(t\\,1\\,2)\\,0\\,0.2*sin(2*PI*440*t)):s=48000:d=4",
        "-shortest", "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True)

    await render_vertical(source, output, 0, 4, [], speaker_focus="center")

    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
        "-of", "json", str(output),
    ], check=True, capture_output=True, text=True)
    durations = {stream["codec_type"]: float(stream["duration"])
                 for stream in json.loads(result.stdout)["streams"]}
    assert durations["audio"] == pytest.approx(3.24, abs=0.10)
    assert durations["video"] == pytest.approx(durations["audio"], abs=0.10)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "source"])
async def test_scene_changes_preserve_clock_without_letterboxing(
    tmp_path, monkeypatch, mode
):
    from app import media

    source = tmp_path / "scene-source.mp4"
    output = tmp_path / "scene-render.mp4"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=green:size=640x360:rate=24:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-shortest", "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True)
    monkeypatch.setattr(media, "analyze_layout", lambda *_: {"scenes": [
        {"start": 0, "end": 2, "composition": "single", "tiles": []},
        {"start": 2, "end": 4, "composition": "source", "tiles": []},
    ]})
    await media.render_vertical(
        source, output, 0, 4, [], speaker_tracking=("(iw-ow)/2", 0), speaker_focus=mode
    )
    capture = cv2.VideoCapture(str(output))
    capture.set(cv2.CAP_PROP_POS_MSEC, 1000)
    first_ok, first = capture.read()
    capture.set(cv2.CAP_PROP_POS_MSEC, 3000)
    second_ok, second = capture.read()
    capture.release()
    assert first_ok and second_ok
    assert first[50, 50, 1] > 100  # Speaker crop fills the canvas in the first scene.
    assert second[50, 50, 1] > 100  # Uncertain shots must also fill the vertical canvas.
    capture = cv2.VideoCapture(str(output))
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        assert frame[50, 50, 1] > 100
        assert frame[-50, -50, 1] > 100
    capture.release()
    duration = await media.probe_duration(output)
    assert duration == pytest.approx(4, abs=0.1)
