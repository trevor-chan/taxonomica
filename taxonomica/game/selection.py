"""Species selection helpers for playable Taxonomica rounds."""

from __future__ import annotations

import hashlib
import random

from taxonomica.runtime_db import RuntimeTaxonomyData
from taxonomica.taxonomy import TaxonNode


def select_playable_species(
    data: RuntimeTaxonomyData,
    seed: int | None = None,
    difficulty: str | None = None,
) -> tuple[TaxonNode, str] | None:
    """Select a playable species from the runtime database.

    Difficulty is intentionally ignored until the new runtime tree has ratings.
    """
    _ = difficulty
    species_nodes = [
        node
        for node in data.playable_species_nodes
        if node.has_complete_path() and data.match_taxon_key(node.id)
    ]

    print(f"  Found {len(species_nodes):,} eligible species")

    if not species_nodes:
        return None

    species_nodes.sort(key=lambda node: node.id)
    rng = random.Random(seed) if seed is not None else random.Random()
    rng.shuffle(species_nodes)

    node = species_nodes[0]
    description = data.match_taxon_key(node.id)
    if description:
        return node, description.description

    return None


def get_seed_from_string(seed_string: str) -> int:
    """Convert any seed string to a deterministic integer seed."""
    hash_bytes = hashlib.sha256(seed_string.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big")
