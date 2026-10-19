import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from math import floor
from pathlib import Path

import aiofiles
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_session
from app.domain import (
    InvalidTransition,
    clean_caption_text,
    project_status_after_clip_approval,
    require_transition,
)
from app.layout import analyze_layout
from app.media import CAPTION_WORDS_PER_PHRASE, CURRENT_RENDER_VERSION
from app.models import BrandFolder, Clip, Project, PublicationSchedule
from app.providers import generate_publishing_copy
from app.quality import QUALITY_INSPECTOR_VERSION
from app.queue import (
    create_job,
    find_job,
    notify_worker,
    retry_failed_job,
)
from app.schemas import (
    AutoScheduleRequest,
    BatchAccepted,
    BrandFolderOut,
    ClipOut,
    CoverOptionOut,
    CoverSelectionRequest,
    DirectorEditRequest,
    FeedbackOut,
    FeedbackRequest,
    HookRepairOut,
    JobAccepted,
    ManualScheduleRequest,
    ProjectOut,
    ProjectSummary,
    PublicationOut,
    QualityReportOut,
    TranscriptSegmentOut,
)
from app.taste import concept_signature


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Video Clip Factory API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _caption_overrides(clip: Clip) -> dict[str, str]:
    try:
        value = json.loads(clip.caption_overrides or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _publication_out(publication: PublicationSchedule) -> PublicationOut:
    try:
        platforms = json.loads(publication.platforms)
    except (TypeError, json.JSONDecodeError):
        platforms = []
    if not isinstance(platforms, list):
        platforms = []
    return PublicationOut(
        scheduled_for=publication.scheduled_for,
        cover_title=publication.cover_title,
        seo_caption=publication.seo_caption,
        platforms=platforms,
        status=publication.status,
    )


def clip_out(clip: Clip, project: Project) -> ClipOut:
    caption_overrides = _caption_overrides(clip)
    original_start = clip.original_start_seconds
    original_end = clip.original_end_seconds
    if original_start is None:
        original_start = clip.start_seconds
    if original_end is None:
        original_end = clip.end_seconds
    caption_motion = clip.caption_motion or project.caption_motion
    caption_font = clip.caption_font or project.caption_font
    caption_accent = clip.caption_accent or project.caption_accent
    caption_words = clip.caption_words_per_phrase or CAPTION_WORDS_PER_PHRASE[caption_motion]
    try:
        quality_payload = json.loads(clip.quality_report or "{}")
    except (TypeError, json.JSONDecodeError):
        quality_payload = {}
    quality_checks = quality_payload.get("checks", [])
    if not isinstance(quality_checks, list):
        quality_checks = []
    try:
        cover_payload = json.loads(clip.cover_options or "[]")
    except (TypeError, json.JSONDecodeError):
        cover_payload = []
    if not isinstance(cover_payload, list):
        cover_payload = []
    selected_cover = clip.selected_cover_index if clip.selected_cover_index is not None else 0
    covers = [
        CoverOptionOut(
            index=int(option["index"]),
            label=str(option["label"]),
            url=f"/api/clips/{clip.id}/covers/{int(option['index'])}",
            selected=int(option["index"]) == selected_cover,
        )
        for option in cover_payload
        if isinstance(option, dict) and "index" in option and "label" in option
    ]
    return ClipOut(
        id=clip.id,
        rank=clip.rank,
        title=clip.title,
        start_seconds=clip.start_seconds,
        end_seconds=clip.end_seconds,
        original_start_seconds=original_start,
        original_end_seconds=original_end,
        score=clip.score,
        rationale=clip.rationale,
        status=clip.status,
        render_url=(
            f"/api/clips/{clip.id}/media"
            if clip.render_path and clip.render_version >= CURRENT_RENDER_VERSION
            else None
        ),
        generation=clip.generation,
        series_id=clip.series_id,
        series_index=clip.series_index,
        series_count=clip.series_count,
        caption_overrides=caption_overrides,
        speaker_focus=clip.speaker_focus,
        caption_position=clip.caption_position,
        caption_motion=caption_motion,
        caption_font=caption_font,
        caption_accent=caption_accent,
        caption_words_per_phrase=caption_words,
        caption_size_percent=clip.caption_size_percent or 100,
        watermark_position=clip.watermark_position or project.watermark_position,
        watermark_size_percent=clip.watermark_size_percent or project.watermark_size_percent,
        edit_revision=clip.edit_revision,
        quality=QualityReportOut(
            status=clip.quality_status,
            score=clip.quality_score,
            checked_at=clip.quality_checked_at,
            checks=quality_checks,
        ),
        hook_repair=HookRepairOut(
            status=clip.hook_repair_status,
            suggested_start=clip.hook_repair_start or clip.start_seconds,
            suggested_end=clip.hook_repair_end or clip.end_seconds,
            opening_note=clip.hook_repair_opening_note
            or "Hook analysis will run with the next render.",
            ending_note=clip.hook_repair_ending_note
            or "Ending analysis will run with the next render.",
        ),
        covers=covers,
        feedback=FeedbackOut(
            decision=clip.feedback_decision,
            reason=clip.feedback_reason,
            detail=clip.feedback_detail,
            recorded_at=clip.feedback_at,
        ),
        is_edited=(
            abs(clip.start_seconds - original_start) > 0.01
            or abs(clip.end_seconds - original_end) > 0.01
            or bool(caption_overrides)
            or clip.speaker_focus != "auto"
            or clip.caption_position != "lower"
            or clip.caption_motion is not None
            or clip.caption_font is not None
            or clip.caption_accent is not None
            or clip.caption_words_per_phrase is not None
            or clip.caption_size_percent is not None
            or clip.watermark_position is not None
            or clip.watermark_size_percent is not None
        ),
        publication=_publication_out(clip.publication)
        if clip.publication
        else None,
    )


def project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        archived=project.archived,
        id=project.id,
        title=project.title,
        source_url=project.source_url,
        status=project.status,
        duration_seconds=project.duration_seconds,
        error=project.error,
        retryable=project.retryable,
        requested_clip_count=project.requested_clip_count,
        brand_folder_id=project.brand_folder_id,
        platform=project.platform,
        watermark_url=(
            f"/api/brand-folders/{project.brand_folder_id}/watermark"
            if project.brand_folder_id
            and project.watermark_path
            and Path(project.watermark_path).exists()
            else None
        ),
        watermark_position=project.watermark_position,
        watermark_size_percent=project.watermark_size_percent,
        caption_motion=project.caption_motion,
        caption_font=project.caption_font,
        caption_accent=project.caption_accent,
        analysis_generation=project.analysis_generation,
        duplicate_ideas_filtered=project.duplicate_ideas_filtered,
        created_at=project.created_at,
        clips=[
            clip_out(clip, project)
            for clip in sorted(
                (item for item in project.clips if item.is_current),
                key=lambda item: item.rank,
            )
        ],
        transcript=[
            TranscriptSegmentOut(
                id=segment.id,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=clean_caption_text(segment.text),
            )
            for segment in sorted(project.transcript, key=lambda item: item.start_seconds)
        ],
    )


