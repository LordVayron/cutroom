import re
from dataclasses import dataclass
from html import unescape


class InvalidTransition(ValueError):
    pass


PROJECT_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"ingesting", "scoring", "failed"},
    "ingesting": {"transcribing", "failed"},
    "transcribing": {"scoring", "failed"},
    "scoring": {"ready", "failed"},
    "ready": {"rendering", "scoring", "failed"},
    "rendering": {"review", "ready", "failed"},
    "review": {"approved", "rendering", "scoring", "failed"},
    "approved": {"rendering", "scoring"},
    "failed": {"queued", "ready"},
}


def require_transition(current: str, target: str) -> None:
    if target not in PROJECT_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"Project cannot move from {current!r} to {target!r}")


def project_status_after_clip_approval(current: str) -> str:
    """Approve a completed clip without interrupting other active renders."""
    if current == "rendering":
        return current
    if current != "approved":
        require_transition(current, "approved")
    return "approved"


@dataclass(frozen=True)
class TimedWord:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class TimedText:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[TimedWord, ...] = ()


def clean_caption_text(text: str) -> str:
    """Remove caption-provider control marks without changing spoken punctuation."""
    cleaned = unescape(text).replace("\u200b", "").replace("\ufeff", "")
    cleaned = re.sub(r"(?:^|\s)>>+(?=\s|$)", " ", cleaned)
    cleaned = cleaned.replace("♪", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class Candidate:
    title: str
    start_seconds: float
    end_seconds: float
    score: float
    rationale: str
    series_id: str | None = None
    series_index: int | None = None
    series_count: int | None = None
    series_eligible: bool = False
    long_clip_eligible: bool = False


STANDARD_CLIP_MAX_SECONDS = 55
MAX_CLIP_SECONDS = 120


HOOK_WORDS = {
    "actually",
    "because",
    "but",
    "change",
    "changed",
    "difference",
    "exactly",
    "first",
    "hardest",
    "how",
    "important",
    "learned",
    "mistake",
    "never",
    "problem",
    "realized",
    "reason",
    "secret",
    "surprise",
    "truth",
    "what",
    "why",
    "without",
}

PROMO_PHRASES = {
    "brought to you",
    "check out",
    "discount code",
    "follow us",
    "promo code",
    "show notes",
    "subscribe",
    "today's sponsor",
}

STRONG_PHRASES = {
    "changed my life",
    "here's the thing",
    "i learned",
    "i realized",
    "most people",
    "the problem is",
    "the reason",
    "the truth is",
    "what happens",
    "you have to",
}


def _title_for(text: str, start: float) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if not sentences:
        return f"Moment at {int(start)}s"

    def sentence_value(sentence: str) -> tuple[int, int]:
        words = [word.strip(".,!?—:;\"'").lower() for word in sentence.split()]
        signals = len(set(words) & HOOK_WORDS) + int("?" in sentence) + int("!" in sentence)
        useful_length = int(6 <= len(words) <= 20)
        return signals + useful_length, -abs(12 - len(words))

    sentence = max(sentences, key=sentence_value)
    words = sentence.replace("?", "").replace("!", "").split()
    title = " ".join(words[:10]).strip(".,:;—\"'")
    return title or f"Moment at {int(start)}s"


def ranges_overlap(
    start: float, end: float, ranges: list[tuple[float, float]], padding: float = 0
) -> bool:
    return any(
        start < range_end + padding and end > range_start - padding
        for range_start, range_end in ranges
    )


def rank_candidates(
    segments: list[TimedText],
    limit: int = 10,
    excluded_ranges: list[tuple[float, float]] | None = None,
) -> list[Candidate]:
    """Rank non-overlapping transcript windows with a deterministic, explainable heuristic."""
    if not segments:
        return []

    scored: list[Candidate] = []
    excluded_ranges = excluded_ranges or []
    for index, _segment in enumerate(segments):
        window = segments[index : index + 4]
        start = window[0].start_seconds
        end = min(window[-1].end_seconds, start + STANDARD_CLIP_MAX_SECONDS)
        if end - start < 18:
            continue
        if ranges_overlap(start, end, excluded_ranges, padding=3):
            continue
        text = " ".join(item.text for item in window)
        normalized = re.sub(r"\s+", " ", text).strip()
        lowered = normalized.lower()
        word_list = [word.strip(".,!?—:;\"'").lower() for word in normalized.split()]
        words = set(word_list)
        if len(word_list) < 16:
            continue
        hook_hits = len(words & HOOK_WORDS)
        strong_hits = sum(phrase in lowered for phrase in STRONG_PHRASES)
        promo_hits = sum(phrase in lowered for phrase in PROMO_PHRASES)
        punctuation = int("?" in normalized) + int("!" in normalized)
        duration = end - start
        words_per_second = len(word_list) / duration
        pace_score = max(0.0, 1 - abs(words_per_second - 2.3) / 2.3)
        diversity = len(words) / len(word_list)
        score = (
            0.35
            + min(hook_hits, 6) * 0.035
            + min(strong_hits, 3) * 0.055
            + min(punctuation, 2) * 0.035
            + int(any(character.isdigit() for character in normalized)) * 0.025
            + int(normalized.rstrip().endswith((".", "?", "!"))) * 0.035
            + pace_score * 0.07
            + diversity * 0.08
            - promo_hits * 0.32
        )
        score = round(max(0.05, min(0.97, score)), 2)
        signals = []
        if "?" in normalized:
            signals.append("question-led")
        if strong_hits:
            signals.append(f"{strong_hits} strong phrase{'s' if strong_hits != 1 else ''}")
        if hook_hits:
            signals.append(f"{hook_hits} hook term{'s' if hook_hits != 1 else ''}")
        if normalized.rstrip().endswith((".", "?", "!")):
            signals.append("complete thought")
        rationale = "; ".join(signals[:3]) or "clear, self-contained passage"
        title = _title_for(normalized, start)
        scored.append(Candidate(title, start, end, score, rationale))

    selected: list[Candidate] = []
    for candidate in sorted(scored, key=lambda item: (-item.score, item.start_seconds)):
        overlaps = any(
            candidate.start_seconds < existing.end_seconds
            and candidate.end_seconds > existing.start_seconds
            for existing in selected
        )
        if not overlaps:
            selected.append(candidate)
        if len(selected) == limit:
            break

    return sorted(selected, key=lambda item: (-item.score, item.start_seconds))
