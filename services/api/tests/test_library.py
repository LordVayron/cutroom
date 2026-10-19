from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import main


@pytest.mark.asyncio
async def test_archive_restore_and_remove_project_preserve_media():
    project = SimpleNamespace(
        deleted=False, archived=False, status="ready", source_path="/media/source.mp4"
    )
    session = SimpleNamespace(get=AsyncMock(return_value=project), commit=AsyncMock())
    await main.manage_library("projects", "p", "archive", session)
    assert project.archived
    await main.manage_library("projects", "p", "restore", session)
    assert not project.archived
    await main.manage_library("projects", "p", "delete", session)
    assert project.deleted
    assert project.source_path == "/media/source.mp4"


@pytest.mark.asyncio
async def test_folder_removal_unfiles_episodes_without_deleting_them():
    folder = SimpleNamespace(deleted=False, archived=False)
    episode = SimpleNamespace(brand_folder_id="b", status="ready", deleted=False)
    session = SimpleNamespace(
        get=AsyncMock(return_value=folder), commit=AsyncMock(),
        scalars=AsyncMock(return_value=[episode]),
    )
    await main.manage_library("folders", "b", "delete", session)
    assert folder.deleted
    assert episode.brand_folder_id is None
    assert not episode.deleted


@pytest.mark.asyncio
async def test_processing_library_item_cannot_be_removed():
    project = SimpleNamespace(deleted=False, archived=False, status="rendering")
    session = SimpleNamespace(get=AsyncMock(return_value=project), commit=AsyncMock())
    with pytest.raises(HTTPException) as caught:
        await main.manage_library("projects", "p", "delete", session)
    assert caught.value.status_code == 409
    assert not project.deleted
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [False, True])
async def test_new_film_brand_defaults_can_be_overridden(monkeypatch, override):
    folder = SimpleNamespace(
        id="b", archived=False, deleted=False, platform="reels",
        caption_motion="pulse", caption_font="sans", caption_accent="#ABCDEF",
        watermark_path="/brand.png", watermark_position="upper-left", watermark_size_percent=20,
    )
    projects = []
    session = SimpleNamespace(
        get=AsyncMock(return_value=folder), add=projects.append,
        flush=AsyncMock(), commit=AsyncMock(),
    )
    monkeypatch.setattr(main, "create_job", AsyncMock(return_value=SimpleNamespace(id="j")))
    monkeypatch.setattr(main, "notify_worker", AsyncMock())
    monkeypatch.setattr(main, "load_project", AsyncMock(side_effect=lambda *args: projects[0]))
    monkeypatch.setattr(main, "project_out", lambda project: project)
    project = await main.create_project(
        title="Film", source_url="https://example.com/video", clip_count=4,
        caption_motion="kinetic", caption_font="serif", caption_accent="#123456",
        platform="tiktok", brand_folder_id="b", override_brand_captions=override,
        file=None, session=session,
    )
    assert project.caption_motion == ("kinetic" if override else "pulse")
    assert project.caption_font == ("serif" if override else "sans")
    assert project.caption_accent == ("#123456" if override else "#ABCDEF")
    assert project.watermark_path == "/brand.png"
    assert project.platform == "reels"
