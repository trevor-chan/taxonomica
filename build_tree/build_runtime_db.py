#!/usr/bin/env python3
"""Build a slim playable runtime database from the assembled description DB."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import sqlite3
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
MAJOR_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]


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

    output.parent.mkdir(parents=True, exist_ok=True)
    taxa: dict[str, dict[str, int | str]] = {}
    edges: dict[tuple[str, str], int] = {}
    descriptions: list[tuple[object, ...]] = []
    skipped_bad_paths = 0

    with sqlite3.connect(assembled_db) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute(
            """
            SELECT
                t.target_key,
                t.scientific_name,
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
                        "playable_species_count": 0,
                    },
                )
                taxon["playable_species_count"] = int(taxon["playable_species_count"]) + 1
                edges[(parent_key, taxon_key)] = edges.get((parent_key, taxon_key), 0) + 1
                parent_key = taxon_key

            description_length = len(row["description"])
            word_count = int(row["word_count"])
            multimedia_count = int(row["multimedia_count"])
            pageview_count = int(row["pageview_count"] or 0)
            backlink_count = int(row["backlink_count"] or 0)
            descriptions.append(
                (
                    row["target_key"],
                    row["matched_title"] or row["primary_title"],
                    row["description"],
                    word_count,
                    description_length,
                    max(2, min(10, word_count // 80)),
                    multimedia_count,
                    pageview_count,
                    backlink_count,
                    _difficulty_score(
                        description_length=description_length,
                        multimedia_count=multimedia_count,
                        pageview_count=pageview_count,
                        backlink_count=backlink_count,
                    ),
                )
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
                section_count INTEGER NOT NULL,
                multimedia_count INTEGER NOT NULL,
                pageview_count INTEGER NOT NULL,
                backlink_count INTEGER NOT NULL,
                difficulty_score REAL NOT NULL,
                FOREIGN KEY(taxon_key) REFERENCES runtime_taxa(taxon_key)
            );

            CREATE INDEX idx_runtime_taxa_rank
                ON runtime_taxa(rank);
            CREATE INDEX idx_runtime_taxa_name
                ON runtime_taxa(scientific_name COLLATE NOCASE);
            CREATE INDEX idx_runtime_edges_parent
                ON runtime_edges(parent_key);
            CREATE INDEX idx_runtime_descriptions_score
                ON runtime_descriptions(difficulty_score);
            """
        )
        target.executemany(
            """
            INSERT INTO runtime_taxa (
                taxon_key,
                rank,
                scientific_name,
                playable_species_count
            )
            VALUES (:taxon_key, :rank, :scientific_name, :playable_species_count)
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
                section_count,
                multimedia_count,
                pageview_count,
                backlink_count,
                difficulty_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            descriptions,
        )
        metadata = {
            "runtime_schema_version": "1",
            "source_assembled_db": str(assembled_db),
            "dump_date": dump_date,
            "min_description_length": str(min_description_length),
            "playable_species_count": str(len(descriptions)),
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
        "playable_species_count": len(descriptions),
        "taxon_count": len(taxa),
        "edge_count": len(edges),
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


def _difficulty_score(
    *,
    description_length: int,
    multimedia_count: int,
    pageview_count: int,
    backlink_count: int,
) -> float:
    description_score = min(35.0, math.log10(max(description_length, 1)) * 8.5)
    multimedia_score = min(35.0, multimedia_count * 7.0)
    pageview_score = min(20.0, math.log10(pageview_count + 1) * 4.0)
    backlink_score = min(10.0, math.log10(backlink_count + 1) * 3.0)
    return min(100.0, description_score + multimedia_score + pageview_score + backlink_score)


def main() -> None:
    args = build_parser().parse_args()
    summary = build_runtime_db(
        assembled_db=args.assembled_db,
        output=args.output,
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
    print(f"  Taxa:                 {summary['taxon_count']:>12,}")
    print(f"  Edges:                {summary['edge_count']:>12,}")
    print(f"  Skipped bad paths:    {summary['skipped_bad_paths']:>12,}")
    print(f"  Min description len:  {summary['min_description_length']:>12,}")


if __name__ == "__main__":
    main()
