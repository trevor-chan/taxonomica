#!/usr/bin/env python3
"""Extract target Wikipedia descriptions from a multistream XML dump."""

from __future__ import annotations

import argparse
import bz2
import html
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

try:
    from export_wikipedia_targets import title_from_wikipedia_url
except ModuleNotFoundError:
    from build_tree.export_wikipedia_targets import title_from_wikipedia_url


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DUMP_DATE = "20260501"
DEFAULT_XML_DUMP = (
    REPO_ROOT
    / "assets"
    / "raw"
    / "wikipedia-dumps"
    / f"enwiki-{DEFAULT_DUMP_DATE}-pages-articles-multistream.xml.bz2"
)
DEFAULT_INDEX = (
    REPO_ROOT
    / "assets"
    / "raw"
    / "wikipedia-dumps"
    / f"enwiki-{DEFAULT_DUMP_DATE}-pages-articles-multistream-index.txt.bz2"
)
DEFAULT_CANDIDATE_DB = (
    REPO_ROOT / "assets" / "generated" / "candidate_trees" / "wikidata-gbif-candidates.sqlite"
)
DEFAULT_TARGET_PAGES = (
    REPO_ROOT
    / "assets"
    / "generated"
    / "wikipedia_targets"
    / f"enwiki-{DEFAULT_DUMP_DATE}-candidate-pages.jsonl"
)
DEFAULT_SPOT_CHECK_TITLES = [
    "Aa achalensis",
    "Homo sapiens",
    "Lion",
    "Monarch butterfly",
    "? Nycticebus linglom",
]


