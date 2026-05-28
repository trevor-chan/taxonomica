from __future__ import annotations

import sqlite3

from taxonomica.game.selection import select_playable_species
from taxonomica.runtime_db import RuntimeTaxonomyData


def test_runtime_db_loads_path_keyed_tree_and_selects_species(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)

    data = RuntimeTaxonomyData.from_sqlite(db_path)
    species = data.tree.find_by_id("s-panthera-leo")

    assert species is not None
    assert species.has_complete_path()
    assert [node.rank for node in reversed(species.get_path_to_root())][1:] == [
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "species",
    ]
    assert data.tree.find_by_id("g-panthera").count_descendants() == 1

    result = select_playable_species(data, seed=1, difficulty="easy")

    assert result is not None
    node, description = result
    assert node.name == "Panthera leo"
    assert "large cat" in description


def test_seeded_selection_is_deterministic_and_ignores_difficulty(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)
    data = RuntimeTaxonomyData.from_sqlite(db_path)

    easy = select_playable_species(data, seed=42, difficulty="easy")
    expert = select_playable_species(data, seed=42, difficulty="expert")

    assert easy is not None
    assert expert is not None
    assert easy[0].id == expert[0].id
    assert easy[1] == expert[1]


def test_runtime_descriptions_include_parent_info_when_available(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)

    data = RuntimeTaxonomyData.from_sqlite(db_path)

    assert data.match_taxon_key("g-panthera").title == "Panthera"
    assert data.match_taxon_key("f-felidae") is None
    assert data.playable_species_count == 1


def _write_runtime_fixture(db_path):
    species_description = "\n".join(
        f"The lion is a large cat in a social pride with a detailed clue line {i}."
        for i in range(13)
    )
    parent_description = "Panthera is a genus of cats that includes several large species."
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
    descriptions = [
        (
            "g-panthera",
            "Panthera",
            parent_description,
            len(parent_description.split()),
            len(parent_description),
            0,
            0,
            0,
        ),
        (
            "s-panthera-leo",
            "Lion",
            species_description,
            len(species_description.split()),
            len(species_description),
            5,
            0,
            0,
        ),
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
                multimedia_count INTEGER NOT NULL,
                pageview_count INTEGER NOT NULL,
                backlink_count INTEGER NOT NULL
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
        conn.executemany(
            """
            INSERT INTO runtime_descriptions (
                taxon_key,
                title,
                description,
                word_count,
                description_length,
                multimedia_count,
                pageview_count,
                backlink_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            descriptions,
        )
