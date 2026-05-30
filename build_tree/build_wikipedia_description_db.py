#!/usr/bin/env python3
"""Build the assembled Wikipedia description database for candidate taxa."""

from __future__ import annotations

import argparse
import bz2
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from export_wikipedia_targets import title_from_wikipedia_url
    from extract_wikipedia_descriptions import (
        DEFAULT_CANDIDATE_DB,
        DEFAULT_DESCRIPTION_CHAR_LIMIT,
        DEFAULT_INDEX,
        DEFAULT_XML_DUMP,
        ExtractedPage,
        clean_wikitext_description,
        clean_wikitext_lead,
        parse_pages_from_stream,
        read_bzip2_stream_at,
    )
except ModuleNotFoundError:
    from build_tree.export_wikipedia_targets import title_from_wikipedia_url
    from build_tree.extract_wikipedia_descriptions import (
        DEFAULT_CANDIDATE_DB,
        DEFAULT_DESCRIPTION_CHAR_LIMIT,
        DEFAULT_INDEX,
        DEFAULT_XML_DUMP,
        ExtractedPage,
        clean_wikitext_description,
        clean_wikitext_lead,
        parse_pages_from_stream,
        read_bzip2_stream_at,
    )

if TYPE_CHECKING:
    from collections.abc import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DUMP_DATE = "20260501"
DEFAULT_OUTPUT = (
    REPO_ROOT / "assets" / "generated" / "assembled" / "taxonomica-20260501.sqlite"
)
DEFAULT_PAGEVIEWS_DB = REPO_ROOT / "assets" / "raw" / "legacy" / "species.db"
MAJOR_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
FILE_LINK_RE = re.compile(r"\[\[(?:File|Image):", re.IGNORECASE)
GALLERY_FILE_RE = re.compile(r"(?im)^\s*(?:File|Image):")
INFOBOX_MEDIA_PARAM_RE = re.compile(
    r"(?im)^\s*\|\s*(?:image\d*|range_map|map|image_map|distribution_map)\s*=\s*(.+?)\s*$"
)
BACKBONE_SUFFIX_RE = re.compile(r"^(.+)_([A-Z])$")


@dataclass(frozen=True)
class AssemblyTarget:
    """A species or parent taxon that should be matched to Wikipedia text."""

    target_key: str
    kind: str
    rank: str
    scientific_name: str
    primary_title: str
    path: tuple[str, ...]
    title_aliases: tuple[str, ...] = ()
    accepted_species: str = ""
    gbif_id: str = ""
    wikidata_id: str = ""
    wikipedia_url: str = ""
    descendant_species_count: int = 0

    @property
    def title_candidates(self) -> tuple[str, ...]:
        return (self.primary_title, *self.title_aliases)


@dataclass(frozen=True)
class TitleIndexEntry:
    """A title entry from the Wikipedia multistream index."""

    title: str
    page_id: str
    offset: int


@dataclass(frozen=True)
class ResolvedTarget:
    """A target after matching its title candidates against the dump index."""

    target: AssemblyTarget
    matched_title: str = ""
    match_strategy: str = "none"
    page_id: str = ""
    offset: int | None = None

    @property
    def matched(self) -> bool:
        return bool(self.matched_title)


