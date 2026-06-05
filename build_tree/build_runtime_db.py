#!/usr/bin/env python3
"""Build a slim playable runtime database from the assembled description DB."""
# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import shutil
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from taxonomica.difficulty import (
    DIFFICULTY_SCORE_WEIGHTS,
    TARGET_RANK_CUTOFFS,
    TREE_RANK_CUTOFFS,
    category_modifier_for_path,
    difficulty_for_target_rank,
    normalized_category_score,
)

DEFAULT_DUMP_DATE = "20260501"
DEFAULT_ASSEMBLED_DB = (
    REPO_ROOT / "assets" / "generated" / "assembled" / f"taxonomica-{DEFAULT_DUMP_DATE}.sqlite"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "assets"
    / "generated"
    / "runtime"
    / f"taxonomica-runtime-{DEFAULT_DUMP_DATE}.sqlite"
)
DEFAULT_COMPRESSED_OUTPUT = (
    REPO_ROOT / "assets" / "game" / f"taxonomica-runtime-{DEFAULT_DUMP_DATE}.sqlite.gz"
)
DEFAULT_GBIF_BACKBONE = REPO_ROOT / "assets" / "raw" / "gbif-backbone"
MAJOR_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
COMMON_NAME_LANGUAGES = {"en", "eng"}
COMMON_NAME_COUNTRY_PRIORITY = {"US": 5, "GB": 4, "CA": 3, "AU": 3, "NZ": 3, "": 2}
COMMON_NAME_CATEGORY_TERMS = {
    "carnivore",
    "carnivores",
    "cultivated plant",
    "domestic animal",
    "domesticated animal",
    "herbivore",
    "herbivores",
    "host",
    "hosts",
    "introduced species",
    "invasive species",
    "omnivore",
    "omnivores",
    "parasite",
    "parasites",
    "pest",
    "pests",
    "predator",
    "predators",
    "prey",
    "weed",
    "weeds",
}
MANUAL_COMMON_NAMES = {
    ("class", "Actinopterygii"): "Ray-finned Fishes",
}

csv.field_size_limit(sys.maxsize)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assembled-db",
        type=Path,
        default=DEFAULT_ASSEMBLED_DB,
        help="Assembled description SQLite database",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Uncompressed runtime SQLite output path",
    )
    parser.add_argument(
        "--compressed-output",
        type=Path,
        default=DEFAULT_COMPRESSED_OUTPUT,
        help="Compressed runtime SQLite asset path",
    )
    parser.add_argument(
        "--dump-date",
        default=DEFAULT_DUMP_DATE,
        help="Wikipedia dump date recorded in runtime metadata",
    )
    parser.add_argument(
        "--gbif-backbone",
        type=Path,
        default=DEFAULT_GBIF_BACKBONE,
        help="GBIF Backbone directory used to add common names",
    )
    parser.add_argument(
        "--min-description-length",
        type=int,
        default=400,
        help="Expert target cutoff; target descriptions must be longer than this many chars",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing runtime outputs",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Skip writing the compressed assets/game copy",
    )
    return parser


