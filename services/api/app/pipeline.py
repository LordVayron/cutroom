import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.creative import generate_cover_options, suggest_hook_repair
from app.domain import (
    MAX_CLIP_SECONDS,
    Candidate,
    TimedText,
    TimedWord,
    clean_caption_text,
    require_transition,
)
from app.layout import analyze_layout
from app.media import (
    CURRENT_RENDER_VERSION,
    PLATFORM_PROFILES,
    download_source,
    extract_audio_chunks,
    find_source_caption,
    probe_duration,
    render_vertical,
    track_speaker_crop,
)
from app.models import Clip, Project, TranscriptSegment
from app.providers import AIClipRanker, Json3CaptionTranscript, OpenAIAudioTranscript
from app.quality import QUALITY_INSPECTOR_VERSION, inspect_clip
from app.taste import (
    ConceptMemory,
    FeedbackSignal,
    candidate_text,
    concept_signature,
    filter_duplicate_candidates,
    learning_digest,
    taste_context,
)


class PermanentPipelineError(ValueError):
    pass


logger = logging.getLogger(__name__)
ANALYSIS_CACHE_VERSION = 1
SPEAKER_TRACKING_VERSION = 3


def store_hook_repair(
    clip: Clip, transcript: list[TimedText], source_duration: float
) -> None:
    suggestion = suggest_hook_repair(
        transcript, clip.start_seconds, clip.end_seconds, source_duration
    )
    clip.hook_repair_status = str(suggestion["status"])
    clip.hook_repair_start = float(suggestion["suggested_start"])
    clip.hook_repair_end = float(suggestion["suggested_end"])
    clip.hook_repair_opening_note = str(suggestion["opening_note"])
    clip.hook_repair_ending_note = str(suggestion["ending_note"])


async def generate_clip_covers(project: Project, clip: Clip) -> None:
    if not clip.render_path:
        return
    try:
        options = await asyncio.to_thread(
            generate_cover_options,
            Path(clip.render_path),
            settings.storage_path / project.id / "covers" / clip.id,
            clip.title,
            clip.caption_accent or project.caption_accent,
        )
    except Exception:
        logger.warning("Cover generation failed for clip %s", clip.id, exc_info=True)
        return
    clip.cover_options = json.dumps(options, ensure_ascii=False)
    valid_indexes = {int(option["index"]) for option in options}
    if clip.selected_cover_index not in valid_indexes:
        clip.selected_cover_index = min(valid_indexes)


def _stored_timed_text(item: TranscriptSegment) -> TimedText:
    words: tuple[TimedWord, ...] = ()
    if item.word_timings:
        try:
            words = tuple(
                TimedWord(float(word["start"]), float(word["end"]), str(word["text"]))
                for word in json.loads(item.word_timings)
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            words = ()
    return TimedText(
        item.start_seconds, item.end_seconds, clean_caption_text(item.text), words
    )


async def clip_transcript(session: AsyncSession, clip: Clip) -> list[TimedText]:
    stored_segments = await session.scalars(
        select(TranscriptSegment)
        .where(
            TranscriptSegment.project_id == clip.project_id,
            TranscriptSegment.start_seconds < clip.end_seconds,
            TranscriptSegment.end_seconds > clip.start_seconds,
        )
        .order_by(TranscriptSegment.start_seconds)
    )
    try:
        overrides = json.loads(clip.caption_overrides or "{}")
    except (TypeError, json.JSONDecodeError):
        overrides = {}
    if not isinstance(overrides, dict):
        overrides = {}
    transcript: list[TimedText] = []
    for item in stored_segments:
        timed = _stored_timed_text(item)
        if item.id in overrides:
            timed = TimedText(
                timed.start_seconds,
                timed.end_seconds,
                clean_caption_text(str(overrides[item.id])),
            )
        transcript.append(timed)
    return transcript


async def stored_project_transcript(
    session: AsyncSession, project_id: str
) -> list[TimedText]:
    stored_segments = await session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.project_id == project_id)
        .order_by(TranscriptSegment.start_seconds)
    )
    return [_stored_timed_text(item) for item in stored_segments]