@dataclass(frozen=True)
class PopularityMetrics:
    """Optional popularity metrics from the older pageview/backlink DB."""

    pageview_count: int = 0
    backlink_count: int = 0


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
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output assembled SQLite database",
    )
    parser.add_argument(
        "--pageviews-db",
        type=Path,
        default=DEFAULT_PAGEVIEWS_DB,
        help="Optional species.db with pageview_count/backlink_count",
    )
    parser.add_argument(
        "--dump-date",
        default=DEFAULT_DUMP_DATE,
        help="Wikipedia dump date recorded in assembly metadata",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve targets and print extraction stats without writing output",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output database",
    )
    parser.add_argument(
        "--limit-targets",
        type=int,
        help="Limit targets for smoke tests",
    )
    parser.add_argument(
        "--max-redirects",
        type=int,
        default=1,
        help="Maximum redirect hops to follow during full extraction",
    )
    parser.add_argument(
        "--paragraphs",
        type=int,
        default=2,
        help="Number of cleaned lead paragraphs to store when description-char-limit is disabled",
    )
    parser.add_argument(
        "--description-char-limit",
        type=int,
        default=DEFAULT_DESCRIPTION_CHAR_LIMIT,
        help="Maximum cleaned description characters to store; 0 stores cleaned lead paragraphs",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=250000,
        help="Print progress every N rows during long scans",
    )
    parser.add_argument(
        "--extraction-progress-interval",
        type=int,
        default=5000,
        help="Print progress every N Wikipedia dump offsets during page extraction",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=10,
        help="Number of missing/alias examples to print in dry-run summaries",
    )
    return parser


