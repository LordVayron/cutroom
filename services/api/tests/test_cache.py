import json
from dataclasses import asdict
from pathlib import Path

from app.domain import Candidate, TimedText
from app.models import Project
from app.pipeline import (
    _cached_candidates,
    analysis_cache_key,
    speaker_tracking_cache_key,
)


def test_analysis_cache_key_tracks_every_ranking_input() -> None:
    transcript = [TimedText(0, 8, "A complete thought.")]
    baseline = analysis_cache_key(transcript, [], 6, "gpt-5.6-sol")

    assert analysis_cache_key(transcript, [], 6, "gpt-5.6-sol") == baseline
    assert analysis_cache_key(transcript, [(0, 8)], 6, "gpt-5.6-sol") != baseline
    assert analysis_cache_key(transcript, [], 8, "gpt-5.6-sol") != baseline
    assert analysis_cache_key(transcript, [], 6, "another-model") != baseline
    assert analysis_cache_key(transcript, [], 6, "gpt-5.6-sol", "new-taste") != baseline


def test_cached_analysis_round_trips_candidates() -> None:
    candidate = Candidate(
        title="Strong moment",
        start_seconds=10,
        end_seconds=42,
        score=0.94,
        rationale="Self-contained and specific.",
    )
    project = Project(title="Cache test")
    project.analysis_cache_key = "matching-key"
    project.analysis_cache_payload = json.dumps([asdict(candidate)])

    cached = _cached_candidates(project, "matching-key")

    assert cached == [candidate]
    assert _cached_candidates(project, "different-key") is None


def test_speaker_tracking_cache_changes_only_with_media_or_cut(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    baseline = speaker_tracking_cache_key(source, 10, 40)

    assert speaker_tracking_cache_key(source, 10, 40) == baseline
    assert speaker_tracking_cache_key(source, 11, 40) != baseline
    assert speaker_tracking_cache_key(source, 10, 41) != baseline
    assert speaker_tracking_cache_key(source, 10, 40, "linkedin") != baseline

    source.write_bytes(b"changed-video")
    assert speaker_tracking_cache_key(source, 10, 40) != baseline


def test_cut_aware_tracking_invalidates_older_maps(tmp_path, monkeypatch):
    from app import pipeline

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    current = pipeline.speaker_tracking_cache_key(source, 0, 10)
    monkeypatch.setattr(pipeline, "SPEAKER_TRACKING_VERSION", 1)
    assert pipeline.speaker_tracking_cache_key(source, 0, 10) != current
