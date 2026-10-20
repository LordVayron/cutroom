import json
import logging
import os
import re
from pathlib import Path
from typing import Literal, Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.domain import (
    HOOK_WORDS,
    MAX_CLIP_SECONDS,
    PROMO_PHRASES,
    Candidate,
    TimedText,
    TimedWord,
    clean_caption_text,
    ranges_overlap,
    rank_candidates,
)

logger = logging.getLogger(__name__)


class TranscriptProvider(Protocol):
    async def transcribe(self, *, title: str, duration_seconds: float) -> list[TimedText]: ...


class ClipRanker(Protocol):
    async def rank(self, segments: list[TimedText]) -> list[Candidate]: ...


class TimedOutlineTranscript:
    """Credential-free milestone provider; replace with speech-to-text behind this contract."""

    phrases = (
        "Here is the context most people miss when they first approach the problem.",
        "But the obvious answer creates a second problem that is much harder to see.",
        "Why does that happen? The constraint changes the decision completely.",
        "The common mistake is optimizing the visible step instead of the whole system.",
        "The surprise is that a smaller move can create a much stronger result.",
        "You can use this test without adding another tool or complicated workflow.",
        "The practical change is to make the decision before the pressure arrives.",
        "Never measure only the final number; watch what produced it.",
    )

    async def transcribe(self, *, title: str, duration_seconds: float) -> list[TimedText]:
        segment_length = 10.0
        usable_duration = max(0.0, duration_seconds)
        segments: list[TimedText] = []
        cursor = 0.0
        index = 0
        while cursor < usable_duration:
            end = min(cursor + segment_length, usable_duration)
            phrase = self.phrases[index % len(self.phrases)]
            prefix = f"In {title}, " if index == 0 else ""
            segments.append(TimedText(cursor, end, prefix + phrase))
            cursor = end
            index += 1
        return segments


def _caption_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in clean_caption_text(text).split():
        if tokens and re.fullmatch(r"[.,!?;:]+", token):
            tokens[-1] += token
        else:
            tokens.append(token)
    return tokens


def _spread_words(
    tokens: list[str], start: float, end: float, duration_seconds: float
) -> list[TimedWord]:
    if not tokens:
        return []
    end = min(duration_seconds, max(start + 0.08, end))
    weights = [
        0.7
        + min(10, len(token.strip(".,!?;:\"'"))) * 0.08
        + int(token.endswith((".", "?", "!"))) * 0.18
        for token in tokens
    ]
    total_weight = sum(weights)
    cursor = start
    words: list[TimedWord] = []
    for index, (token, weight) in enumerate(zip(tokens, weights, strict=True)):
        word_end = (
            end
            if index == len(tokens) - 1
            else cursor + (end - start) * weight / total_weight
        )
        words.append(TimedWord(cursor, max(cursor + 0.04, word_end), token))
        cursor = word_end
    return words


def _json3_event_words(event: dict, duration_seconds: float) -> list[TimedWord]:
    event_start = max(0.0, float(event.get("tStartMs", 0)) / 1000)
    event_end = min(
        duration_seconds,
        event_start + max(0.1, float(event.get("dDurationMs", 2000)) / 1000),
    )
    parts: list[tuple[float, list[str]]] = []
    for segment in event.get("segs", []):
        tokens = _caption_tokens(str(segment.get("utf8", "")))
        if tokens:
            parts.append(
                (
                    event_start + max(0.0, float(segment.get("tOffsetMs", 0)) / 1000),
                    tokens,
                )
            )

    words: list[TimedWord] = []
    for index, (part_start, tokens) in enumerate(parts):
        next_start = parts[index + 1][0] if index + 1 < len(parts) else event_end
        part_end = next_start if next_start > part_start else event_end
        words.extend(_spread_words(tokens, part_start, part_end, duration_seconds))
    return words


def _caption_overlap(existing: list[TimedWord], incoming: list[TimedWord]) -> int:
    """Find rolling-caption words repeated at the start of the next JSON3 event."""
    largest = min(12, len(existing), len(incoming))
    for size in range(largest, 1, -1):
        previous = [word.text.casefold() for word in existing[-size:]]
        current = [word.text.casefold() for word in incoming[:size]]
        if previous == current:
            return size
    return 0


