#!/usr/bin/env python3
"""Randomly audit Wikipedia dump matching for candidate species and parent taxa."""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from export_wikipedia_targets import title_from_wikipedia_url
    from extract_wikipedia_descriptions import (
        DEFAULT_CANDIDATE_DB,
        DEFAULT_INDEX,
        DEFAULT_XML_DUMP,
        extract_pages,
        write_jsonl,
    )
except ModuleNotFoundError:
    from utilities.export_wikipedia_targets import title_from_wikipedia_url
    from utilities.extract_wikipedia_descriptions import (
        DEFAULT_CANDIDATE_DB,
        DEFAULT_INDEX,
        DEFAULT_XML_DUMP,
        extract_pages,
        write_jsonl,
    )

if TYPE_CHECKING:
    from collections.abc import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "wikipedia_targets" / "random-taxa-spot-check.jsonl"
PARENT_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus"]
BACKBONE_SUFFIX_RE = re.compile(r"^(.+)_([A-Z])$")


@dataclass(frozen=True)
class SampleTarget:
    """One sampled taxon/title to audit."""

    title: str
    kind: str
    rank: str
    scientific_name: str
    accepted_species: str
    path: tuple[str, ...]
    title_aliases: tuple[str, ...] = ()
    gbif_id: str = ""
    wikidata_id: str = ""
    wikipedia_url: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-db",
        type=Path,
        default=DEFAULT_CANDIDATE_DB,
        help="Candidate tree SQLite database",
    )
    parser.add_argument(
        "--xml-dump",
        type=Path,
        default=DEFAULT_XML_DUMP,
        help="English Wikipedia pages-articles multistream XML dump",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help="English Wikipedia pages-articles multistream index",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=100,
        help="Total sampled taxa; split between species and parent taxa",
    )
    parser.add_argument(
        "--species",
        type=int,
        help="Number of candidate species to sample; default is half of --total",
    )
    parser.add_argument(
        "--parents",
        type=int,
        help="Number of parent taxa to sample; default is total minus species",
    )
    parser.add_argument(
        "--balanced-parent-ranks",
        action="store_true",
        help="Sample parent taxa roughly evenly across kingdom/phylum/class/order/family/genus",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260528,
        help="Random seed for repeatable audits",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=0,
        help="Minimum cleaned-description word count considered usable",
    )
    parser.add_argument(
        "--no-parent-aliases",
        action="store_true",
        help="Disable parent-title fallbacks such as stripping GBIF _A/_B suffixes",
    )
    parser.add_argument(
        "--paragraphs",
        type=int,
        default=2,
        help="Number of cleaned lead paragraphs to keep",
    )
    parser.add_argument(
        "--max-redirects",
        type=int,
        default=1,
        help="Maximum redirect hops to follow",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=8,
        help="Number of matched and missing examples to print",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSONL output path for sampled taxon audit rows",
    )
    return parser


def sample_targets(
    candidate_db: Path,
    *,
    species_count: int,
    parent_count: int,
    seed: int,
    balanced_parent_ranks: bool,
) -> list[SampleTarget]:
    """Sample species and parent taxa from the candidate tree."""
    rng = random.Random(seed)
    with sqlite3.connect(candidate_db) as conn:
        conn.row_factory = sqlite3.Row
        species = _sample_species(conn, species_count, rng)
        parents = _sample_parents(
            conn,
            parent_count,
            rng,
            balanced_parent_ranks=balanced_parent_ranks,
        )
    return [*species, *parents]


def _sample_species(
    conn: sqlite3.Connection,
    count: int,
    rng: random.Random,
) -> list[SampleTarget]:
    rows = list(
        conn.execute(
            """
            SELECT
                wikidata_id,
                scientific_name,
                wikipedia_url,
                gbif_id,
                kingdom,
                phylum,
                class_name,
                order_name,
                family,
                genus,
                species
            FROM candidate_species
            """
        )
    )
    selected = rng.sample(rows, min(count, len(rows)))
    targets = []
    for row in selected:
        title, _ = title_from_wikipedia_url(row["wikipedia_url"])
        path = (
            row["kingdom"],
            row["phylum"],
            row["class_name"],
            row["order_name"],
            row["family"],
            row["genus"],
            row["species"],
        )
        targets.append(
            SampleTarget(
                title=title,
                kind="species",
                rank="species",
                scientific_name=row["scientific_name"],
                accepted_species=row["species"],
                path=path,
                gbif_id=row["gbif_id"],
                wikidata_id=row["wikidata_id"],
                wikipedia_url=row["wikipedia_url"],
            )
        )
    return targets


