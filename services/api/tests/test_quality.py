from pathlib import Path

from app.domain import TimedText
from app.quality import (
    incomplete_cut_check,
    silence_check,
    subtitle_safety_check,
    subtitle_sync_check,
    summarize_quality,
)


def _caption_file(path: Path, left: int = 72, right: int = 240, vertical: int = 500) -> Path:
    path.write_text(
        "\n".join(
            (
                "[V4+ Styles]",
                (
                    "Style: Dynamic,Arial,64,&H00FFFFFF,&H00FFFFFF,&H00101010,"
                    "&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,"
                    f"{left},{right},{vertical},1"
                ),
                "[Events]",
                "Dialogue: 0,0:00:00.00,0:00:01.20,Dynamic,,0,0,0,,Hello",
            )
        ),
        encoding="utf-8",
    )
    return path


def test_subtitle_safety_uses_rendered_ass_margins(tmp_path: Path) -> None:
    transcript = [TimedText(10, 11, "Hello.")]
    safe, events = subtitle_safety_check(_caption_file(tmp_path / "safe.ass"), transcript)
    unsafe, _ = subtitle_safety_check(
        _caption_file(tmp_path / "unsafe.ass", right=40), transcript
    )

    assert safe["status"] == "pass"
    assert events == [(0.0, 1.2)]
    assert unsafe["status"] == "fail"


def test_linkedin_subtitle_safety_uses_its_own_profile(tmp_path: Path) -> None:
    transcript = [TimedText(10, 11, "Hello professionals.")]
    check, _ = subtitle_safety_check(
        _caption_file(tmp_path / "linkedin.ass", left=64, right=120, vertical=280),
        transcript,
        "linkedin",
    )

    assert check["status"] == "pass"


def test_silence_and_caption_desync_can_block_approval() -> None:
    intervals = [(0.0, 6.0)]
    events = [(0.2, 0.8), (1.0, 1.5), (2.0, 2.4), (3.0, 3.4)]

    assert silence_check(intervals, 10)["status"] == "fail"
    assert subtitle_sync_check(events, intervals)["status"] == "fail"


def test_incomplete_cut_detects_interrupted_transcript() -> None:
    transcript = [TimedText(9.0, 12.0, "A sentence already in progress")]

    result = incomplete_cut_check(transcript, 10.0, 12.0)

    assert result["status"] == "fail"
    assert "opening" in result["summary"]


def test_quality_summary_distinguishes_warning_from_failure() -> None:
    warning_checks = [
        {"status": "pass"},
        {"status": "warn"},
    ]
    failed_checks = warning_checks + [{"status": "fail"}]

    assert summarize_quality(warning_checks) == ("warning", 92)
    assert summarize_quality(failed_checks) == ("failed", 68)
