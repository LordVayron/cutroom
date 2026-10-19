import json
from types import SimpleNamespace

import pytest

from app.domain import (
    Candidate,
    InvalidTransition,
    TimedText,
    TimedWord,
    project_status_after_clip_approval,
    rank_candidates,
    require_transition,
)
from app.media import (
    FaceObservation,
    _advance_tracking_center,
    _contains_hard_cut,
    _dynamic_caption_events,
    _interpolated_crop_expression,
    _keep_ranges_from_silence,
    _scene_change_score,
    _select_active_speaker,
    _source_caption_languages,
    _speaker_crop_expression,
    _stabilize_crop_positions,
    _watermark_overlay,
    _write_dynamic_captions,
    find_source_caption,
)
from app.providers import (
    AIClipRanker,
    Json3CaptionTranscript,
    OpenAIAudioTranscript,
    TimedOutlineTranscript,
    _long_clip_candidates,
    _split_series,
)


def test_happy_path_transitions_are_allowed() -> None:
    path = [
        "queued",
        "ingesting",
        "transcribing",
        "scoring",
        "ready",
        "rendering",
        "review",
        "approved",
    ]
    for current, target in zip(path, path[1:]):
        require_transition(current, target)


def test_invalid_transition_fails_closed() -> None:
    with pytest.raises(InvalidTransition):
        require_transition("queued", "approved")


def test_source_caption_selection_matches_podcast_language() -> None:
    info = {
        "language": "es",
        "subtitles": {"en": [{}], "es": [{}]},
        "automatic_captions": {"en": [{}], "es-orig": [{}], "fr": [{}]},
    }

    assert _source_caption_languages(info) == ["es"]


def test_original_automatic_caption_wins_over_translations() -> None:
    info = {
        "language": "es",
        "subtitles": {},
        "automatic_captions": {"en": [{}], "fr": [{}], "es-orig": [{}]},
    }

    assert _source_caption_languages(info) == ["es-orig"]


def test_source_caption_finder_accepts_non_english_tracks(tmp_path) -> None:
    translated = tmp_path / "source.en.json3"
    original = tmp_path / "source.es-orig.json3"
    translated.write_text("{}", encoding="utf-8")
    original.write_text("{}", encoding="utf-8")

    assert find_source_caption(tmp_path) == original


def test_clip_can_be_approved_while_other_clips_are_rendering() -> None:
    assert project_status_after_clip_approval("rendering") == "rendering"
    assert project_status_after_clip_approval("review") == "approved"


def test_failed_work_can_return_to_the_correct_retry_state() -> None:
    require_transition("failed", "queued")
    require_transition("failed", "ready")


def test_ranker_returns_three_non_empty_ranked_candidates() -> None:
    phrases = [
        "Here is the context people miss.",
        "But the obvious answer is a mistake!",
        "Why does the constraint change everything?",
        "The practical move is surprisingly small.",
        "Never optimize just the visible step.",
        "You can use this without a new tool.",
        "The secret is deciding before pressure arrives.",
        "That change creates a stronger result.",
        "Now the whole system becomes easier to see.",
    ]
    segments = [TimedText(index * 10, (index + 1) * 10, text) for index, text in enumerate(phrases)]

    candidates = rank_candidates(segments, limit=3)

    assert len(candidates) == 2
    assert all(candidate.end_seconds > candidate.start_seconds for candidate in candidates)
    assert [candidate.score for candidate in candidates] == sorted(
        [candidate.score for candidate in candidates], reverse=True
    )
    assert all(candidate.rationale for candidate in candidates)


def test_short_source_fallback_preserves_score_order() -> None:
    segments = [
        TimedText(0, 10, "Here is the context people miss."),
        TimedText(10, 20, "But the obvious answer is a mistake!"),
        TimedText(20, 30, "Why does this change everything?"),
        TimedText(30, 40, "Never optimize only the visible step."),
        TimedText(40, 46, "The surprise is a stronger result."),
    ]

    candidates = rank_candidates(segments, limit=3)

    assert len(candidates) == 1
    assert [item.score for item in candidates] == sorted(
        [item.score for item in candidates], reverse=True
    )