def _sample_parents(
    conn: sqlite3.Connection,
    count: int,
    rng: random.Random,
    *,
    balanced_parent_ranks: bool,
) -> list[SampleTarget]:
    if not balanced_parent_ranks:
        rows = list(
            conn.execute(
                """
                SELECT taxon_key, rank, scientific_name, descendant_species_count
                FROM candidate_taxa
                WHERE rank != 'species'
                """
            )
        )
        return [
            _parent_target_from_row(row)
            for row in rng.sample(rows, min(count, len(rows)))
        ]

    per_rank = _balanced_rank_counts(count, PARENT_RANKS)
    targets = []
    for rank, rank_count in per_rank.items():
        rows = list(
            conn.execute(
                """
                SELECT taxon_key, rank, scientific_name, descendant_species_count
                FROM candidate_taxa
                WHERE rank = ?
                """,
                (rank,),
            )
        )
        selected = rng.sample(rows, min(rank_count, len(rows)))
        targets.extend(_parent_target_from_row(row) for row in selected)

    if len(targets) < count:
        existing_keys = {target.path for target in targets}
        rows = list(
            conn.execute(
                """
                SELECT taxon_key, rank, scientific_name, descendant_species_count
                FROM candidate_taxa
                WHERE rank != 'species'
                """
            )
        )
        remaining = [
            row
            for row in rows
            if tuple(name for _, name in json.loads(row["taxon_key"])) not in existing_keys
        ]
        needed = count - len(targets)
        targets.extend(
            _parent_target_from_row(row)
            for row in rng.sample(remaining, min(needed, len(remaining)))
        )

    return targets[:count]


def _balanced_rank_counts(total: int, ranks: list[str]) -> dict[str, int]:
    base, remainder = divmod(total, len(ranks))
    return {
        rank: base + (1 if index < remainder else 0)
        for index, rank in enumerate(ranks)
    }


def _parent_target_from_row(row: sqlite3.Row) -> SampleTarget:
    path_pairs = json.loads(row["taxon_key"])
    path = tuple(name for _, name in path_pairs)
    return SampleTarget(
        title=row["scientific_name"],
        kind="parent",
        rank=row["rank"],
        scientific_name=row["scientific_name"],
        accepted_species="",
        path=path,
        title_aliases=_parent_title_aliases(row["scientific_name"]),
    )


def _parent_title_aliases(title: str) -> tuple[str, ...]:
    """Return weaker fallback page titles for parent-taxon exact-name checks."""
    aliases = []
    suffix_match = BACKBONE_SUFFIX_RE.match(title)
    if suffix_match:
        aliases.append(suffix_match.group(1))
    return tuple(dict.fromkeys(alias for alias in aliases if alias and alias != title))


def annotate_results(
    targets: list[SampleTarget],
    records: list[dict[str, object]],
    *,
    min_words: int,
    use_parent_aliases: bool,
) -> list[dict[str, object]]:
    """Attach extraction outcomes to sampled taxa."""
    records_by_title = {str(record["requested_title"]): record for record in records}
    output = []
    for target in targets:
        title_candidates = [target.title]
        if use_parent_aliases:
            title_candidates.extend(target.title_aliases)

        matched_title = ""
        record = None
        for title in title_candidates:
            record = records_by_title.get(title)
            if record is not None:
                matched_title = title
                break

        word_count = int(record["word_count"]) if record else 0
        output.append(
            {
                "title": target.title,
                "title_aliases": list(target.title_aliases),
                "matched_title": matched_title,
                "match_strategy": _match_strategy(target.title, matched_title),
                "kind": target.kind,
                "rank": target.rank,
                "scientific_name": target.scientific_name,
                "accepted_species": target.accepted_species,
                "gbif_id": target.gbif_id,
                "wikidata_id": target.wikidata_id,
                "wikipedia_url": target.wikipedia_url,
                "path": list(target.path),
                "matched": record is not None,
                "usable": bool(record and word_count >= min_words),
                "word_count": word_count,
                "resolved_title": record["resolved_title"] if record else "",
                "redirect_chain": record["redirect_chain"] if record else [],
                "description": record["description"] if record else "",
            }
        )
    return output


def _match_strategy(primary_title: str, matched_title: str) -> str:
    if not matched_title:
        return "none"
    if matched_title == primary_title:
        return "exact"
    return "alias"


