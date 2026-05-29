#!/usr/bin/env python3
"""Build a slim playable runtime database from the assembled description DB."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
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
        help="Minimum description length for playable species",
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
    taxa: dict[str, dict[str, int | str]] = {}
    edges: dict[tuple[str, str], int] = {}
    descriptions: dict[str, tuple[object, ...]] = {}
    taxon_gbif_ids: dict[str, str] = {}
    skipped_bad_paths = 0

    with sqlite3.connect(assembled_db) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute(
            """
            SELECT
                t.target_key,
                t.scientific_name,
                t.gbif_id,
                t.primary_title,
                t.matched_title,
                t.path_json,
                COALESCE(t.pageview_count, 0) AS target_pageview_count,
                COALESCE(t.backlink_count, 0) AS target_backlink_count,
                d.word_count,
                d.description_length,
                d.multimedia_count,
                COALESCE(p.pageview_count, t.pageview_count, 0) AS pageview_count,
                COALESCE(p.backlink_count, t.backlink_count, 0) AS backlink_count,
                p.description
            FROM taxon_targets t
            JOIN taxon_descriptions d ON d.target_key = t.target_key
            JOIN wikipedia_pages p ON p.title = d.resolved_title
            WHERE t.kind = 'species'
              AND t.rank = 'species'
              AND d.extraction_status = 'matched'
              AND p.extracted_ok = 1
              AND length(p.description) >= ?
            ORDER BY t.target_key
            """,
            (min_description_length,),
        )

        for row in rows:
            path = json.loads(row["path_json"])
            if len(path) != len(MAJOR_RANKS) or any(not name for name in path):
                skipped_bad_paths += 1
                continue

            parent_key = "0"
            path_pairs: list[tuple[str, str]] = []
            for rank, name in zip(MAJOR_RANKS, path):
                path_pairs.append((rank, name))
                taxon_key = row["target_key"] if rank == "species" else _taxon_key(path_pairs)
                taxon = taxa.setdefault(
                    taxon_key,
                    {
                        "taxon_key": taxon_key,
                        "rank": rank,
                        "scientific_name": name,
                        "common_name": "",
                        "playable_species_count": 0,
                    },
                )
                taxon["playable_species_count"] = int(taxon["playable_species_count"]) + 1
                edges[(parent_key, taxon_key)] = edges.get((parent_key, taxon_key), 0) + 1
                parent_key = taxon_key

            if row["gbif_id"]:
                taxon_gbif_ids[row["target_key"]] = row["gbif_id"]

            description_length = len(row["description"])
            word_count = int(row["word_count"])
            multimedia_count = int(row["multimedia_count"])
            pageview_count = int(row["pageview_count"] or 0)
            backlink_count = int(row["backlink_count"] or 0)
            descriptions[row["target_key"]] = (
                row["target_key"],
                row["matched_title"] or row["primary_title"],
                row["description"],
                word_count,
                description_length,
                multimedia_count,
                pageview_count,
                backlink_count,
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
                backlink_count INTEGER NOT NULL,
                FOREIGN KEY(taxon_key) REFERENCES runtime_taxa(taxon_key)
            );

            CREATE INDEX idx_runtime_taxa_rank
                ON runtime_taxa(rank);
            CREATE INDEX idx_runtime_taxa_name
                ON runtime_taxa(scientific_name COLLATE NOCASE);
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
                playable_species_count
            )
            VALUES (
                :taxon_key,
                :rank,
                :scientific_name,
                :common_name,
                :playable_species_count
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
            "runtime_schema_version": "2",
            "source_assembled_db": str(assembled_db),
            "source_gbif_backbone": str(gbif_backbone),
            "dump_date": dump_date,
            "min_description_length": str(min_description_length),
            "common_name_count": str(common_name_count),
            "playable_species_count": str(
                sum(1 for key in descriptions if taxa.get(key, {}).get("rank") == "species")
            ),
            "parent_description_count": str(
                sum(1 for key in descriptions if taxa.get(key, {}).get("rank") != "species")
            ),
            "taxon_count": str(len(taxa)),
            "edge_count": str(len(edges)),
            "skipped_bad_paths": str(skipped_bad_paths),
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
        "playable_species_count": sum(
            1 for key in descriptions if taxa.get(key, {}).get("rank") == "species"
        ),
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
    with open(source, "rb") as source_file:
        with gzip.open(output, "wb", compresslevel=9) as output_file:
            shutil.copyfileobj(source_file, output_file)


def _taxon_key(path_pairs: list[tuple[str, str]]) -> str:
    return "taxon:" + json.dumps(path_pairs, ensure_ascii=False, separators=(",", ":"))


def _populate_common_names(
    *,
    gbif_backbone: Path,
    taxa: dict[str, dict[str, int | str]],
    taxon_gbif_ids: dict[str, str],
) -> int:
    """Attach one English common name to runtime taxa when GBIF provides one."""
    if not gbif_backbone.exists():
        return 0

    parent_gbif_ids = _resolve_parent_gbif_ids(gbif_backbone, taxa, taxon_gbif_ids)
    taxon_gbif_ids.update(parent_gbif_ids)

    wanted_gbif_ids = {gbif_id for gbif_id in taxon_gbif_ids.values() if gbif_id}
    if not wanted_gbif_ids:
        return 0

    common_names = _load_english_common_names(gbif_backbone, wanted_gbif_ids)
    common_name_count = 0
    for taxon_key, gbif_id in taxon_gbif_ids.items():
        common_name = common_names.get(gbif_id)
        taxon = taxa.get(taxon_key)
        if common_name and taxon is not None:
            taxon["common_name"] = common_name
            common_name_count += 1

    return common_name_count


def _resolve_parent_gbif_ids(
    gbif_backbone: Path,
    taxa: dict[str, dict[str, int | str]],
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


def _load_english_common_names(gbif_backbone: Path, wanted_gbif_ids: set[str]) -> dict[str, str]:
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
            score = _common_name_score(language, country_code)
            current = selected.get(taxon_id)
            if current is None or score > current[0]:
                selected[taxon_id] = (score, name)

    return {taxon_id: name for taxon_id, (_, name) in selected.items()}


def _common_name_score(language: str, country_code: str) -> int:
    language_score = 2 if language == "en" else 1
    country_score = COMMON_NAME_COUNTRY_PRIORITY.get(country_code, 1)
    return language_score * 10 + country_score


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
    print(f"  Playable species:     {summary['playable_species_count']:>12,}")
    print(f"  Parent descriptions:  {summary['parent_description_count']:>12,}")
    print(f"  Taxa:                 {summary['taxon_count']:>12,}")
    print(f"  Edges:                {summary['edge_count']:>12,}")
    print(f"  Common names:         {summary['common_name_count']:>12,}")
    print(f"  Skipped bad paths:    {summary['skipped_bad_paths']:>12,}")
    print(f"  Min description len:  {summary['min_description_length']:>12,}")


if __name__ == "__main__":
    main()