def transcript_for_clip(transcript: list[TimedText], clip: Clip) -> list[TimedText]:
    return [
        segment
        for segment in transcript
        if segment.start_seconds < clip.end_seconds
        and segment.end_seconds > clip.start_seconds
    ]


def analysis_cache_key(
    segments: list[TimedText],
    excluded_ranges: list[tuple[float, float]],
    clip_count: int,
    model: str,
    taste_digest: str = "",
) -> str:
    transcript_payload = [
        {
            "start": round(item.start_seconds, 3),
            "end": round(item.end_seconds, 3),
            "text": item.text,
        }
        for item in segments
    ]
    payload = {
        "version": ANALYSIS_CACHE_VERSION,
        "transcript": transcript_payload,
        "excluded": sorted(
            (round(start, 3), round(end, 3)) for start, end in excluded_ranges
        ),
        "clip_count": clip_count,
        "model": model,
        "taste_digest": taste_digest,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _cached_candidates(project: Project, key: str) -> list[Candidate] | None:
    if project.analysis_cache_key != key or not project.analysis_cache_payload:
        return None
    try:
        payload = json.loads(project.analysis_cache_payload)
        if not isinstance(payload, list):
            return None
        return [Candidate(**item) for item in payload]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def speaker_tracking_cache_key(
    source: Path, start: float, end: float, platform: str = "tiktok"
) -> str:
    stat = source.stat()
    payload = (
        f"{SPEAKER_TRACKING_VERSION}|{source.resolve()}|{stat.st_size}|"
        f"{stat.st_mtime_ns}|{start:.3f}|{end:.3f}|{platform}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def cached_speaker_tracking(
    session: AsyncSession, project: Project, clip: Clip, layout_report: dict | None = None
) -> tuple[str, int] | None:
    if clip.speaker_focus != "auto":
        return None
    source = Path(project.source_path or "")
    key = speaker_tracking_cache_key(
        source, clip.start_seconds, clip.end_seconds, project.platform
    )
    if clip.tracking_cache_key == key and clip.tracking_crop_expression:
        logger.info("Speaker tracking cache hit for clip %s", clip.id)
        return clip.tracking_crop_expression, clip.tracking_detection_count or 0
    profile = PLATFORM_PROFILES.get(project.platform, PLATFORM_PROFILES["tiktok"])
    tracking = await track_speaker_crop(
        source,
        clip.start_seconds,
        clip.end_seconds,
        profile.width,
        profile.height,
    )
    clip.tracking_cache_key = key
    clip.tracking_crop_expression = tracking[0]
    clip.tracking_detection_count = tracking[1]
    await session.commit()
    return tracking


async def has_approved_clips(session: AsyncSession, project_id: str) -> bool:
    approved_clip = await session.scalar(
        select(Clip.id)
        .where(
            Clip.project_id == project_id,
            Clip.is_current.is_(True),
            Clip.status == "approved",
        )
        .limit(1)
    )
    return approved_clip is not None


async def set_project_status(session: AsyncSession, project: Project, target: str) -> None:
    require_transition(project.status, target)
    project.status = target
    project.error = None
    project.retryable = True
    await session.commit()


async def process_ingest(session: AsyncSession, project_id: str) -> None:
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError("Project no longer exists")
    if project.status != "queued":
        return

    await set_project_status(session, project, "ingesting")
    project_dir = settings.storage_path / project.id
    project_dir.mkdir(parents=True, exist_ok=True)
    if project.source_url:
        source_path = await download_source(
            project.source_url, project_dir, settings.ingest_max_height
        )
        project.source_path = str(source_path)
    if not project.source_path:
        raise ValueError("Project has no source media")
    source = Path(project.source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source media does not exist: {source}")
    project.duration_seconds = await probe_duration(source)
    await session.commit()
    if project.duration_seconds < settings.min_source_duration_seconds:
        raise PermanentPipelineError(
            f"Source must be at least {settings.min_source_duration_seconds:g} seconds; "
            f"received {project.duration_seconds:.2f} seconds"
        )

    await set_project_status(session, project, "transcribing")
    caption_path = find_source_caption(project_dir)
    if caption_path:
        provider = Json3CaptionTranscript(caption_path)
    else:
        if not os.getenv("OPENAI_API_KEY"):
            raise PermanentPipelineError(
                "This video has no source-language captions. Configure OPENAI_API_KEY "
                "to transcribe its spoken language automatically."
            )
        audio_chunks = await extract_audio_chunks(source, project_dir / "transcription")
        provider = OpenAIAudioTranscript(
            audio_chunks, settings.openai_transcription_model
        )
    segments = await provider.transcribe(
        title=project.title, duration_seconds=project.duration_seconds
    )
    if not segments:
        raise PermanentPipelineError("Speech transcription returned no usable words")
    await session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.project_id == project.id)
    )
    session.add_all(
        TranscriptSegment(
            project_id=project.id,
            start_seconds=item.start_seconds,
            end_seconds=item.end_seconds,
            text=item.text,
            word_timings=(
                json.dumps(
                    [
                        {"start": word.start_seconds, "end": word.end_seconds, "text": word.text}
                        for word in item.words
                    ]
                )
                if item.words
                else None
            ),
        )
        for item in segments
    )
    project.analysis_cache_key = None
    project.analysis_cache_payload = None
    await session.commit()

    await process_score(session, project.id)