def build_runtime_db(
    *,
    assembled_db: Path,
    output: Path,
    gbif_backbone: Path,
    dump_date: str,
    min_description_length: int,
    force: bool,
) -> dict[str, int | str]:
    """Build the uncompressed runtime database and return summary stats."""
    if not assembled_db.exists():
        raise FileNotFoundError(assembled_db)
    if output.exists():
        if not force:
            raise FileExistsError(f"{output} already exists; pass --force to rebuild")
        output.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = output.with_name(f"{output.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()

    output.parent.mkdir(parents=True, exist_ok=True)
    taxa: dict[str, dict[str, object]] = {}
    edges: dict[tuple[str, str], int] = {}
    parents: dict[str, str] = {}
    descriptions: dict[str, tuple[object, ...]] = {}
    taxon_gbif_ids: dict[str, str] = {}
    eligible_target_keys: set[str] = set()
    skipped_bad_paths = 0

    with sqlite3.connect(assembled_db) as source:
        source.row_factory = sqlite3.Row
        species_rows = source.execute(
            """
            SELECT
                t.target_key,
                t.scientific_name,
                t.gbif_id,
                COALESCE(t.pageview_count, 0) AS pageview_count,
                t.path_json
            FROM taxon_targets t
            WHERE t.kind = 'species'
              AND t.rank = 'species'
            ORDER BY t.target_key
            """
        )

        for row in species_rows:
            path = json.loads(row["path_json"])
            if len(path) != len(MAJOR_RANKS) or any(not name for name in path):
                skipped_bad_paths += 1
                continue

            parent_key = "0"
            path_pairs: list[tuple[str, str]] = []
            for rank, name in zip(MAJOR_RANKS, path, strict=True):
                path_pairs.append((rank, name))
                taxon_key = row["target_key"] if rank == "species" else _taxon_key(path_pairs)
                taxon = taxa.setdefault(taxon_key, _new_taxon(taxon_key, rank, name))
                taxon["tree_species_count"] = int(taxon["tree_species_count"]) + 1
                taxon["playable_species_count"] = int(taxon["tree_species_count"])
                edges[(parent_key, taxon_key)] = edges.get((parent_key, taxon_key), 0) + 1
                parents.setdefault(taxon_key, parent_key)
                parent_key = taxon_key

            species_taxon = taxa[row["target_key"]]
            species_taxon["pageview_count"] = int(row["pageview_count"] or 0)
            species_taxon["category_modifier"] = category_modifier_for_path(path)
            if row["gbif_id"]:
                taxon_gbif_ids[row["target_key"]] = row["gbif_id"]

        description_rows = source.execute(
            """
            SELECT
                t.target_key,
                t.primary_title,
                t.matched_title,
                d.word_count,
                d.multimedia_count,
                COALESCE(p.pageview_count, t.pageview_count, 0) AS pageview_count,
                COALESCE(p.backlink_count, t.backlink_count, 0) AS backlink_count,
                p.raw_lead_wikitext,
                p.description
            FROM taxon_targets t
            JOIN taxon_descriptions d ON d.target_key = t.target_key
            JOIN wikipedia_pages p ON p.title = d.resolved_title
            WHERE t.kind = 'species'
              AND t.rank = 'species'
              AND d.extraction_status = 'matched'
              AND p.extracted_ok = 1
            ORDER BY t.target_key
            """
        )

        for row in description_rows:
            taxon = taxa.get(row["target_key"])
            if taxon is None:
                continue

            description_length = len(row["description"])
            article_length = len(row["raw_lead_wikitext"] or "")
            taxon["description_length"] = description_length
            taxon["article_length"] = article_length
            taxon["pageview_count"] = int(row["pageview_count"] or 0)
            if description_length <= min_description_length:
                continue

            eligible_target_keys.add(row["target_key"])
            descriptions[row["target_key"]] = (
                row["target_key"],
                row["matched_title"] or row["primary_title"],
                row["description"],
                int(row["word_count"]),
                description_length,
                int(row["multimedia_count"]),
                int(row["pageview_count"] or 0),
                int(row["backlink_count"] or 0),
            )

        parent_rows = source.execute(
            """
            SELECT
                t.target_key,
                t.scientific_name,
                t.primary_title,
                t.matched_title,
                d.word_count,
                d.description_length,
                d.multimedia_count,
                COALESCE(p.pageview_count, t.pageview_count, 0) AS pageview_count,
                COALESCE(p.backlink_count, t.backlink_count, 0) AS backlink_count,
                p.description
            FROM taxon_targets t
            JOIN taxon_descriptions d ON d.target_key = t.target_key
            JOIN wikipedia_pages p ON p.title = d.resolved_title
            WHERE t.kind = 'parent'
              AND d.extraction_status = 'matched'
              AND p.extracted_ok = 1
            ORDER BY t.target_key
            """
        )
        for row in parent_rows:
            if row["target_key"] not in taxa:
                continue
            descriptions[row["target_key"]] = (
                row["target_key"],
                row["matched_title"] or row["primary_title"],
                row["description"],
                int(row["word_count"]),
                len(row["description"]),
                int(row["multimedia_count"]),
                int(row["pageview_count"] or 0),
                int(row["backlink_count"] or 0),
            )

    common_name_count = _populate_common_names(
        gbif_backbone=gbif_backbone,
        taxa=taxa,
        taxon_gbif_ids=taxon_gbif_ids,
    )
    score_summary = _score_species(
        taxa=taxa,
        parents=parents,
        eligible_target_keys=eligible_target_keys,
    )

    with sqlite3.connect(output) as target:
        target.execute("PRAGMA journal_mode = WAL")
        target.execute("PRAGMA synchronous = NORMAL")
        target.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

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
                backlink_count INTEGER NOT NULL,
                FOREIGN KEY(taxon_key) REFERENCES runtime_taxa(taxon_key)
            );

            CREATE INDEX idx_runtime_taxa_rank
                ON runtime_taxa(rank);
            CREATE INDEX idx_runtime_taxa_name
                ON runtime_taxa(scientific_name COLLATE NOCASE);
            CREATE INDEX idx_runtime_taxa_difficulty
                ON runtime_taxa(difficulty_level);
            CREATE INDEX idx_runtime_edges_parent
                ON runtime_edges(parent_key);
            """
        )
        target.executemany(
            """
            INSERT INTO runtime_taxa (
                taxon_key,
                rank,
                scientific_name,
                common_name,
                difficulty_level,
                description_length,
                article_length,
                pageview_count,
                difficulty_score,
                pageview_score,
                article_score,
                vernacular_score,
                category_score,
                category_modifier,
                target_rank,
                tree_rank,
                playable_species_count,
                tree_species_count,
                easy_species_count,
                medium_species_count,
                hard_species_count,
                expert_target_species_count
            )
            VALUES (
                :taxon_key,
                :rank,
                :scientific_name,
                :common_name,
                :difficulty_level,
                :description_length,
                :article_length,
                :pageview_count,
                :difficulty_score,
                :pageview_score,
                :article_score,
                :vernacular_score,
                :category_score,
                :category_modifier,
                :target_rank,
                :tree_rank,
                :playable_species_count,
                :tree_species_count,
                :easy_species_count,
                :medium_species_count,
                :hard_species_count,
                :expert_target_species_count
            )
            """,
            sorted(taxa.values(), key=lambda item: (str(item["rank"]), str(item["taxon_key"]))),
        )
        target.executemany(
            """
            INSERT INTO runtime_edges (
                parent_key,
                child_key,
                playable_species_count
            )
            VALUES (?, ?, ?)
            """,
            [(parent, child, count) for (parent, child), count in sorted(edges.items())],
        )
        target.executemany(
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
            sorted(descriptions.values(), key=lambda row: str(row[0])),
        )
        metadata = {
            "runtime_schema_version": "4",
            "source_assembled_db": str(assembled_db),
            "source_gbif_backbone": str(gbif_backbone),
            "dump_date": dump_date,
            "min_description_length": str(min_description_length),
            "common_name_count": str(common_name_count),
            "difficulty_score_weights": json.dumps(DIFFICULTY_SCORE_WEIGHTS, sort_keys=True),
            "target_rank_cutoffs": json.dumps(TARGET_RANK_CUTOFFS, sort_keys=True),
            "tree_rank_cutoffs": json.dumps(TREE_RANK_CUTOFFS, sort_keys=True),
            "tree_includes_target_cutoffs": "true",
            "eligible_target_species_count": str(len(eligible_target_keys)),
            "playable_species_count": str(_species_count(taxa, "tree_species_count")),
            "tree_species_count": str(_species_count(taxa, "tree_species_count")),
            "target_species_count": str(_species_count(taxa, "expert_target_species_count")),
            "easy_species_count": str(_species_count(taxa, "easy_species_count")),
            "medium_species_count": str(_species_count(taxa, "medium_species_count")),
            "hard_species_count": str(_species_count(taxa, "hard_species_count")),
            "expert_target_species_count": str(
                _species_count(taxa, "expert_target_species_count")
            ),
            "parent_description_count": str(
                sum(1 for key in descriptions if taxa.get(key, {}).get("rank") != "species")
            ),
            "taxon_count": str(len(taxa)),
            "edge_count": str(len(edges)),
            "skipped_bad_paths": str(skipped_bad_paths),
            "score_pageview_p01": str(score_summary["pageview_p01"]),
            "score_pageview_p99": str(score_summary["pageview_p99"]),
            "score_article_p01": str(score_summary["article_p01"]),
            "score_article_p99": str(score_summary["article_p99"]),
        }
        target.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        target.commit()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target.execute("VACUUM")

    return {
        "assembled_db": str(assembled_db),
        "output": str(output),
        "playable_species_count": _species_count(taxa, "tree_species_count"),
        "tree_species_count": _species_count(taxa, "tree_species_count"),
        "target_species_count": _species_count(taxa, "expert_target_species_count"),
        "eligible_target_species_count": len(eligible_target_keys),
        "easy_species_count": _species_count(taxa, "easy_species_count"),
        "medium_species_count": _species_count(taxa, "medium_species_count"),
        "hard_species_count": _species_count(taxa, "hard_species_count"),
        "expert_target_species_count": _species_count(taxa, "expert_target_species_count"),
        "parent_description_count": sum(
            1 for key in descriptions if taxa.get(key, {}).get("rank") != "species"
        ),
        "taxon_count": len(taxa),
        "edge_count": len(edges),
        "common_name_count": common_name_count,
        "skipped_bad_paths": skipped_bad_paths,
        "min_description_length": min_description_length,
    }


def compress_runtime_db(source: Path, output: Path, *, force: bool) -> None:
    """Write a gzip-compressed runtime asset."""
    if output.exists():
        if not force:
            raise FileExistsError(f"{output} already exists; pass --force to rebuild")
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as source_file, gzip.open(
        output,
        "wb",
        compresslevel=9,
    ) as output_file:
        shutil.copyfileobj(source_file, output_file)


def _taxon_key(path_pairs: list[tuple[str, str]]) -> str:
    return "taxon:" + json.dumps(path_pairs, ensure_ascii=False, separators=(",", ":"))


def _new_taxon(taxon_key: str, rank: str, scientific_name: str) -> dict[str, object]:
    return {
        "taxon_key": taxon_key,
        "rank": rank,
        "scientific_name": scientific_name,
        "common_name": "",
        "difficulty_level": "",
        "description_length": 0,
        "article_length": 0,
        "pageview_count": 0,
        "difficulty_score": 0.0,
        "pageview_score": 0.0,
        "article_score": 0.0,
        "vernacular_score": 0.0,
        "category_score": 0.0,
        "category_modifier": 0,
        "target_rank": 0,
        "tree_rank": 0,
        "playable_species_count": 0,
        "tree_species_count": 0,
        "easy_species_count": 0,
        "medium_species_count": 0,
        "hard_species_count": 0,
        "expert_target_species_count": 0,
    }


def _score_species(
    *,
    taxa: dict[str, dict[str, object]],
    parents: dict[str, str],
    eligible_target_keys: set[str],
) -> dict[str, float]:
    species_taxa = [
        taxon
        for taxon in taxa.values()
        if taxon["rank"] == "species"
    ]
    pageview_logs = [math.log1p(int(taxon["pageview_count"])) for taxon in species_taxa]
    article_logs = [math.log1p(int(taxon["article_length"])) for taxon in species_taxa]
    pageview_p01 = _percentile(pageview_logs, 0.01)
    pageview_p99 = _percentile(pageview_logs, 0.99)
    article_p01 = _percentile(article_logs, 0.01)
    article_p99 = _percentile(article_logs, 0.99)

    for taxon in species_taxa:
        pageview_score = _normalize(
            math.log1p(int(taxon["pageview_count"])),
            pageview_p01,
            pageview_p99,
        )
        article_score = _normalize(
            math.log1p(int(taxon["article_length"])),
            article_p01,
            article_p99,
        )
        vernacular_score = 1.0 if taxon["common_name"] else 0.0
        category_score = normalized_category_score(int(taxon["category_modifier"]))
        difficulty_score = (
            DIFFICULTY_SCORE_WEIGHTS["pageviews"] * pageview_score
            + DIFFICULTY_SCORE_WEIGHTS["article_length"] * article_score
            + DIFFICULTY_SCORE_WEIGHTS["vernacular"] * vernacular_score
            + DIFFICULTY_SCORE_WEIGHTS["category"] * category_score
        )
        taxon["pageview_score"] = round(pageview_score, 6)
        taxon["article_score"] = round(article_score, 6)
        taxon["vernacular_score"] = round(vernacular_score, 6)
        taxon["category_score"] = round(category_score, 6)
        taxon["difficulty_score"] = round(difficulty_score, 6)

    ranked_species = sorted(species_taxa, key=_difficulty_sort_key)
    for rank, taxon in enumerate(ranked_species, start=1):
        taxon["tree_rank"] = rank

    eligible_targets = [taxa[key] for key in eligible_target_keys if key in taxa]
    for rank, taxon in enumerate(sorted(eligible_targets, key=_difficulty_sort_key), start=1):
        taxon["target_rank"] = rank
        difficulty = difficulty_for_target_rank(rank)
        if difficulty:
            taxon["difficulty_level"] = difficulty
            _increment_count_fields(
                taxa,
                parents,
                str(taxon["taxon_key"]),
                ["expert_target_species_count"],
            )

    for taxon in species_taxa:
        tree_rank = int(taxon["tree_rank"])
        target_rank = int(taxon["target_rank"])
        fields = []
        if _included_in_ranked_tree(tree_rank, target_rank, "easy"):
            fields.append("easy_species_count")
        if _included_in_ranked_tree(tree_rank, target_rank, "medium"):
            fields.append("medium_species_count")
        if _included_in_ranked_tree(tree_rank, target_rank, "hard"):
            fields.append("hard_species_count")
        if fields:
            _increment_count_fields(taxa, parents, str(taxon["taxon_key"]), fields)

    return {
        "pageview_p01": pageview_p01,
        "pageview_p99": pageview_p99,
        "article_p01": article_p01,
        "article_p99": article_p99,
    }


def _included_in_ranked_tree(tree_rank: int, target_rank: int, difficulty: str) -> bool:
    return (
        tree_rank <= TREE_RANK_CUTOFFS[difficulty]
        or 0 < target_rank <= TARGET_RANK_CUTOFFS[difficulty]
    )


def _difficulty_sort_key(taxon: dict[str, object]) -> tuple[float, float, float, str, str]:
    return (
        -float(taxon["difficulty_score"]),
        -float(taxon["pageview_score"]),
        -float(taxon["article_score"]),
        str(taxon["scientific_name"]).lower(),
        str(taxon["taxon_key"]),
    )


def _increment_count_fields(
    taxa: dict[str, dict[str, object]],
    parents: dict[str, str],
    species_key: str,
    fields: list[str],
) -> None:
    taxon_key = species_key
    while taxon_key and taxon_key != "0":
        taxon = taxa[taxon_key]
        for field in fields:
            taxon[field] = int(taxon[field]) + 1
        taxon_key = parents.get(taxon_key, "")


def _species_count(taxa: dict[str, dict[str, object]], field: str) -> int:
    return sum(
        1
        for taxon in taxa.values()
        if taxon["rank"] == "species" and int(taxon[field]) > 0
    )


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * quantile)
    return ordered[index]


def _normalize(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    normalized = (value - lower) / (upper - lower)
    return max(0.0, min(1.0, normalized))


def _populate_common_names(
    *,
    gbif_backbone: Path,
    taxa: dict[str, dict[str, object]],
    taxon_gbif_ids: dict[str, str],
) -> int:
    """Attach one English common name to runtime taxa when GBIF provides one."""
    if not gbif_backbone.exists():
        return _apply_manual_common_names(taxa)

    parent_gbif_ids = _resolve_parent_gbif_ids(gbif_backbone, taxa, taxon_gbif_ids)
    taxon_gbif_ids.update(parent_gbif_ids)

    wanted_gbif_ids = {gbif_id for gbif_id in taxon_gbif_ids.values() if gbif_id}
    if not wanted_gbif_ids:
        return _apply_manual_common_names(taxa)

    ranks_by_gbif_id = {
        gbif_id: str(taxon["rank"])
        for taxon_key, gbif_id in taxon_gbif_ids.items()
        if gbif_id and (taxon := taxa.get(taxon_key)) is not None
    }
    common_names = _load_english_common_names(
        gbif_backbone,
        wanted_gbif_ids,
        ranks_by_gbif_id,
    )
    common_name_count = 0
    for taxon_key, gbif_id in taxon_gbif_ids.items():
        common_name = common_names.get(gbif_id)
        taxon = taxa.get(taxon_key)
        if common_name and taxon is not None:
            taxon["common_name"] = common_name
            common_name_count += 1

    return common_name_count + _apply_manual_common_names(taxa)


def _apply_manual_common_names(taxa: dict[str, dict[str, object]]) -> int:
    common_name_count = 0
    for taxon in taxa.values():
        if taxon["common_name"]:
            continue

        manual_name = MANUAL_COMMON_NAMES.get(
            (str(taxon["rank"]), str(taxon["scientific_name"]))
        )
        if not manual_name:
            continue

        taxon["common_name"] = manual_name
        common_name_count += 1

    return common_name_count


def _resolve_parent_gbif_ids(
    gbif_backbone: Path,
    taxa: dict[str, dict[str, object]],
    existing_gbif_ids: dict[str, str],
) -> dict[str, str]:
    """Resolve GBIF IDs for path-keyed parent taxa by scanning the Backbone taxon file."""
    taxon_file = gbif_backbone / "Taxon.tsv"
    if not taxon_file.exists():
        return {}

    unresolved = {
        taxon_key
        for taxon_key, taxon in taxa.items()
        if taxon["rank"] != "species" and taxon_key not in existing_gbif_ids
    }
    if not unresolved:
        return {}

    resolved: dict[str, str] = {}
    with open(taxon_file, encoding="utf-8", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        header = next(reader, None)
        if header is None:
            return resolved
        index = {name: position for position, name in enumerate(header)}
        required_columns = [
            "taxonID",
            "taxonRank",
            "taxonomicStatus",
            "scientificName",
            "canonicalName",
            *MAJOR_RANKS[:-1],
        ]
        if any(column not in index for column in required_columns):
            return resolved

        for row in reader:
            rank = _cell(row, index["taxonRank"]).lower()
            if rank not in MAJOR_RANKS[:-1]:
                continue
            if _cell(row, index["taxonomicStatus"]).lower() != "accepted":
                continue

            taxon_key = _gbif_parent_taxon_key(row, index, rank)
            if taxon_key not in unresolved or taxon_key in resolved:
                continue

            gbif_id = _cell(row, index["taxonID"])
            if gbif_id:
                resolved[taxon_key] = gbif_id
                if len(resolved) == len(unresolved):
                    break

    return resolved


def _gbif_parent_taxon_key(row: list[str], index: dict[str, int], rank: str) -> str:
    path_pairs: list[tuple[str, str]] = []
    for path_rank in MAJOR_RANKS[: MAJOR_RANKS.index(rank) + 1]:
        name = _cell(row, index[path_rank])
        if path_rank == rank and not name:
            name = _cell(row, index["canonicalName"]) or _cell(row, index["scientificName"])
        if not name:
            return ""
        path_pairs.append((path_rank, name))
    return _taxon_key(path_pairs)


def _load_english_common_names(
    gbif_backbone: Path,
    wanted_gbif_ids: set[str],
    ranks_by_gbif_id: dict[str, str],
) -> dict[str, str]:
    vernacular_file = gbif_backbone / "VernacularName.tsv"
    if not vernacular_file.exists():
        return {}

    selected: dict[str, tuple[int, str]] = {}
    with open(vernacular_file, encoding="utf-8", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        header = next(reader, None)
        if header is None:
            return {}
        index = {name: position for position, name in enumerate(header)}
        required_columns = ["taxonID", "vernacularName", "language", "countryCode"]
        if any(column not in index for column in required_columns):
            return {}

        for row in reader:
            taxon_id = _cell(row, index["taxonID"])
            if taxon_id not in wanted_gbif_ids:
                continue

            language = _cell(row, index["language"]).lower()
            if language not in COMMON_NAME_LANGUAGES:
                continue

            name = _cell(row, index["vernacularName"])
            if not name:
                continue

            country_code = _cell(row, index["countryCode"]).upper()
            rank = ranks_by_gbif_id.get(taxon_id, "")
            score = _common_name_score(
                name=name,
                language=language,
                country_code=country_code,
                rank=rank,
            )
            current = selected.get(taxon_id)
            if current is None or score > current[0]:
                selected[taxon_id] = (score, name)

    return {taxon_id: name for taxon_id, (_, name) in selected.items()}


def _common_name_score(*, name: str, language: str, country_code: str, rank: str) -> int:
    language_score = 200 if language == "en" else 100
    country_score = COMMON_NAME_COUNTRY_PRIORITY.get(country_code, 1) * 10
    score = language_score + country_score

    normalized_name = _normalize_common_name(name)
    if normalized_name in COMMON_NAME_CATEGORY_TERMS:
        score -= 100

    if rank != "species" and _looks_plural_common_name(normalized_name):
        score += 25

    return score


def _normalize_common_name(name: str) -> str:
    return " ".join(name.casefold().replace("-", " ").split())


def _looks_plural_common_name(normalized_name: str) -> bool:
    if not normalized_name:
        return False
    last_word = normalized_name.rsplit(" ", maxsplit=1)[-1]
    return last_word.endswith("s") and not last_word.endswith(("'s", "ss"))


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


def main() -> None:
    args = build_parser().parse_args()
    summary = build_runtime_db(
        assembled_db=args.assembled_db,
        output=args.output,
        gbif_backbone=args.gbif_backbone,
        dump_date=args.dump_date,
        min_description_length=args.min_description_length,
        force=args.force,
    )
    compressed_output = ""
    if not args.no_compress:
        compress_runtime_db(args.output, args.compressed_output, force=args.force)
        compressed_output = str(args.compressed_output)

    print("RUNTIME DATABASE BUILD")
    print("=" * 80)
    print(f"  Assembled DB:         {summary['assembled_db']}")
    print(f"  Runtime DB:           {summary['output']}")
    if compressed_output:
        print(f"  Compressed asset:     {compressed_output}")
    print(f"  Tree species:         {summary['tree_species_count']:>12,}")
    print(f"  Target species:       {summary['target_species_count']:>12,}")
    print(f"    Easy tree:          {summary['easy_species_count']:>12,}")
    print(f"    Medium tree:        {summary['medium_species_count']:>12,}")
    print(f"    Hard tree:          {summary['hard_species_count']:>12,}")
    print(f"    Expert targets:     {summary['expert_target_species_count']:>12,}")
    print(f"  Parent descriptions:  {summary['parent_description_count']:>12,}")
    print(f"  Taxa:                 {summary['taxon_count']:>12,}")
    print(f"  Edges:                {summary['edge_count']:>12,}")
    print(f"  Common names:         {summary['common_name_count']:>12,}")
    print(f"  Skipped bad paths:    {summary['skipped_bad_paths']:>12,}")
    print(f"  Min description len:  {summary['min_description_length']:>12,}")


if __name__ == "__main__":
    main()