HEADING_RE = re.compile(r"(?m)^==[^=].*?==\s*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
REF_BLOCK_RE = re.compile(r"<ref\b[^>/]*?>.*?</ref>", re.IGNORECASE | re.DOTALL)
REF_SELF_CLOSING_RE = re.compile(r"<ref\b[^>]*/\s*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
EXTERNAL_LINK_RE = re.compile(r"\[(?:https?|ftp)://[^\s\]]+\s+([^\]]+)\]")
BARE_EXTERNAL_LINK_RE = re.compile(r"\[(?:https?|ftp)://[^\]]+\]")
WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
TABLE_RE = re.compile(r"\{\|.*?\|\}", re.DOTALL)
TEMPLATE_RE = re.compile(r"\{\{")
REDIRECT_RE = re.compile(r"(?im)^\s*#redirect\s*:?\s*\[\[([^\]]+)\]\]")
DISPLAY_TITLE_RE = re.compile(r"(?is)\{\{\s*DISPLAYTITLE\s*:[^}]+\}\}")


@dataclass(frozen=True)
class IndexEntry:
    """A page entry from the multistream index."""

    title: str
    page_id: str
    offset: int


@dataclass
class ExtractedPage:
    """A parsed and cleaned Wikipedia page."""

    title: str
    page_id: str
    revision_id: str
    timestamp: str
    raw_wikitext: str
    lead_wikitext: str
    description: str
    redirect_title: str = ""

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\b\w+\b", self.description))

    @property
    def is_redirect(self) -> bool:
        return bool(self.redirect_title)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
        help="Matching pages-articles multistream index",
    )
    parser.add_argument(
        "--candidate-db",
        type=Path,
        default=DEFAULT_CANDIDATE_DB,
        help="Candidate tree SQLite DB used for path metadata",
    )
    parser.add_argument(
        "--target-pages",
        type=Path,
        default=DEFAULT_TARGET_PAGES,
        help="Candidate target JSONL from export_wikipedia_targets.py",
    )
    parser.add_argument(
        "--title",
        action="append",
        dest="titles",
        help="Page title to extract; can be passed multiple times",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Extract the first N titles from the target JSONL instead of defaults",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSONL output path for extracted page records",
    )
    parser.add_argument(
        "--max-description-chars",
        type=int,
        default=900,
        help="Maximum description characters to print per page",
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
        help="Maximum redirect hops to follow during extraction",
    )
    return parser


def load_requested_titles(args: argparse.Namespace) -> list[str]:
    """Resolve titles from CLI flags, a target sample, or defaults."""
    if args.titles:
        return list(dict.fromkeys(args.titles))

    if args.sample:
        titles = []
        with open(args.target_pages, encoding="utf-8") as f:
            for line in f:
                if len(titles) >= args.sample:
                    break
                record = json.loads(line)
                titles.append(record["title"])
        return titles

    return DEFAULT_SPOT_CHECK_TITLES


def find_index_entries(index_path: Path, titles: set[str]) -> dict[str, IndexEntry]:
    """Find selected page titles in the compressed multistream index."""
    entries = {}
    with bz2.open(index_path, "rt", encoding="utf-8") as f:
        for line in f:
            offset, page_id, title = line.rstrip("\n").split(":", 2)
            if title in titles:
                entries[title] = IndexEntry(
                    title=title,
                    page_id=page_id,
                    offset=int(offset),
                )
                if len(entries) == len(titles):
                    break
    return entries


def read_bzip2_stream_at(xml_dump_path: Path, offset: int) -> bytes:
    """Decompress exactly one bzip2 member starting at a multistream offset."""
    decompressor = bz2.BZ2Decompressor()
    chunks = []
    with open(xml_dump_path, "rb") as f:
        f.seek(offset)
        while not decompressor.eof:
            compressed = f.read(1024 * 1024)
            if not compressed:
                break
            chunks.append(decompressor.decompress(compressed))
    return b"".join(chunks)


def parse_pages_from_stream(xml_bytes: bytes) -> dict[str, ExtractedPage]:
    """Parse all page records from a decompressed multistream XML member."""
    root = ET.fromstring(b"<root>" + xml_bytes + b"</root>")
    pages = {}
    for page in root.findall("page"):
        title = page.findtext("title", default="")
        redirect_el = page.find("redirect")
        revision = page.find("revision")
        text_el = revision.find("text") if revision is not None else None
        raw_wikitext = text_el.text if text_el is not None and text_el.text else ""
        redirect_match = REDIRECT_RE.search(raw_wikitext)
        redirect_title = redirect_el.get("title", "") if redirect_el is not None else ""
        if not redirect_title and redirect_match:
            redirect_title = redirect_match.group(1).split("|", 1)[0]

        lead_wikitext = extract_lead_wikitext(raw_wikitext)
        description = clean_wikitext_lead(lead_wikitext)

        pages[title] = ExtractedPage(
            title=title,
            page_id=page.findtext("id", default=""),
            revision_id=revision.findtext("id", default="") if revision is not None else "",
            timestamp=revision.findtext("timestamp", default="")
            if revision is not None
            else "",
            raw_wikitext=raw_wikitext,
            lead_wikitext=lead_wikitext,
            description=description,
            redirect_title=redirect_title,
        )
    return pages


def extract_lead_wikitext(wikitext: str) -> str:
    """Return page wikitext before the first top-level heading."""
    match = HEADING_RE.search(wikitext)
    return wikitext[: match.start()] if match else wikitext


def clean_wikitext_lead(wikitext: str, *, paragraphs: int = 2) -> str:
    """Clean enough lead-section wikitext for description spot checks."""
    redirect = REDIRECT_RE.search(wikitext)
    if redirect:
        return ""

    text = html.unescape(wikitext)
    text = COMMENT_RE.sub("", text)
    text = DISPLAY_TITLE_RE.sub("", text)
    text = REF_BLOCK_RE.sub("", text)
    text = REF_SELF_CLOSING_RE.sub("", text)
    text = TABLE_RE.sub("", text)
    text = _replace_selected_templates(text)
    text = _remove_balanced_templates(text)
    text = _replace_wikilinks(text)
    text = EXTERNAL_LINK_RE.sub(r"\1", text)
    text = BARE_EXTERNAL_LINK_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"(?m)^\s*(\[\[Category:[^\]]+\]\]|\{\{DEFAULTSORT:[^}]+\}\})\s*$", "", text)
    text = re.sub(r"(?m)^\s*__[A-Z_]+__\s*$", "", text)

    cleaned_paragraphs = []
    for paragraph in re.split(r"\n\s*\n+", text):
        paragraph = _clean_paragraph(paragraph)
        if not paragraph:
            continue
        cleaned_paragraphs.append(paragraph)
        if len(cleaned_paragraphs) >= paragraphs:
            break

    return "\n\n".join(cleaned_paragraphs)