def summarize(rows: list[dict[str, object]], *, min_words: int, examples: int) -> None:
    """Print match-rate summaries and representative examples."""
    print("\nMATCHING SUMMARY")
    print("=" * 80)
    _print_group_summary("Overall", rows, min_words=min_words)

    print("\nBY KIND")
    print("=" * 80)
    for kind in ["species", "parent"]:
        group = [row for row in rows if row["kind"] == kind]
        if group:
            _print_group_summary(kind, group, min_words=min_words)

    print("\nBY RANK")
    print("=" * 80)
    rank_order = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
    for rank in rank_order:
        group = [row for row in rows if row["rank"] == rank]
        if group:
            _print_group_summary(rank, group, min_words=min_words)

    missing = [row for row in rows if not row["matched"]]
    low_word = [row for row in rows if row["matched"] and not row["usable"]]
    matched = [row for row in rows if row["usable"]]
    alias_matches = [row for row in rows if row["match_strategy"] == "alias"]

    _print_examples("ALIAS MATCH EXAMPLES", alias_matches, examples)
    _print_examples("MISSING TITLE EXAMPLES", missing, examples)
    _print_examples("LOW-WORD EXAMPLES", low_word, examples)
    _print_examples("USABLE MATCH EXAMPLES", matched, examples, include_description=True)


def _print_group_summary(label: str, rows: list[dict[str, object]], *, min_words: int) -> None:
    total = len(rows)
    matched = sum(1 for row in rows if row["matched"])
    usable = sum(1 for row in rows if row["usable"])
    redirects = sum(1 for row in rows if len(row.get("redirect_chain", [])) > 1)
    avg_words = (
        sum(int(row["word_count"]) for row in rows if row["matched"]) / matched
        if matched
        else 0
    )
    print(
        f"  {label:<10} sampled={total:>3} "
        f"matched={matched:>3} ({_percent(matched, total):>5}) "
        f"usable>={min_words}w={usable:>3} ({_percent(usable, total):>5}) "
        f"redirects={redirects:>2} avg_words={avg_words:>6.1f}"
    )


def _print_examples(
    label: str,
    rows: list[dict[str, object]],
    count: int,
    *,
    include_description: bool = False,
) -> None:
    print(f"\n{label}")
    print("=" * 80)
    if not rows:
        print("  none")
        return

    for row in rows[:count]:
        path = " -> ".join(row["path"])
        print(
            f"  {row['title']} [{row['rank']}, {row['kind']}] "
            f"words={row['word_count']} matched={row['matched_title'] or '-'} "
            f"resolved={row['resolved_title'] or '-'}"
        )
        print(f"    Path: {path}")
        if include_description:
            description = str(row["description"]).replace("\n", " ")
            if len(description) > 260:
                description = description[:257].rstrip() + "..."
            print(f"    {description}")


def _percent(numerator: int, denominator: int) -> str:
    if not denominator:
        return "0.0%"
    return f"{(numerator / denominator) * 100:.1f}%"


def write_audit_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    """Write per-taxon audit rows to JSONL."""
    write_jsonl(path, list(rows))


def main() -> None:
    args = build_parser().parse_args()
    species_count = args.species if args.species is not None else args.total // 2
    parent_count = args.parents if args.parents is not None else args.total - species_count

    targets = sample_targets(
        args.candidate_db,
        species_count=species_count,
        parent_count=parent_count,
        seed=args.seed,
        balanced_parent_ranks=args.balanced_parent_ranks,
    )
    title_candidates = []
    for target in targets:
        title_candidates.append(target.title)
        if not args.no_parent_aliases:
            title_candidates.extend(target.title_aliases)
    titles = list(dict.fromkeys(title_candidates))

    print("RANDOM WIKIPEDIA MATCHING SPOT CHECK")
    print("=" * 80)
    print(f"  Candidate DB:          {args.candidate_db}")
    print(f"  XML dump:              {args.xml_dump}")
    print(f"  Index:                 {args.index}")
    print(f"  Seed:                  {args.seed}")
    print(f"  Species sampled:       {species_count:,}")
    print(f"  Parent taxa sampled:   {parent_count:,}")
    print(f"  Unique titles checked: {len(titles):,}")

    records, missing = extract_pages(
        xml_dump=args.xml_dump,
        index=args.index,
        titles=titles,
        candidate_db=args.candidate_db,
        paragraphs=args.paragraphs,
        max_redirects=args.max_redirects,
    )
    print(f"  Extracted pages:       {len(records):,}")
    print(f"  Missing index titles:  {len(missing):,}")

    rows = annotate_results(
        targets,
        records,
        min_words=args.min_words,
        use_parent_aliases=not args.no_parent_aliases,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_audit_jsonl(args.output, rows)
    print(f"  Output:                {args.output}")

    summarize(rows, min_words=args.min_words, examples=args.examples)


if __name__ == "__main__":
    main()
