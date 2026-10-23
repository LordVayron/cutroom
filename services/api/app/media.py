import asyncio
import json
import logging
import re
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from statistics import median

import cv2
from yt_dlp import YoutubeDL

from app.domain import TimedText, TimedWord, clean_caption_text
from app.layout import analyze_layout

logger = logging.getLogger(__name__)

CURRENT_RENDER_VERSION = 22

CAPTION_FONTS = {
    "sans": ("DejaVu Sans", 72),
    "mono": ("DejaVu Sans Mono", 62),
    "serif": ("DejaVu Serif", 70),
}
CAPTION_WORDS_PER_PHRASE = {"clean": 6, "pulse": 4, "kinetic": 3}
CAPTION_SAFE_MARGIN_LEFT = 72
CAPTION_SAFE_MARGIN_RIGHT = 240
CAPTION_SAFE_MARGIN_BOTTOMS = {"upper": 1000, "middle": 730, "lower": 500}


@dataclass(frozen=True)
class PlatformProfile:
    width: int
    height: int
    caption_left: int
    caption_right: int
    caption_positions: dict[str, int]


PLATFORM_PROFILES = {
    "tiktok": PlatformProfile(
        1080,
        1920,
        CAPTION_SAFE_MARGIN_LEFT,
        CAPTION_SAFE_MARGIN_RIGHT,
        CAPTION_SAFE_MARGIN_BOTTOMS,
    ),
    "reels": PlatformProfile(1080, 1920, 72, 240, CAPTION_SAFE_MARGIN_BOTTOMS),
    "shorts": PlatformProfile(1080, 1920, 72, 240, CAPTION_SAFE_MARGIN_BOTTOMS),
    "linkedin": PlatformProfile(
        1080, 1350, 64, 120, {"upper": 700, "middle": 500, "lower": 280}
    ),
}


@dataclass(frozen=True)
class FaceObservation:
    center: float
    area: float
    mouth_motion: float


