"""Difficulty tiers for runtime target selection and tree pruning."""

from __future__ import annotations

DIFFICULTY_LEVELS = ("easy", "medium", "hard", "expert")

DIFFICULTY_THRESHOLDS = {
    "easy": 6_000,
    "medium": 3_000,
    "hard": 800,
    "expert": 400,
}

TREE_COUNT_FIELD_BY_DIFFICULTY = {
    "easy": "easy_species_count",
    "medium": "medium_species_count",
    "hard": "hard_species_count",
    "expert": "tree_species_count",
}

TARGET_COUNT_FIELD_BY_DIFFICULTY = {
    "easy": "easy_species_count",
    "medium": "medium_species_count",
    "hard": "hard_species_count",
    "expert": "expert_target_species_count",
}

TARGET_DIFFICULTIES_BY_MODE = {
    "easy": {"easy"},
    "medium": {"easy", "medium"},
    "hard": {"easy", "medium", "hard"},
    "expert": {"easy", "medium", "hard", "expert"},
}


def normalize_difficulty(difficulty: str | None) -> str:
    """Return a known difficulty level, defaulting to expert."""
    if difficulty in DIFFICULTY_LEVELS:
        return difficulty
    return "expert"


def assign_difficulty(article_length: int, *, expert_threshold: int = 400) -> str:
    """Assign a target difficulty from a species article-length metric.

    Thresholds are intentionally strict: a species must exceed the cutoff to
    enter a tier.
    """
    if article_length > DIFFICULTY_THRESHOLDS["easy"]:
        return "easy"
    if article_length > DIFFICULTY_THRESHOLDS["medium"]:
        return "medium"
    if article_length > DIFFICULTY_THRESHOLDS["hard"]:
        return "hard"
    if article_length > expert_threshold:
        return "expert"
    return ""


def target_allowed_for_difficulty(target_difficulty: str, difficulty: str | None) -> bool:
    """Return whether a target tier is selectable in a game difficulty."""
    normalized = normalize_difficulty(difficulty)
    return target_difficulty in TARGET_DIFFICULTIES_BY_MODE[normalized]


def tree_count_field_for_difficulty(difficulty: str | None) -> str:
    """Return the node count field used for the visible tree in a mode."""
    return TREE_COUNT_FIELD_BY_DIFFICULTY[normalize_difficulty(difficulty)]


def target_count_field_for_difficulty(difficulty: str | None) -> str:
    """Return the node count field used for target selection in a mode."""
    return TARGET_COUNT_FIELD_BY_DIFFICULTY[normalize_difficulty(difficulty)]
