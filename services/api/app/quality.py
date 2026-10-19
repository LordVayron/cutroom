import asyncio
import re
from pathlib import Path

import cv2
import numpy as np

from app.domain import TimedText
from app.media import PLATFORM_PROFILES, probe_duration

QUALITY_INSPECTOR_VERSION = 1


def _check(key: str, label: str, status: str, summary: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "summary": summary}


def _ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _read_ass(path: Path) -> tuple[list[tuple[float, float]], tuple[int, int, int] | None]:
    if not path.exists():
        return [], None
    events: list[tuple[float, float]] = []
    margins: tuple[int, int, int] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Style: Dynamic,"):
            fields = line.split(",")
            if len(fields) >= 23:
                try:
                    margins = (int(fields[19]), int(fields[20]), int(fields[21]))
                except ValueError:
                    margins = None
        elif line.startswith("Dialogue:"):
            fields = line.split(",", 3)
            if len(fields) >= 3:
                try:
                    events.append((_ass_seconds(fields[1]), _ass_seconds(fields[2])))
                except ValueError:
                    continue
    return events, margins


def subtitle_safety_check(
    caption_path: Path, transcript: list[TimedText], platform: str = "tiktok"
) -> tuple[dict[str, str], list[tuple[float, float]]]:
    events, margins = _read_ass(caption_path)
    if transcript and not events:
        return _check(
            "subtitle_safety",
            "Safe subtitles",
            "fail",
            "Speech is present, but no rendered subtitle events were found.",
        ), events
    if not transcript:
        return _check(
            "subtitle_safety", "Safe subtitles", "pass", "No spoken captions are required."
        ), events
    if margins is None:
        return _check(
            "subtitle_safety",
            "Safe subtitles",
            "fail",
            "The subtitle safe-zone margins could not be verified.",
        ), events
    left, right, vertical = margins
    profile = PLATFORM_PROFILES.get(platform, PLATFORM_PROFILES["tiktok"])
    if (
        left < profile.caption_left
        or right < profile.caption_right
        or vertical not in set(profile.caption_positions.values())
    ):
        return _check(
            "subtitle_safety",
            "Safe subtitles",
            "fail",
            "Captions extend into a platform control or edge exclusion zone.",
        ), events
    return _check(
        "subtitle_safety",
        "Safe subtitles",
        "pass",
        f"All {len(events)} caption cues stay inside the vertical safe area.",
    ), events


async def _silence_intervals(path: Path, duration: float) -> list[tuple[float, float]]:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "silencedetect=noise=-35dB:d=0.45",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError("FFmpeg could not inspect the rendered audio")
    starts = [float(value) for value in re.findall(rb"silence_start: ([\d.]+)", stderr)]
    ends = [float(value) for value in re.findall(rb"silence_end: ([\d.]+)", stderr)]
    intervals: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration
        intervals.append((max(0.0, start), min(duration, end)))
    return intervals


def silence_check(
    intervals: list[tuple[float, float]], duration: float
) -> dict[str, str]:
    silent_seconds = sum(max(0.0, end - start) for start, end in intervals)
    ratio = silent_seconds / max(duration, 0.1)
    longest = max((end - start for start, end in intervals), default=0.0)
    if ratio >= 0.5 or longest >= 8:
        return _check(
            "silence",
            "Audio continuity",
            "fail",
            f"Silence occupies {ratio:.0%} of the clip; the longest gap is {longest:.1f}s.",
        )
    if ratio >= 0.2 or longest >= 3.5:
        return _check(
            "silence",
            "Audio continuity",
            "warn",
            f"A noticeable silent stretch was detected ({longest:.1f}s longest).",
        )
    return _check(
        "silence",
        "Audio continuity",
        "pass",
        f"Speech flow is continuous; silence is {ratio:.0%} of the clip.",
    )


def subtitle_sync_check(
    events: list[tuple[float, float]], intervals: list[tuple[float, float]]
) -> dict[str, str]:
    if not events:
        return _check(
            "subtitle_sync", "Subtitle sync", "warn", "There are no subtitle cues to compare."
        )
    silent_cues = sum(
        any(start <= (cue_start + cue_end) / 2 <= end for start, end in intervals)
        for cue_start, cue_end in events
    )
    ratio = silent_cues / len(events)
    if len(events) >= 4 and ratio >= 0.35:
        return _check(
            "subtitle_sync",
            "Subtitle sync",
            "fail",
            f"{ratio:.0%} of subtitle cues appear while the audio is silent.",
        )
    if silent_cues and ratio >= 0.15:
        return _check(
            "subtitle_sync",
            "Subtitle sync",
            "warn",
            f"{silent_cues} subtitle cues may be slightly out of sync with speech.",
        )
    return _check(
        "subtitle_sync",
        "Subtitle sync",
        "pass",
        "Caption timing follows the detected speech regions.",
    )