async def load_project(session: AsyncSession, project_id: str) -> Project:
    project = await session.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.clips).selectinload(Clip.publication),
            selectinload(Project.transcript),
        )
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=list[ProjectSummary])
async def list_projects(
    session: AsyncSession = Depends(get_session),
) -> list[ProjectSummary]:
    result = await session.scalars(
        select(Project).where(Project.deleted.is_(False)).order_by(Project.created_at.desc())
    )
    return [
        ProjectSummary(
            archived=project.archived,
            id=project.id,
            title=project.title,
            status=project.status,
            duration_seconds=project.duration_seconds,
            error=project.error,
            retryable=project.retryable,
            requested_clip_count=project.requested_clip_count,
            brand_folder_id=project.brand_folder_id,
            platform=project.platform,
            watermark_url=(
                f"/api/brand-folders/{project.brand_folder_id}/watermark"
                if project.brand_folder_id
                and project.watermark_path
                and Path(project.watermark_path).exists()
                else None
            ),
            watermark_position=project.watermark_position,
            watermark_size_percent=project.watermark_size_percent,
            caption_motion=project.caption_motion,
            caption_font=project.caption_font,
            caption_accent=project.caption_accent,
            analysis_generation=project.analysis_generation,
            duplicate_ideas_filtered=project.duplicate_ideas_filtered,
            created_at=project.created_at,
        )
        for project in result
    ]


PLATFORMS = {"tiktok", "reels", "shorts", "linkedin"}
WATERMARK_POSITIONS = {
    "upper-left",
    "upper-center",
    "upper-right",
    "middle-left",
    "center",
    "middle-right",
    "lower-left",
    "lower-center",
    "lower-right",
}


def brand_folder_out(folder: BrandFolder) -> BrandFolderOut:
    watermark = Path(folder.watermark_path or "")
    return BrandFolderOut(
        archived=folder.archived,
        id=folder.id,
        name=folder.name,
        platform=folder.platform,
        caption_motion=folder.caption_motion,
        caption_font=folder.caption_font,
        caption_accent=folder.caption_accent,
        watermark_url=(
            f"/api/brand-folders/{folder.id}/watermark"
            if folder.watermark_path and watermark.exists()
            else None
        ),
        watermark_position=folder.watermark_position,
        watermark_size_percent=folder.watermark_size_percent,
        created_at=folder.created_at,
    )


@app.get("/api/brand-folders", response_model=list[BrandFolderOut])
async def list_brand_folders(
    session: AsyncSession = Depends(get_session),
) -> list[BrandFolderOut]:
    folders = await session.scalars(
        select(BrandFolder).where(BrandFolder.deleted.is_(False)).order_by(BrandFolder.created_at)
    )
    return [brand_folder_out(folder) for folder in folders]


