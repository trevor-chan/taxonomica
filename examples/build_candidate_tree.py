#!/usr/bin/env python3
"""Build an initial seven-rank candidate tree from Wikidata ColDP and GBIF."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.candidate_tree import build_candidate_tree


DEFAULT_COLDP_ARCHIVE = Path(__file__).parent.parent / "data" / "coldp" / "wikidata.zip"
DEFAULT_GBIF_BACKBONE = Path(__file__).parent.parent / "backbone"
DEFAULT_OUTPUT = (
    Path(__file__).parent.parent
    / "data"
    / "candidate_trees"
    / "wikidata-gbif-candidates.sqlite"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coldp",
        type=Path,
        default=DEFAULT_COLDP_ARCHIVE,
        help="Wikidata ColDP ZIP or extracted archive path",
    )
    parser.add_argument(
        "--gbif",
        type=Path,
        default=DEFAULT_GBIF_BACKBONE,
        help="GBIF Backbone directory containing Taxon.tsv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output SQLite path for the candidate tree",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild an existing output database",
    )
    parser.add_argument(
        "--no-name-fallback",
        action="store_true",
        help="Only match GBIF IDs from Wikidata; skip exact-name fallback",
    )
    parser.add_argument(
        "--coldp-limit",
        type=int,
        help="Read only the first N ColDP NameUsage rows for smoke tests",
    )
    parser.add_argument(
        "--gbif-limit",
        type=int,
        help="Read only the first N GBIF Taxon.tsv rows for smoke tests",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=500000,
        help="Print progress every N rows",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of grouped rows to print in summary tables",
    )
    return parser


def print_summary(db_path: Path, *, top: int) -> None:
    """Print a compact summary from the generated candidate database."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        article_row_count = conn.execute(
            "SELECT COUNT(*) AS count FROM candidate_species"
        ).fetchone()["count"]
        path_node_count = conn.execute(
            "SELECT COUNT(*) AS count FROM candidate_taxa"
        ).fetchone()["count"]
        species_node_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM candidate_taxa
            WHERE rank = 'species'
            """
        ).fetchone()["count"]
        parent_node_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM candidate_taxa
            WHERE rank != 'species'
            """
        ).fetchone()["count"]
        unique_label_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM (
                SELECT rank, scientific_name
                FROM candidate_taxa
                GROUP BY rank, scientific_name
            )
            """
        ).fetchone()["count"]
        edge_count = conn.execute(
            "SELECT COUNT(*) AS count FROM candidate_edges"
        ).fetchone()["count"]
        duplicate_species_groups = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM (
                SELECT gbif_id
                FROM candidate_species
                GROUP BY gbif_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()["count"]

        print("\nCANDIDATE TREE SUMMARY")
        print("=" * 80)
        print(f"  Article-backed rows:      {article_row_count:>12,}")
        print(f"  Unique accepted species:  {species_node_count:>12,}")
        print(f"  Duplicate species rows:   {article_row_count - species_node_count:>12,}")
        print(f"  Duplicate species groups: {duplicate_species_groups:>12,}")
        print(f"  Parent taxa nodes:        {parent_node_count:>12,}")
        print(f"  Total tree nodes:         {path_node_count:>12,}")
        print(f"  Path-keyed tree nodes:    {path_node_count:>12,}")
        print(f"  Unique taxon labels:      {unique_label_count:>12,}")
        print(f"  Candidate edges:          {edge_count:>12,}")

        print("\nNODES BY RANK")
        print("=" * 80)
        for row in conn.execute(
            """
            SELECT rank, COUNT(*) AS count
            FROM candidate_taxa
            GROUP BY rank
            ORDER BY
                CASE rank
                    WHEN 'kingdom' THEN 1
                    WHEN 'phylum' THEN 2
                    WHEN 'class' THEN 3
                    WHEN 'order' THEN 4
                    WHEN 'family' THEN 5
                    WHEN 'genus' THEN 6
                    WHEN 'species' THEN 7
                    ELSE 99
                END
            """
        ):
            print(f"  {row['rank']:<10}              {row['count']:>12,}")

        print("\nMATCH TYPES")
        print("=" * 80)
        for row in conn.execute(
            """
            SELECT match_type, COUNT(*) AS count
            FROM candidate_species
            GROUP BY match_type
            ORDER BY count DESC
            """
        ):
            print(f"  {row['match_type']:<24} {row['count']:>12,}")

        print("\nTOP ROOT CHILDREN")
        print("=" * 80)
        for row in conn.execute(
            """
            SELECT child.scientific_name, child.rank, edge.descendant_species_count
            FROM candidate_edges edge
            JOIN candidate_taxa parent ON parent.taxon_key = edge.parent_key
            JOIN candidate_taxa child ON child.taxon_key = edge.child_key
            WHERE parent.rank = 'kingdom'
            ORDER BY edge.descendant_species_count DESC, child.scientific_name
            LIMIT ?
            """,
            (top,),
        ):
            print(
                f"  {row['scientific_name']:<35} "
                f"[{row['rank']:<8}] {row['descendant_species_count']:>12,}"
            )

        print("\nREJECTION SUMMARY")
        print("=" * 80)
        for row in conn.execute(
            """
            SELECT reason, count
            FROM rejection_summary
            ORDER BY count DESC, reason
            LIMIT ?
            """,
            (top,),
        ):
            print(f"  {row['reason']:<36} {row['count']:>12,}")

        print("\nSAMPLE SPECIES")
        print("=" * 80)
        for row in conn.execute(
            """
            SELECT
                scientific_name,
                wikidata_id,
                gbif_id,
                match_type,
                kingdom,
                phylum,
                class_name,
                order_name,
                family,
                genus,
                wikipedia_url
            FROM candidate_species
            ORDER BY scientific_name COLLATE NOCASE
            LIMIT ?
            """,
            (min(top, 10),),
        ):
            path = " -> ".join(
                [
                    row["kingdom"],
                    row["phylum"],
                    row["class_name"],
                    row["order_name"],
                    row["family"],
                    row["genus"],
                    row["scientific_name"],
                ]
            )
            print(f"  {row['scientific_name']} ({row['wikidata_id']}, GBIF {row['gbif_id']})")
            print(f"    Match: {row['match_type']}")
            print(f"    Path: {path}")
            print(f"    URL: {row['wikipedia_url']}")


def main() -> None:
    args = build_parser().parse_args()

    if args.output.exists() and not args.force:
        print(f"Using existing candidate tree SQLite: {args.output}")
        print("  Pass --force to rebuild it.")
        print_summary(args.output, top=args.top)
        return

    result = build_candidate_tree(
        coldp_archive_path=args.coldp,
        gbif_backbone_path=args.gbif,
        output_path=args.output,
        include_name_fallback=not args.no_name_fallback,
        force=args.force,
        coldp_limit=args.coldp_limit,
        gbif_limit=args.gbif_limit,
        progress_interval=args.progress_interval,
    )

    print_summary(result.output_path, top=args.top)


if __name__ == "__main__":
    main()
