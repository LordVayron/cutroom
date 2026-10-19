from pathlib import Path

import cv2
import numpy as np

from app.creative import design_cover, generate_cover_options, suggest_hook_repair
from app.domain import TimedText, TimedWord


def _segment(*words: tuple[float, float, str]) -> TimedText:
    timed = tuple(TimedWord(start, end, text) for start, end, text in words)
    return TimedText(words[0][0], words[-1][1], " ".join(word[2] for word in words), timed)


def test_hook_repair_trims_filler_and_dead_air() -> None:
    transcript = [
        _segment(
            (10.0, 10.3, "Um"),
            (10.4, 10.7, "so"),
                (11.0, 11.4, "markets"),
                (11.5, 12.0, "can"),
                (12.1, 12.6, "move"),
                (12.7, 13.2, "faster"),
                (13.3, 14.0, "now."),
            )
        ]

    result = suggest_hook_repair(transcript, 10.0, 15.0, 60.0)

    assert result["status"] == "recommended"
    assert result["suggested_start"] == 10.92
    assert result["suggested_end"] == 14.12


def test_hook_repair_extends_to_complete_sentence() -> None:
    transcript = [
        _segment(
            (20.0, 20.5, "This"),
            (20.6, 21.0, "changes"),
            (21.1, 21.8, "everything"),
            (22.0, 22.7, "for"),
            (22.8, 23.4, "creators."),
        )
    ]

    result = suggest_hook_repair(transcript, 20.0, 22.0, 60.0)

    assert result["status"] == "recommended"
    assert result["suggested_end"] == 23.52


def test_cover_styles_keep_platform_dimensions() -> None:
    frame = np.full((1920, 1080, 3), 90, dtype=np.uint8)

    signal = design_cover(frame, "A strong opening changes everything", "#D8E25B", "signal")
    editorial = design_cover(
        frame, "A strong opening changes everything", "#D8E25B", "editorial"
    )

    assert signal.shape == frame.shape
    assert editorial.shape == frame.shape
    assert not np.array_equal(signal, editorial)


def test_generate_cover_options_writes_three_files(tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (180, 320)
    )
    for value in range(12):
        writer.write(np.full((320, 180, 3), 30 + value * 5, dtype=np.uint8))
    writer.release()

    options = generate_cover_options(
        video_path, tmp_path / "covers", "Why this idea matters", "#E3422D"
    )

    assert [option["label"] for option in options] == ["Signal", "Editorial", "Focus"]
    assert all((tmp_path / "covers" / str(option["filename"])).exists() for option in options)
