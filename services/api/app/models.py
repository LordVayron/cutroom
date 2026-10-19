import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class BrandFolder(Base):
    __tablename__ = "brand_folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    platform: Mapped[str] = mapped_column(String(16), default="tiktok")
    caption_motion: Mapped[str] = mapped_column(String(16), default="pulse")
    caption_font: Mapped[str] = mapped_column(String(16), default="sans")
    caption_accent: Mapped[str] = mapped_column(String(7), default="#D8E25B")
    watermark_path: Mapped[str | None] = mapped_column(Text)
    watermark_position: Mapped[str] = mapped_column(String(24), default="upper-right")
    watermark_size_percent: Mapped[int] = mapped_column(Integer, default=18)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    projects: Mapped[list["Project"]] = relationship(back_populates="brand_folder")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("brand_folders.id", ondelete="SET NULL"), index=True
    )
    platform: Mapped[str] = mapped_column(String(16), default="tiktok")
    watermark_path: Mapped[str | None] = mapped_column(Text)
    watermark_position: Mapped[str] = mapped_column(String(24), default="upper-right")
    watermark_size_percent: Mapped[int] = mapped_column(Integer, default=18)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    requested_clip_count: Mapped[int] = mapped_column(Integer, default=10)
    caption_motion: Mapped[str] = mapped_column(String(16), default="pulse")
    caption_font: Mapped[str] = mapped_column(String(16), default="sans")
    caption_accent: Mapped[str] = mapped_column(String(7), default="#D8E25B")
    analysis_generation: Mapped[int] = mapped_column(Integer, default=0)
    analysis_cache_key: Mapped[str | None] = mapped_column(String(64))
    analysis_cache_payload: Mapped[str | None] = mapped_column(Text)
    duplicate_ideas_filtered: Mapped[int] = mapped_column(Integer, default=0)
    director_defaults: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    clips: Mapped[list["Clip"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    transcript: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    brand_folder: Mapped[BrandFolder | None] = relationship(back_populates="projects")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    word_timings: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="transcript")


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "generation", "rank", name="uq_clips_project_generation_rank"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    original_start_seconds: Mapped[float] = mapped_column(Float)
    original_end_seconds: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate")
    render_path: Mapped[str | None] = mapped_column(Text)
    render_version: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    series_id: Mapped[str | None] = mapped_column(String(80))
    series_index: Mapped[int | None] = mapped_column(Integer)
    series_count: Mapped[int | None] = mapped_column(Integer)
    caption_overrides: Mapped[str | None] = mapped_column(Text)
    speaker_focus: Mapped[str] = mapped_column(String(16), default="auto")
    caption_position: Mapped[str] = mapped_column(String(16), default="lower")
    caption_motion: Mapped[str | None] = mapped_column(String(16))
    caption_font: Mapped[str | None] = mapped_column(String(16))
    caption_accent: Mapped[str | None] = mapped_column(String(7))
    caption_words_per_phrase: Mapped[int | None] = mapped_column(Integer)
    caption_size_percent: Mapped[int | None] = mapped_column(Integer)
    watermark_position: Mapped[str | None] = mapped_column(String(24))
    watermark_size_percent: Mapped[int | None] = mapped_column(Integer)
    edit_revision: Mapped[int] = mapped_column(Integer, default=0)
    tracking_cache_key: Mapped[str | None] = mapped_column(String(64))
    tracking_crop_expression: Mapped[str | None] = mapped_column(Text)
    tracking_detection_count: Mapped[int | None] = mapped_column(Integer)
    quality_status: Mapped[str] = mapped_column(String(16), default="not_checked")
    quality_score: Mapped[int | None] = mapped_column(Integer)
    quality_report: Mapped[str | None] = mapped_column(Text)
    quality_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hook_repair_status: Mapped[str] = mapped_column(String(16), default="not_checked")
    hook_repair_start: Mapped[float | None] = mapped_column(Float)
    hook_repair_end: Mapped[float | None] = mapped_column(Float)
    hook_repair_opening_note: Mapped[str | None] = mapped_column(Text)
    hook_repair_ending_note: Mapped[str | None] = mapped_column(Text)
    cover_options: Mapped[str | None] = mapped_column(Text)
    selected_cover_index: Mapped[int | None] = mapped_column(Integer)
    feedback_decision: Mapped[str | None] = mapped_column(String(16))
    feedback_reason: Mapped[str | None] = mapped_column(String(32))
    feedback_detail: Mapped[str | None] = mapped_column(Text)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    concept_signature: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="clips")
    publication: Mapped["PublicationSchedule | None"] = relationship(
        back_populates="clip", cascade="all, delete-orphan", uselist=False
    )


class PublicationSchedule(Base):
    __tablename__ = "publication_schedules"
    __table_args__ = (Index("ix_publication_queue", "status", "scheduled_for"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    clip_id: Mapped[str] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), unique=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cover_title: Mapped[str] = mapped_column(String(80))
    seo_caption: Mapped[str] = mapped_column(Text)
    platforms: Mapped[str] = mapped_column(Text, default='["tiktok"]')
    status: Mapped[str] = mapped_column(String(24), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    clip: Mapped[Clip] = relationship(back_populates="publication")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_ready", "status", "run_after"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    clip_id: Mapped[str | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    lock_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