def load_targets(candidate_db: Path, *, limit: int | None = None) -> list[AssemblyTarget]:
    """Load species and parent-taxon targets from the candidate tree."""
    if not candidate_db.exists():
        raise FileNotFoundError(candidate_db)

    targets: list[AssemblyTarget] = []
    with sqlite3.connect(candidate_db) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
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
            ORDER BY wikidata_id
            """
        ):
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
                AssemblyTarget(
                    target_key=f"species:{row['wikidata_id']}",
                    kind="species",
                    rank="species",
                    scientific_name=row["scientific_name"],
                    primary_title=title,
                    accepted_species=row["species"],
                    path=path,
                    gbif_id=row["gbif_id"],
                    wikidata_id=row["wikidata_id"],
                    wikipedia_url=row["wikipedia_url"],
                    descendant_species_count=1,
                )
            )
            if limit and len(targets) >= limit:
                return targets

        for row in conn.execute(
            """
            SELECT taxon_key, rank, scientific_name, descendant_species_count
            FROM candidate_taxa
            WHERE rank != 'species'
            ORDER BY rank, scientific_name, taxon_key
            """
        ):
            path_pairs = json.loads(row["taxon_key"])
            path = tuple(name for _, name in path_pairs)
            targets.append(
                AssemblyTarget(
                    target_key=f"taxon:{row['taxon_key']}",
                    kind="parent",
                    rank=row["rank"],
                    scientific_name=row["scientific_name"],
                    primary_title=row["scientific_name"],
                    title_aliases=_parent_title_aliases(row["scientific_name"]),
                    path=path,
                    descendant_species_count=int(row["descendant_species_count"]),
                )
            )
            if limit and len(targets) >= limit:
                return targets

    return targets


def scan_index_for_titles(
    index_path: Path,
    title_candidates: set[str],
    *,
    progress_interval: int,
) -> tuple[dict[str, TitleIndexEntry], int, int]:
    """Scan the multistream index once and keep entries for candidate titles."""
    if not index_path.exists():
        raise FileNotFoundError(index_path)

    matches = {}
    total_rows = 0
    offsets = set()
    with bz2.open(index_path, "rt", encoding="utf-8") as f:
        for line in f:
            total_rows += 1
            offset_text, page_id, title = line.rstrip("\n").split(":", 2)
            offsets.add(int(offset_text))
            if title in title_candidates:
                matches[title] = TitleIndexEntry(
                    title=title,
                    page_id=page_id,
                    offset=int(offset_text),
                )
            if progress_interval and total_rows % progress_interval == 0:
                print(
                    f"  Scanned {total_rows:,} index rows; "
                    f"matched {len(matches):,}/{len(title_candidates):,} titles..."
                )
    return matches, total_rows, len(offsets)


def resolve_targets(
    targets: Iterable[AssemblyTarget],
    title_index: dict[str, TitleIndexEntry],
) -> list[ResolvedTarget]:
    """Resolve target title candidates against the title index."""
    resolved = []
    for target in targets:
        match = None
        for title in target.title_candidates:
            match = title_index.get(title)
            if match:
                strategy = "exact" if title == target.primary_title else "alias"
                resolved.append(
                    ResolvedTarget(
                        target=target,
                        matched_title=title,
                        match_strategy=strategy,
                        page_id=match.page_id,
                        offset=match.offset,
                    )
                )
                break
        if match is None:
            resolved.append(ResolvedTarget(target=target))
    return resolved


def load_popularity_metrics(pageviews_db: Path | None) -> dict[str, PopularityMetrics]:
    """Load optional article popularity metrics keyed by dump title."""
    if not pageviews_db or not pageviews_db.exists():
        return {}

    metrics = {}
    with sqlite3.connect(pageviews_db) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            """
            SELECT title, pageview_count, backlink_count
            FROM species
            """
        ):
            title = row["title"]
            metric = PopularityMetrics(
                pageview_count=int(row["pageview_count"] or 0),
                backlink_count=int(row["backlink_count"] or 0),
            )
            metrics[title] = metric
            metrics[title.replace("_", " ")] = metric
    return metrics


def _parent_title_aliases(title: str) -> tuple[str, ...]:
    """Return conservative fallback page titles for parent-taxon matches."""
    aliases = []
    suffix_match = BACKBONE_SUFFIX_RE.match(title)
    if suffix_match:
        aliases.append(suffix_match.group(1))
    return tuple(dict.fromkeys(alias for alias in aliases if alias and alias != title))


def summarize_dry_run(
    *,
    targets: list[AssemblyTarget],
    resolved: list[ResolvedTarget],
    title_index_matches: dict[str, TitleIndexEntry],
    total_index_rows: int,
    total_index_offsets: int,
    popularity_metrics: dict[str, PopularityMetrics],
    examples: int,
) -> None:
    """Print a dry-run summary."""
    matched = [row for row in resolved if row.matched]
    unmatched = [row for row in resolved if not row.matched]
    alias_matches = [row for row in resolved if row.match_strategy == "alias"]
    matched_titles = {row.matched_title for row in matched}
    matched_offsets = {row.offset for row in matched if row.offset is not None}
    popularity_matches = sum(
        1 for row in matched if row.matched_title in popularity_metrics
    )

    print("\nDRY RUN SUMMARY")
    print("=" * 80)
    print(f"  Targets loaded:               {len(targets):>12,}")
    print(f"  Index rows scanned:           {total_index_rows:>12,}")
    print(f"  Total bzip2 stream offsets:   {total_index_offsets:>12,}")
    print(f"  Candidate page titles:        {len(title_index_matches):>12,} matched")
    print(
        f"  Matched targets:              {len(matched):>12,}  "
        f"({_percent(len(matched), len(targets))})"
    )
    print(f"  Unmatched targets:            {len(unmatched):>12,}")
    print(f"  Alias-matched targets:        {len(alias_matches):>12,}")
    print(f"  Unique matched page titles:   {len(matched_titles):>12,}")
    print(f"  Unique extraction offsets:    {len(matched_offsets):>12,}")
    print(
        f"  Offset coverage:              "
        f"{_percent(len(matched_offsets), total_index_offsets):>12}"
    )
    print(f"  Matched-title popularity rows:{popularity_matches:>12,}")

    _print_summary_table("BY KIND", resolved, key=lambda row: row.target.kind)
    _print_summary_table("BY RANK", resolved, key=lambda row: row.target.rank, order=MAJOR_RANKS)
    _print_examples("ALIAS MATCH EXAMPLES", alias_matches, examples)
    _print_examples("UNMATCHED EXAMPLES", unmatched, examples)


def create_output_database(
    output_path: Path,
    *,
    force: bool,
    metadata: dict[str, str | int],
) -> sqlite3.Connection:
    """Create the assembled output database and schema."""
    if output_path.exists() and not force:
        raise FileExistsError(f"{output_path} already exists; pass --force to rebuild")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE taxon_targets (
            target_key TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            rank TEXT NOT NULL,
            scientific_name TEXT NOT NULL,
            accepted_species TEXT NOT NULL,
            gbif_id TEXT NOT NULL,
            wikidata_id TEXT NOT NULL,
            wikipedia_url TEXT NOT NULL,
            primary_title TEXT NOT NULL,
            title_aliases_json TEXT NOT NULL,
            matched_title TEXT NOT NULL,
            match_strategy TEXT NOT NULL,
            page_id TEXT NOT NULL,
            offset INTEGER,
            path_json TEXT NOT NULL,
            descendant_species_count INTEGER NOT NULL,
            pageview_count INTEGER,
            backlink_count INTEGER
        );

        CREATE TABLE wikipedia_pages (
            title TEXT PRIMARY KEY,
            page_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            redirect_title TEXT NOT NULL,
            resolved_title TEXT NOT NULL,
            redirect_chain_json TEXT NOT NULL,
            raw_lead_wikitext TEXT NOT NULL,
            description TEXT NOT NULL,
            word_count INTEGER NOT NULL,
            description_length INTEGER NOT NULL,
            multimedia_count INTEGER NOT NULL,
            pageview_count INTEGER,
            backlink_count INTEGER,
            extracted_ok INTEGER NOT NULL
        );

        CREATE TABLE taxon_descriptions (
            target_key TEXT PRIMARY KEY,
            requested_title TEXT NOT NULL,
            matched_title TEXT NOT NULL,
            resolved_title TEXT NOT NULL,
            extraction_status TEXT NOT NULL,
            word_count INTEGER NOT NULL,
            description_length INTEGER NOT NULL,
            multimedia_count INTEGER NOT NULL,
            FOREIGN KEY(target_key) REFERENCES taxon_targets(target_key)
        );

        CREATE INDEX idx_taxon_targets_kind_rank
            ON taxon_targets(kind, rank);
        CREATE INDEX idx_taxon_targets_matched_title
            ON taxon_targets(matched_title);
        CREATE INDEX idx_taxon_descriptions_resolved_title
            ON taxon_descriptions(resolved_title);
        """
    )
    conn.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        [(key, str(value)) for key, value in sorted(metadata.items())],
    )
    conn.commit()
    return conn


