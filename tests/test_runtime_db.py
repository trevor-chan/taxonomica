from __future__ import annotations

import gzip
import sqlite3

from build_tree.build_runtime_db import _new_taxon, _populate_common_names
from taxonomica.game.selection import select_playable_species
from taxonomica.runtime_db import RuntimeTaxonomyData


def test_runtime_db_loads_path_keyed_tree_and_selects_species(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)

    data = RuntimeTaxonomyData.from_sqlite(db_path)
    species = data.tree.find_by_id("s-panthera-leo")

    assert species is not None
    assert species.vernacular_names == ["lion"]
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
    assert data.tree.find_by_id("g-panthera").count_descendants() == 5

    result = select_playable_species(data, seed=1, difficulty="easy")

    assert result is not None
    node, description = result
    assert node.name == "Panthera leo"
    assert "large cat" in description


def test_seeded_selection_is_deterministic_within_difficulty(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)
    data = RuntimeTaxonomyData.from_sqlite(db_path)

    first = select_playable_species(data, seed=42, difficulty="hard")
    second = select_playable_species(data, seed=42, difficulty="hard")

    assert first is not None
    assert second is not None
    assert first[0].id == second[0].id
    assert first[1] == second[1]


def test_difficulty_filters_are_inclusive_and_prune_empty_branches(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)

    data = RuntimeTaxonomyData.from_sqlite(db_path)

    easy = data.for_difficulty("easy")
    assert easy.playable_species_count == 1
    assert easy.target_species_count == 1
    assert easy.tree.find_by_id("k-fungi") is None
    assert easy.tree.find_by_id("s-panthera-leo") is not None
    assert easy.tree.find_by_id("s-panthera-pardus") is None

    medium = data.for_difficulty("medium")
    assert medium.playable_species_count == 2
    assert medium.target_species_count == 2
    assert medium.tree.find_by_id("s-panthera-leo") is not None
    assert medium.tree.find_by_id("s-panthera-pardus") is not None
    assert medium.tree.find_by_id("s-panthera-onca") is None

    hard = data.for_difficulty("hard")
    assert hard.playable_species_count == 4
    assert hard.target_species_count == 4
    assert hard.tree.find_by_id("k-fungi") is not None
    assert hard.tree.find_by_id("s-panthera-tigris") is None

    expert = data.for_difficulty("expert")
    assert expert.playable_species_count == 6
    assert expert.target_species_count == 5
    assert expert.tree.find_by_id("s-panthera-short") is not None
    assert "s-panthera-short" not in expert.target_species_keys


