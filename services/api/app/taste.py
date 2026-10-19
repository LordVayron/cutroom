import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from app.domain import Candidate, TimedText

STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "being",
    "but",
    "can",
    "could",
    "did",
    "does",
    "for",
    "from",
    "get",
    "had",
    "has",
    "have",
    "how",
    "into",
    "its",
    "just",
    "like",
    "more",
    "not",
    "now",
    "one",
    "our",
    "out",
    "really",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "was",
    "were",
    "what",
    "when",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}


@dataclass(frozen=True)
class ConceptMemory:
    clip_id: str
    project_title: str
    clip_title: str
    signature: str


@dataclass(frozen=True)
class FeedbackSignal:
    decision: str
    reason: str
    title: str
    detail: str = ""


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9']+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    ]


def concept_signature(title: str, transcript: str = "", limit: int = 18) -> str:
    counts = Counter(_tokens(transcript))
    for token in _tokens(title):
        counts[token] += 4
    ranked = sorted(counts, key=lambda token: (-counts[token], token))[:limit]
    return " ".join(ranked)


def concept_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    overlap = len(left_tokens & right_tokens)
    if overlap < 3 or not left_tokens or not right_tokens:
        return 0.0
    jaccard = overlap / len(left_tokens | right_tokens)
    containment = overlap / min(len(left_tokens), len(right_tokens))
    return round(max(jaccard, containment * 0.86), 3)


def candidate_text(candidate: Candidate, transcript: list[TimedText]) -> str:
    return " ".join(
        segment.text
        for segment in transcript
        if segment.start_seconds < candidate.end_seconds
        and segment.end_seconds > candidate.start_seconds
    )


def filter_duplicate_candidates(
    candidates: list[Candidate],
    transcript: list[TimedText],
    memories: list[ConceptMemory],
    limit: int,
    threshold: float = 0.5,
) -> tuple[list[Candidate], list[tuple[Candidate, ConceptMemory, float]]]:
    accepted: list[Candidate] = []
    rejected: list[tuple[Candidate, ConceptMemory, float]] = []
    for candidate in candidates:
        signature = concept_signature(
            f"{candidate.title} {candidate.rationale}", candidate_text(candidate, transcript)
        )
        match = max(
            (
                (memory, concept_similarity(signature, memory.signature))
                for memory in memories
            ),
            key=lambda item: item[1],
            default=None,
        )
        if match and match[1] >= threshold:
            rejected.append((candidate, match[0], match[1]))
            continue
        accepted.append(candidate)
        if len(accepted) >= limit:
            break
    return accepted, rejected


def taste_context(signals: list[FeedbackSignal]) -> str:
    if not signals:
        return "No explicit editorial feedback has been recorded yet."
    approved = [signal for signal in signals if signal.decision == "approved"]
    rejected = [signal for signal in signals if signal.decision == "rejected"]

    def summary(items: list[FeedbackSignal]) -> str:
        reason_counts = Counter(item.reason for item in items)
        reasons = ", ".join(
            f"{reason} ({count})" for reason, count in reason_counts.most_common(5)
        )
        examples = "; ".join(
            f"{item.title}: {item.detail}" if item.detail else item.title
            for item in items[-5:]
        )
        return f"reasons: {reasons or 'none'}; examples: {examples or 'none'}"

    return f"APPROVED — {summary(approved)}\nREJECTED — {summary(rejected)}"


def learning_digest(context: str, memories: list[ConceptMemory]) -> str:
    memory_text = "|".join(sorted(memory.signature for memory in memories))
    return hashlib.sha256(f"{context}\n{memory_text}".encode()).hexdigest()