def incomplete_cut_check(
    transcript: list[TimedText], clip_start: float, clip_end: float
) -> dict[str, str]:
    if not transcript:
        return _check(
            "complete_cut", "Complete cut", "warn", "No timed transcript is available."
        )
    cuts_opening_word = any(
        item.start_seconds < clip_start - 0.08
        and item.end_seconds > clip_start + 0.65
        for item in transcript
    )
    cuts_closing_word = any(
        item.start_seconds < clip_end - 0.65
        and item.end_seconds > clip_end + 0.08
        for item in transcript
    )
    if cuts_opening_word or cuts_closing_word:
        edge = "opening and ending" if cuts_opening_word and cuts_closing_word else (
            "opening" if cuts_opening_word else "ending"
        )
        return _check(
            "complete_cut",
            "Complete cut",
            "fail",
            f"The {edge} boundary interrupts an active transcript segment.",
        )
    final_text = transcript[-1].text.strip()
    if final_text and final_text[-1:] not in ".?!\u2026\"\u201d":
        return _check(
            "complete_cut",
            "Complete cut",
            "warn",
            "The clip ends without a clear sentence boundary; review the out point.",
        )
    return _check(
        "complete_cut",
        "Complete cut",
        "pass",
        "The opening and ending land on complete transcript boundaries.",
    )


def _visual_checks(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    capture = cv2.VideoCapture(str(path))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not capture.isOpened() or frame_count < 2:
        capture.release()
        raise RuntimeError("The rendered video could not be sampled")
    face = cv2.CascadeClassifier(
        str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    )
    sample_count = min(20, max(8, frame_count // 30))
    indices = np.linspace(0, frame_count - 1, sample_count, dtype=int)
    speaker_frames = 0
    jumps = 0
    comparisons = 0
    previous_gray: np.ndarray | None = None
    previous_hist: np.ndarray | None = None
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = capture.read()
        if not ok:
            continue
        scale = 360 / frame.shape[1]
        small = cv2.resize(frame, (360, max(1, int(frame.shape[0] * scale))))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        detected = face.detectMultiScale(gray, 1.12, 4, minSize=(26, 26))
        if len(detected):
            speaker_frames += 1
        histogram = cv2.calcHist([gray], [0], None, [32], [0, 256])
        cv2.normalize(histogram, histogram)
        if previous_gray is not None and previous_hist is not None:
            hist_match = cv2.compareHist(previous_hist, histogram, cv2.HISTCMP_CORREL)
            if hist_match > 0.72:
                shift, response = cv2.phaseCorrelate(
                    np.float32(previous_gray), np.float32(gray)
                )
                comparisons += 1
                if response > 0.08 and abs(shift[0]) > 16:
                    jumps += 1
        previous_gray = gray
        previous_hist = histogram
    capture.release()

    visible_ratio = speaker_frames / max(1, sample_count)
    if visible_ratio < 0.15:
        speaker = _check(
            "speaker_visibility",
            "Speaker visibility",
            "warn",
            "A speaker face is rarely visible; this may be a slide or an incorrect crop.",
        )
    elif visible_ratio < 0.45:
        speaker = _check(
            "speaker_visibility",
            "Speaker visibility",
            "warn",
            f"A speaker is visible in only {visible_ratio:.0%} of sampled frames.",
        )
    else:
        speaker = _check(
            "speaker_visibility",
            "Speaker visibility",
            "pass",
            f"A speaker stays visible in {visible_ratio:.0%} of sampled frames.",
        )

    jump_ratio = jumps / max(1, comparisons)
    if comparisons >= 4 and jump_ratio >= 0.35:
        framing = _check(
            "stable_framing",
            "Stable framing",
            "warn",
            f"The crop makes {jumps} abrupt horizontal moves across sampled frames.",
        )
    else:
        framing = _check(
            "stable_framing",
            "Stable framing",
            "pass",
            "No repeated crop jumps were detected.",
        )
    return speaker, framing


def summarize_quality(checks: list[dict[str, str]]) -> tuple[str, int]:
    failures = sum(item["status"] == "fail" for item in checks)
    warnings = sum(item["status"] == "warn" for item in checks)
    status = "failed" if failures else "warning" if warnings else "passed"
    return status, max(0, 100 - failures * 24 - warnings * 8)


async def inspect_clip(
    render_path: Path,
    caption_path: Path,
    transcript: list[TimedText],
    clip_start: float,
    clip_end: float,
    platform: str = "tiktok",
) -> dict[str, object]:
    duration = max(0.1, await probe_duration(render_path))
    subtitle_check, events = subtitle_safety_check(caption_path, transcript, platform)
    intervals, visual = await asyncio.gather(
        _silence_intervals(render_path, duration),
        asyncio.to_thread(_visual_checks, render_path),
    )
    speaker_check, framing_check = visual
    checks = [
        speaker_check,
        subtitle_check,
        subtitle_sync_check(events, intervals),
        silence_check(intervals, duration),
        framing_check,
        incomplete_cut_check(transcript, clip_start, clip_end),
    ]
    status, score = summarize_quality(checks)
    return {
        "version": QUALITY_INSPECTOR_VERSION,
        "status": status,
        "score": score,
        "checks": checks,
    }