def temporary_output_path(output_path: Path) -> Path:
    """Return the transient SQLite path used during full rebuilds."""
    return output_path.with_name(f"{output_path.name}.tmp")


def sqlite_sidecars(path: Path) -> tuple[Path, Path]:
    """Return WAL-mode sidecar paths for a SQLite database path."""
    return (
        path.with_name(f"{path.name}-wal"),
        path.with_name(f"{path.name}-shm"),
    )


def remove_sqlite_outputs(path: Path) -> None:
    """Remove an incomplete generated SQLite database and its sidecars."""
    for candidate in (path, *sqlite_sidecars(path)):
        if candidate.exists():
            candidate.unlink()


def replace_output_database(temp_output: Path, output_path: Path, *, force: bool) -> None:
    """Atomically publish a completed temporary SQLite database."""
    if output_path.exists() and not force:
        raise FileExistsError(f"{output_path} already exists; pass --force to rebuild")
    for sidecar in sqlite_sidecars(output_path):
        if sidecar.exists():
            sidecar.unlink()
    temp_output.replace(output_path)
    remove_sqlite_outputs(temp_output)


def write_resolved_targets(
    conn: sqlite3.Connection,
    resolved: Iterable[ResolvedTarget],
    popularity_metrics: dict[str, PopularityMetrics],
) -> None:
    """Insert resolved target rows into the output database."""
    rows = []
    for item in resolved:
        metric = popularity_metrics.get(item.matched_title, PopularityMetrics())
        target = item.target
        rows.append(
            (
                target.target_key,
                target.kind,
                target.rank,
                target.scientific_name,
                target.accepted_species,
                target.gbif_id,
                target.wikidata_id,
                target.wikipedia_url,
                target.primary_title,
                json.dumps(target.title_aliases, ensure_ascii=False),
                item.matched_title,
                item.match_strategy,
                item.page_id,
                item.offset,
                json.dumps(target.path, ensure_ascii=False),
                target.descendant_species_count,
                metric.pageview_count if item.matched else None,
                metric.backlink_count if item.matched else None,
            )
        )

    conn.executemany(
        """
        INSERT INTO taxon_targets (
            target_key,
            kind,
            rank,
            scientific_name,
            accepted_species,
            gbif_id,
            wikidata_id,
            wikipedia_url,
            primary_title,
            title_aliases_json,
            matched_title,
            match_strategy,
            page_id,
            offset,
            path_json,
            descendant_species_count,
            pageview_count,
            backlink_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def extract_and_store_pages(
    conn: sqlite3.Connection,
    *,
    xml_dump: Path,
    index: Path,
    resolved: list[ResolvedTarget],
    title_index: dict[str, TitleIndexEntry],
    popularity_metrics: dict[str, PopularityMetrics],
    max_redirects: int,
    paragraphs: int,
    description_char_limit: int,
    progress_interval: int,
) -> None:
    """Extract matched pages and redirects, then write page/description rows."""
    pages_by_title: dict[str, ExtractedPage] = {}
    titles_to_fetch = {row.matched_title for row in resolved if row.matched}

    for redirect_depth in range(max_redirects + 1):
        pending_titles = titles_to_fetch - set(pages_by_title)
        offsets_to_titles: dict[int, set[str]] = defaultdict(set)
        for title in pending_titles:
            entry = title_index.get(title)
            if entry:
                offsets_to_titles[entry.offset].add(title)

        for offset_index, (offset, titles_at_offset) in enumerate(
            sorted(offsets_to_titles.items()),
            1,
        ):
            xml_bytes = read_bzip2_stream_at(xml_dump, offset)
            chunk_pages = parse_pages_from_stream(xml_bytes)
            for title in titles_at_offset:
                page = chunk_pages.get(title)
                if page is None:
                    continue
                if description_char_limit > 0:
                    page.description = clean_wikitext_description(
                        page.raw_wikitext,
                        max_chars=description_char_limit,
                    )
                else:
                    page.description = clean_wikitext_lead(
                        page.lead_wikitext,
                        paragraphs=paragraphs,
                    )
                pages_by_title[title] = page
            if progress_interval and offset_index % progress_interval == 0:
                print(
                    f"  Redirect pass {redirect_depth}: extracted "
                    f"{offset_index:,}/{len(offsets_to_titles):,} offsets..."
                )

        redirect_targets = {
            page.redirect_title
            for page in pages_by_title.values()
            if page.redirect_title and page.redirect_title not in pages_by_title
        }
        new_redirect_targets = redirect_targets - titles_to_fetch
        if not new_redirect_targets:
            break
        print(
            f"  Redirect pass {redirect_depth}: found "
            f"{len(new_redirect_targets):,} new redirect targets."
        )
        redirect_index_matches, _, _ = scan_index_for_titles(
            index,
            new_redirect_targets,
            progress_interval=0,
        )
        title_index.update(redirect_index_matches)
        titles_to_fetch.update(new_redirect_targets)

    _write_pages(conn, pages_by_title, popularity_metrics, max_redirects)
    _write_taxon_descriptions(conn, resolved, pages_by_title, max_redirects)


def _write_pages(
    conn: sqlite3.Connection,
    pages_by_title: dict[str, ExtractedPage],
    popularity_metrics: dict[str, PopularityMetrics],
    max_redirects: int,
) -> None:
    rows = []
    for title, page in sorted(pages_by_title.items()):
        resolved_page, chain = _resolve_redirect_chain(
            title,
            pages_by_title,
            max_redirects=max_redirects,
        )
        resolved_title = resolved_page.title if resolved_page else page.title
        metric = popularity_metrics.get(resolved_title) or popularity_metrics.get(title)
        metric = metric or PopularityMetrics()
        description = resolved_page.description if resolved_page else page.description
        raw_lead = resolved_page.lead_wikitext if resolved_page else page.lead_wikitext
        rows.append(
            (
                title,
                page.page_id,
                page.revision_id,
                page.timestamp,
                page.redirect_title,
                resolved_title,
                json.dumps(chain, ensure_ascii=False),
                raw_lead,
                description,
                _word_count(description),
                len(description),
                count_multimedia_links(
                    resolved_page.raw_wikitext if resolved_page else page.raw_wikitext
                ),
                metric.pageview_count,
                metric.backlink_count,
                1 if description else 0,
            )
        )

    conn.executemany(
        """
        INSERT OR REPLACE INTO wikipedia_pages (
            title,
            page_id,
            revision_id,
            timestamp,
            redirect_title,
            resolved_title,
            redirect_chain_json,
            raw_lead_wikitext,
            description,
            word_count,
            description_length,
            multimedia_count,
            pageview_count,
            backlink_count,
            extracted_ok
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def _write_taxon_descriptions(
    conn: sqlite3.Connection,
    resolved: list[ResolvedTarget],
    pages_by_title: dict[str, ExtractedPage],
    max_redirects: int,
) -> None:
    rows = []
    for item in resolved:
        if not item.matched:
            rows.append(
                (
                    item.target.target_key,
                    item.target.primary_title,
                    "",
                    "",
                    "unmatched",
                    0,
                    0,
                    0,
                )
            )
            continue

        page, chain = _resolve_redirect_chain(
            item.matched_title,
            pages_by_title,
            max_redirects=max_redirects,
        )
        if page is None:
            rows.append(
                (
                    item.target.target_key,
                    item.target.primary_title,
                    item.matched_title,
                    "",
                    "missing_extraction",
                    0,
                    0,
                    0,
                )
            )
            continue

        status = "matched" if page.description else "empty_description"
        rows.append(
            (
                item.target.target_key,
                item.target.primary_title,
                item.matched_title,
                page.title,
                status,
                _word_count(page.description),
                len(page.description),
                count_multimedia_links(page.raw_wikitext),
            )
        )

    conn.executemany(
        """
        INSERT OR REPLACE INTO taxon_descriptions (
            target_key,
            requested_title,
            matched_title,
            resolved_title,
            extraction_status,
            word_count,
            description_length,
            multimedia_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def count_multimedia_links(wikitext: str) -> int:
    """Count likely multimedia links/references in page wikitext."""
    count = len(FILE_LINK_RE.findall(wikitext))
    count += len(GALLERY_FILE_RE.findall(wikitext))
    for match in INFOBOX_MEDIA_PARAM_RE.finditer(wikitext):
        value = match.group(1).strip()
        if not value or value in {"-", "none", "None", "N/A"}:
            continue
        if "{{" in value or value.startswith("[["):
            continue
        count += 1
    return count


def _resolve_redirect_chain(
    title: str,
    pages_by_title: dict[str, ExtractedPage],
    *,
    max_redirects: int,
) -> tuple[ExtractedPage | None, list[str]]:
    chain = [title]
    page = pages_by_title.get(title)
    for _ in range(max_redirects):
        if page is None or not page.redirect_title:
            return page, chain
        next_title = page.redirect_title
        chain.append(next_title)
        next_page = pages_by_title.get(next_title)
        if next_page is None:
            return page, chain
        page = next_page
    return page, chain


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _print_summary_table(
    title: str,
    rows: list[ResolvedTarget],
    *,
    key,
    order: list[str] | None = None,
) -> None:
    print(f"\n{title}")
    print("=" * 80)
    groups: dict[str, list[ResolvedTarget]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)

    labels = order or sorted(groups)
    for label in labels:
        group = groups.get(label, [])
        if not group:
            continue
        matched = sum(1 for row in group if row.matched)
        alias = sum(1 for row in group if row.match_strategy == "alias")
        print(
            f"  {label:<10} targets={len(group):>8,} "
            f"matched={matched:>8,} ({_percent(matched, len(group)):>6}) "
            f"alias={alias:>6,}"
        )


def _print_examples(title: str, rows: list[ResolvedTarget], examples: int) -> None:
    print(f"\n{title}")
    print("=" * 80)
    if not rows:
        print("  none")
        return
    for row in rows[:examples]:
        target = row.target
        print(
            f"  {target.primary_title} [{target.rank}, {target.kind}] "
            f"matched={row.matched_title or '-'} strategy={row.match_strategy}"
        )
        if target.title_aliases:
            print(f"    Aliases: {', '.join(target.title_aliases)}")
        print(f"    Path: {' -> '.join(target.path)}")


def _percent(numerator: int, denominator: int) -> str:
    if not denominator:
        return "0.0%"
    return f"{(numerator / denominator) * 100:.1f}%"


def main() -> None:
    args = build_parser().parse_args()

    print("WIKIPEDIA DESCRIPTION DB ASSEMBLY")
    print("=" * 80)
    print(f"  Candidate DB:    {args.candidate_db}")
    print(f"  XML dump:        {args.xml_dump}")
    print(f"  Index:           {args.index}")
    print(f"  Output:          {args.output}")
    print(f"  Dry run:         {args.dry_run}")

    print("\nPass 1: Loading candidate taxa/species targets...")
    targets = load_targets(args.candidate_db, limit=args.limit_targets)
    title_candidates = {
        title for target in targets for title in target.title_candidates
    }
    print(f"  Targets loaded:       {len(targets):,}")
    print(f"  Candidate titles:     {len(title_candidates):,}")

    print("\nPass 2: Scanning Wikipedia multistream index...")
    title_index, total_index_rows, total_index_offsets = scan_index_for_titles(
        args.index,
        title_candidates,
        progress_interval=args.progress_interval,
    )
    resolved = resolve_targets(targets, title_index)

    print("\nPass 3: Loading optional popularity metrics...")
    popularity_metrics = load_popularity_metrics(args.pageviews_db)
    if popularity_metrics:
        print(f"  Popularity title keys: {len(popularity_metrics):,}")
        print(f"  Source:                {args.pageviews_db}")
    else:
        print("  No popularity metrics loaded.")

    if args.dry_run:
        summarize_dry_run(
            targets=targets,
            resolved=resolved,
            title_index_matches=title_index,
            total_index_rows=total_index_rows,
            total_index_offsets=total_index_offsets,
            popularity_metrics=popularity_metrics,
            examples=args.examples,
        )
        return

    if args.output.exists() and not args.force:
        raise FileExistsError(f"{args.output} already exists; pass --force to rebuild")
    temp_output = temporary_output_path(args.output)
    remove_sqlite_outputs(temp_output)

    print("\nPass 4: Creating output database and writing resolved targets...")
    conn = create_output_database(
        temp_output,
        force=True,
        metadata={
            "dump_date": args.dump_date,
            "candidate_db": str(args.candidate_db),
            "xml_dump": str(args.xml_dump),
            "index": str(args.index),
            "pageviews_db": str(args.pageviews_db),
            "target_count": len(targets),
            "matched_target_count": sum(1 for row in resolved if row.matched),
            "total_index_rows": total_index_rows,
            "total_index_offsets": total_index_offsets,
            "description_char_limit": args.description_char_limit,
            "lead_paragraphs": args.paragraphs,
        },
    )
    try:
        write_resolved_targets(conn, resolved, popularity_metrics)

        print("\nPass 5: Extracting matched pages and writing descriptions...")
        extract_and_store_pages(
            conn,
            xml_dump=args.xml_dump,
            index=args.index,
            resolved=resolved,
            title_index=title_index,
            popularity_metrics=popularity_metrics,
            max_redirects=args.max_redirects,
            paragraphs=args.paragraphs,
            description_char_limit=args.description_char_limit,
            progress_interval=args.extraction_progress_interval,
        )
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    replace_output_database(temp_output, args.output, force=args.force)
    print(f"\nWrote assembled description database: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