def test_runtime_descriptions_include_parent_info_when_available(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(db_path)

    data = RuntimeTaxonomyData.from_sqlite(db_path)

    assert data.match_taxon_key("g-panthera").title == "Panthera"
    assert data.match_taxon_key("f-felidae") is None
    assert data.playable_species_count == 6
    assert data.target_species_count == 5


def test_default_runtime_can_load_compressed_database_in_memory(tmp_path):
    source_db_path = tmp_path / "runtime.sqlite"
    _write_runtime_fixture(source_db_path)

    game_dir = tmp_path / "assets" / "game"
    game_dir.mkdir(parents=True)
    compressed_db_path = game_dir / "taxonomica-runtime-20260101.sqlite.gz"
    database_bytes = bytearray(source_db_path.read_bytes())
    database_bytes[18] = 2
    database_bytes[19] = 2
    with gzip.open(compressed_db_path, "wb") as target:
        target.write(database_bytes)
    source_db_path.unlink()

    data = RuntimeTaxonomyData.from_default(tmp_path, in_memory=True)

    assert data.db_path == compressed_db_path
    assert data.tree.find_by_id("s-panthera-leo") is not None
    assert data.target_species_count == 5
    assert not (tmp_path / "assets" / "generated" / "runtime").exists()


def test_runtime_build_adds_manual_common_name_for_actinopterygii(tmp_path):
    taxa = {
        "c-actinopterygii": _new_taxon(
            "c-actinopterygii",
            "class",
            "Actinopterygii",
        )
    }

    common_name_count = _populate_common_names(
        gbif_backbone=tmp_path / "missing-gbif-backbone",
        taxa=taxa,
        taxon_gbif_ids={},
    )

    assert common_name_count == 1
    assert taxa["c-actinopterygii"]["common_name"] == "Ray-finned Fishes"


def test_runtime_build_keeps_existing_common_name_for_actinopterygii(tmp_path):
    taxa = {
        "c-actinopterygii": _new_taxon(
            "c-actinopterygii",
            "class",
            "Actinopterygii",
        )
    }
    taxa["c-actinopterygii"]["common_name"] = "Existing name"

    common_name_count = _populate_common_names(
        gbif_backbone=tmp_path / "missing-gbif-backbone",
        taxa=taxa,
        taxon_gbif_ids={},
    )

    assert common_name_count == 0
    assert taxa["c-actinopterygii"]["common_name"] == "Existing name"


def _write_runtime_fixture(db_path):
    descriptions = {
        "s-panthera-leo": _pad_description("The lion is a large cat.", 10_050),
        "s-panthera-pardus": _pad_description("The leopard is a spotted cat.", 2_050),
        "s-panthera-onca": _pad_description("The jaguar is a powerful cat.", 850),
        "s-panthera-tigris": _pad_description("The tiger is a striped cat.", 450),
        "s-agaricus-testus": _pad_description("This mushroom has a cap and gills.", 850),
    }
    parent_description = "Panthera is a genus of cats that includes several large species."
    taxa = [
        _taxon("k-animalia", "kingdom", "Animalia", "", "", 0, 5, 1, 2, 3, 4),
        _taxon("p-chordata", "phylum", "Chordata", "", "", 0, 5, 1, 2, 3, 4),
        _taxon("c-mammalia", "class", "Mammalia", "", "", 0, 5, 1, 2, 3, 4),
        _taxon("o-carnivora", "order", "Carnivora", "", "", 0, 5, 1, 2, 3, 4),
        _taxon("f-felidae", "family", "Felidae", "", "", 0, 5, 1, 2, 3, 4),
        _taxon("g-panthera", "genus", "Panthera", "", "", 0, 5, 1, 2, 3, 4),
        _taxon("s-panthera-leo", "species", "Panthera leo", "lion", "easy", 10050, 1, 1, 1, 1, 1),
        _taxon(
            "s-panthera-pardus",
            "species",
            "Panthera pardus",
            "leopard",
            "medium",
            2050,
            1,
            0,
            1,
            1,
            1,
        ),
        _taxon("s-panthera-onca", "species", "Panthera onca", "jaguar", "hard", 850, 1, 0, 0, 1, 1),
        _taxon(
            "s-panthera-tigris",
            "species",
            "Panthera tigris",
            "tiger",
            "expert",
            450,
            1,
            0,
            0,
            0,
            1,
        ),
        _taxon("s-panthera-short", "species", "Panthera brevis", "", "", 100, 1, 0, 0, 0, 0),
        _taxon("k-fungi", "kingdom", "Fungi", "", "", 0, 1, 0, 0, 1, 1),
        _taxon("p-basidiomycota", "phylum", "Basidiomycota", "", "", 0, 1, 0, 0, 1, 1),
        _taxon("c-agaricomycetes", "class", "Agaricomycetes", "", "", 0, 1, 0, 0, 1, 1),
        _taxon("o-agaricales", "order", "Agaricales", "", "", 0, 1, 0, 0, 1, 1),
        _taxon("f-agaricaceae", "family", "Agaricaceae", "", "", 0, 1, 0, 0, 1, 1),
        _taxon("g-agaricus", "genus", "Agaricus", "", "", 0, 1, 0, 0, 1, 1),
        _taxon(
            "s-agaricus-testus",
            "species",
            "Agaricus testus",
            "test mushroom",
            "hard",
            850,
            1,
            0,
            0,
            1,
            1,
        ),
    ]
    edges = [
        ("0", "k-animalia", 5),
        ("k-animalia", "p-chordata", 5),
        ("p-chordata", "c-mammalia", 5),
        ("c-mammalia", "o-carnivora", 5),
        ("o-carnivora", "f-felidae", 5),
        ("f-felidae", "g-panthera", 5),
        ("g-panthera", "s-panthera-leo", 1),
        ("g-panthera", "s-panthera-pardus", 1),
        ("g-panthera", "s-panthera-onca", 1),
        ("g-panthera", "s-panthera-tigris", 1),
        ("g-panthera", "s-panthera-short", 1),
        ("0", "k-fungi", 1),
        ("k-fungi", "p-basidiomycota", 1),
        ("p-basidiomycota", "c-agaricomycetes", 1),
        ("c-agaricomycetes", "o-agaricales", 1),
        ("o-agaricales", "f-agaricaceae", 1),
        ("f-agaricaceae", "g-agaricus", 1),
        ("g-agaricus", "s-agaricus-testus", 1),
    ]
    description_rows = [
        _description_row("g-panthera", "Panthera", parent_description),
        *[
            _description_row(taxon_key, taxon_key.removeprefix("s-"), description)
            for taxon_key, description in descriptions.items()
        ],
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE runtime_taxa (
                taxon_key TEXT PRIMARY KEY,
                rank TEXT NOT NULL,
                scientific_name TEXT NOT NULL,
                common_name TEXT NOT NULL DEFAULT '',
                difficulty_level TEXT NOT NULL DEFAULT '',
                description_length INTEGER NOT NULL DEFAULT 0,
                article_length INTEGER NOT NULL DEFAULT 0,
                pageview_count INTEGER NOT NULL DEFAULT 0,
                difficulty_score REAL NOT NULL DEFAULT 0,
                pageview_score REAL NOT NULL DEFAULT 0,
                article_score REAL NOT NULL DEFAULT 0,
                vernacular_score REAL NOT NULL DEFAULT 0,
                category_score REAL NOT NULL DEFAULT 0,
                category_modifier INTEGER NOT NULL DEFAULT 0,
                target_rank INTEGER NOT NULL DEFAULT 0,
                tree_rank INTEGER NOT NULL DEFAULT 0,
                playable_species_count INTEGER NOT NULL,
                tree_species_count INTEGER NOT NULL,
                easy_species_count INTEGER NOT NULL,
                medium_species_count INTEGER NOT NULL,
                hard_species_count INTEGER NOT NULL,
                expert_target_species_count INTEGER NOT NULL
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
                difficulty_level,
                description_length,
                playable_species_count,
                tree_species_count,
                easy_species_count,
                medium_species_count,
                hard_species_count,
                expert_target_species_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            description_rows,
        )


def _taxon(
    taxon_key,
    rank,
    scientific_name,
    common_name,
    difficulty_level,
    description_length,
    tree_species_count,
    easy_species_count,
    medium_species_count,
    hard_species_count,
    expert_target_species_count,
):
    return (
        taxon_key,
        rank,
        scientific_name,
        common_name,
        difficulty_level,
        description_length,
        tree_species_count,
        tree_species_count,
        easy_species_count,
        medium_species_count,
        hard_species_count,
        expert_target_species_count,
    )


def _description_row(taxon_key, title, description):
    return (
        taxon_key,
        title,
        description,
        len(description.split()),
        len(description),
        0,
        0,
        0,
    )


def _pad_description(text, minimum_length):
    while len(text) <= minimum_length:
        text += " detail"
    return text