def _download(url: str, destination: Path, max_height: int) -> Path:
    metadata_options = {
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "js_runtimes": {"node": {}},
    }
    with YoutubeDL(metadata_options) as metadata_downloader:
        metadata = metadata_downloader.extract_info(url, download=False)
    caption_languages = _source_caption_languages(metadata)

    for old_caption in destination.glob("source.*.json3"):
        old_caption.unlink()
    template = str(destination / "source.%(ext)s")
    options = {
        "format": (f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"),
        "outtmpl": template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "js_runtimes": {"node": {}},
        "writesubtitles": bool(caption_languages),
        "writeautomaticsub": bool(caption_languages),
        "subtitleslangs": caption_languages,
        "subtitlesformat": "json3",
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        requested = info.get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            return Path(requested[0]["filepath"])
        prepared = Path(downloader.prepare_filename(info))
        merged = prepared.with_suffix(".mp4")
        return merged if merged.exists() else prepared


async def download_source(url: str, destination: Path, max_height: int) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    return await asyncio.to_thread(_download, url, destination, max_height)


def _source_caption_languages(info: dict) -> list[str]:
    """Choose one caption track in the video's spoken language, never a translation."""
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    language = str(info.get("language") or "").lower()
    language_base = language.split("-", 1)[0]

    def matches_source(candidate: str) -> bool:
        lowered = candidate.lower()
        return bool(language_base) and (
            lowered == language or lowered.split("-", 1)[0] == language_base
        )

    matching_manual = [key for key in manual if key != "live_chat" and matches_source(key)]
    if matching_manual:
        return [matching_manual[0]]

    original_automatic = [
        key for key in automatic if key != "live_chat" and key.lower().endswith("-orig")
    ]
    if original_automatic:
        matching_original = [key for key in original_automatic if matches_source(key)]
        return [matching_original[0] if matching_original else original_automatic[0]]

    matching_automatic = [
        key for key in automatic if key != "live_chat" and matches_source(key)
    ]
    if matching_automatic:
        return [matching_automatic[0]]

    available_manual = [key for key in manual if key != "live_chat"]
    return [available_manual[0]] if len(available_manual) == 1 else []


def find_source_caption(destination: Path) -> Path | None:
    captions = sorted(destination.glob("source.*-orig.json3"))
    if not captions:
        captions = sorted(destination.glob("source.*.json3"))
    return captions[0] if captions else None


async def probe_duration(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode().strip()}")
    return float(json.loads(stdout)["format"]["duration"])


async def extract_audio_chunks(
    source: Path, destination: Path, chunk_seconds: int = 600
) -> list[tuple[Path, float]]:
    destination.mkdir(parents=True, exist_ok=True)
    for old_chunk in destination.glob("audio-*.mp3"):
        old_chunk.unlink()
    output_pattern = destination / "audio-%03d.mp3"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-reset_timestamps",
        "1",
        str(output_pattern),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"audio extraction failed: {stderr.decode()[-1200:]}")
    chunks = sorted(destination.glob("audio-*.mp3"))
    if not chunks:
        raise RuntimeError("audio extraction did not produce any transcription chunks")
    return [(path, index * chunk_seconds) for index, path in enumerate(chunks)]


def _rolling_median(values: list[float | None]) -> list[float | None]:
    filtered: list[float | None] = []
    for index, value in enumerate(values):
        if value is None:
            filtered.append(None)
            continue
        neighborhood = sorted(
            item
            for item in values[max(0, index - 1) : index + 2]
            if item is not None
        )
        filtered.append(float(median(neighborhood)))
    return filtered


def _stabilize_crop_positions(
    detected_positions: list[float | None],
    max_x: float,
    interval: float,
    hard_cut_indices: set[int] | None = None,
) -> list[int]:
    """Hold a target flat, then make one deliberate switch after persistent evidence."""
    if not detected_positions:
        return [round(max_x / 2)]
    filtered = _rolling_median(detected_positions)
    hard_cut_indices = hard_cut_indices or set()
    opening_samples = [value for value in filtered[:5] if value is not None][:3]
    first = median(opening_samples) if opening_samples else max_x / 2
    lock = float(first)
    held: list[float] = []
    candidate: list[float] = []
    dead_zone = max(96.0, max_x * 0.16)
    candidate_zone = max(128.0, max_x * 0.18)

    for index, value in enumerate(filtered):
        if index in hard_cut_indices and detected_positions[index] is not None:
            lock = detected_positions[index]
            candidate = []
            held.append(lock)
            continue
        if value is None or abs(value - lock) <= dead_zone:
            candidate = []
        elif candidate and abs(value - candidate[-1]) > candidate_zone:
            candidate = [value]
        else:
            candidate.append(value)
        if len(candidate) >= 2:
            lock = sum(candidate[-2:]) / 2
            candidate = []
        held.append(lock)
    return [round(min(max_x, max(0.0, value))) for value in held]


def _piecewise_crop_expression(boundaries: list[float], segments: list[str]) -> str:
    """Bound parser depth without changing which expression owns each time range."""
    def build(left: int, right: int) -> str:
        if right - left == 1:
            return segments[left]
        middle = (left + right) // 2
        return (
            f"if(lt(t\\,{boundaries[middle - 1]})\\,"
            f"{build(left, middle)}\\,{build(middle, right)})"
        )

    return build(0, len(segments))


def _interpolated_crop_expression(
    positions: list[int], interval: float, hard_cut_indices: set[int] | None = None
) -> str:
    if len(positions) == 1:
        return str(positions[0])
    hard_cut_indices = hard_cut_indices or set()
    boundaries = []
    segments = []
    transition = min(0.45, interval * 0.6)
    for index in range(len(positions) - 1):
        next_index = index + 1
        if positions[index] == positions[next_index]:
            continue
        if next_index in hard_cut_indices:
            cut_boundary = round((index + 0.5) * interval, 3)
            boundaries.append(cut_boundary)
            segments.append(str(positions[index]))
            continue
        boundary = round((index + 1) * interval, 3)
        delta = positions[index + 1] - positions[index]
        if delta:
            transition_start = round(boundary - transition, 3)
            progress = f"(t-{transition_start})/{transition:.3f}"
            eased = f"{positions[index]}+({delta})*({progress})*({progress})*(3-2*({progress}))"
            segment = (
                f"if(lt(t\\,{transition_start})\\,{positions[index]}\\,{eased})"
            )
        else:
            segment = str(positions[index])
        boundaries.append(boundary)
        segments.append(segment)
    return _piecewise_crop_expression(boundaries, [*segments, str(positions[-1])])


def _scene_change_score(
    previous: cv2.typing.MatLike, current: cv2.typing.MatLike
) -> float:
    previous_small = cv2.resize(previous, (160, 90), interpolation=cv2.INTER_AREA)
    current_small = cv2.resize(current, (160, 90), interpolation=cv2.INTER_AREA)
    return float(cv2.mean(cv2.absdiff(previous_small, current_small))[0])


def _contains_hard_cut(frames: list[cv2.typing.MatLike]) -> bool:
    """Detect a cut between adjacent frames, not ordinary motion across samples."""
    gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
    return any(
        _scene_change_score(previous, current) >= 32
        for previous, current in zip(gray_frames, gray_frames[1:])
    )


def _rect_iou(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> float:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    overlap_width = max(
        0, min(left_x + left_width, right_x + right_width) - max(left_x, right_x)
    )
    overlap_height = max(
        0, min(left_y + left_height, right_y + right_height) - max(left_y, right_y)
    )
    intersection = overlap_width * overlap_height
    union = left_width * left_height + right_width * right_height - intersection
    return intersection / union if union else 0


def _dedupe_rects(
    rects: list[tuple[int, int, int, int]], frame_width: float
) -> list[tuple[int, int, int, int]]:
    kept: list[tuple[int, int, int, int]] = []
    for rect in sorted(rects, key=lambda item: item[2] * item[3], reverse=True):
        center = (rect[0] + rect[2] / 2) / frame_width
        if any(
            _rect_iou(rect, existing) > 0.25
            or abs(center - (existing[0] + existing[2] / 2) / frame_width) < 0.06
            for existing in kept
        ):
            continue
        kept.append(rect)
    return kept


def _region_difference(
    before: cv2.typing.MatLike,
    after: cv2.typing.MatLike,
    rect: tuple[int, int, int, int],
    vertical_range: tuple[float, float],
    horizontal_range: tuple[float, float] = (0.15, 0.85),
) -> float:
    x, y, width, height = rect
    left = max(0, round(x + width * horizontal_range[0]))
    right = min(before.shape[1], round(x + width * horizontal_range[1]))
    top = max(0, round(y + height * vertical_range[0]))
    bottom = min(before.shape[0], round(y + height * vertical_range[1]))
    if right <= left or bottom <= top:
        return 0
    before_region = cv2.GaussianBlur(before[top:bottom, left:right], (3, 3), 0)
    after_region = cv2.GaussianBlur(after[top:bottom, left:right], (3, 3), 0)
    return float(cv2.mean(cv2.absdiff(before_region, after_region))[0])


def _mouth_motion(
    before: cv2.typing.MatLike,
    after: cv2.typing.MatLike,
    rect: tuple[int, int, int, int],
    body_fallback: bool,
) -> float:
    if body_fallback:
        mouth = _region_difference(before, after, rect, (0.08, 0.34), (0.3, 0.7))
        reference = _region_difference(before, after, rect, (0.35, 0.7), (0.2, 0.8))
    else:
        mouth = _region_difference(before, after, rect, (0.52, 0.96))
        reference = _region_difference(before, after, rect, (0.08, 0.48))
    return max(0.0, mouth - reference * 0.35)


def _select_active_speaker(
    observations: list[FaceObservation], previous_center: float | None
) -> float | None:
    if not observations:
        return None
    if len(observations) == 1:
        return observations[0].center
    ranked_motion = sorted(observations, key=lambda item: item.mouth_motion, reverse=True)
    strongest, runner_up = ranked_motion[:2]
    motion_is_decisive = (
        strongest.mouth_motion >= 2.4
        and strongest.mouth_motion >= runner_up.mouth_motion * 1.22 + 0.35
    )
    if motion_is_decisive:
        return strongest.center
    if previous_center is not None:
        nearby = [
            item for item in observations if abs(item.center - previous_center) <= 0.2
        ]
        if nearby:
            return max(nearby, key=lambda item: item.area).center
    return max(observations, key=lambda item: item.area).center


def _advance_tracking_center(
    locked_center: float | None,
    pending_center: float | None,
    pending_count: int,
    proposed_center: float | None,
) -> tuple[float | None, float | None, int]:
    """Keep ambiguous frames tied to the confirmed speaker, not a one-frame reaction."""
    if proposed_center is None:
        return locked_center, None, 0
    if locked_center is None or abs(proposed_center - locked_center) <= 0.2:
        return proposed_center, None, 0
    if pending_center is None or abs(proposed_center - pending_center) > 0.14:
        return locked_center, proposed_center, 1
    pending_count += 1
    if pending_count >= 2:
        return (pending_center + proposed_center) / 2, None, 0
    return locked_center, pending_center, pending_count


def _sample_motion_frames(
    capture: cv2.VideoCapture,
    timestamp: float,
    fps: float,
    clip_start: float,
    clip_end: float,
    allow_short: bool = False,
) -> (
    tuple[
        cv2.typing.MatLike,
        cv2.typing.MatLike,
        cv2.typing.MatLike,
        bool,
    ]
    | None
):
    motion_span = 0.24
    sample_start = max(clip_start, timestamp - motion_span / 2)
    sample_end = min(clip_end, timestamp + motion_span / 2)
    if sample_start >= clip_end:
        return None
    capture.set(cv2.CAP_PROP_POS_MSEC, sample_start * 1000)
    frame_count = max(3, round(max(12.0, fps) * (sample_end - sample_start)) + 1)
    frames = []
    for _ in range(frame_count):
        ok, frame = capture.read()
        if not ok:
            break
        if capture.get(cv2.CAP_PROP_POS_MSEC) / 1000 >= clip_end:
            break
        frames.append(frame)
    if len(frames) < 3:
        if allow_short and frames:
            return frames[0], frames[len(frames) // 2], frames[-1], False
        return None
    contains_hard_cut = _contains_hard_cut(frames)
    if contains_hard_cut:
        # Motion measured across an edit is meaningless. Use the settled frame after
        # the cut and let face size choose the initial target for the new shot.
        settled = frames[-1]
        return settled, settled, settled, True
    return frames[0], frames[len(frames) // 2], frames[-1], False


def _speaker_crop_segment(
    source: Path, start: float, end: float, output_width: int = 1080,
    output_height: int = 1920, sample_interval: float | None = None,
) -> tuple[str, int]:
    capture = cv2.VideoCapture(str(source))
    width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not capture.isOpened() or width <= 0 or height <= 0:
        capture.release()
        return "(iw-ow)/2", 0

    frontal_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    upper_body_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_upperbody.xml"
    )
    duration = max(1.0, end - start)
    interval = sample_interval or min(1.0, max(0.75, duration / 45))
    sample_count = max(1, int(duration / interval) + 1)
    scaled_width = width * output_height / height
    max_x = max(0.0, scaled_width - output_width)
    positions: list[float | None] = []
    detected = 0
    previous_center: float | None = None
    pending_center: float | None = None
    pending_count = 0
    hard_cut_indices: set[int] = set()

    for index in range(sample_count):
        offset = min(duration, index * interval)
        sampled_frames = _sample_motion_frames(
            capture, start + offset, fps, start, end, allow_short=sample_interval is not None
        )
        crop_position: float | None = None
        if sampled_frames:
            before_frame, frame, after_frame, contains_hard_cut = sampled_frames
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            before_gray = cv2.cvtColor(before_frame, cv2.COLOR_BGR2GRAY)
            after_gray = cv2.cvtColor(after_frame, cv2.COLOR_BGR2GRAY)
            if contains_hard_cut:
                hard_cut_indices.add(index)
                previous_center = None
                pending_center = None
                pending_count = 0
            faces = list(
                frontal_cascade.detectMultiScale(
                    gray, scaleFactor=1.08, minNeighbors=4, minSize=(32, 32)
                )
            )
            profiles = list(
                profile_cascade.detectMultiScale(
                    gray, scaleFactor=1.08, minNeighbors=3, minSize=(32, 32)
                )
            )
            flipped_profiles = profile_cascade.detectMultiScale(
                cv2.flip(gray, 1), scaleFactor=1.08, minNeighbors=3, minSize=(32, 32)
            )
            profiles.extend(
                (round(width - x - face_width), y, face_width, face_height)
                for x, y, face_width, face_height in flipped_profiles
            )
            faces.extend(profiles)
            faces = [
                (x, y, face_width, face_height)
                for x, y, face_width, face_height in faces
                if y + face_height / 2 < height * 0.72
                and 0.58 <= face_width / face_height <= 1.55
            ]
            faces = _dedupe_rects(faces, width)
            body_fallback = False
            if not faces:
                body_fallback = True
                faces = list(
                    upper_body_cascade.detectMultiScale(
                        gray, scaleFactor=1.08, minNeighbors=3, minSize=(55, 70)
                    )
                )
            if faces:
                observations = [
                    FaceObservation(
                        center=(x + face_width / 2) / width,
                        area=face_width * face_height,
                        mouth_motion=_mouth_motion(
                            before_gray,
                            after_gray,
                            (x, y, face_width, face_height),
                            body_fallback,
                        ),
                    )
                    for x, y, face_width, face_height in faces
                ]
                center = _select_active_speaker(observations, previous_center)
                if center is not None:
                    previous_center, pending_center, pending_count = (
                        _advance_tracking_center(
                            previous_center,
                            pending_center,
                            pending_count,
                            center,
                        )
                    )
                    if previous_center is not None:
                        crop_position = min(
                            max_x,
                            max(
                                0.0,
                                previous_center * scaled_width - output_width / 2,
                            ),
                        )
                        detected += 1
            else:
                pending_center = None
                pending_count = 0
        positions.append(crop_position)
    capture.release()

    if detected == 0 or max_x == 0:
        return "(iw-ow)/2", detected
    stabilized = _stabilize_crop_positions(
        positions, max_x, interval, hard_cut_indices
    )
    return (
        _interpolated_crop_expression(stabilized, interval, hard_cut_indices),
        detected,
    )


def _tracking_shot_boundaries(source: Path, start: float, end: float) -> list[float]:
    """Locate edits on the decoded frame clock before computing any crop targets."""
    capture = cv2.VideoCapture(str(source))
    boundaries = []
    try:
        if not capture.isOpened():
            return boundaries
        fps = capture.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            return boundaries
        capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        previous = None
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if timestamp <= 0:
                timestamp = (capture.get(cv2.CAP_PROP_POS_FRAMES) - 1) / fps
            if timestamp >= end:
                break
            if timestamp < start:
                continue
            small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
            if previous is not None and _scene_change_score(previous, small) >= 32:
                boundaries.append(round(timestamp - start, 6))
            previous = small
    finally:
        capture.release()
    return boundaries


def _speaker_crop_expression(
    source: Path, start: float, end: float, output_width: int = 1080, output_height: int = 1920
) -> tuple[str, int]:
    boundaries = _tracking_shot_boundaries(source, start, end)
    if not boundaries:
        return _speaker_crop_segment(source, start, end, output_width, output_height)
    edges = [0.0, *boundaries, end - start]
    shots = []
    detected = 0
    interval = min(1.0, max(0.75, max(1.0, end - start) / 45))
    for left, right in zip(edges, edges[1:]):
        expression, count = _speaker_crop_segment(
            source, start + left, start + right, output_width, output_height, interval
        )
        # Targets and motion windows stay inside their own shot, even when the
        # first usable face observation occurs after the opening frame.
        shots.append(re.sub(r"\bt\b", f"(t-{left:.6f})", expression))
        detected += count
    return _piecewise_crop_expression(boundaries, shots), detected


async def track_speaker_crop(
    source: Path,
    start: float,
    end: float,
    output_width: int = 1080,
    output_height: int = 1920,
) -> tuple[str, int]:
    return await asyncio.to_thread(
        _speaker_crop_expression, source, start, end, output_width, output_height
    )


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _safe_ass_word(word: str) -> str:
    return (
        clean_caption_text(word)
        .replace("\\", "")
        .replace("{", "")
        .replace("}", "")
    )


def _ass_color(hex_color: str) -> str:
    match = re.fullmatch(r"#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})", hex_color)
    if not match:
        hex_color = "#D8E25B"
        match = re.fullmatch(r"#([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})", hex_color)
    assert match
    red, green, blue = match.groups()
    return f"&H00{blue}{green}{red}&".upper()


def _estimated_words(segment: TimedText) -> list[TimedWord]:
    tokens = [_safe_ass_word(word) for word in re.findall(r"\S+", clean_caption_text(segment.text))]
    tokens = [word for word in tokens if word]
    if not tokens:
        return []
    duration = max(0.1, segment.end_seconds - segment.start_seconds)
    weights = [
        0.7
        + min(10, len(word.strip(".,!?;:\"'"))) * 0.08
        + int(word.endswith((".", "?", "!"))) * 0.18
        for word in tokens
    ]
    total_weight = sum(weights)
    cursor = segment.start_seconds
    words: list[TimedWord] = []
    for index, (word, weight) in enumerate(zip(tokens, weights, strict=True)):
        end = (
            segment.end_seconds
            if index == len(tokens) - 1
            else cursor + duration * weight / total_weight
        )
        words.append(TimedWord(cursor, max(cursor + 0.04, end), word))
        cursor = end
    return words


def _caption_words(transcript: list[TimedText]) -> list[TimedWord]:
    words: list[TimedWord] = []
    for segment in transcript:
        candidates = list(segment.words) if segment.words else _estimated_words(segment)
        for word in candidates:
            text = _safe_ass_word(word.text)
            if not text:
                continue
            normalized = TimedWord(
                word.start_seconds, max(word.start_seconds + 0.04, word.end_seconds), text
            )
            if (
                words
                and normalized.text.casefold() == words[-1].text.casefold()
                and abs(normalized.start_seconds - words[-1].start_seconds) < 0.12
            ):
                continue
            words.append(normalized)
    return sorted(words, key=lambda word: (word.start_seconds, word.end_seconds))


def _caption_phrases(words: list[TimedWord], max_words: int) -> list[list[TimedWord]]:
    phrases: list[list[TimedWord]] = []
    phrase: list[TimedWord] = []
    for word in words:
        should_break = bool(
            phrase
            and (
                len(phrase) >= max_words
                or word.start_seconds - phrase[-1].end_seconds > 0.65
                or phrase[-1].text.endswith((".", "?", "!"))
            )
        )
        if should_break:
            phrases.append(phrase)
            phrase = []
        phrase.append(word)
    if phrase:
        phrases.append(phrase)
    return phrases


def _keep_ranges_from_silence(
    duration: float,
    silence_intervals: list[tuple[float, float]],
    pause_padding: float = 0.12,
) -> list[tuple[float, float]]:
    """Turn detected silence into a compact timeline while retaining natural pauses."""
    cuts: list[tuple[float, float]] = []
    for silence_start, silence_end in silence_intervals:
        start = max(0.0, silence_start)
        end = min(duration, silence_end)
        cut_start = 0.0 if start <= 0.05 else start + pause_padding
        cut_end = duration if end >= duration - 0.05 else end - pause_padding
        if cut_end - cut_start >= 0.18:
            cuts.append((cut_start, cut_end))

    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for cut_start, cut_end in cuts:
        if cut_start > cursor + 0.02:
            keep.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < duration - 0.02:
        keep.append((cursor, duration))
    kept_duration = sum(end - start for start, end in keep)
    if kept_duration < min(0.5, duration * 0.15):
        return [(0.0, duration)]
    return keep or [(0.0, duration)]


async def _speech_keep_ranges(
    source: Path, start: float, end: float
) -> list[tuple[float, float]]:
    duration = max(0.1, end - start)
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(source),
        "-vn",
        "-af",
        "silencedetect=noise=-38dB:d=0.60",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.warning("Silence detection failed; preserving the original clip timing")
        return [(0.0, duration)]
    starts = [float(value) for value in re.findall(rb"silence_start: ([\d.]+)", stderr)]
    ends = [float(value) for value in re.findall(rb"silence_end: ([\d.]+)", stderr)]
    intervals = [
        (silence_start, ends[index] if index < len(ends) else duration)
        for index, silence_start in enumerate(starts)
    ]
    return _keep_ranges_from_silence(duration, intervals)


def _retime_caption_span(
    start: float,
    end: float,
    clip_start: float,
    keep_ranges: list[tuple[float, float]],
) -> tuple[float, float] | None:
    relative_start = start - clip_start
    relative_end = end - clip_start
    output_cursor = 0.0
    mapped: list[tuple[float, float]] = []
    for keep_start, keep_end in keep_ranges:
        overlap_start = max(relative_start, keep_start)
        overlap_end = min(relative_end, keep_end)
        if overlap_end > overlap_start:
            mapped.append(
                (
                    output_cursor + overlap_start - keep_start,
                    output_cursor + overlap_end - keep_start,
                )
            )
        output_cursor += keep_end - keep_start
    if not mapped:
        return None
    return mapped[0][0], mapped[-1][1]


def _animated_phrase(
    phrase: list[TimedWord], active_index: int, motion: str, accent: str
) -> str:
    entrance = {
        "clean": "",
        "pulse": "{\\fscx94\\fscy94\\t(0,90,\\fscx100\\fscy100)}",
        "kinetic": "{\\fscx86\\fscy86\\frz-1\\t(0,100,\\fscx103\\fscy103\\frz0)}",
    }[motion]
    rendered: list[str] = []
    for index, word in enumerate(phrase):
        text = word.text.upper()
        if index == active_index:
            scale = {"clean": 100, "pulse": 114, "kinetic": 126}[motion]
            rendered.append(
                f"{{\\c{accent}\\fscx100\\fscy{scale}\\bord7}}{text}"
                "{\\c&H00FFFFFF&\\fscx100\\fscy100\\bord5}"
            )
        else:
            rendered.append(text)
    return entrance + " ".join(rendered)


def _dynamic_caption_events(
    transcript: list[TimedText],
    clip_start: float,
    clip_end: float,
    motion: str = "pulse",
    accent_color: str = "#D8E25B",
    words_per_phrase: int | None = None,
    keep_ranges: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = []
    motion = motion if motion in CAPTION_WORDS_PER_PHRASE else "pulse"
    accent = _ass_color(accent_color)
    phrase_length = (
        max(1, min(8, words_per_phrase))
        if words_per_phrase is not None
        else CAPTION_WORDS_PER_PHRASE[motion]
    )
    phrases = _caption_phrases(_caption_words(transcript), phrase_length)
    timeline = keep_ranges or [(0.0, clip_end - clip_start)]
    for phrase in phrases:
        for active_index, word in enumerate(phrase):
            if word.end_seconds <= clip_start or word.start_seconds >= clip_end:
                continue
            retimed = _retime_caption_span(
                word.start_seconds,
                word.end_seconds,
                clip_start,
                timeline,
            )
            if not retimed:
                continue
            events.append(
                (
                    retimed[0],
                    retimed[1],
                    _animated_phrase(phrase, active_index, motion, accent),
                )
            )
    return events


def _write_dynamic_captions(
    path: Path,
    transcript: list[TimedText],
    clip_start: float,
    clip_end: float,
    motion: str = "pulse",
    font: str = "sans",
    accent_color: str = "#D8E25B",
    position: str = "lower",
    words_per_phrase: int | None = None,
    platform: str = "tiktok",
    keep_ranges: list[tuple[float, float]] | None = None,
    caption_size_percent: int = 100,
) -> int:
    events = _dynamic_caption_events(
        transcript,
        clip_start,
        clip_end,
        motion,
        accent_color,
        words_per_phrase,
        keep_ranges,
    )
    font_name, font_size = CAPTION_FONTS.get(font, CAPTION_FONTS["sans"])
    font_size = round(font_size * max(60, min(140, caption_size_percent)) / 100)
    profile = PLATFORM_PROFILES.get(platform, PLATFORM_PROFILES["tiktok"])
    margin_bottom = profile.caption_positions.get(
        position, profile.caption_positions["lower"]
    )
    style_format = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding"
    )
    dynamic_style = (
        f"Style: Dynamic,{font_name},{font_size},&H00FFFFFF,{_ass_color(accent_color)},"
        "&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,"
        f"{profile.caption_left},{profile.caption_right},"
        f"{margin_bottom},1"
    )
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {profile.width}\n"
        f"PlayResY: {profile.height}\n"
        "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        f"{style_format}\n{dynamic_style}\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_time(start)},{_ass_time(max(start + 0.04, end))},Dynamic,,0,0,0,,{text}"
        for start, end, text in events
    ]
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(events)


def _ffmpeg_filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _watermark_overlay(position: str, width: int, height: int) -> tuple[str, str]:
    side = max(42, round(width * 0.045))
    vertical = max(64, round(height * 0.065))
    columns = {
        "left": str(side),
        "center": "(main_w-overlay_w)/2",
        "right": f"main_w-overlay_w-{side}",
    }
    rows = {
        "upper": str(vertical),
        "middle": "(main_h-overlay_h)/2",
        "lower": f"main_h-overlay_h-{vertical}",
    }
    if position == "center":
        return columns["center"], rows["middle"]
    row, column = position.split("-", 1) if "-" in position else ("upper", "right")
    return columns.get(column, columns["right"]), rows.get(row, rows["upper"])


def _cut_timeline_filter(keep_ranges: list[tuple[float, float]]) -> str:
    count = len(keep_ranges)
    video_labels = "".join(f"[v{index}]" for index in range(count))
    audio_labels = "".join(f"[a{index}]" for index in range(count))
    filters = [
        f"[framed]split={count}{video_labels}",
        f"[0:a]asetpts=PTS-STARTPTS,asplit={count}{audio_labels}",
    ]
    for index, (start, end) in enumerate(keep_ranges):
        filters.extend([
            f"[v{index}]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[vc{index}]",
            f"[a{index}]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[ac{index}]",
        ])
    inputs = "".join(f"[vc{index}][ac{index}]" for index in range(count))
    filters.append(f"{inputs}concat=n={count}:v=1:a=1[base][outa]")
    return ";".join(filters)


def _duo_speaker_pairs(activity: list[list[float]]) -> list[tuple[int, int]]:
    """Keep the two speaking participants visible without shuffling occupied panes."""
    if not activity or len(activity[0]) < 2:
        return []
    pair = sorted(range(len(activity[0])), key=lambda index: -activity[0][index])[:2]
    pending: dict[int, int] = {}
    selections: list[tuple[int, int]] = []
    for scores in activity:
        candidates = sorted(range(len(scores)), key=lambda index: -scores[index])[:2]
        supported: set[int] = set()
        for candidate in candidates:
            if candidate in pair:
                continue
            quiet_slot = min(range(2), key=lambda slot: scores[pair[slot]])
            quiet_score = scores[pair[quiet_slot]]
            if scores[candidate] < 2.4 or scores[candidate] < quiet_score * 1.25 + 0.35:
                continue
            supported.add(candidate)
            pending[candidate] = pending.get(candidate, 0) + 1
            if pending[candidate] >= 2:
                pair[quiet_slot] = candidate
                pending.pop(candidate, None)
                # Once confirmed, cut at the first supporting sample so the
                # opening word does not wait for the confirmation window.
                if selections:
                    previous = list(selections[-1])
                    previous[quiet_slot] = candidate
                    if len(set(previous)) == 2:
                        selections[-1] = (previous[0], previous[1])
        pending = {index: count for index, count in pending.items() if index in supported}
        selections.append((pair[0], pair[1]))
    return selections


def _podcast_duo_regions(
    source: Path, start: float, end: float, tiles: list[list[int]] | None = None
) -> tuple[tuple[str, str, int, int], tuple[str, str, int, int]] | None:
    """Track two people only within camera tiles verified by layout analysis."""
    if not tiles or len(tiles) < 2:
        return None
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        return None
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    clusters: list[list[tuple[float, float, float]]] = [[] for _ in tiles]
    activity: list[dict[int, float]] = []
    sample_count = max(7, ceil((end - start) / 0.4))
    for index in range(sample_count):
        capture.set(
            cv2.CAP_PROP_POS_MSEC,
            (start + (end - start) * index / sample_count) * 1000,
        )
        ok, frame = capture.read()
        if not ok:
            activity.append({})
            continue
        scale = min(1.0, 960 / max(1, width))
        small = cv2.resize(frame, (round(width * scale), round(height * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        capture.set(
            cv2.CAP_PROP_POS_MSEC,
            min(end - 0.01, start + (end - start) * index / sample_count + 0.12) * 1000,
        )
        after_ok, after = capture.read()
        after_gray = gray
        if after_ok:
            after_gray = cv2.cvtColor(
                cv2.resize(after, (small.shape[1], small.shape[0])), cv2.COLOR_BGR2GRAY
            )
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(25, 25))
        sample_activity: dict[int, float] = {}
        for x, y, face_width, face_height in faces:
            tile_index = next((i for i, (tx, ty, tw, th) in enumerate(tiles)
                               if tx * scale <= x and ty * scale <= y
                               and x + face_width <= (tx + tw) * scale
                               and y + face_height <= (ty + th) * scale), None)
            if tile_index is None or tile_index in sample_activity:
                continue
            center = ((x + face_width / 2) / small.shape[1],
                      (y + face_height / 2) / small.shape[0], face_width / small.shape[1])
            clusters[tile_index].append(center)
            sample_activity[tile_index] = _mouth_motion(
                gray, after_gray, (x, y, face_width, face_height), False
            )
        activity.append(sample_activity)
    capture.release()
    stable_indices = [index for index, cluster in enumerate(clusters)
                      if len(cluster) >= max(2, sample_count * 0.55)]
    stable = [clusters[index] for index in stable_indices]
    if len(stable) < 2:
        return None
    centers = [(median(p[0] for p in cluster), median(p[1] for p in cluster),
                median(p[2] for p in cluster)) for cluster in stable]
    crop_height = min(tiles[i][3] - 8 for i in stable_indices)
    crop_width = min(min(tiles[i][2] - 8 for i in stable_indices), crop_height * 1.125)
    crop_height = min(crop_height, crop_width / 1.125)
    if crop_width < 32 or crop_height < 32:
        return None
    regions = []
    for tile_index, (cx, cy, _) in zip(stable_indices, centers, strict=True):
        tx, ty, tw, th = tiles[tile_index]
        crop_x = min(tx + tw - crop_width - 4, max(tx + 4, cx * width - crop_width / 2))
        crop_y = min(ty + th - crop_height - 4,
                     max(ty + 4, cy * height - crop_height * 0.32))
        regions.append(tuple(int(value) // 2 * 2 for value in
                             (crop_x, crop_y, crop_width, crop_height)))
    selections = _duo_speaker_pairs([
        [sample.get(index, 0) for index in stable_indices] for sample in activity
    ])
    verified = sum(all(stable_indices[index] in sample for index in pair)
                   for pair, sample in zip(selections, activity, strict=True))
    if verified / len(selections) < 0.8:
        return None

    def pane(pane_index: int) -> tuple[str, str, int, int]:
        def coordinate(axis: int) -> str:
            expression = str(regions[selections[-1][pane_index]][axis])
            for index in range(len(selections) - 2, -1, -1):
                if selections[index][pane_index] == selections[index + 1][pane_index]:
                    continue
                boundary = (end - start) * (index + 1) / sample_count
                value = regions[selections[index][pane_index]][axis]
                expression = f"if(lt(t\\,{boundary:.3f})\\,{value}\\,{expression})"
            return expression
        return coordinate(0), coordinate(1), regions[0][2], regions[0][3]

    return pane(0), pane(1)


async def _layout_framing(
    source: Path, start: float, end: float, profile: PlatformProfile,
    report: dict, mode: str, crop_x: str,
) -> str:
    """Compose scenes on the original clock; overlays never stretch shot timing."""
    changes = []
    for scene in report["scenes"]:
        composition = scene["composition"]
        if mode == "source":
            composition = "source"
        elif mode in {"left", "center", "right", "single"}:
            composition = "single"
        duo = None
        if composition == "duo":
            duo = await asyncio.to_thread(
                _podcast_duo_regions, source, start + scene["start"],
                start + scene["end"], scene["tiles"],
            )
            if not duo:
                composition = "single"
        if composition == "source" and mode != "source":
            # Uncertainty must not turn a vertical podcast into a letterboxed shot.
            composition = "single"
        if composition != "source":
            changes.append((scene, composition, duo))
    labels = "".join(f"[layout{index}]" for index in range(len(changes) + 1))
    filters = [f"[0:v]setpts=PTS-STARTPTS,split={len(changes) + 1}{labels}"]
    if mode == "source":
        # Explicit full-source override keeps slides/content legible, but uses
        # the actual scene as a blurred backdrop rather than empty padding.
        filters.extend([
            "[layout0]split=2[backdrop][original]",
            f"[backdrop]scale={profile.width // 4}:{profile.height // 4}:"
            "force_original_aspect_ratio=increase,"
            f"crop={profile.width // 4}:{profile.height // 4},gblur=sigma=20,"
            f"scale={profile.width}:{profile.height},setsar=1[background]",
            f"[original]scale={profile.width}:{profile.height}:"
            "force_original_aspect_ratio=decrease,setsar=1[foreground]",
            "[background][foreground]overlay=(W-w)/2:(H-h)/2[canvas0]",
        ])
    else:
        # A filled base also covers fractional scene boundaries and decode gaps.
        filters.append(
            f"[layout0]scale={profile.width}:{profile.height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={profile.width}:{profile.height}:'{crop_x}':(ih-{profile.height})/2,"
            "setsar=1[canvas0]"
        )
    for index, (scene, composition, duo) in enumerate(changes, start=1):
        trim = f"trim=start={scene['start']:.6f}:end={scene['end']:.6f}"
        if composition == "duo":
            filters.append(f"[layout{index}]{trim},split=2[camera{index}a][camera{index}b]")
            for pane_index, (x, y, width, height) in enumerate(duo):
                x = x.replace("t\\,", f"t-{scene['start']:.6f}\\,")
                y = y.replace("t\\,", f"t-{scene['start']:.6f}\\,")
                camera = "a" if pane_index == 0 else "b"
                filters.append(
                    f"[camera{index}{camera}]crop={width}:{height}:'{x}':'{y}',"
                    f"scale={profile.width}:{profile.height // 2}:"
                    "force_original_aspect_ratio=increase,"
                    f"crop={profile.width}:{profile.height // 2},setsar=1[pane{index}{camera}]"
                )
            filters.append(f"[pane{index}a][pane{index}b]vstack=inputs=2[scene{index}]")
        else:
            filters.append(
                f"[layout{index}]{trim},scale={profile.width}:{profile.height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={profile.width}:{profile.height}:'{crop_x}':(ih-{profile.height})/2,"
                f"setsar=1[scene{index}]"
            )
        filters.append(
            f"[canvas{index - 1}][scene{index}]overlay=0:0:eof_action=pass:repeatlast=0:"
            f"enable='gte(t,{scene['start']:.6f})*lt(t,{scene['end']:.6f})'[canvas{index}]"
        )
    filters.append(f"[canvas{len(changes)}]null[framed]")
    return ";".join(filters) + ";"


async def render_vertical(
    source: Path,
    output: Path,
    start: float,
    end: float,
    transcript: list[TimedText],
    caption_motion: str = "pulse",
    caption_font: str = "sans",
    caption_accent: str = "#D8E25B",
    speaker_focus: str = "auto",
    caption_position: str = "lower",
    caption_words_per_phrase: int | None = None,
    speaker_tracking: tuple[str, int] | None = None,
    platform: str = "tiktok",
    watermark_path: Path | None = None,
    watermark_position: str = "upper-right",
    watermark_size_percent: int = 18,
    caption_size_percent: int = 100,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1, end - start)
    keep_ranges = await _speech_keep_ranges(source, start, end)
    output_duration = sum(range_end - range_start for range_start, range_end in keep_ranges)
    profile = PLATFORM_PROFILES.get(platform, PLATFORM_PROFILES["tiktok"])
    report = (
        await asyncio.to_thread(analyze_layout, source, start, end)
        if speaker_focus in {"auto", "duo", "single"} else {
            "scenes": [{"start": 0.0, "end": end - start, "composition": "source",
                        "tiles": []}]
        }
    )
    if speaker_focus == "left":
        crop_x, detected_frames = "0", 0
    elif speaker_focus == "right":
        crop_x, detected_frames = "iw-ow", 0
    elif speaker_focus in {"center", "source"}:
        crop_x, detected_frames = "(iw-ow)/2", 0
    elif speaker_tracking is not None:
        crop_x, detected_frames = speaker_tracking
    else:
        crop_x, detected_frames = await track_speaker_crop(
            source, start, end, profile.width, profile.height
        )
    caption_path = output.with_suffix(".captions.ass")
    caption_events = await asyncio.to_thread(
        _write_dynamic_captions,
        caption_path,
        transcript,
        start,
        end,
        caption_motion,
        caption_font,
        caption_accent,
        caption_position,
        caption_words_per_phrase,
        platform,
        keep_ranges,
        caption_size_percent,
    )
    logger.info(
        "Render %s uses %d person detections, %d caption events, and removes %.2fs of silence",
        output.name,
        detected_frames,
        caption_events,
        duration - output_duration,
    )
    caption_filter = (
        f"ass='{_ffmpeg_filter_path(caption_path)}'" if caption_events else None
    )
    command = ["ffmpeg", "-y", "-ss", str(start), "-t", str(duration), "-i", str(source)]
    # Trim both streams at the same source timestamps, then concatenate them.
    # Counting frames as 30 fps changes the speed of 24/25/60 fps sources.
    framing = await _layout_framing(source, start, end, profile, report, speaker_focus, crop_x)
    timeline_filter = _cut_timeline_filter(keep_ranges)
    base_filter = framing + timeline_filter
    has_watermark = bool(watermark_path and watermark_path.exists())
    if has_watermark:
        assert watermark_path
        watermark_width = round(profile.width * max(8, min(35, watermark_size_percent)) / 100)
        overlay_x, overlay_y = _watermark_overlay(
            watermark_position, profile.width, profile.height
        )
        command.extend(["-loop", "1", "-i", str(watermark_path)])
        overlay_output = "branded" if caption_filter else "outv"
        filter_complex = (
            base_filter
            + ";"
            f"[1:v]scale={watermark_width}:-1[mark];"
            f"[base][mark]overlay={overlay_x}:{overlay_y}:format=auto[{overlay_output}]"
        )
        if caption_filter:
            filter_complex += f";[branded]{caption_filter}[outv]"
        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "[outa]",
            ]
        )
    else:
        command.extend(
            [
                "-filter_complex",
                base_filter + f";[base]{caption_filter or 'null'}[outv]",
                "-map",
                "[outv]",
                "-map",
                "[outa]",
            ]
        )
    command.extend(
        [
        "-t",
        str(output_duration),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output),
        ]
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()[-1200:]}")