def _replace_selected_templates(text: str) -> str:
    """Replace simple templates that carry useful prose."""
    simple_template_re = re.compile(r"\{\{([^{}]+)\}\}")

    def replacement(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split("|")]
        name = parts[0].casefold()
        positional = [part for part in parts[1:] if "=" not in part]

        if name in {"gloss", "nowrap", "nobr", "small"} and positional:
            return positional[0]
        if name in {"lang", "langx", "lang-la", "lang-grc"} and len(positional) >= 2:
            return positional[1]
        if name in {"convert", "cvt"}:
            return _format_convert_template(positional)
        return match.group(0)

    previous = None
    while previous != text:
        previous = text
        text = simple_template_re.sub(replacement, text)
    return text


def _format_convert_template(parts: list[str]) -> str:
    """Return a compact approximation of common convert/cvt templates."""
    if len(parts) >= 4 and parts[1] in {"-", "–", "—", "to"}:
        separator = "–" if parts[1] in {"-", "–", "—"} else " to "
        return f"{parts[0]}{separator}{parts[2]} {parts[3]}"
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return " ".join(parts)


def _remove_balanced_templates(text: str) -> str:
    """Remove balanced ``{{...}}`` spans, including nested templates."""
    while TEMPLATE_RE.search(text):
        output = []
        index = 0
        removed_any = False
        while index < len(text):
            if text.startswith("{{", index):
                depth = 1
                index += 2
                while index < len(text) and depth:
                    if text.startswith("{{", index):
                        depth += 1
                        index += 2
                    elif text.startswith("}}", index):
                        depth -= 1
                        index += 2
                    else:
                        index += 1
                removed_any = True
            else:
                output.append(text[index])
                index += 1
        text = "".join(output)
        if not removed_any:
            break
    return text


def _replace_wikilinks(text: str) -> str:
    """Replace simple MediaWiki links with display text."""
    def replacement(match: re.Match[str]) -> str:
        target = match.group(1)
        parts = target.split("|")
        page_title = parts[0]
        display = parts[-1] if len(parts) > 1 else page_title
        namespace = page_title.split(":", 1)[0].lower() if ":" in page_title else ""
        if namespace in {"category", "file", "image"}:
            return ""
        return display.replace("_", " ")

    previous = None
    while previous != text:
        previous = text
        text = WIKILINK_RE.sub(replacement, text)
    return text


def _clean_paragraph(paragraph: str) -> str:
    """Normalize one candidate paragraph."""
    lines = []
    for line in paragraph.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("*", "|", "!", "{", "}", "[[Category:")):
            continue
        lines.append(stripped)

    paragraph = " ".join(lines)
    paragraph = re.sub(r"\s+", " ", paragraph)
    paragraph = re.sub(r"\s+([,.;:!?])", r"\1", paragraph)
    return paragraph.strip()


