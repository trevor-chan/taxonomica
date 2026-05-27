"""Score title helpers for Taxonomica."""

from __future__ import annotations

import json
import random
from importlib import resources
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from taxonomica.gbif_tree import TaxonomyNode


def load_rank_titles() -> dict[str, Any]:
    """Load packaged rank title data."""
    title_path = resources.files("taxonomica.game.resources").joinpath("rank_titles.json")
    with title_path.open(encoding="utf-8") as title_file:
        return json.load(title_file)


def get_rank_title(score: int, target: TaxonomyNode) -> str | None:
    """Get a rank title based on score and the target species' taxonomy."""
    titles_data = load_rank_titles()
    if not titles_data or "titles" not in titles_data:
        return None

    if score == 0:
        tier_name = "perfect"
    elif score <= 7:
        tier_name = "excellent"
    elif score <= 14:
        tier_name = "good"
    else:
        tier_name = "needs_improvement"

    player_taxa = {"generic"}
    node = target
    while node and node.parent:
        if node.name:
            player_taxa.add(node.name)
        node = node.parent

    specific_matches = []
    generic_matches = []

    for title, info in titles_data["titles"].items():
        if tier_name not in info.get("tiers", []):
            continue

        title_taxa = set(info.get("taxa", []))
        matching_taxa = title_taxa & player_taxa

        if matching_taxa == {"generic"}:
            generic_matches.append(title)
        elif matching_taxa:
            specific_matches.append(title)

    if specific_matches:
        return random.choice(specific_matches)
    if generic_matches:
        return random.choice(generic_matches)

    return None
