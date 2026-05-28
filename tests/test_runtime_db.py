from __future__ import annotations

import sqlite3

from taxonomica.game.selection import find_species_with_wikipedia
from taxonomica.runtime_db import RuntimeTaxonomyData


def test_runtime_db_loads_tree_and_selects_species(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)

    data = RuntimeTaxonomyData.from_sqlite(db_path)

    assert data.tree.root.children
    assert data.match_gbif_taxon("Panthera leo").title == "Lion"

    result = find_species_with_wikipedia(
        data.tree,
        data,
        data.popularity_index,
        difficulty="easy",
        seed=1,
        max_attempts=10,
    )

    assert result is not None
    node, description = result
    assert node.name == "Panthera leo"
    assert "large cat" in description


def _write_runtime_fixture(db_path):
    description = "\n".join(
        f"The lion is a large cat in a social pride with a detailed clue line {i}."
        for i in range(13)
    )
    taxa = [
        ("k-animalia", "kingdom", "Animalia", "", 1),
        ("p-chordata", "phylum", "Chordata", "", 1),
        ("c-mammalia", "class", "Mammalia", "", 1),
        ("o-carnivora", "order", "Carnivora", "", 1),
        ("f-felidae", "family", "Felidae", "", 1),
        ("g-panthera", "genus", "Panthera", "", 1),
        ("s-panthera-leo", "species", "Panthera leo", "lion", 1),
    ]
    edges = [
        ("0", "k-animalia", 1),
        ("k-animalia", "p-chordata", 1),
        ("p-chordata", "c-mammalia", 1),
        ("c-mammalia", "o-carnivora", 1),
        ("o-carnivora", "f-felidae", 1),
        ("f-felidae", "g-panthera", 1),
        ("g-panthera", "s-panthera-leo", 1),
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE runtime_taxa (
                taxon_key TEXT PRIMARY KEY,
                rank TEXT NOT NULL,
                scientific_name TEXT NOT NULL,
                common_name TEXT NOT NULL DEFAULT '',
                playable_species_count INTEGER NOT NULL
            );

            CREATE TABLE runtime_edges (
                parent_key TEXT NOT NULL,
                child_key TEXT NOT NULL,
                playable_species_count INTEGER NOT NULL,
                PRIMARY KEY (parent_key, child_key)
            );

            CREATE TABLE runtime_descriptions (
                taxon_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                description_length INTEGER NOT NULL,
                section_count INTEGER NOT NULL,
                multimedia_count INTEGER NOT NULL,
                pageview_count INTEGER NOT NULL,
                backlink_count INTEGER NOT NULL,
                difficulty_score REAL NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO runtime_taxa (
                taxon_key,
                rank,
                scientific_name,
                common_name,
                playable_species_count
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            taxa,
        )
        conn.executemany(
            """
            INSERT INTO runtime_edges (
                parent_key,
                child_key,
                playable_species_count
            )
            VALUES (?, ?, ?)
            """,
            edges,
        )
        conn.execute(
            """
            INSERT INTO runtime_descriptions (
                taxon_key,
                title,
                description,
                word_count,
                description_length,
                section_count,
                multimedia_count,
                pageview_count,
                backlink_count,
                difficulty_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s-panthera-leo",
                "Lion",
                description,
                len(description.split()),
                len(description),
                2,
                5,
                0,
                0,
                60.0,
            ),
        )
