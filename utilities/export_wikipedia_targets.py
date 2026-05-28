#!/usr/bin/env python3
"""Export English Wikipedia page targets from the candidate species database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_DB = (
    REPO_ROOT / "data" / "candidate_trees" / "wikidata-gbif-candidates.sqlite"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "wikipedia_targets"
DEFAULT_DUMP_DATE = "20260501"
WIKIPEDIA_PATH_PREFIX = "/wiki/"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-db",
        type=Path,
        default=DEFAULT_CANDIDATE_DB,
        help="Candidate tree SQLite database containing candidate_species",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated target-title files",
    )
    parser.add_argument(
        "--dump-date",
        default=DEFAULT_DUMP_DATE,
        help="English Wikipedia dump date used in output filenames",
    )
    parser.add_argument(
        "--prefix",
        help="Output filename prefix; defaults to enwiki-DATE-candidate",
    )
    return parser


def title_from_wikipedia_url(url: str) -> tuple[str, str]:
    """Return ``(dump_title, url_title)`` from an English Wikipedia article URL."""
    parsed = urlparse(url)
    if parsed.netloc not in {"en.wikipedia.org", "en.m.wikipedia.org"}:
        raise ValueError(f"not an English Wikipedia URL: {url}")
    if not parsed.path.startswith(WIKIPEDIA_PATH_PREFIX):
        raise ValueError(f"not a /wiki/ article URL: {url}")

    raw_url_title = parsed.path[len(WIKIPEDIA_PATH_PREFIX) :]
    if parsed.query:
        # Some ColDP URLs contain literal question marks from page titles instead
        # of percent-encoding them. Recover those because XML dumps use the
        # decoded MediaWiki title, not URL query semantics.
        if not raw_url_title:
            raw_url_title = f"?{parsed.query}"
        elif "=" not in parsed.query and "&" not in parsed.query:
            raw_url_title = f"{raw_url_title}?{parsed.query}"

    url_title = unquote(raw_url_title)
    if not url_title:
        raise ValueError(f"missing page title in URL: {url}")
    # A small number of ColDP URLs contain literal quote characters around the
    # genus/title segment even though the actual Wikipedia title omits them.
    url_title = url_title.replace('"', "")

    # XML dumps use spaces in <title>; article URLs conventionally use underscores.
    dump_title = url_title.replace("_", " ")
    return dump_title, url_title


def iter_candidate_species(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Load candidate species rows in a stable order."""
    return list(
        conn.execute(
            """
            SELECT
                wikidata_id,
                scientific_name,
                wikipedia_url,
                gbif_id,
                match_type,
                kingdom,
                phylum,
                class_name,
                order_name,
                family,
                genus,
                species
            FROM candidate_species
            ORDER BY wikipedia_url COLLATE NOCASE, wikidata_id
            """
        )
    )


def export_targets(
    *,
    candidate_db: Path,
    output_dir: Path,
    dump_date: str,
    prefix: str | None = None,
) -> dict[str, int | str]:
    """Export target title text, JSONL metadata, and a manifest."""
    if not candidate_db.exists():
        raise FileNotFoundError(candidate_db)

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = prefix or f"enwiki-{dump_date}-candidate"
    titles_path = output_dir / f"{prefix}-titles.txt"
    pages_path = output_dir / f"{prefix}-pages.jsonl"
    manifest_path = output_dir / f"{prefix}-manifest.json"

    targets_by_title: dict[str, list[dict[str, object]]] = defaultdict(list)
    invalid_url_count = 0

    with sqlite3.connect(candidate_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = iter_candidate_species(conn)

    for row in rows:
        try:
            title, url_title = title_from_wikipedia_url(row["wikipedia_url"])
        except ValueError:
            invalid_url_count += 1
            continue

        targets_by_title[title].append(
            {
                "wikidata_id": row["wikidata_id"],
                "scientific_name": row["scientific_name"],
                "accepted_species": row["species"],
                "gbif_id": row["gbif_id"],
                "match_type": row["match_type"],
                "wikipedia_url": row["wikipedia_url"],
                "url_title": url_title,
                "path": [
                    row["kingdom"],
                    row["phylum"],
                    row["class_name"],
                    row["order_name"],
                    row["family"],
                    row["genus"],
                    row["species"],
                ],
            }
        )

    with open(titles_path, "w", encoding="utf-8", newline="\n") as f:
        for title in sorted(targets_by_title, key=str.casefold):
            f.write(f"{title}\n")

    duplicate_title_groups = 0
    duplicate_candidate_rows = 0
    with open(pages_path, "w", encoding="utf-8", newline="\n") as f:
        for title in sorted(targets_by_title, key=str.casefold):
            candidates = targets_by_title[title]
            if len(candidates) > 1:
                duplicate_title_groups += 1
                duplicate_candidate_rows += len(candidates) - 1

            first = candidates[0]
            record = {
                "title": title,
                "url_title": first["url_title"],
                "wikipedia_url": first["wikipedia_url"],
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            f.write("\n")

    manifest: dict[str, int | str] = {
        "candidate_db": str(candidate_db),
        "dump_date": dump_date,
        "candidate_rows": len(rows),
        "target_titles": len(targets_by_title),
        "invalid_url_rows": invalid_url_count,
        "duplicate_title_groups": duplicate_title_groups,
        "duplicate_candidate_rows": duplicate_candidate_rows,
        "titles_path": str(titles_path),
        "pages_path": str(pages_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return manifest


def main() -> None:
    args = build_parser().parse_args()
    manifest = export_targets(
        candidate_db=args.candidate_db,
        output_dir=args.output_dir,
        dump_date=args.dump_date,
        prefix=args.prefix,
    )

    print("WIKIPEDIA TARGET EXPORT")
    print("=" * 80)
    print(f"  Candidate DB:             {manifest['candidate_db']}")
    print(f"  Candidate rows:           {manifest['candidate_rows']:>12,}")
    print(f"  Target page titles:       {manifest['target_titles']:>12,}")
    print(f"  Invalid URL rows:         {manifest['invalid_url_rows']:>12,}")
    print(f"  Duplicate title groups:   {manifest['duplicate_title_groups']:>12,}")
    print(f"  Duplicate candidate rows: {manifest['duplicate_candidate_rows']:>12,}")
    print(f"  Titles:                   {manifest['titles_path']}")
    print(f"  Page metadata:            {manifest['pages_path']}")


if __name__ == "__main__":
    main()