class Json3CaptionTranscript:
    """Read real timed captions downloaded by yt-dlp and group them into readable passages."""

    def __init__(self, path: Path):
        self.path = path

    async def transcribe(self, *, title: str, duration_seconds: float) -> list[TimedText]:
        del title
        events = json.loads(self.path.read_text(encoding="utf-8")).get("events", [])
        timeline: list[TimedWord] = []
        for event in events:
            words = _json3_event_words(event, duration_seconds)
            text = clean_caption_text(" ".join(word.text for word in words))
            if not text or text.startswith("[") and text.endswith("]"):
                continue
            timeline.extend(words[_caption_overlap(timeline, words) :])

        precise_words: list[TimedWord] = []
        for index, word in enumerate(timeline):
            next_start = timeline[index + 1].start_seconds if index + 1 < len(timeline) else None
            end = word.end_seconds
            if next_start is not None and word.start_seconds < next_start < end:
                end = next_start
            precise_words.append(
                TimedWord(word.start_seconds, max(word.start_seconds + 0.04, end), word.text)
            )

        passages: list[TimedText] = []
        pending: list[str] = []
        pending_words: list[TimedWord] = []
        start = 0.0
        end = 0.0
        for word in precise_words:
            if not pending:
                start = word.start_seconds
            pending.append(word.text)
            pending_words.append(word)
            end = word.end_seconds
            span = end - start
            if span >= 12 or span >= 6 and word.text.rstrip().endswith((".", "?", "!")):
                passages.append(
                    TimedText(start, end, " ".join(pending), tuple(pending_words))
                )
                pending = []
                pending_words = []
        if pending:
            passages.append(TimedText(start, end, " ".join(pending), tuple(pending_words)))
        return passages