async def process_score(session: AsyncSession, project_id: str) -> None:
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError("Project no longer exists")
    if project.status not in {"queued", "transcribing"}:
        return
    segments = await stored_project_transcript(session, project.id)
    if not segments:
        raise PermanentPipelineError("No stored transcript is available for re-analysis")

    prior_clips = list(
        await session.scalars(select(Clip).where(Clip.project_id == project.id))
    )
    excluded_ranges = [(item.start_seconds, item.end_seconds) for item in prior_clips]
    feedback_rows = list(
        await session.scalars(
            select(Clip)
            .where(Clip.feedback_decision.is_not(None))
            .order_by(Clip.feedback_at)
        )
    )
    feedback_signals = [
        FeedbackSignal(
            decision=clip.feedback_decision or "",
            reason=clip.feedback_reason or "other",
            title=clip.title,
            detail=clip.feedback_detail or "",
        )
        for clip in feedback_rows
    ]
    memory_rows = (
        await session.execute(
            select(Clip, Project.title)
            .join(Project, Clip.project_id == Project.id)
            .where(
                Clip.project_id != project.id,
                or_(Clip.feedback_decision == "approved", Clip.status == "approved"),
            )
            .order_by(Clip.feedback_at.desc().nullslast())
            .limit(100)
        )
    ).all()
    memories = [
        ConceptMemory(
            clip_id=clip.id,
            project_title=project_title,
            clip_title=clip.title,
            signature=clip.concept_signature
            or concept_signature(clip.title, clip.rationale),
        )
        for clip, project_title in memory_rows
    ]
    profile = taste_context(feedback_signals)
    taste_digest = learning_digest(profile, memories)
    await set_project_status(session, project, "scoring")
    cache_key = analysis_cache_key(
        segments,
        excluded_ranges,
        project.requested_clip_count,
        settings.openai_scoring_model,
        taste_digest,
    )
    ranked = _cached_candidates(project, cache_key)
    if ranked is None:
        expanded_limit = min(
            20,
            max(project.requested_clip_count + 4, project.requested_clip_count * 2),
        )
        proposed = await AIClipRanker(
            expanded_limit, settings.openai_scoring_model
        ).rank(
            segments,
            excluded_ranges=excluded_ranges,
            taste_profile=profile,
            concept_memories=[
                f"{memory.project_title} — {memory.clip_title}" for memory in memories
            ],
        )
        ranked, duplicate_matches = filter_duplicate_candidates(
            proposed,
            segments,
            memories,
            project.requested_clip_count,
        )
        project.duplicate_ideas_filtered = len(duplicate_matches)
        project.analysis_cache_key = cache_key
        project.analysis_cache_payload = json.dumps(
            [asdict(item) for item in ranked], ensure_ascii=False
        )
        await session.commit()
    else:
        logger.info("Analysis cache hit for project %s", project.id)
    if not ranked:
        raise PermanentPipelineError(
            "No unused moments remain for this clip count. The clip-memory database prevented "
            "duplicate or overlapping selections."
        )
    if any(item.end_seconds - item.start_seconds > MAX_CLIP_SECONDS for item in ranked):
        raise PermanentPipelineError(
            f"Clip selection exceeded the hard {MAX_CLIP_SECONDS:g}-second limit"
        )
    for clip in prior_clips:
        clip.is_current = False
    project.analysis_generation += 1
    new_clips: list[Clip] = []
    for rank, item in enumerate(ranked, start=1):
        clip = Clip(
            project_id=project.id,
            rank=rank,
            title=item.title,
            start_seconds=item.start_seconds,
            end_seconds=item.end_seconds,
            original_start_seconds=item.start_seconds,
            original_end_seconds=item.end_seconds,
            score=item.score,
            rationale=item.rationale,
            generation=project.analysis_generation,
            is_current=True,
            series_id=item.series_id,
            series_index=item.series_index,
            series_count=item.series_count,
            concept_signature=concept_signature(
                f"{item.title} {item.rationale}", candidate_text(item, segments)
            ),
            **json.loads(project.director_defaults or "{}"),
        )
        store_hook_repair(clip, segments, project.duration_seconds or item.end_seconds)
        new_clips.append(clip)
    session.add_all(new_clips)
    await session.commit()
    await set_project_status(session, project, "ready")


