from app.domain import Candidate, TimedText
from app.taste import (
    ConceptMemory,
    FeedbackSignal,
    concept_signature,
    concept_similarity,
    filter_duplicate_candidates,
    learning_digest,
    taste_context,
)


def _candidate(title: str, text: str, start: float = 0) -> tuple[Candidate, TimedText]:
    candidate = Candidate(title, start, start + 20, 0.9, "A specific complete idea.")
    return candidate, TimedText(start, start + 20, text)


def test_concept_similarity_requires_meaningful_overlap() -> None:
    first = concept_signature(
        "Why chip manufacturing depends on Taiwan",
        "Semiconductor supply chains rely on Taiwanese fabrication plants.",
    )
    repeated = concept_signature(
        "The hidden Taiwan chip dependency",
        "Global semiconductor supply depends on Taiwan fabrication capacity.",
    )
    unrelated = concept_signature(
        "Parents need better AI assistants",
        "Family calendars and local activities make personal agents useful.",
    )

    assert concept_similarity(first, repeated) >= 0.5
    assert concept_similarity(first, unrelated) == 0


def test_duplicate_filter_uses_cross_project_memory() -> None:
    repeated, repeated_text = _candidate(
        "Taiwan's chip dependency",
        "The semiconductor supply chain depends on Taiwan fabrication plants.",
    )
    fresh, fresh_text = _candidate(
        "Why parents want AI agents",
        "Parents use personal agents for school calendars and family activities.",
        30,
    )
    memory = ConceptMemory(
        clip_id="old",
        project_title="Earlier podcast",
        clip_title="Why chip manufacturing depends on Taiwan",
        signature=concept_signature(
            "Why chip manufacturing depends on Taiwan",
            "Semiconductor supply chains rely on Taiwan fabrication plants.",
        ),
    )

    accepted, rejected = filter_duplicate_candidates(
        [repeated, fresh], [repeated_text, fresh_text], [memory], 2
    )

    assert accepted == [fresh]
    assert rejected[0][0] == repeated
    assert rejected[0][1] == memory


def test_feedback_changes_learning_digest() -> None:
    empty = taste_context([])
    learned = taste_context(
        [FeedbackSignal("rejected", "too_generic", "Vague advice", "Needs specifics")]
    )

    assert "too_generic" in learned
    assert learning_digest(empty, []) != learning_digest(learned, [])