class OpenAIAudioTranscript:
    """Transcribe uploaded media chunks with timestamped speech-to-text."""

    def __init__(self, chunks: list[tuple[Path, float]], model: str):
        self.chunks = chunks
        self.model = model

    async def transcribe(self, *, title: str, duration_seconds: float) -> list[TimedText]:
        del title
        client = AsyncOpenAI()
        transcript: list[TimedText] = []
        for path, offset in self.chunks:
            with path.open("rb") as audio:
                response = await client.audio.transcriptions.create(
                    model=self.model,
                    file=audio,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
            segments = getattr(response, "segments", None) or []
            response_words = [
                TimedWord(
                    offset + float(getattr(word, "start", 0)),
                    offset + float(getattr(word, "end", 0.1)),
                    clean_caption_text(str(getattr(word, "word", ""))),
                )
                for word in (getattr(response, "words", None) or [])
                if clean_caption_text(str(getattr(word, "word", "")))
            ]
            for segment in segments:
                text = clean_caption_text(str(getattr(segment, "text", "")))
                if not text:
                    continue
                relative_start = float(getattr(segment, "start", 0))
                relative_end = float(getattr(segment, "end", relative_start + 0.1))
                start = offset + relative_start
                end = offset + relative_end
                segment_words = tuple(
                    word
                    for word in response_words
                    if word.start_seconds < end and word.end_seconds > start
                )
                transcript.append(
                    TimedText(
                        max(0.0, start),
                        min(duration_seconds, max(start + 0.1, end)),
                        text,
                        segment_words,
                    )
                )
            if not segments and getattr(response, "text", "").strip():
                chunk_end = min(duration_seconds, offset + 600)
                transcript.append(
                    TimedText(
                        offset,
                        chunk_end,
                        clean_caption_text(response.text),
                        tuple(response_words),
                    )
                )
        return transcript


class HeuristicClipRanker:
    def __init__(self, limit: int = 10):
        self.limit = limit

    async def rank(self, segments: list[TimedText]) -> list[Candidate]:
        return rank_candidates(segments, limit=self.limit)


class RankedMoment(BaseModel):
    candidate_index: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
    title: str = Field(min_length=3, max_length=80)
    rationale: str = Field(min_length=3, max_length=180)
    series_parts: Literal[1, 3, 4] = 1


class RankedMoments(BaseModel):
    moments: list[RankedMoment]


def _series_candidates(
    segments: list[TimedText], excluded_ranges: list[tuple[float, float]], limit: int = 8
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index in range(0, len(segments), 6):
        window = segments[index : index + 14]
        if len(window) < 9:
            continue
        start = window[0].start_seconds
        end = min(window[-1].end_seconds, start + 180)
        if end - start < 90 or ranges_overlap(start, end, excluded_ranges, padding=3):
            continue
        text = " ".join(item.text for item in window)
        lowered = text.lower()
        words = {word.strip(".,!?—:;\"'").lower() for word in text.split()}
        hook_hits = len(words & HOOK_WORDS)
        promo_hits = sum(phrase in lowered for phrase in PROMO_PHRASES)
        score = round(min(0.92, 0.45 + min(hook_hits, 8) * 0.04 - promo_hits * 0.35), 2)
        if promo_hits:
            continue
        candidates.append(
            Candidate(
                title=f"Series candidate at {int(start)}s",
                start_seconds=start,
                end_seconds=end,
                score=score,
                rationale="A sustained idea that may justify a short multi-part series.",
                series_eligible=True,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.start_seconds))[:limit]


def _long_clip_candidates(
    segments: list[TimedText], excluded_ranges: list[tuple[float, float]], limit: int = 8
) -> list[Candidate]:
    """Offer Sol transcript-complete 1–2 minute exceptions without making them the default."""
    candidates: list[Candidate] = []
    for index in range(0, len(segments), 3):
        window = segments[index : index + 12]
        if len(window) < 6:
            continue
        start = window[0].start_seconds
        valid_ends = [
            item.end_seconds
            for item in window
            if item.end_seconds - start <= MAX_CLIP_SECONDS
        ]
        if not valid_ends:
            continue
        end = max(valid_ends)
        if end - start <= 60 or ranges_overlap(start, end, excluded_ranges, padding=3):
            continue
        text = " ".join(item.text for item in window if item.start_seconds < end)
        lowered = text.lower()
        words = {word.strip(".,!?—:;\"'").lower() for word in text.split()}
        hook_hits = len(words & HOOK_WORDS)
        promo_hits = sum(phrase in lowered for phrase in PROMO_PHRASES)
        if promo_hits:
            continue
        score = round(min(0.93, 0.5 + min(hook_hits, 8) * 0.04), 2)
        candidates.append(
            Candidate(
                title=f"Long-form candidate at {int(start)}s",
                start_seconds=start,
                end_seconds=end,
                score=score,
                rationale="A complete sustained moment that may justify a 1–2 minute exception.",
                long_clip_eligible=True,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.start_seconds))[:limit]


def _split_series(
    source: Candidate,
    segments: list[TimedText],
    parts: int,
    title: str,
    rationale: str,
    score: float,
) -> list[Candidate]:
    boundaries = [source.start_seconds]
    available_ends = [
        segment.end_seconds
        for segment in segments
        if source.start_seconds < segment.end_seconds < source.end_seconds
    ]
    duration = source.end_seconds - source.start_seconds
    for part in range(1, parts):
        target = source.start_seconds + duration * part / parts
        boundaries.append(min(available_ends, key=lambda value: abs(value - target)))
    boundaries.append(source.end_seconds)
    series_id = f"series-{round(source.start_seconds * 10)}-{round(source.end_seconds * 10)}"
    return [
        Candidate(
            title=f"{title} — Part {index + 1}",
            start_seconds=boundaries[index],
            end_seconds=boundaries[index + 1],
            score=round(max(0, score - index * 0.01), 2),
            rationale=rationale,
            series_id=series_id,
            series_index=index + 1,
            series_count=parts,
        )
        for index in range(parts)
    ]


class AIClipRanker:
    """Use Sol to make the editorial decision, with deterministic candidates as fallback."""

    def __init__(self, limit: int, model: str):
        self.limit = limit
        self.model = model

    async def rank(
        self,
        segments: list[TimedText],
        excluded_ranges: list[tuple[float, float]] | None = None,
        taste_profile: str = "",
        concept_memories: list[str] | None = None,
    ) -> list[Candidate]:
        excluded_ranges = excluded_ranges or []
        concept_memories = concept_memories or []
        short_candidates = rank_candidates(
            segments,
            limit=max(self.limit * 3, self.limit),
            excluded_ranges=excluded_ranges,
        )
        shortlist = (
            short_candidates
            + _long_clip_candidates(segments, excluded_ranges)
            + _series_candidates(segments, excluded_ranges)
        )
        if not shortlist or not os.getenv("OPENAI_API_KEY"):
            return short_candidates[: self.limit]

        payload = []
        for index, candidate in enumerate(shortlist):
            transcript = " ".join(
                segment.text
                for segment in segments
                if segment.start_seconds < candidate.end_seconds
                and segment.end_seconds > candidate.start_seconds
            )
            payload.append(
                {
                    "candidate_index": index,
                    "start_seconds": round(candidate.start_seconds, 2),
                    "end_seconds": round(candidate.end_seconds, 2),
                    "series_eligible": candidate.series_eligible,
                    "long_clip_eligible": candidate.long_clip_eligible,
                    "transcript": transcript,
                }
            )

        try:
            response = await AsyncOpenAI().responses.parse(
                model=self.model,
                reasoning={"effort": "low"},
                store=False,
                max_output_tokens=2500,
                text_format=RankedMoments,
                instructions=(
                    "You are a ruthless senior short-form podcast editor. Select the strongest "
                    f"{min(self.limit, len(short_candidates))} clips from the supplied candidates. "
                    "Prioritize a fast hook, one self-contained idea, emotional or practical "
                    "stakes, "
                    "specificity, and a satisfying payoff. Reject intros, sponsors, housekeeping, "
                    "rambling setup, vague fragments, and moments that require missing context. "
                    "Write a crisp editorial title of 4-9 words, not a raw transcript fragment. "
                    "Give a concrete one-sentence rationale and a calibrated 0-1 score. Return "
                    "each candidate at most once and order moments best first. A candidate marked "
                    "series_eligible is a rare exception for an unusually captivating sustained "
                    "idea: select at most one such candidate and set series_parts to 3 or 4 so it "
                    "becomes a sequential series. Never turn an ordinary moment into a series. "
                    "A candidate marked long_clip_eligible is a separate rare exception: it may "
                    "remain one uninterrupted clip over 60 seconds, but never over 120 seconds. "
                    "Select no more than two long clips, and only when the entire sustained arc is "
                    "more captivating than a shorter edit. The series parts count toward the "
                    "requested total. Use series_parts=1 for every normal or long candidate. "
                    "Use the editorial feedback below as preference evidence, not absolute rules. "
                    "Do not repeat the central idea of any prior approved concept, even if the "
                    "new speaker uses different wording.\n\n"
                    f"EDITORIAL FEEDBACK\n{taste_profile or 'No feedback yet.'}\n\n"
                    "PRIOR APPROVED CONCEPTS\n"
                    + ("\n".join(concept_memories[:30]) or "None yet.")
                ),
                input=json.dumps(payload, ensure_ascii=False),
            )
            parsed = response.output_parsed
            if not parsed:
                return short_candidates[: self.limit]
        except Exception as exc:
            logger.warning("AI clip ranking failed; using heuristic fallback: %s", exc)
            return short_candidates[: self.limit]

        chosen: list[Candidate] = []
        seen: set[int] = set()
        series_used = False
        long_clips_used = 0
        long_clip_limit = 1 if self.limit < 10 else 2
        for moment in sorted(parsed.moments, key=lambda item: -item.score):
            if moment.candidate_index in seen or moment.candidate_index >= len(shortlist):
                continue
            source = shortlist[moment.candidate_index]
            if ranges_overlap(
                source.start_seconds,
                source.end_seconds,
                [(item.start_seconds, item.end_seconds) for item in chosen],
            ):
                continue
            seen.add(moment.candidate_index)
            if source.series_eligible:
                if series_used or moment.series_parts == 1:
                    continue
                if len(chosen) + moment.series_parts > self.limit:
                    continue
                chosen.extend(
                    _split_series(
                        source,
                        segments,
                        moment.series_parts,
                        moment.title.strip(),
                        moment.rationale.strip(),
                        moment.score,
                    )
                )
                series_used = True
            else:
                if moment.series_parts != 1:
                    continue
                if source.long_clip_eligible:
                    if long_clips_used >= long_clip_limit:
                        continue
                    long_clips_used += 1
                chosen.append(
                    Candidate(
                        title=moment.title.strip(),
                        start_seconds=source.start_seconds,
                        end_seconds=source.end_seconds,
                        score=round(moment.score, 2),
                        rationale=moment.rationale.strip(),
                    )
                )
            if len(chosen) >= self.limit:
                break

        for index, source in enumerate(short_candidates):
            if len(chosen) >= self.limit:
                break
            if index not in seen and not ranges_overlap(
                source.start_seconds,
                source.end_seconds,
                [(item.start_seconds, item.end_seconds) for item in chosen],
            ):
                chosen.append(source)
        return sorted(chosen[: self.limit], key=lambda candidate: -candidate.score)
