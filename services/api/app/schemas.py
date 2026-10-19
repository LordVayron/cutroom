from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TranscriptSegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    start_seconds: float
    end_seconds: float
    text: str


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scheduled_for: datetime
    cover_title: str
    seo_caption: str
    platforms: list[Literal["tiktok", "reels", "shorts", "linkedin"]]
    status: str


class QualityCheckOut(BaseModel):
    key: str
    label: str
    status: str
    summary: str


class QualityReportOut(BaseModel):
    status: str
    score: int | None
    checked_at: datetime | None
    checks: list[QualityCheckOut]


class BrandFolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    archived: bool = False
    platform: str
    caption_motion: str
    caption_font: str
    caption_accent: str
    watermark_url: str | None
    watermark_position: str
    watermark_size_percent: int
    created_at: datetime


class HookRepairOut(BaseModel):
    status: str
    suggested_start: float
    suggested_end: float
    opening_note: str
    ending_note: str


class CoverOptionOut(BaseModel):
    index: int
    label: str
    url: str
    selected: bool


class FeedbackOut(BaseModel):
    decision: str | None
    reason: str | None
    detail: str | None
    recorded_at: datetime | None


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rank: int
    title: str
    start_seconds: float
    end_seconds: float
    original_start_seconds: float
    original_end_seconds: float
    score: float
    rationale: str
    status: str
    render_url: str | None = None
    generation: int
    series_id: str | None
    series_index: int | None
    series_count: int | None
    caption_overrides: dict[str, str]
    speaker_focus: str
    caption_position: str
    caption_motion: str
    caption_font: str
    caption_accent: str
    caption_words_per_phrase: int
    caption_size_percent: int
    watermark_position: str
    watermark_size_percent: int
    edit_revision: int
    is_edited: bool
    quality: QualityReportOut
    hook_repair: HookRepairOut
    covers: list[CoverOptionOut]
    feedback: FeedbackOut
    publication: PublicationOut | None = None


class ProjectSummary(BaseModel):
    archived: bool = False
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: str
    duration_seconds: float | None
    error: str | None
    retryable: bool
    requested_clip_count: int
    brand_folder_id: str | None
    platform: str
    watermark_url: str | None
    watermark_position: str
    watermark_size_percent: int
    caption_motion: str
    caption_font: str
    caption_accent: str
    analysis_generation: int
    duplicate_ideas_filtered: int
    created_at: datetime


class ProjectOut(ProjectSummary):
    source_url: str | None
    clips: list[ClipOut]
    transcript: list[TranscriptSegmentOut]


class JobAccepted(BaseModel):
    job_id: str
    status: str = "pending"


class BatchAccepted(BaseModel):
    job_id: str
    status: str = "pending"
    clip_count: int


class AutoScheduleRequest(BaseModel):
    clip_ids: list[str] = Field(min_length=1, max_length=20)
    days: int = Field(ge=1, le=7)
    start_date: date | None = None
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    platforms: list[Literal["tiktok", "reels", "shorts", "linkedin"]] = Field(
        min_length=1, max_length=4
    )


class ManualScheduleRequest(BaseModel):
    scheduled_for: datetime
    platforms: list[Literal["tiktok", "reels", "shorts", "linkedin"]] = Field(
        min_length=1, max_length=4
    )


class CoverSelectionRequest(BaseModel):
    index: int = Field(ge=0, le=2)


class FeedbackRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=32)
    detail: str = Field(default="", max_length=500)


class DirectorEditRequest(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    speaker_focus: Literal["auto", "left", "center", "right", "duo", "single", "source"] = "auto"
    caption_position: Literal["upper", "middle", "lower"] = "lower"
    caption_motion: Literal["clean", "pulse", "kinetic"] = "pulse"
    caption_font: Literal["sans", "mono", "serif"] = "sans"
    caption_accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    caption_words_per_phrase: int = Field(ge=1, le=8)
    caption_overrides: dict[str, str] = Field(default_factory=dict)
    caption_size_percent: int = Field(default=100, ge=60, le=140)
    watermark_position: Literal[
        "upper-left", "upper-center", "upper-right", "middle-left", "center",
        "middle-right", "lower-left", "lower-center", "lower-right"
    ] = "upper-right"
    watermark_size_percent: int = Field(default=18, ge=8, le=35)
    apply_to_all: bool = False
