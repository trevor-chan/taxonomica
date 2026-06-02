"""Difficulty tiers for runtime target selection and tree pruning."""

from __future__ import annotations

DIFFICULTY_LEVELS = ("easy", "medium", "hard", "expert")

DIFFICULTY_SCORE_WEIGHTS = {
    "pageviews": 0.50,
    "article_length": 0.15,
    "vernacular": 0.10,
    "category": 0.25,
}

TARGET_RANK_CUTOFFS = {
    "easy": 500,
    "medium": 4_000,
    "hard": 20_000,
    "expert": 40_000,
}

TREE_RANK_CUTOFFS = {
    "easy": 4_000,
    "medium": 20_000,
    "hard": 40_000,
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

CATEGORY_MODIFIERS = {
    2: {
        "Chordata",
        "Animalia",
    },
    1: {
        "Mammalia",
        "Canidae",
        "Cetacea",
        "Felidae",
        "Primates",
    },
    -1: {
        "Plantae",
        "Aves",
    },
    -2: {
        "Archaea",
        "Bacteria",
        "Viruses",
        "Lepidoptera",
        "Chromista",
        "Protozoa",
        "Fungi",
    },
}

CATEGORY_NORMALIZATION_LIMIT = 4


def normalize_difficulty(difficulty: str | None) -> str:
    """Return a known difficulty level, defaulting to expert."""
    if difficulty in DIFFICULTY_LEVELS:
        return difficulty
    return "expert"


def difficulty_for_target_rank(target_rank: int) -> str:
    """Return the inclusive difficulty tier for a scored target rank."""
    if target_rank <= 0:
        return ""
    for difficulty in DIFFICULTY_LEVELS:
        if target_rank <= TARGET_RANK_CUTOFFS[difficulty]:
            return difficulty
    return ""


def category_modifier_for_path(path_names: list[str]) -> int:
    """Return the cumulative category modifier for a species path."""
    modifiers_by_name = {
        name: modifier
        for modifier, names in CATEGORY_MODIFIERS.items()
        for name in names
    }
    return sum(modifiers_by_name.get(name, 0) for name in path_names)


def normalized_category_score(category_modifier: int) -> float:
    """Convert a cumulative category modifier into a 0..1 easiness score."""
    limited = max(
        -CATEGORY_NORMALIZATION_LIMIT,
        min(CATEGORY_NORMALIZATION_LIMIT, category_modifier),
    )
    return (limited + CATEGORY_NORMALIZATION_LIMIT) / (CATEGORY_NORMALIZATION_LIMIT * 2)


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
