import re
from pathlib import Path

import cv2
import numpy as np

from app.domain import MAX_CLIP_SECONDS, TimedText, TimedWord

LEADING_FILLERS = {
    "ah",
    "and",
    "basically",
    "like",
    "okay",
    "right",
    "so",
    "um",
    "uh",
    "well",
}


def _clean_word(text: str) -> str:
    return re.sub(r"[^a-z0-9']", "", text.lower())


def _timed_words(transcript: list[TimedText]) -> list[TimedWord]:
    words: list[TimedWord] = []
    for segment in transcript:
        if segment.words:
            words.extend(segment.words)
            continue
        tokens = segment.text.split()
        if not tokens:
            continue
        step = max(0.04, (segment.end_seconds - segment.start_seconds) / len(tokens))
        words.extend(
            TimedWord(
                segment.start_seconds + index * step,
                min(segment.end_seconds, segment.start_seconds + (index + 1) * step),
                token,
            )
            for index, token in enumerate(tokens)
        )
    return sorted(words, key=lambda word: word.start_seconds)


def suggest_hook_repair(
    transcript: list[TimedText],
    clip_start: float,
    clip_end: float,
    source_duration: float,
) -> dict[str, object]:
    words = [
        word
        for word in _timed_words(transcript)
        if word.end_seconds > clip_start - 0.1
        and word.start_seconds < min(source_duration, clip_end + 4.1)
    ]
    proposed_start = clip_start
    proposed_end = clip_end
    opening_note = "The opening already begins on a direct spoken idea."
    ending_note = "The ending already lands on a complete thought."

    opening_words = [word for word in words if word.start_seconds < clip_start + 4]
    filler_count = 0
    for word in opening_words:
        if word.end_seconds <= clip_start:
            continue
        if _clean_word(word.text) not in LEADING_FILLERS:
            if filler_count:
                candidate = max(clip_start, word.start_seconds - 0.08)
                if 0.35 <= candidate - clip_start <= 3.5:
                    proposed_start = candidate
                    opening_note = (
                        f"Trim {candidate - clip_start:.1f}s of conversational filler "
                        "before the first concrete phrase."
                    )
            break
        filler_count += 1

    spoken_before_end = [word for word in words if word.end_seconds <= clip_end + 0.08]
    last_word = spoken_before_end[-1] if spoken_before_end else None
    if last_word:
        closes_sentence = last_word.text.rstrip().endswith((".", "?", "!", "…"))
        trailing_gap = clip_end - last_word.end_seconds
        if closes_sentence and 0.65 <= trailing_gap <= 3.5:
            proposed_end = last_word.end_seconds + 0.12
            ending_note = f"Remove {trailing_gap:.1f}s after the final spoken payoff."
        elif not closes_sentence:
            next_boundary = next(
                (
                    word
                    for word in words
                    if word.end_seconds > clip_end
                    and word.end_seconds <= min(source_duration, clip_end + 4)
                    and word.text.rstrip().endswith((".", "?", "!", "…"))
                ),
                None,
            )
            if next_boundary:
                proposed_end = next_boundary.end_seconds + 0.12
                ending_note = (
                    f"Extend {proposed_end - clip_end:.1f}s to reach the next complete sentence."
                )

    proposed_start = round(max(0.0, proposed_start), 3)
    proposed_end = round(min(source_duration, proposed_end), 3)
    if proposed_end - proposed_start > MAX_CLIP_SECONDS:
        proposed_end = round(proposed_start + MAX_CLIP_SECONDS, 3)
        ending_note = "The repaired ending is capped at the two-minute maximum."
    if proposed_end - proposed_start < 3:
        proposed_start, proposed_end = clip_start, clip_end
        opening_note = "The current opening is retained to preserve a complete idea."
        ending_note = "The current ending is retained to preserve a complete idea."

    changed = (
        abs(proposed_start - clip_start) >= 0.25
        or abs(proposed_end - clip_end) >= 0.25
    )
    return {
        "status": "recommended" if changed else "strong",
        "suggested_start": proposed_start,
        "suggested_end": proposed_end,
        "opening_note": opening_note,
        "ending_note": ending_note,
    }


def _cover_lines(title: str, width: int, max_lines: int = 4) -> list[str]:
    clean = title.replace("—", "-").encode("ascii", "ignore").decode().upper()
    words = clean.split()
    max_chars = max(12, round(width / 58))
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .") + "..."
    return lines


def _hex_bgr(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#([0-9A-Fa-f]{6})", value)
    if not match:
        return 91, 226, 216
    red, green, blue = bytes.fromhex(match.group(1))
    return blue, green, red


def design_cover(
    frame: np.ndarray, title: str, accent: str, style: str
) -> np.ndarray:
    canvas = frame.copy()
    height, width = canvas.shape[:2]
    accent_bgr = _hex_bgr(accent)
    lines = _cover_lines(title, width)
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = max(1.0, width / 720)
    thickness = max(2, round(width / 320))

    if style == "editorial":
        canvas = cv2.cvtColor(cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        panel_top = round(height * 0.08)
        panel_bottom = panel_top + round(height * 0.34)
        cv2.rectangle(
            canvas,
            (0, panel_top),
            (round(width * 0.86), panel_bottom),
            (232, 237, 245),
            -1,
        )
        text_color = (22, 21, 17)
        start_y = panel_top + round(height * 0.075)
    elif style == "signal":
        shade = np.zeros_like(canvas)
        canvas = cv2.addWeighted(canvas, 0.54, shade, 0.46, 0)
        panel_top = round(height * 0.58)
        cv2.rectangle(canvas, (0, panel_top), (width, height), (18, 17, 14), -1)
        cv2.rectangle(
            canvas,
            (0, panel_top),
            (width, panel_top + max(12, height // 100)),
            accent_bgr,
            -1,
        )
        text_color = (245, 245, 240)
        start_y = panel_top + round(height * 0.1)
    else:
        canvas = cv2.GaussianBlur(canvas, (0, 0), sigmaX=10)
        shade = np.full_like(canvas, (10, 10, 10))
        canvas = cv2.addWeighted(canvas, 0.5, shade, 0.5, 0)
        text_color = (245, 245, 240)
        start_y = round(height * 0.38)
        cv2.rectangle(
            canvas,
            (round(width * 0.08), start_y - round(height * 0.07)),
            (round(width * 0.14), start_y - round(height * 0.055)),
            accent_bgr,
            -1,
        )

    line_height = round(height * 0.062)
    x = round(width * 0.08)
    for index, line in enumerate(lines):
        cv2.putText(
            canvas,
            line,
            (x, start_y + index * line_height),
            font,
            scale,
            text_color,
            thickness,
            cv2.LINE_AA,
        )
    return canvas


def generate_cover_options(
    render_path: Path, output_dir: Path, title: str, accent: str
) -> list[dict[str, object]]:
    capture = cv2.VideoCapture(str(render_path))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(frame_count * 0.18)))
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError("Could not read a cover frame from the rendered clip")
    output_dir.mkdir(parents=True, exist_ok=True)
    options = []
    for index, (style, label) in enumerate(
        (("signal", "Signal"), ("editorial", "Editorial"), ("minimal", "Focus"))
    ):
        filename = f"cover-{index}.jpg"
        path = output_dir / filename
        if not cv2.imwrite(
            str(path),
            design_cover(frame, title, accent, style),
            [cv2.IMWRITE_JPEG_QUALITY, 92],
        ):
            raise RuntimeError("Could not save a generated cover")
        options.append({"index": index, "label": label, "filename": filename})
    return options