def load_candidate_metadata(
    candidate_db: Path,
    titles: set[str],
) -> dict[str, list[dict[str, object]]]:
    """Load candidate species metadata keyed by Wikipedia dump title."""
    if not candidate_db.exists():
        return {}

    metadata: dict[str, list[dict[str, object]]] = {title: [] for title in titles}
    with sqlite3.connect(candidate_db) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
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
            """
        ):
            try:
                title, _ = title_from_wikipedia_url(row["wikipedia_url"])
            except ValueError:
                continue
            if title not in titles:
                continue
            metadata[title].append(
                {
                    "wikidata_id": row["wikidata_id"],
                    "scientific_name": row["scientific_name"],
                    "accepted_species": row["species"],
                    "gbif_id": row["gbif_id"],
                    "match_type": row["match_type"],
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
    return metadata


def extract_pages(
    *,
    xml_dump: Path,
    index: Path,
    titles: list[str],
    candidate_db: Path,
    paragraphs: int,
    max_redirects: int,
) -> tuple[list[dict[str, object]], set[str]]:
    """Extract selected pages and return serializable records."""
    requested_title_set = set(titles)
    metadata_by_title = load_candidate_metadata(candidate_db, requested_title_set)

    pages_by_title: dict[str, ExtractedPage] = {}
    known_index_entries: dict[str, IndexEntry] = {}
    titles_to_fetch = set(titles)

    for _ in range(max_redirects + 1):
        titles_to_lookup = titles_to_fetch - set(known_index_entries)
        if titles_to_lookup:
            found_entries = find_index_entries(index, titles_to_lookup)
            known_index_entries.update(found_entries)

        offsets = sorted(
            {
                entry.offset
                for title, entry in known_index_entries.items()
                if title in titles_to_fetch and title not in pages_by_title
            }
        )
        for offset in offsets:
            xml_bytes = read_bzip2_stream_at(xml_dump, offset)
            chunk_pages = parse_pages_from_stream(xml_bytes)
            for title in titles_to_fetch:
                if title in chunk_pages:
                    page = chunk_pages[title]
                    page.description = clean_wikitext_lead(
                        page.lead_wikitext,
                        paragraphs=paragraphs,
                    )
                    pages_by_title[title] = page

        redirect_targets = {
            page.redirect_title
            for page in pages_by_title.values()
            if page.redirect_title and page.redirect_title not in pages_by_title
        }
        new_redirect_targets = redirect_targets - titles_to_fetch
        if not new_redirect_targets:
            break
        titles_to_fetch.update(new_redirect_targets)

    records = []
    for title in titles:
        page, redirect_chain = _resolve_redirect_chain(
            title,
            pages_by_title,
            max_redirects=max_redirects,
        )
        if page is None:
            continue
        records.append(
            {
                "title": page.title,
                "requested_title": title,
                "resolved_title": page.title,
                "page_id": page.page_id,
                "revision_id": page.revision_id,
                "timestamp": page.timestamp,
                "redirect_title": page.redirect_title,
                "redirect_chain": redirect_chain,
                "description": page.description,
                "word_count": page.word_count,
                "candidate_count": len(metadata_by_title.get(title, [])),
                "candidates": metadata_by_title.get(title, []),
            }
        )

    missing_requested = requested_title_set - set(known_index_entries)
    return records, missing_requested


def _resolve_redirect_chain(
    title: str,
    pages_by_title: dict[str, ExtractedPage],
    *,
    max_redirects: int,
) -> tuple[ExtractedPage | None, list[str]]:
    """Follow a fetched redirect chain and return the resolved page."""
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


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """Write extracted records to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def print_records(records: list[dict[str, object]], *, max_description_chars: int) -> None:
    """Print spot-check records in a compact human-readable format."""
    print("\nEXTRACTED PAGE SPOT CHECKS")
    print("=" * 80)
    for record in records:
        print(f"\n{record['requested_title']}")
        print("-" * 80)
        if record["requested_title"] != record["resolved_title"]:
            print(f"  Resolved to:   {record['resolved_title']}")
        print(f"  Page ID:       {record['page_id']}")
        print(f"  Revision ID:   {record['revision_id']}")
        print(f"  Timestamp:     {record['timestamp']}")
        redirect_chain = record.get("redirect_chain", [])
        if len(redirect_chain) > 1:
            print(f"  Redirect chain: {' -> '.join(redirect_chain)}")
        print(f"  Word count:    {record['word_count']}")
        print(f"  Candidates:    {record['candidate_count']}")

        candidates = record.get("candidates", [])
        if candidates:
            first = candidates[0]
            print(f"  Scientific:    {first['scientific_name']}")
            print(f"  Accepted:      {first['accepted_species']}")
            print(f"  GBIF/Wikidata: {first['gbif_id']} / {first['wikidata_id']}")
            print(f"  Path:          {' -> '.join(first['path'])}")

        description = str(record["description"])
        if len(description) > max_description_chars:
            description = description[: max_description_chars - 3].rstrip() + "..."
        print("\n" + description)


def main() -> None:
    args = build_parser().parse_args()
    titles = load_requested_titles(args)

    print("WIKIPEDIA DESCRIPTION EXTRACTION")
    print("=" * 80)
    print(f"  XML dump:      {args.xml_dump}")
    print(f"  Index:         {args.index}")
    print(f"  Requested:     {len(titles):,} titles")

    records, missing = extract_pages(
        xml_dump=args.xml_dump,
        index=args.index,
        titles=titles,
        candidate_db=args.candidate_db,
        paragraphs=args.paragraphs,
        max_redirects=args.max_redirects,
    )

    print(f"  Extracted:     {len(records):,} pages")
    print(f"  Missing index: {len(missing):,} titles")
    if missing:
        print("  Missing sample:")
        for title in sorted(missing, key=str.casefold)[:10]:
            print(f"    - {title}")

    if args.output:
        write_jsonl(args.output, records)
        print(f"  Output:        {args.output}")

    print_records(records, max_description_chars=args.max_description_chars)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