async def process_render(session: AsyncSession, project_id: str, clip_id: str) -> None:
    project = await session.get(Project, project_id)
    clip = await session.scalar(
        select(Clip).where(Clip.id == clip_id, Clip.project_id == project_id)
    )
    if not project or not clip:
        raise ValueError("Project or clip no longer exists")
    if clip.status == "rejected":
        raise PermanentPipelineError("Rejected clips cannot be rendered")
    if (
        clip.render_version >= CURRENT_RENDER_VERSION
        and clip.render_path
        and Path(clip.render_path).exists()
    ):
        return
    was_approved = clip.status == "approved"
    if project.status != "rendering":
        await set_project_status(session, project, "rendering")
    clip.status = "rendering"
    await session.commit()

    output = settings.storage_path / project.id / "renders" / f"{clip.id}.mp4"
    full_transcript = await stored_project_transcript(session, project.id)
    if clip.hook_repair_status == "not_checked":
        store_hook_repair(
            clip, full_transcript, project.duration_seconds or clip.end_seconds
        )
    transcript = await clip_transcript(session, clip)
    layout_report = await asyncio.to_thread(
        analyze_layout, Path(project.source_path or ""), clip.start_seconds, clip.end_seconds
    )
    speaker_tracking = await cached_speaker_tracking(session, project, clip, layout_report)
    await render_vertical(
        Path(project.source_path or ""),
        output,
        clip.start_seconds,
        clip.end_seconds,
        transcript,
        clip.caption_motion or project.caption_motion,
        clip.caption_font or project.caption_font,
        clip.caption_accent or project.caption_accent,
        clip.speaker_focus,
        clip.caption_position,
        clip.caption_words_per_phrase,
        speaker_tracking,
        project.platform,
        Path(project.watermark_path) if project.watermark_path else None,
        clip.watermark_position or project.watermark_position,
        clip.watermark_size_percent or project.watermark_size_percent,
        clip.caption_size_percent or 100,
    )
    clip.render_path = str(output)
    clip.render_version = CURRENT_RENDER_VERSION
    await inspect_render_quality(session, clip, transcript, project.platform)
    clip.status = (
        "approved" if was_approved and clip.quality_status != "failed" else "rendered"
    )
    await session.commit()
    has_approved = await has_approved_clips(session, project.id)
    await set_project_status(session, project, "review")
    if has_approved:
        await set_project_status(session, project, "approved")


