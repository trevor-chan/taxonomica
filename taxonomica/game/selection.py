"""Species selection helpers for playable Taxonomica rounds."""

from __future__ import annotations

import hashlib
import random

from taxonomica.game.text import split_into_lines
from taxonomica.gbif_tree import GBIFTaxonomyTree, TaxonomyNode
from taxonomica.popularity import PopularityIndex
from taxonomica.wikipedia import WikipediaData


DIFFICULTY_THRESHOLDS = {
    "easy": 55,
    "medium": 49,
    "hard": 24,
    "expert": 0,
}


def find_species_with_wikipedia(
    tree: GBIFTaxonomyTree,
    wiki: WikipediaData,
    popularity_index: PopularityIndex | None = None,
    difficulty: str = "expert",
    seed: int | None = None,
    max_attempts: int = 200,
) -> tuple[TaxonomyNode, str] | None:
    """Find a random species that has a substantive Wikipedia description."""
    min_score = DIFFICULTY_THRESHOLDS.get(difficulty, 0)

    candidate_names: set[str] | None = None
    if difficulty != "expert" and popularity_index and min_score > 0:
        candidate_names = {
            metrics.scientific_name.lower()
            for metrics in popularity_index._by_id.values()
            if metrics.popularity_score >= min_score and metrics.section_count >= 2
        }

    species_nodes = []
    for node in tree._nodes_by_id.values():
        if node.rank != "species" or not node.has_complete_path():
            continue
        if candidate_names is not None and node.name.lower() not in candidate_names:
            continue
        species_nodes.append(node)

    print(f"  Found {len(species_nodes):,} eligible species")

    if not species_nodes:
        return None

    species_nodes.sort(key=lambda node: node.id)
    rng = random.Random(seed) if seed is not None else random.Random()
    rng.shuffle(species_nodes)

    for attempts, node in enumerate(species_nodes[:max_attempts], start=1):
        if attempts % 100 == 0:
            print("    Searching...")

        match_taxon_key = getattr(wiki, "match_taxon_key", None)
        if match_taxon_key:
            wiki_species = match_taxon_key(node.id)
        else:
            wiki_species = wiki.match_gbif_taxon(node.name)
        if not wiki_species:
            continue

        full_text = wiki_species.get_useful_text()
        if full_text and len(full_text) > 400 and len(split_into_lines(full_text)) >= 12:
            return node, full_text

    return None


def get_seed_from_string(seed_string: str) -> int:
    """Convert any seed string to a deterministic integer seed."""
    hash_bytes = hashlib.sha256(seed_string.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big")
