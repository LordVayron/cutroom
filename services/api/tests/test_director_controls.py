import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain import TimedText
from app.media import _write_dynamic_captions
from app.schemas import DirectorEditRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("apply_all", [False, True])
async def test_director_shares_visual_settings_without_overwriting_other_cuts(
    monkeypatch, apply_all
):
    from app import main

    def clip(clip_id, start, end):
        return SimpleNamespace(
            id=clip_id, is_current=True, status="rendered", start_seconds=start,
            end_seconds=end, caption_overrides=None, speaker_focus="auto",
            caption_position="lower", caption_motion=None, caption_font=None,
            caption_accent=None, caption_words_per_phrase=None, caption_size_percent=None,
            watermark_position=None, watermark_size_percent=None, edit_revision=0,
        )

    first = clip("first", 10, 30)
    other = clip("other", 50, 80)
    other.caption_overrides = '{"segment":"My own correction"}'
    project = SimpleNamespace(
        id="project", clips=[first, other], duration_seconds=100, transcript=[],
        status="ready", caption_motion="pulse", caption_font="sans",
        caption_accent="#D8E25B", watermark_position="upper-right",
        watermark_size_percent=18, director_defaults=None,
    )
    monkeypatch.setattr(main, "load_project", AsyncMock(return_value=project))
    monkeypatch.setattr(main, "project_out", lambda project: project)
    session = SimpleNamespace(commit=AsyncMock())
    request = DirectorEditRequest(
        start_seconds=12, end_seconds=32, caption_accent="#FF1234",
        caption_size_percent=125, watermark_position="lower-left",
        watermark_size_percent=24, caption_words_per_phrase=3, apply_to_all=apply_all,
    )

    await main.update_director_cut("project", "first", request, session)

    assert first.caption_size_percent == 125
    assert first.watermark_position == "lower-left"
    assert (other.start_seconds, other.end_seconds) == (50, 80)
    assert other.caption_overrides == '{"segment":"My own correction"}'
    if apply_all:
        assert other.caption_size_percent == 125
        assert other.watermark_position == "lower-left"
        assert other.edit_revision == 1
        defaults = json.loads(project.director_defaults)
        assert defaults["caption_size_percent"] == 125
        assert "start_seconds" not in defaults
        assert "caption_overrides" not in defaults
    else:
        assert other.caption_size_percent is None
        assert other.edit_revision == 0
        assert project.director_defaults is None


def test_caption_size_changes_burned_in_font_and_preserves_safe_margins(tmp_path):
    path = tmp_path / "sized.ass"
    _write_dynamic_captions(
        path, [TimedText(0, 3, "Easy to read")], 0, 3, caption_size_percent=125
    )
    contents = path.read_text(encoding="utf-8")
    assert "Style: Dynamic,DejaVu Sans,90," in contents
    assert ",2,72,240,500,1" in contents