@pytest.mark.asyncio
async def test_outline_transcript_never_extends_beyond_source() -> None:
    segments = await TimedOutlineTranscript().transcribe(title="Tiny", duration_seconds=8.02)

    assert segments[-1].end_seconds == 8.02


@pytest.mark.asyncio
async def test_json3_provider_uses_real_caption_text(tmp_path) -> None:
    caption = tmp_path / "source.en-orig.json3"
    caption.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 0,
                        "dDurationMs": 3000,
                        "segs": [
                            {"utf8": ">>"},
                            {"utf8": "I", "tOffsetMs": 100},
                            {"utf8": " learned", "tOffsetMs": 350},
                            {"utf8": " this", "tOffsetMs": 800},
                            {"utf8": " the hard way.", "tOffsetMs": 1200},
                        ],
                    },
                    {"tStartMs": 3000, "dDurationMs": 3000, "segs": [{"utf8": "\n"}]},
                    {
                        "tStartMs": 2400,
                        "dDurationMs": 4600,
                        "segs": [
                            {"utf8": "this"},
                            {"utf8": " the", "tOffsetMs": 120},
                            {"utf8": " hard", "tOffsetMs": 260},
                            {"utf8": " way.", "tOffsetMs": 400},
                            {"utf8": " Why does the system fail?", "tOffsetMs": 610},
                        ],
                    },
                    {"tStartMs": 7100, "dDurationMs": 2000, "segs": [{"utf8": "[Music]"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    segments = await Json3CaptionTranscript(caption).transcribe(
        title="Ignored", duration_seconds=10
    )

    assert "I learned this the hard way." in segments[0].text
    assert "Why does the system fail?" in segments[0].text
    assert all("Music" not in segment.text for segment in segments)
    assert ">>" not in segments[0].text
    assert segments[0].text.count("this the hard way.") == 1
    assert segments[0].words[0] == TimedWord(0.1, 0.35, "I")
    assert segments[0].words[1].start_seconds == 0.35


@pytest.mark.asyncio
async def test_uploaded_audio_transcript_preserves_chunk_offset(tmp_path, monkeypatch) -> None:
    chunk = tmp_path / "audio-001.mp3"
    chunk.write_bytes(b"audio")

    class FakeSegment:
        start = 1.25
        end = 3.5
        text = "The actual spoken words."

    class FakeWord:
        def __init__(self, word: str, start: float, end: float):
            self.word = word
            self.start = start
            self.end = end

    class FakeTranscriptions:
        async def create(self, **kwargs):
            assert kwargs["model"] == "whisper-1"
            assert kwargs["timestamp_granularities"] == ["word", "segment"]
            return type(
                "Response",
                (),
                {
                    "segments": [FakeSegment()],
                    "words": [FakeWord("The", 1.25, 1.5), FakeWord("actual", 1.5, 2.0)],
                },
            )()

    fake_client = type(
        "Client",
        (),
        {"audio": type("Audio", (), {"transcriptions": FakeTranscriptions()})()},
    )()
    monkeypatch.setattr("app.providers.AsyncOpenAI", lambda: fake_client)

    segments = await OpenAIAudioTranscript([(chunk, 600)], "whisper-1").transcribe(
        title="Upload", duration_seconds=700
    )

    assert segments == [
        TimedText(
            601.25,
            603.5,
            "The actual spoken words.",
            (TimedWord(601.25, 601.5, "The"), TimedWord(601.5, 602.0, "actual")),
        )
    ]


def test_long_transcript_returns_ten_non_overlapping_content_candidates() -> None:
    phrases = (
        "I learned this the hard way because the obvious answer caused a bigger problem.",
        "Why do most people miss what actually changes the outcome?",
        "The truth is you have to measure the system, not just the final number.",
        "Here is the thing that changed my life when I finally understood the reason.",
    )
    segments = [
        TimedText(index * 8, (index + 1) * 8, phrases[index % len(phrases)])
        for index in range(64)
    ]
    segments[16] = TimedText(
        128,
        136,
        "Today's sponsor has a discount code. Subscribe and check out the show notes.",
    )

    candidates = rank_candidates(segments, limit=10)

    assert len(candidates) == 10
    assert [candidate.score for candidate in candidates] == sorted(
        [candidate.score for candidate in candidates], reverse=True
    )
    assert all(
        left.end_seconds <= right.start_seconds or right.end_seconds <= left.start_seconds
        for index, left in enumerate(candidates)
        for right in candidates[index + 1 :]
    )
    assert all("sponsor" not in candidate.title.lower() for candidate in candidates)


def test_clip_memory_excludes_old_and_overlapping_ranges() -> None:
    segments = [
        TimedText(index * 10, (index + 1) * 10, "Why this important change solves the problem.")
        for index in range(24)
    ]

    candidates = rank_candidates(segments, limit=10, excluded_ranges=[(40, 95), (160, 205)])

    assert candidates
    assert all(
        candidate.end_seconds <= 37
        or 98 <= candidate.start_seconds and candidate.end_seconds <= 157
        or candidate.start_seconds >= 208
        for candidate in candidates
    )


def test_worthy_long_moment_splits_into_contiguous_series() -> None:
    segments = [TimedText(index * 10, (index + 1) * 10, f"Passage {index}.") for index in range(15)]
    source = Candidate("Long idea", 0, 150, 0.9, "Sustained payoff", series_eligible=True)

    parts = _split_series(source, segments, 3, "The Full Story", "Worth the sequence", 0.94)

    assert len(parts) == 3
    assert [part.series_index for part in parts] == [1, 2, 3]
    assert all(part.series_count == 3 for part in parts)
    assert parts[0].end_seconds == parts[1].start_seconds
    assert parts[1].end_seconds == parts[2].start_seconds


def test_long_clip_candidates_are_rare_bounded_single_clips() -> None:
    segments = [
        TimedText(
            index * 10,
            (index + 1) * 10,
            "Why this important sustained argument changes what people believe.",
        )
        for index in range(24)
    ]

    candidates = _long_clip_candidates(segments, [], limit=3)

    assert candidates
    assert len(candidates) <= 3
    assert all(60 < item.end_seconds - item.start_seconds <= 120 for item in candidates)
    assert all(item.long_clip_eligible for item in candidates)
    assert all(not item.series_eligible for item in candidates)


@pytest.mark.asyncio
async def test_ai_ranker_enforces_long_clip_frequency(monkeypatch) -> None:
    short = [
        Candidate(f"Short {index}", index * 200, index * 200 + 45, 0.8, "Brief payoff")
        for index in range(3)
    ]
    long = [
        Candidate(
            f"Long {index}",
            600 + index * 200,
            690 + index * 200,
            0.9,
            "Sustained payoff",
            long_clip_eligible=True,
        )
        for index in range(3)
    ]
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("app.providers.rank_candidates", lambda *args, **kwargs: short)
    monkeypatch.setattr("app.providers._long_clip_candidates", lambda *args, **kwargs: long)
    monkeypatch.setattr("app.providers._series_candidates", lambda *args, **kwargs: [])

    moments = [
        SimpleNamespace(
            candidate_index=index,
            score=0.95 - index * 0.01,
            title=f"Chosen {index}",
            rationale="Worth the longer arc",
            series_parts=1,
        )
        for index in (3, 4, 5)
    ]

    class FakeResponses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=SimpleNamespace(moments=moments))

    fake_client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setattr("app.providers.AsyncOpenAI", lambda: fake_client)

    selected = await AIClipRanker(10, "gpt-5.6-sol").rank(
        [TimedText(0, 10, "Transcript")]
    )

    selected_long = [item for item in selected if item.end_seconds - item.start_seconds > 60]
    assert len(selected_long) == 2
    assert all(item.end_seconds - item.start_seconds <= 120 for item in selected)


def test_speaker_crop_falls_back_safely_when_video_is_missing(tmp_path) -> None:
    expression, detected = _speaker_crop_expression(tmp_path / "missing.mp4", 0, 30)

    assert expression == "(iw-ow)/2"
    assert detected == 0


def test_crop_lock_rejects_brief_false_target_and_missing_detection() -> None:
    positions = _stabilize_crop_positions(
        [300, 310, 920, 305, None, 315, 308], max_x=1260, interval=0.6
    )

    assert max(positions) - min(positions) < 30


def test_crop_lock_ignores_normal_movement_within_the_same_speaker() -> None:
    positions = _stabilize_crop_positions(
        [1000, 1090, 1210, 1280, 1120, 1040], max_x=2330, interval=1.0
    )

    assert len(set(positions)) == 1


def test_crop_bootstraps_from_opening_consensus_not_first_detection() -> None:
    positions = _stabilize_crop_positions(
        [900, 210, 205, 215, 208], max_x=1260, interval=0.8
    )

    assert all(position < 300 for position in positions)


def test_crop_switch_requires_persistence_then_commits_to_new_target() -> None:
    positions = _stabilize_crop_positions(
        [200, 205, 198, 900, 905, 910, 915, 920, 925],
        max_x=1260,
        interval=0.6,
    )

    assert len(set(positions[:4])) == 1
    assert positions[4] > positions[3]
    assert positions[-1] == positions[4]
    assert len(set(positions)) == 2
    expression = _interpolated_crop_expression(positions, 0.6)
    assert "3-2*" in expression


def test_camera_cut_snaps_instead_of_panning_across_shots() -> None:
    expression = _interpolated_crop_expression([200, 900], 1.0, {1})

    assert "3-2*" not in expression
    assert "lt(t\\,0.5)" in expression


def test_camera_cut_immediately_resets_spatial_lock() -> None:
    positions = _stabilize_crop_positions(
        [200, 205, 900, 905], max_x=1260, interval=1.0, hard_cut_indices={2}
    )

    assert positions[:2] == [205, 205]
    assert positions[2:] == [900, 900]


def test_scene_change_score_separates_a_hard_cut() -> None:
    import numpy as np

    dark = np.zeros((90, 160), dtype=np.uint8)
    light = np.full((90, 160), 255, dtype=np.uint8)

    assert _scene_change_score(dark, dark) == 0
    assert _scene_change_score(dark, light) > 24


def test_hard_cut_detection_uses_adjacent_frames() -> None:
    import numpy as np

    dark = np.zeros((90, 160, 3), dtype=np.uint8)
    light = np.full((90, 160, 3), 255, dtype=np.uint8)

    assert not _contains_hard_cut([dark, dark, dark])
    assert _contains_hard_cut([dark, dark, light])


def test_active_speaker_motion_overrides_larger_silent_face() -> None:
    observations = [
        FaceObservation(center=0.25, area=12000, mouth_motion=0.8),
        FaceObservation(center=0.75, area=8000, mouth_motion=5.2),
    ]

    assert _select_active_speaker(observations, previous_center=0.25) == 0.75


def test_ambiguous_mouth_motion_holds_current_speaker() -> None:
    observations = [
        FaceObservation(center=0.25, area=8000, mouth_motion=2.5),
        FaceObservation(center=0.75, area=12000, mouth_motion=2.4),
    ]

    assert _select_active_speaker(observations, previous_center=0.25) == 0.25


def test_reaction_shot_cannot_retarget_tracking_in_one_sample() -> None:
    locked, pending, count = _advance_tracking_center(0.25, None, 0, 0.75)

    assert locked == 0.25
    assert pending == 0.75
    assert count == 1

    locked, pending, count = _advance_tracking_center(locked, pending, count, 0.25)
    assert locked == 0.25
    assert pending is None
    assert count == 0


def test_repeated_speech_evidence_commits_new_tracking_target() -> None:
    locked, pending, count = _advance_tracking_center(0.25, None, 0, 0.75)
    locked, pending, count = _advance_tracking_center(locked, pending, count, 0.76)

    assert locked == pytest.approx(0.755)
    assert pending is None
    assert count == 0


def test_dynamic_captions_highlight_each_spoken_word(tmp_path) -> None:
    transcript = [
        TimedText(
            10,
            12,
            ">> this framing now feels much smoother",
            (
                TimedWord(10.05, 10.22, ">>"),
                TimedWord(10.22, 10.45, "this"),
                TimedWord(10.45, 10.72, "framing"),
                TimedWord(10.72, 10.91, "now"),
                TimedWord(10.91, 11.18, "feels"),
                TimedWord(11.18, 11.55, "much"),
                TimedWord(11.55, 11.92, "smoother"),
            ),
        )
    ]

    events = _dynamic_caption_events(transcript, 10, 12)
    output = tmp_path / "clip.captions.ass"
    count = _write_dynamic_captions(
        output, transcript, 10, 12, "kinetic", "serif", "#12AB34"
    )

    assert count == 6
    assert len(events) == 6
    assert events[0][0] == pytest.approx(0.22)
    assert events[0][1] == pytest.approx(0.45)
    assert events[0][2].count("&H005BE2D8&") == 1
    assert "THIS" in events[0][2]
    assert "FRAMING" in events[0][2]
    assert ">>" not in " ".join(event[2] for event in events)
    contents = output.read_text(encoding="utf-8")
    assert "Style: Dynamic,DejaVu Serif,70" in contents
    assert ",2,72,240,500,1" in contents
    assert "&H0034AB12&" in contents
    assert "\\frz-1" in contents
    assert "\\fscx126" not in contents
    assert "\\fscy126" in contents
    assert contents.count("Dialogue:") == 6


def test_silence_removal_keeps_short_natural_pauses() -> None:
    keep = _keep_ranges_from_silence(
        8.0,
        [(2.0, 3.0), (5.0, 5.5)],
        pause_padding=0.1,
    )

    assert keep == pytest.approx([(0.0, 2.1), (2.9, 5.1), (5.4, 8.0)])
    assert sum(end - start for start, end in keep) == pytest.approx(6.9)


def test_captions_follow_the_compacted_speech_timeline() -> None:
    transcript = [
        TimedText(
            0,
            7,
            "First second third",
            (
                TimedWord(1.0, 1.3, "First"),
                TimedWord(4.0, 4.3, "second"),
                TimedWord(6.0, 6.3, "third"),
            ),
        )
    ]
    keep = [(0.0, 2.1), (2.9, 5.1), (5.4, 8.0)]

    events = _dynamic_caption_events(transcript, 0, 8, keep_ranges=keep)

    assert [event[0] for event in events] == pytest.approx([1.0, 3.2, 4.9])


def test_director_caption_positions_remain_inside_safe_zone(tmp_path) -> None:
    transcript = [TimedText(0, 2, "A safe subtitle line")]

    expected_margins = {"upper": 1000, "middle": 730, "lower": 500}
    for position, margin in expected_margins.items():
        output = tmp_path / f"{position}.ass"
        _write_dynamic_captions(
            output,
            transcript,
            0,
            2,
            position=position,
        )

        assert f",2,72,240,{margin},1" in output.read_text(encoding="utf-8")


def test_linkedin_profile_uses_four_by_five_canvas_and_safe_captions(tmp_path) -> None:
    output = tmp_path / "linkedin.ass"

    _write_dynamic_captions(
        output,
        [TimedText(0, 2, "Professional video caption")],
        0,
        2,
        position="lower",
        platform="linkedin",
    )

    contents = output.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in contents
    assert "PlayResY: 1350" in contents
    assert ",2,64,120,280,1" in contents


def test_watermark_positions_cover_the_nine_point_grid() -> None:
    assert _watermark_overlay("upper-left", 1080, 1920) == ("49", "125")
    assert _watermark_overlay("center", 1080, 1920) == (
        "(main_w-overlay_w)/2",
        "(main_h-overlay_h)/2",
    )
    assert _watermark_overlay("lower-right", 1080, 1920) == (
        "main_w-overlay_w-49",
        "main_h-overlay_h-125",
    )


def test_director_controls_how_many_words_appear_together() -> None:
    transcript = [TimedText(0, 4, "one two three four")]

    compact = _dynamic_caption_events(
        transcript,
        0,
        4,
        words_per_phrase=2,
    )
    roomy = _dynamic_caption_events(
        transcript,
        0,
        4,
        words_per_phrase=4,
    )

    assert "THREE" not in compact[0][2]
    assert "THREE" in roomy[0][2]