@app.post("/api/library/{kind}/{item_id}/{action}")
async def manage_library(
    kind: str, item_id: str, action: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if kind not in {"projects", "folders"} or action not in {"archive", "restore", "delete"}:
        raise HTTPException(status_code=422, detail="Unknown library action")
    item = await session.get(Project if kind == "projects" else BrandFolder, item_id)
    if not item or item.deleted:
        raise HTTPException(status_code=404, detail="Library item not found")
    affected = [item] if kind == "projects" else list(
        await session.scalars(select(Project).where(Project.brand_folder_id == item_id))
    )
    processing = {"queued", "ingesting", "transcribing", "scoring", "rendering"}
    if any(project.status in processing for project in affected):
        raise HTTPException(
            status_code=409,
            detail="Wait for processing to finish before changing this library item",
        )
    if action == "delete":
        # Soft delete keeps media and history safe. Folder removal never deletes episodes.
        item.deleted = True
        if kind == "folders":
            for project in affected:
                project.brand_folder_id = None
    else:
        item.archived = action == "archive"
    await session.commit()
    return {"status": "ok"}


@app.post(
    "/api/brand-folders",
    response_model=BrandFolderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_brand_folder(
    name: str = Form(..., min_length=1, max_length=120),
    platform: str = Form("tiktok"),
    caption_motion: str = Form("pulse"),
    caption_font: str = Form("sans"),
    caption_accent: str = Form("#D8E25B"),
    watermark_position: str = Form("upper-right"),
    watermark_size_percent: int = Form(18, ge=8, le=35),
    watermark: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
) -> BrandFolderOut:
    clean_name = name.strip()
    if await session.scalar(select(BrandFolder.id).where(BrandFolder.name == clean_name)):
        raise HTTPException(status_code=409, detail="A brand folder already uses that name")
    if platform not in PLATFORMS:
        raise HTTPException(status_code=422, detail="Unknown platform preset")
    if caption_motion not in {"clean", "pulse", "kinetic"}:
        raise HTTPException(status_code=422, detail="Unknown caption motion")
    if caption_font not in {"sans", "mono", "serif"}:
        raise HTTPException(status_code=422, detail="Unknown caption font")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", caption_accent):
        raise HTTPException(status_code=422, detail="Caption accent must be a hex color")
    if watermark_position not in WATERMARK_POSITIONS:
        raise HTTPException(status_code=422, detail="Unknown watermark position")

    folder = BrandFolder(
        name=clean_name,
        platform=platform,
        caption_motion=caption_motion,
        caption_font=caption_font,
        caption_accent=caption_accent.upper(),
        watermark_position=watermark_position,
        watermark_size_percent=watermark_size_percent,
    )
    session.add(folder)
    await session.flush()
    if watermark:
        contents = await watermark.read(10 * 1024 * 1024 + 1)
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Watermark PNG must be 10 MB or smaller")
        if not contents.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=415, detail="Watermark must be a valid PNG image")
        destination = settings.storage_path / "brands" / folder.id / "watermark.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(destination, "wb") as output:
            await output.write(contents)
        folder.watermark_path = str(destination)
    await session.commit()
    return brand_folder_out(folder)


@app.get("/api/brand-folders/{folder_id}/watermark")
async def brand_folder_watermark(
    folder_id: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    folder = await session.get(BrandFolder, folder_id)
    watermark = Path(folder.watermark_path or "") if folder else Path("")
    if not folder or not folder.watermark_path or not watermark.exists():
        raise HTTPException(status_code=404, detail="Watermark not found")
    return FileResponse(watermark, media_type="image/png")


@app.post("/api/projects", response_model=ProjectOut, status_code=status.HTTP_202_ACCEPTED)
async def create_project(
    title: str = Form(..., min_length=1, max_length=200),
    source_url: str | None = Form(None),
    clip_count: int = Form(10, ge=1, le=20),
    caption_motion: str = Form("pulse"),
    caption_font: str = Form("sans"),
    caption_accent: str = Form("#D8E25B"),
    platform: str = Form("tiktok"),
    brand_folder_id: str | None = Form(None),
    override_brand_captions: bool = Form(False),
    file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    if bool(source_url) == bool(file):
        raise HTTPException(status_code=422, detail="Provide exactly one URL or video file")
    if source_url and not source_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Source URL must use http or https")
    if file and file.content_type and not file.content_type.startswith("video/"):
        raise HTTPException(status_code=415, detail="Uploaded file must be a video")
    if caption_motion not in {"clean", "pulse", "kinetic"}:
        raise HTTPException(status_code=422, detail="Unknown caption motion")
    if caption_font not in {"sans", "mono", "serif"}:
        raise HTTPException(status_code=422, detail="Unknown caption font")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", caption_accent):
        raise HTTPException(status_code=422, detail="Caption accent must be a hex color")
    if platform not in PLATFORMS:
        raise HTTPException(status_code=422, detail="Unknown platform preset")

    folder = await session.get(BrandFolder, brand_folder_id) if brand_folder_id else None
    if brand_folder_id and (not folder or folder.archived or folder.deleted):
        raise HTTPException(status_code=404, detail="Brand folder not found")
    if folder:
        platform = folder.platform
        if not override_brand_captions:
            caption_motion = folder.caption_motion
            caption_font = folder.caption_font
            caption_accent = folder.caption_accent

    project = Project(
        title=title.strip(),
        brand_folder_id=folder.id if folder else None,
        platform=platform,
        watermark_path=folder.watermark_path if folder else None,
        watermark_position=folder.watermark_position if folder else "upper-right",
        watermark_size_percent=folder.watermark_size_percent if folder else 18,
        source_url=source_url,
        requested_clip_count=clip_count,
        caption_motion=caption_motion,
        caption_font=caption_font,
        caption_accent=caption_accent.upper(),
    )
    session.add(project)
    await session.flush()

    if file:
        extension = Path(file.filename or "source.mp4").suffix.lower() or ".mp4"
        destination = settings.storage_path / project.id / f"source{extension}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(destination, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                await output.write(chunk)
        project.source_path = str(destination)

    job = await create_job(session, kind="ingest", project_id=project.id)
    await session.commit()
    await notify_worker(job.id)
    return project_out(await load_project(session, project.id))


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    return project_out(await load_project(session, project_id))


@app.get("/api/projects/{project_id}/source")
async def project_source(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    project = await load_project(session, project_id)
    source = Path(project.source_path or "")
    if not project.source_path or not source.exists():
        raise HTTPException(status_code=404, detail="Source media not found")
    return FileResponse(source)


def _invalidate_director_render(clip: Clip) -> None:
    clip.edit_revision += 1
    clip.render_version = 0
    clip.status = "candidate"
    clip.quality_status = "not_checked"
    clip.quality_score = None
    clip.quality_report = None
    clip.quality_checked_at = None
    clip.cover_options = None
    clip.selected_cover_index = None
    clip.hook_repair_status = "not_checked"
    clip.hook_repair_start = None
    clip.hook_repair_end = None
    clip.hook_repair_opening_note = None
    clip.hook_repair_ending_note = None


@app.get("/api/projects/{project_id}/clips/{clip_id}/layout")
async def inspect_source_layout(
    project_id: str, clip_id: str, start_seconds: float | None = None,
    end_seconds: float | None = None, session: AsyncSession = Depends(get_session),
) -> dict:
    project = await load_project(session, project_id)
    clip = next((item for item in project.clips if item.id == clip_id and item.is_current), None)
    if not clip or not project.source_path or not Path(project.source_path).exists():
        raise HTTPException(status_code=404, detail="Source video is unavailable")
    start = clip.start_seconds if start_seconds is None else start_seconds
    end = clip.end_seconds if end_seconds is None else end_seconds
    if start < 0 or not 0 < end - start <= 120 or end > (project.duration_seconds or 0) + 0.05:
        raise HTTPException(status_code=422, detail="Choose a valid clip range up to 120 seconds")
    return await asyncio.to_thread(analyze_layout, Path(project.source_path), start, end)


@app.put(
    "/api/projects/{project_id}/clips/{clip_id}/director",
    response_model=ProjectOut,
)
async def update_director_cut(
    project_id: str,
    clip_id: str,
    request: DirectorEditRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status == "rendering" or project.status == "rendering":
        raise HTTPException(status_code=409, detail="Wait for the current render to finish")
    if project.duration_seconds is None:
        raise HTTPException(status_code=409, detail="Source duration is unavailable")
    if request.end_seconds <= request.start_seconds:
        raise HTTPException(status_code=422, detail="The out point must follow the in point")
    duration = request.end_seconds - request.start_seconds
    if duration < 3 or duration > 120:
        raise HTTPException(status_code=422, detail="A directed clip must be 3 to 120 seconds")
    if request.end_seconds > project.duration_seconds + 0.05:
        raise HTTPException(status_code=422, detail="The out point is beyond the source")
    if len(request.caption_overrides) > 80:
        raise HTTPException(status_code=422, detail="Too many subtitle edits in one clip")

    valid_segment_ids = {segment.id for segment in project.transcript}
    unknown_ids = set(request.caption_overrides) - valid_segment_ids
    if unknown_ids:
        raise HTTPException(status_code=422, detail="A subtitle line no longer exists")
    cleaned_overrides: dict[str, str] = {}
    transcript_by_id = {segment.id: segment for segment in project.transcript}
    for segment_id, text in request.caption_overrides.items():
        cleaned = clean_caption_text(text)
        if len(cleaned) > 500:
            raise HTTPException(
                status_code=422, detail="Subtitle lines are limited to 500 characters"
            )
        if cleaned != clean_caption_text(transcript_by_id[segment_id].text):
            cleaned_overrides[segment_id] = cleaned

    directed_start = round(request.start_seconds, 3)
    directed_end = round(request.end_seconds, 3)
    directed_accent = request.caption_accent.upper()
    current_motion = clip.caption_motion or project.caption_motion
    current_font = clip.caption_font or project.caption_font
    current_accent = clip.caption_accent or project.caption_accent
    current_words = (
        clip.caption_words_per_phrase or CAPTION_WORDS_PER_PHRASE[current_motion]
    )
    if (
        clip.start_seconds == directed_start
        and clip.end_seconds == directed_end
        and _caption_overrides(clip) == cleaned_overrides
        and clip.speaker_focus == request.speaker_focus
        and clip.caption_position == request.caption_position
        and current_motion == request.caption_motion
        and current_font == request.caption_font
        and current_accent == directed_accent
        and current_words == request.caption_words_per_phrase
        and (clip.caption_size_percent or 100) == request.caption_size_percent
        and (clip.watermark_position or project.watermark_position) == request.watermark_position
        and (clip.watermark_size_percent or project.watermark_size_percent)
        == request.watermark_size_percent
        and not request.apply_to_all
    ):
        return project_out(project)

    clip.start_seconds = directed_start
    clip.end_seconds = directed_end
    clip.caption_overrides = (
        json.dumps(cleaned_overrides, ensure_ascii=False, sort_keys=True)
        if cleaned_overrides
        else None
    )
    clip.speaker_focus = request.speaker_focus
    clip.caption_position = request.caption_position
    clip.caption_motion = (
        request.caption_motion
        if request.caption_motion != project.caption_motion
        else None
    )
    clip.caption_font = (
        request.caption_font if request.caption_font != project.caption_font else None
    )
    clip.caption_accent = (
        directed_accent if directed_accent != project.caption_accent else None
    )
    clip.caption_words_per_phrase = (
        request.caption_words_per_phrase
        if request.caption_words_per_phrase
        != CAPTION_WORDS_PER_PHRASE[request.caption_motion]
        else None
    )
    _invalidate_director_render(clip)
    clip.caption_size_percent = request.caption_size_percent
    clip.watermark_position = request.watermark_position
    clip.watermark_size_percent = request.watermark_size_percent
    if request.apply_to_all:
        shared = {
            "speaker_focus": request.speaker_focus,
            "caption_position": request.caption_position,
            "caption_motion": request.caption_motion,
            "caption_font": request.caption_font,
            "caption_accent": directed_accent,
            "caption_words_per_phrase": request.caption_words_per_phrase,
            "caption_size_percent": request.caption_size_percent,
            "watermark_position": request.watermark_position,
            "watermark_size_percent": request.watermark_size_percent,
        }
        project.director_defaults = json.dumps(shared, sort_keys=True)
        for other in project.clips:
            if not other.is_current or other.id == clip.id or other.status == "rejected":
                continue
            for field, value in shared.items():
                setattr(other, field, value)
            _invalidate_director_render(other)
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.post(
    "/api/projects/{project_id}/clips/{clip_id}/director/reset",
    response_model=ProjectOut,
)
async def reset_director_cut(
    project_id: str, clip_id: str, session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status == "rendering" or project.status == "rendering":
        raise HTTPException(status_code=409, detail="Wait for the current render to finish")
    clip.start_seconds = clip.original_start_seconds
    clip.end_seconds = clip.original_end_seconds
    clip.caption_overrides = None
    clip.speaker_focus = "auto"
    clip.caption_position = "lower"
    clip.caption_motion = None
    clip.caption_font = None
    clip.caption_accent = None
    clip.caption_words_per_phrase = None
    defaults = json.loads(project.director_defaults or "{}")
    clip.caption_size_percent = None
    clip.watermark_position = None
    clip.watermark_size_percent = None
    for field, value in defaults.items():
        setattr(clip, field, value)
    _invalidate_director_render(clip)
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.post(
    "/api/projects/{project_id}/clips/{clip_id}/hook-repair",
    response_model=ProjectOut,
)
async def apply_hook_repair(
    project_id: str, clip_id: str, session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status == "rendering" or project.status == "rendering":
        raise HTTPException(status_code=409, detail="Wait for the current render to finish")
    if (
        clip.hook_repair_status != "recommended"
        or clip.hook_repair_start is None
        or clip.hook_repair_end is None
    ):
        raise HTTPException(status_code=409, detail="No hook repair is currently recommended")
    opening_note = clip.hook_repair_opening_note
    ending_note = clip.hook_repair_ending_note
    repaired_start = clip.hook_repair_start
    repaired_end = clip.hook_repair_end
    if repaired_end - repaired_start < 3 or repaired_end - repaired_start > 120:
        raise HTTPException(status_code=409, detail="The suggested repair is no longer valid")
    clip.start_seconds = repaired_start
    clip.end_seconds = repaired_end
    _invalidate_director_render(clip)
    clip.hook_repair_status = "applied"
    clip.hook_repair_start = repaired_start
    clip.hook_repair_end = repaired_end
    clip.hook_repair_opening_note = opening_note
    clip.hook_repair_ending_note = ending_note
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.put(
    "/api/projects/{project_id}/clips/{clip_id}/cover",
    response_model=ProjectOut,
)
async def select_cover(
    project_id: str,
    clip_id: str,
    request: CoverSelectionRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    try:
        options = json.loads(clip.cover_options or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []
    available = {
        int(option["index"])
        for option in options
        if isinstance(option, dict) and "index" in option
    }
    if request.index not in available:
        raise HTTPException(status_code=404, detail="Cover option not found")
    clip.selected_cover_index = request.index
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.post("/api/projects/{project_id}/retry", response_model=ProjectOut)
async def retry_project(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    project = await load_project(session, project_id)
    if project.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed projects can be retried")
    if not project.retryable:
        raise HTTPException(status_code=409, detail="This failure requires a different source")
    job = await retry_failed_job(session, project.id)
    if not job:
        raise HTTPException(status_code=409, detail="No failed job is available to retry")
    target = "queued" if job.kind in {"ingest", "score"} else "ready"
    try:
        require_transition(project.status, target)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    project.status = target
    project.error = None
    project.retryable = True
    await session.commit()
    await notify_worker(job.id)
    return project_out(await load_project(session, project.id))


@app.post("/api/projects/{project_id}/reanalyze", response_model=ProjectOut)
async def reanalyze_project(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    project = await load_project(session, project_id)
    if project.status in {"queued", "ingesting", "transcribing", "scoring", "rendering"}:
        raise HTTPException(status_code=409, detail="Project is already processing")
    if not project.transcript:
        raise HTTPException(status_code=409, detail="No stored transcript is available")
    project.status = "queued"
    project.error = None
    project.retryable = True
    job = await create_job(
        session,
        kind="score",
        project_id=project.id,
        key_suffix=f"generation-{project.analysis_generation + 1}",
    )
    await session.commit()
    await notify_worker(job.id)
    return project_out(await load_project(session, project.id))


@app.post("/api/projects/{project_id}/clips/{clip_id}/render", response_model=JobAccepted)
async def render_clip(
    project_id: str, clip_id: str, session: AsyncSession = Depends(get_session)
) -> JobAccepted:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status == "rejected":
        raise HTTPException(status_code=409, detail="Rejected clips cannot be rendered")
    if (
        clip.render_version >= CURRENT_RENDER_VERSION
        and clip.render_path
        and Path(clip.render_path).exists()
    ):
        return JobAccepted(job_id=f"rendered:{clip.id}", status="done")
    render_key = f"{clip.id}:v{CURRENT_RENDER_VERSION}:r{clip.edit_revision}"
    existing = await find_job(
        session,
        kind="render",
        project_id=project.id,
        clip_id=clip.id,
        key_suffix=render_key,
    )
    if existing and existing.status in {"pending", "running", "done"}:
        return JobAccepted(job_id=existing.id, status=existing.status)
    if project.status not in {"ready", "review", "approved"}:
        raise HTTPException(status_code=409, detail="Project is not ready to render")
    job = await create_job(
        session,
        kind="render",
        project_id=project.id,
        clip_id=clip.id,
        key_suffix=render_key,
    )
    await session.commit()
    await notify_worker(job.id)
    return JobAccepted(job_id=job.id, status=job.status)


@app.post("/api/projects/{project_id}/render-all", response_model=BatchAccepted)
async def render_all_clips(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> BatchAccepted:
    project = await load_project(session, project_id)
    clips = [
        item for item in project.clips if item.is_current and item.status != "rejected"
    ]
    pending = [
        item
        for item in clips
        if item.render_version < CURRENT_RENDER_VERSION
        or not item.render_path
        or not Path(item.render_path).exists()
    ]
    if not pending:
        return BatchAccepted(
            job_id=f"rendered-all:{project.analysis_generation}",
            status="done",
            clip_count=0,
        )
    if project.status not in {"ready", "review", "approved"}:
        raise HTTPException(status_code=409, detail="Project is not ready to render")
    edit_signature = "|".join(
        f"{item.id}:{item.edit_revision}" for item in sorted(clips, key=lambda item: item.id)
    ).encode()
    edit_fingerprint = hashlib.sha256(edit_signature).hexdigest()[:12]
    job = await create_job(
        session,
        kind="render_all",
        project_id=project.id,
        key_suffix=(
            f"generation-{project.analysis_generation}-v{CURRENT_RENDER_VERSION}-"
            f"edits-{edit_fingerprint}"
        ),
    )
    if job.status == "done":
        job.status = "pending"
        job.attempt = 0
        job.run_after = datetime.now(UTC)
        job.last_error = None
        job.lock_token = None
        job.lease_expires_at = None
    project.status = "rendering"
    await session.commit()
    await notify_worker(job.id)
    return BatchAccepted(job_id=job.id, status=job.status, clip_count=len(pending))


APPROVAL_REASONS = {"strong_hook", "surprising", "useful", "emotional", "on_brand", "other"}
REJECTION_REASONS = {
    "weak_hook",
    "too_generic",
    "too_similar",
    "incomplete",
    "poor_visual",
    "not_on_brand",
    "other",
}


def _feedback_concept(project: Project, clip: Clip) -> str:
    transcript = " ".join(
        segment.text
        for segment in project.transcript
        if segment.start_seconds < clip.end_seconds
        and segment.end_seconds > clip.start_seconds
    )
    return concept_signature(f"{clip.title} {clip.rationale}", transcript)


@app.post("/api/projects/{project_id}/clips/{clip_id}/approve", response_model=ProjectOut)
async def approve_clip(
    project_id: str,
    clip_id: str,
    request: FeedbackRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip or clip.status != "rendered":
        raise HTTPException(status_code=409, detail="Clip must be rendered before approval")
    if (
        clip.render_version < CURRENT_RENDER_VERSION
        or not clip.render_path
        or not Path(clip.render_path).exists()
    ):
        raise HTTPException(status_code=409, detail="Render the latest project preset first")
    if clip.quality_status in {"not_checked", "checking"}:
        raise HTTPException(
            status_code=409, detail="Run the quality inspector before final approval"
        )
    if clip.quality_status == "failed":
        raise HTTPException(
            status_code=409,
            detail="Resolve the failed quality checks before final approval",
        )
    try:
        project.status = project_status_after_clip_approval(project.status)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if request and request.reason not in APPROVAL_REASONS:
        raise HTTPException(status_code=422, detail="Unknown approval reason")
    clip.status = "approved"
    clip.feedback_decision = "approved"
    clip.feedback_reason = request.reason if request else "other"
    clip.feedback_detail = request.detail.strip() if request else ""
    clip.feedback_at = datetime.now(UTC)
    clip.concept_signature = _feedback_concept(project, clip)
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.post("/api/projects/{project_id}/clips/{clip_id}/reject", response_model=ProjectOut)
async def reject_clip(
    project_id: str,
    clip_id: str,
    request: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status not in {"candidate", "rendered"}:
        raise HTTPException(status_code=409, detail="This clip cannot be rejected now")
    if request.reason not in REJECTION_REASONS:
        raise HTTPException(status_code=422, detail="Unknown rejection reason")
    clip.status = "rejected"
    clip.feedback_decision = "rejected"
    clip.feedback_reason = request.reason
    clip.feedback_detail = request.detail.strip()
    clip.feedback_at = datetime.now(UTC)
    clip.concept_signature = _feedback_concept(project, clip)
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.post(
    "/api/projects/{project_id}/clips/{clip_id}/inspect", response_model=JobAccepted
)
async def inspect_clip_quality(
    project_id: str, clip_id: str, session: AsyncSession = Depends(get_session)
) -> JobAccepted:
    project = await load_project(session, project_id)
    clip = next(
        (item for item in project.clips if item.id == clip_id and item.is_current), None
    )
    if not clip or clip.status not in {"rendered", "approved"}:
        raise HTTPException(status_code=409, detail="Render the clip before inspection")
    if (
        clip.render_version < CURRENT_RENDER_VERSION
        or not clip.render_path
        or not Path(clip.render_path).exists()
    ):
        raise HTTPException(status_code=409, detail="Render the latest cut before inspection")

    inspect_key = (
        f"{clip.id}:v{CURRENT_RENDER_VERSION}:r{clip.edit_revision}:"
        f"q{QUALITY_INSPECTOR_VERSION}"
    )
    job = await create_job(
        session,
        kind="inspect",
        project_id=project.id,
        clip_id=clip.id,
        key_suffix=inspect_key,
    )
    if job.status in {"done", "failed"}:
        job.status = "pending"
        job.attempt = 0
        job.run_after = datetime.now(UTC)
        job.last_error = None
        job.lock_token = None
        job.lease_expires_at = None
    clip.quality_status = "checking"
    clip.quality_score = None
    await session.commit()
    await notify_worker(job.id)
    return JobAccepted(job_id=job.id, status=job.status)


def _publishing_payload(project: Project, clips: list[Clip]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for clip in clips:
        transcript = " ".join(
            segment.text
            for segment in project.transcript
            if segment.start_seconds < clip.end_seconds
            and segment.end_seconds > clip.start_seconds
        )
        payload.append(
            {
                "clip_id": clip.id,
                "title": clip.title,
                "rationale": clip.rationale,
                "transcript": transcript,
            }
        )
    return payload


def _approved_current_clips(project: Project, clip_ids: list[str]) -> list[Clip]:
    requested = set(clip_ids)
    clips = [
        item
        for item in project.clips
        if item.id in requested and item.is_current and item.status == "approved"
    ]
    if len(clips) != len(requested):
        raise HTTPException(
            status_code=409, detail="Only current, approved clips can enter the publishing queue"
        )
    return sorted(clips, key=lambda item: item.rank)


async def _publishing_copy(
    project: Project, clips: list[Clip]
) -> dict[str, tuple[str, str]]:
    copy = {
        clip.id: (clip.publication.cover_title, clip.publication.seo_caption)
        for clip in clips
        if clip.publication
    }
    missing = [clip for clip in clips if not clip.publication]
    copy.update(
        await generate_publishing_copy(
            _publishing_payload(project, missing), settings.openai_scoring_model
        )
    )
    return copy


async def _upsert_publication(
    session: AsyncSession,
    project: Project,
    clip: Clip,
    scheduled_for: datetime,
    copy: tuple[str, str],
    platforms: list[str],
) -> None:
    publication = clip.publication or PublicationSchedule(
        project_id=project.id,
        clip_id=clip.id,
        scheduled_for=scheduled_for,
        cover_title=copy[0],
        seo_caption=copy[1],
    )
    publication.scheduled_for = scheduled_for
    publication.cover_title = copy[0]
    publication.seo_caption = copy[1]
    publication.platforms = json.dumps(list(dict.fromkeys(platforms)))
    publication.status = "queued"
    if not clip.publication:
        session.add(publication)


@app.post("/api/projects/{project_id}/schedule/auto", response_model=ProjectOut)
async def auto_schedule_clips(
    project_id: str,
    request: AutoScheduleRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await load_project(session, project_id)
    clips = _approved_current_clips(project, request.clip_ids)
    copy = await _publishing_copy(project, clips)
    start_date = request.start_date or datetime.now(UTC).date()
    slots_per_day: dict[int, int] = {}
    for index, clip in enumerate(clips):
        day_offset = min(request.days - 1, floor(index * request.days / len(clips)))
        slot = slots_per_day.get(day_offset, 0)
        slots_per_day[day_offset] = slot + 1
        local_publish_time = datetime.combine(
            start_date + timedelta(days=day_offset),
            time(hour=min(21, 10 + slot * 3)),
        )
        scheduled_for = (
            local_publish_time + timedelta(minutes=request.timezone_offset_minutes)
        ).replace(tzinfo=UTC)
        await _upsert_publication(
            session, project, clip, scheduled_for, copy[clip.id], request.platforms
        )
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.put("/api/projects/{project_id}/clips/{clip_id}/schedule", response_model=ProjectOut)
async def manually_schedule_clip(
    project_id: str,
    clip_id: str,
    request: ManualScheduleRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await load_project(session, project_id)
    clips = _approved_current_clips(project, [clip_id])
    clip = clips[0]
    copy = await _publishing_copy(project, clips)
    scheduled_for = request.scheduled_for
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=UTC)
    await _upsert_publication(
        session, project, clip, scheduled_for, copy[clip.id], request.platforms
    )
    await session.commit()
    return project_out(await load_project(session, project.id))


@app.get("/api/clips/{clip_id}/media")
async def clip_media(clip_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    clip = await session.get(Clip, clip_id)
    if (
        not clip
        or clip.render_version < CURRENT_RENDER_VERSION
        or not clip.render_path
        or not Path(clip.render_path).exists()
    ):
        raise HTTPException(status_code=404, detail="Rendered clip not found")
    return FileResponse(clip.render_path, media_type="video/mp4")


def _cover_path(clip: Clip, index: int) -> Path:
    return settings.storage_path / clip.project_id / "covers" / clip.id / f"cover-{index}.jpg"


@app.get("/api/clips/{clip_id}/covers/{index}")
async def clip_cover(
    clip_id: str, index: int, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    clip = await session.get(Clip, clip_id)
    if not clip or index not in {0, 1, 2}:
        raise HTTPException(status_code=404, detail="Cover not found")
    cover = _cover_path(clip, index)
    if not cover.exists():
        raise HTTPException(status_code=404, detail="Cover file is missing")
    return FileResponse(cover, media_type="image/jpeg")


@app.get("/api/clips/{clip_id}/cover/export")
async def export_cover(
    clip_id: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    clip = await session.get(Clip, clip_id)
    if not clip or clip.selected_cover_index is None:
        raise HTTPException(status_code=409, detail="Select a cover before export")
    cover = _cover_path(clip, clip.selected_cover_index)
    if not cover.exists():
        raise HTTPException(status_code=404, detail="Selected cover file is missing")
    return FileResponse(
        cover,
        media_type="image/jpeg",
        filename=f"clip-{clip.id}-cover.jpg",
    )


@app.get("/api/clips/{clip_id}/export")
async def export_clip(clip_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    clip = await session.get(Clip, clip_id)
    if (
        not clip
        or clip.status != "approved"
        or clip.render_version < CURRENT_RENDER_VERSION
        or not clip.render_path
    ):
        raise HTTPException(status_code=409, detail="Approve the rendered clip before export")
    if not Path(clip.render_path).exists():
        raise HTTPException(status_code=404, detail="Rendered clip file is missing")
    return FileResponse(
        clip.render_path,
        media_type="video/mp4",
        filename=f"clip-{clip.id}.mp4",
    )