async def process_render_all(session: AsyncSession, project_id: str) -> None:
    project = await session.get(Project, project_id)
    if not project or not project.source_path:
        raise ValueError("Project or source media no longer exists")
    clips = list(
        await session.scalars(
            select(Clip)
            .where(
                Clip.project_id == project.id,
                Clip.is_current.is_(True),
                Clip.status != "rejected",
            )
            .order_by(Clip.rank)
        )
    )
    pending = [
        clip
        for clip in clips
        if clip.render_version < CURRENT_RENDER_VERSION
        or not clip.render_path
        or not Path(clip.render_path).exists()
    ]
    if not pending:
        return
    if project.status != "rendering":
        await set_project_status(session, project, "rendering")
    stored_transcript = await stored_project_transcript(session, project.id)
    for clip in pending:
        was_approved = clip.status == "approved"
        clip.status = "rendering"
        await session.commit()
        output = settings.storage_path / project.id / "renders" / f"{clip.id}.mp4"
        if clip.hook_repair_status == "not_checked":
            store_hook_repair(
                clip,
                stored_transcript,
                project.duration_seconds or clip.end_seconds,
            )
        transcript = (
            transcript_for_clip(stored_transcript, clip)
            if not clip.caption_overrides
            else await clip_transcript(session, clip)
        )
        layout_report = await asyncio.to_thread(
            analyze_layout, Path(project.source_path), clip.start_seconds, clip.end_seconds
        )
        speaker_tracking = await cached_speaker_tracking(session, project, clip, layout_report)
        await render_vertical(
            Path(project.source_path),
            output,
            clip.start_seconds,
            clip.end_seconds,
            transcript,
            clip.caption_motion or project.caption_motion,
            clip.caption_font or project.caption_font,
            clip.caption_accent or project.caption_accent,
            clip.speaker_focus,
            clip.caption_position,
            clip.caption_words_per_phrase,
            speaker_tracking,
            project.platform,
            Path(project.watermark_path) if project.watermark_path else None,
            clip.watermark_position or project.watermark_position,
            clip.watermark_size_percent or project.watermark_size_percent,
            clip.caption_size_percent or 100,
        )
        clip.render_path = str(output)
        clip.render_version = CURRENT_RENDER_VERSION
        await inspect_render_quality(session, clip, transcript, project.platform)
        clip.status = (
            "approved" if was_approved and clip.quality_status != "failed" else "rendered"
        )
        await session.commit()
    has_approved = await has_approved_clips(session, project.id)
    await set_project_status(session, project, "review")
    if has_approved:
        await set_project_status(session, project, "approved")


def _unavailable_quality_report(message: str) -> dict[str, object]:
    checks = [
        {
            "key": key,
            "label": label,
            "status": "warn",
            "summary": "This check could not run; retry the inspector.",
        }
        for key, label in (
            ("speaker_visibility", "Speaker visibility"),
            ("subtitle_safety", "Safe subtitles"),
            ("subtitle_sync", "Subtitle sync"),
            ("silence", "Audio continuity"),
            ("stable_framing", "Stable framing"),
            ("complete_cut", "Complete cut"),
        )
    ]
    return {
        "version": QUALITY_INSPECTOR_VERSION,
        "status": "warning",
        "score": 52,
        "error": message[:500],
        "checks": checks,
    }


async def inspect_render_quality(
    session: AsyncSession,
    clip: Clip,
    transcript: list[TimedText],
    platform: str = "tiktok",
) -> None:
    clip.quality_status = "checking"
    clip.quality_score = None
    clip.quality_report = None
    clip.quality_checked_at = None
    await session.commit()
    try:
        report = await inspect_clip(
            Path(clip.render_path or ""),
            Path(clip.render_path or "").with_suffix(".captions.ass"),
            transcript,
            clip.start_seconds,
            clip.end_seconds,
            platform,
        )
    except Exception as exc:
        report = _unavailable_quality_report(str(exc))
    clip.quality_status = str(report["status"])
    clip.quality_score = int(report["score"])
    clip.quality_report = json.dumps(report, ensure_ascii=False)
    clip.quality_checked_at = datetime.now(UTC)
    await session.commit()


async def process_inspect(session: AsyncSession, project_id: str, clip_id: str) -> None:
    project = await session.get(Project, project_id)
    clip = await session.scalar(
        select(Clip).where(Clip.id == clip_id, Clip.project_id == project_id)
    )
    if not project or not clip or not clip.render_path:
        raise PermanentPipelineError("Rendered clip is unavailable")
    render_path = Path(clip.render_path)
    if not render_path.exists() or clip.render_version < CURRENT_RENDER_VERSION:
        raise PermanentPipelineError("Render this clip before running the inspector")
    transcript = await clip_transcript(session, clip)
    await inspect_render_quality(session, clip, transcript, project.platform)
