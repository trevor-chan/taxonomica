"""Catalogue of Life Data Package (ColDP) reader.

This module reads ColDP archives produced by tools such as
``coldp-generator``.  It supports both ZIP archives and extracted
directories, and focuses on the tables currently useful for Taxonomica:
``NameUsage.tsv``, ``VernacularName.tsv``, and ``Media.tsv``.
"""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterator


csv.field_size_limit(sys.maxsize)

EN_WIKIPEDIA_RE = re.compile(r"https?://en\.wikipedia\.org/wiki/[^\s\t]+")


def _normalize_header(header: str) -> str:
    """Normalize ColDP column headers to stable field names."""
    header = header.strip()
    if ":" in header:
        header = header.split(":", 1)[1]
    if "#" in header:
        header = header.rsplit("#", 1)[1]
    if "/" in header:
        header = header.rsplit("/", 1)[1]
    return header


def extract_english_wikipedia_url(text: str) -> str:
    """Extract the first English Wikipedia URL from a ColDP text field."""
    match = EN_WIKIPEDIA_RE.search(text or "")
    return match.group(0) if match else ""


@dataclass
class ColdPNameUsage:
    """A row from ``NameUsage.tsv``."""

    id: str
    alternative_id: str = ""
    parent_id: str = ""
    basionym_id: str = ""
    status: str = ""
    name_status: str = ""
    rank: str = ""
    scientific_name: str = ""
    authorship: str = ""
    link: str = ""
    reference_id: str = ""
    remarks: str = ""

    @property
    def is_accepted(self) -> bool:
        """Return whether this name usage should be treated as accepted."""
        status = self.status.strip().lower()
        return status in {"", "accepted", "provisionally accepted"}

    @property
    def wikipedia_url(self) -> str:
        """English Wikipedia URL advertised by the source, if present."""
        return extract_english_wikipedia_url(self.remarks)

    @property
    def display_name(self) -> str:
        """Best display name for this usage."""
        return self.scientific_name or self.id


@dataclass
class ColdPVernacularName:
    """A row from ``VernacularName.tsv``."""

    taxon_id: str
    language: str = ""
    name: str = ""
    reference_id: str = ""


@dataclass
class ColdPMedia:
    """A row from ``Media.tsv``."""

    taxon_id: str
    url: str = ""
    type: str = ""
    format: str = ""
    title: str = ""
    creator: str = ""
    license: str = ""
    link: str = ""
    remarks: str = ""


class ColdPArchive:
    """Reader for a ColDP ZIP archive or extracted directory.

    Args:
        archive_path: Path to a ``.zip`` ColDP archive or a directory
            containing ColDP TSV files.
    """

    def __init__(self, archive_path: str | Path) -> None:
        self.path = Path(archive_path)
        if not self.path.exists():
            raise FileNotFoundError(f"ColDP archive not found: {self.path}")

        self._zip_members: list[str] | None = None
        if not self.has_table("NameUsage.tsv"):
            raise FileNotFoundError(f"NameUsage.tsv not found in {self.path}")

    @property
    def is_zip(self) -> bool:
        """Return whether this archive is stored as a ZIP file."""
        return self.path.is_file() and self.path.suffix.lower() == ".zip"

    def available_tables(self) -> list[str]:
        """List available top-level ColDP table names."""
        if self.is_zip:
            return sorted(Path(name).name for name in self._get_zip_members())
        if self.path.is_dir():
            return sorted(path.name for path in self.path.rglob("*.tsv"))
        return []

    def has_table(self, table_name: str) -> bool:
        """Return whether a table exists in the archive."""
        return self._resolve_table(table_name) is not None

    def iter_name_usages(
        self, *, accepted_only: bool = False
    ) -> Iterator[ColdPNameUsage]:
        """Iterate over rows in ``NameUsage.tsv``."""
        for row in self._iter_dicts("NameUsage.tsv"):
            usage = ColdPNameUsage(
                id=row.get("ID", ""),
                alternative_id=row.get("alternativeID", ""),
                parent_id=row.get("parentID", ""),
                basionym_id=row.get("basionymID", ""),
                status=row.get("status", ""),
                name_status=row.get("nameStatus", ""),
                rank=row.get("rank", ""),
                scientific_name=row.get("scientificName", ""),
                authorship=row.get("authorship", ""),
                link=row.get("link", ""),
                reference_id=row.get("referenceID", ""),
                remarks=row.get("remarks", ""),
            )
            if accepted_only and not usage.is_accepted:
                continue
            yield usage

    def iter_vernacular_names(self) -> Iterator[ColdPVernacularName]:
        """Iterate over rows in ``VernacularName.tsv`` if present."""
        if not self.has_table("VernacularName.tsv"):
            return

        for row in self._iter_dicts("VernacularName.tsv"):
            yield ColdPVernacularName(
                taxon_id=row.get("taxonID", ""),
                language=row.get("language", ""),
                name=row.get("name", ""),
                reference_id=row.get("referenceID", ""),
            )

    def iter_media(self) -> Iterator[ColdPMedia]:
        """Iterate over rows in ``Media.tsv`` if present."""
        if not self.has_table("Media.tsv"):
            return

        for row in self._iter_dicts("Media.tsv"):
            yield ColdPMedia(
                taxon_id=row.get("taxonID", ""),
                url=row.get("url", ""),
                type=row.get("type", ""),
                format=row.get("format", ""),
                title=row.get("title", ""),
                creator=row.get("creator", ""),
                license=row.get("license", ""),
                link=row.get("link", ""),
                remarks=row.get("remarks", ""),
            )

    def count_name_usages(self, *, accepted_only: bool = False) -> int:
        """Count rows in ``NameUsage.tsv``."""
        return sum(1 for _ in self.iter_name_usages(accepted_only=accepted_only))

    def _get_zip_members(self) -> list[str]:
        if self._zip_members is None:
            with zipfile.ZipFile(self.path) as archive:
                self._zip_members = archive.namelist()
        return self._zip_members

    def _resolve_table(self, table_name: str) -> str | Path | None:
        if self.is_zip:
            matches = [
                name
                for name in self._get_zip_members()
                if Path(name).name == table_name
            ]
            return matches[0] if matches else None

        if self.path.is_dir():
            direct = self.path / table_name
            if direct.exists():
                return direct

            matches = list(self.path.rglob(table_name))
            return matches[0] if matches else None

        return None

    @contextmanager
    def _open_table(self, table_name: str) -> Iterator[TextIO]:
        resolved = self._resolve_table(table_name)
        if resolved is None:
            raise FileNotFoundError(f"{table_name} not found in {self.path}")

        if self.is_zip:
            with zipfile.ZipFile(self.path) as archive:
                with archive.open(str(resolved)) as raw:
                    with open_text_stream(raw) as text:
                        yield text
        else:
            with open(resolved, encoding="utf-8", newline="") as text:
                yield text

    def _iter_dicts(self, table_name: str) -> Iterator[dict[str, str]]:
        with self._open_table(table_name) as text:
            reader = csv.reader(text, delimiter="\t")
            try:
                headers = [_normalize_header(header) for header in next(reader)]
            except StopIteration:
                return

            for row in reader:
                if len(row) < len(headers):
                    row.extend([""] * (len(headers) - len(row)))
                yield dict(zip(headers, row, strict=False))


@contextmanager
def open_text_stream(raw) -> Iterator[TextIO]:
    """Open a binary stream as UTF-8 text."""
    import io

    text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
    try:
        yield text
    finally:
        text.detach()
