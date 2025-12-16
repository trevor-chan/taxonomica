"""GBIF Backbone Taxonomy parser.

This module provides classes for parsing the GBIF Backbone Taxonomy
Darwin Core Archive, which has complete taxonomic hierarchies via
parent-child relationships.

The GBIF Backbone is the authoritative taxonomy used by GBIF.org,
synthesized from 100+ sources including Catalogue of Life.

Reference: https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Increase CSV field size limit for large fields in GBIF data
csv.field_size_limit(sys.maxsize)


@dataclass
class GBIFTaxon:
    """A taxonomic record from the GBIF Backbone.

    The GBIF Backbone has explicit parent-child relationships via
    parentNameUsageID, plus denormalized hierarchy fields.
    """

    id: str
    parent_id: str = ""
    accepted_id: str = ""  # For synonyms, points to accepted taxon
    scientific_name: str = ""
    canonical_name: str = ""  # Name without authorship
    authorship: str = ""
    generic_name: str = ""  # Genus part of binomial
    specific_epithet: str = ""  # Species part of binomial
    infraspecific_epithet: str = ""
    rank: str = ""
    taxonomic_status: str = ""  # accepted, synonym, doubtful, etc.
    nomenclatural_status: str = ""
    # Denormalized hierarchy
    kingdom: str = ""
    phylum: str = ""
    class_: str = ""
    order: str = ""
    family: str = ""
    genus: str = ""

    @property
    def is_accepted(self) -> bool:
        """Check if this is an accepted taxon (not a synonym)."""
        return self.taxonomic_status == "accepted"

    @property
    def is_synonym(self) -> bool:
        """Check if this is a synonym."""
        return self.taxonomic_status == "synonym"

    @property
    def display_name(self) -> str:
        """Get a display-friendly name (canonical if available, else scientific)."""
        return self.canonical_name or self.scientific_name


@dataclass
class GBIFVernacularName:
    """A vernacular (common) name for a taxon."""

    taxon_id: str
    name: str
    language: str = ""
    country: str = ""
    country_code: str = ""
    source: str = ""


@dataclass
class GBIFMultimedia:
    """Multimedia record for a taxon."""

    taxon_id: str
    identifier: str = ""  # URL to media
    references: str = ""
    title: str = ""
    description: str = ""
    license: str = ""
    creator: str = ""
    source: str = ""


class GBIFBackbone:
    """Parser for the GBIF Backbone Taxonomy Darwin Core Archive.

    This parser is optimized for the GBIF Backbone structure which uses
    TSV files with headers, and has explicit parent-child relationships.

    Example:
        >>> backbone = GBIFBackbone("backbone")
        >>> for taxon in backbone.iter_taxa():
        ...     if taxon.is_accepted:
        ...         print(f"{taxon.canonical_name} ({taxon.rank})")
    """

    def __init__(self, archive_path: str | Path) -> None:
        """Initialize the backbone parser.

        Args:
            archive_path: Path to the directory containing the archive files.
        """
        self.path = Path(archive_path)

        # Verify required files exist
        self.taxon_file = self.path / "Taxon.tsv"
        if not self.taxon_file.exists():
            raise FileNotFoundError(f"Taxon.tsv not found in {self.path}")

    def iter_taxa(self, *, accepted_only: bool = False) -> Iterator[GBIFTaxon]:
        """Iterate over all taxa in the backbone.

        Args:
            accepted_only: If True, only yield accepted taxa (skip synonyms).

        Yields:
            GBIFTaxon objects for each record.
        """
        with open(self.taxon_file, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")

            for row in reader:
                taxon = GBIFTaxon(
                    id=row.get("taxonID", ""),
                    parent_id=row.get("parentNameUsageID", ""),
                    accepted_id=row.get("acceptedNameUsageID", ""),
                    scientific_name=row.get("scientificName", ""),
                    canonical_name=row.get("canonicalName", ""),
                    authorship=row.get("scientificNameAuthorship", ""),
                    generic_name=row.get("genericName", ""),
                    specific_epithet=row.get("specificEpithet", ""),
                    infraspecific_epithet=row.get("infraspecificEpithet", ""),
                    rank=row.get("taxonRank", ""),
                    taxonomic_status=row.get("taxonomicStatus", ""),
                    nomenclatural_status=row.get("nomenclaturalStatus", ""),
                    kingdom=row.get("kingdom", ""),
                    phylum=row.get("phylum", ""),
                    class_=row.get("class", ""),
                    order=row.get("order", ""),
                    family=row.get("family", ""),
                    genus=row.get("genus", ""),
                )

                if accepted_only and not taxon.is_accepted:
                    continue

                yield taxon

    def iter_vernacular_names(self) -> Iterator[GBIFVernacularName]:
        """Iterate over all vernacular names.

        Yields:
            GBIFVernacularName objects for each record.
        """
        vn_file = self.path / "VernacularName.tsv"
        if not vn_file.exists():
            return

        with open(vn_file, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")

            for row in reader:
                yield GBIFVernacularName(
                    taxon_id=row.get("taxonID", ""),
                    name=row.get("vernacularName", ""),
                    language=row.get("language", ""),
                    country=row.get("country", ""),
                    country_code=row.get("countryCode", ""),
                    source=row.get("source", ""),
                )

    def iter_multimedia(self) -> Iterator[GBIFMultimedia]:
        """Iterate over all multimedia records.

        Yields:
            GBIFMultimedia objects for each record.
        """
        mm_file = self.path / "Multimedia.tsv"
        if not mm_file.exists():
            return

        with open(mm_file, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")

            for row in reader:
                yield GBIFMultimedia(
                    taxon_id=row.get("taxonID", ""),
                    identifier=row.get("identifier", ""),
                    references=row.get("references", ""),
                    title=row.get("title", ""),
                    description=row.get("description", ""),
                    license=row.get("license", ""),
                    creator=row.get("creator", ""),
                    source=row.get("source", ""),
                )

    def get_taxon_by_id(self, taxon_id: str) -> GBIFTaxon | None:
        """Find a single taxon by ID.

        Note: This scans the file sequentially. For repeated lookups,
        consider building an index.

        Args:
            taxon_id: The taxon ID to find.

        Returns:
            The matching taxon, or None if not found.
        """
        for taxon in self.iter_taxa():
            if taxon.id == taxon_id:
                return taxon
        return None

    def count_taxa(self, *, accepted_only: bool = False) -> int:
        """Count the total number of taxa.

        Args:
            accepted_only: If True, only count accepted taxa.

        Returns:
            The count of taxa.
        """
        return sum(1 for _ in self.iter_taxa(accepted_only=accepted_only))

    def get_rank_distribution(self, *, accepted_only: bool = True) -> dict[str, int]:
        """Get the distribution of taxonomic ranks.

        Args:
            accepted_only: If True, only count accepted taxa.

        Returns:
            Dictionary mapping rank names to counts.
        """
        distribution: dict[str, int] = {}
        for taxon in self.iter_taxa(accepted_only=accepted_only):
            rank = taxon.rank or "unknown"
            distribution[rank] = distribution.get(rank, 0) + 1
        return distribution

