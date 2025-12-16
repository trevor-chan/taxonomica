"""Darwin Core Archive (DwC-A) parser for taxonomic data.

This module provides classes for parsing Darwin Core Archive files,
specifically tailored for the Wikipedia species pages dataset.

The Darwin Core Archive format consists of:
- meta.xml: Archive descriptor defining file structure
- Core file (taxon.txt): Main taxonomic data
- Extension files: Additional data linked to core records

Reference: https://en.wikipedia.org/wiki/Darwin_Core_Archive
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


# Darwin Core namespace
DWC_NS = "http://rs.tdwg.org/dwc/text/"


@dataclass
class FieldDefinition:
    """Definition of a field/column in a DwC-A file."""

    index: int
    term: str

    @property
    def name(self) -> str:
        """Extract the field name from the term URI."""
        # Get the last part of the URI path or fragment
        if "#" in self.term:
            return self.term.split("#")[-1]
        return self.term.rsplit("/", 1)[-1]


@dataclass
class FileDescriptor:
    """Descriptor for a file within the archive."""

    location: str
    encoding: str
    fields_terminated_by: str
    lines_terminated_by: str
    fields_enclosed_by: str
    ignore_header_lines: int
    row_type: str
    id_index: int | None  # For core file
    coreid_index: int | None  # For extension files
    fields: list[FieldDefinition] = field(default_factory=list)

    @property
    def is_core(self) -> bool:
        """Check if this is the core file (has id) vs extension (has coreid)."""
        return self.id_index is not None


@dataclass
class Taxon:
    """A taxonomic record from the core taxon file."""

    id: str
    references: str = ""
    modified: str = ""
    scientific_name: str = ""
    scientific_name_authorship: str = ""
    rank: str = ""
    verbatim_rank: str = ""
    kingdom: str = ""
    phylum: str = ""
    class_: str = ""  # 'class' is a Python keyword
    order: str = ""
    family: str = ""
    genus: str = ""
    subgenus: str = ""
    taxon_remarks: str = ""
    trend: str = ""
    fossil_range: str = ""
    taxobox: str = ""
    accepted_name_usage: str = ""
    accepted_name_usage_id: str = ""
    taxonomic_status: str = ""


@dataclass
class VernacularName:
    """A vernacular (common) name for a taxon."""

    taxon_id: str
    is_preferred: bool
    language: str
    name: str


@dataclass
class SpeciesProfile:
    """Species profile information (extinction status, living period)."""

    taxon_id: str
    is_extinct: bool
    living_period: str


@dataclass
class Multimedia:
    """Multimedia (image) record for a taxon."""

    taxon_id: str
    title: str = ""
    created: str = ""
    type: str = ""
    identifier: str = ""  # URL to the image
    creator: str = ""
    references: str = ""
    description: str = ""
    publisher: str = ""
    license: str = ""
    source: str = ""


@dataclass
class Description:
    """Text description for a taxon."""

    taxon_id: str
    language: str = ""
    type: str = ""
    description: str = ""
    references: str = ""
    license: str = ""


@dataclass
class TypeSpecimen:
    """Type specimen record for a taxon."""

    taxon_id: str
    scientific_name: str = ""
    type_status: str = ""


class DarwinCoreArchive:
    """Parser for Darwin Core Archive files.

    This class handles reading and parsing DwC-A files, providing
    iterators for efficient access to large datasets.

    Example:
        >>> archive = DarwinCoreArchive("wikipedia-en-dwca")
        >>> for taxon in archive.iter_taxa():
        ...     print(f"{taxon.scientific_name}: {taxon.rank}")
    """

    def __init__(self, archive_path: str | Path) -> None:
        """Initialize the archive parser.

        Args:
            archive_path: Path to the directory containing the archive files.
        """
        self.path = Path(archive_path)
        self._meta: ET.Element | None = None
        self._core: FileDescriptor | None = None
        self._extensions: dict[str, FileDescriptor] = {}
        self._parse_meta()

    def _parse_meta(self) -> None:
        """Parse the meta.xml archive descriptor."""
        meta_path = self.path / "meta.xml"
        if not meta_path.exists():
            raise FileNotFoundError(f"meta.xml not found in {self.path}")

        tree = ET.parse(meta_path)
        self._meta = tree.getroot()

        # Parse core file descriptor
        core_elem = self._meta.find(f"{{{DWC_NS}}}core")
        if core_elem is not None:
            self._core = self._parse_file_descriptor(core_elem, is_core=True)

        # Parse extension file descriptors
        for ext_elem in self._meta.findall(f"{{{DWC_NS}}}extension"):
            ext_desc = self._parse_file_descriptor(ext_elem, is_core=False)
            self._extensions[ext_desc.row_type] = ext_desc

    def _parse_file_descriptor(
        self, element: ET.Element, *, is_core: bool
    ) -> FileDescriptor:
        """Parse a file descriptor from an XML element."""
        # Get file location
        files_elem = element.find(f"{{{DWC_NS}}}files")
        location_elem = files_elem.find(f"{{{DWC_NS}}}location") if files_elem else None
        location = location_elem.text if location_elem is not None else ""

        # Parse fields
        fields = []
        for field_elem in element.findall(f"{{{DWC_NS}}}field"):
            idx = int(field_elem.get("index", 0))
            term = field_elem.get("term", "")
            fields.append(FieldDefinition(index=idx, term=term))

        # Sort fields by index
        fields.sort(key=lambda f: f.index)

        # Get id/coreid index
        id_index = None
        coreid_index = None
        if is_core:
            id_elem = element.find(f"{{{DWC_NS}}}id")
            if id_elem is not None:
                id_index = int(id_elem.get("index", 0))
        else:
            coreid_elem = element.find(f"{{{DWC_NS}}}coreid")
            if coreid_elem is not None:
                coreid_index = int(coreid_elem.get("index", 0))

        # Handle escape sequences in delimiters
        fields_terminated_by = element.get("fieldsTerminatedBy", "\t")
        if fields_terminated_by == "\\t":
            fields_terminated_by = "\t"

        lines_terminated_by = element.get("linesTerminatedBy", "\n")
        if lines_terminated_by == "\\n":
            lines_terminated_by = "\n"

        return FileDescriptor(
            location=location or "",
            encoding=element.get("encoding", "utf-8"),
            fields_terminated_by=fields_terminated_by,
            lines_terminated_by=lines_terminated_by,
            fields_enclosed_by=element.get("fieldsEnclosedBy", ""),
            ignore_header_lines=int(element.get("ignoreHeaderLines", 0)),
            row_type=element.get("rowType", ""),
            id_index=id_index,
            coreid_index=coreid_index,
            fields=fields,
        )

    def _iter_rows(self, descriptor: FileDescriptor) -> Iterator[list[str]]:
        """Iterate over rows in a data file."""
        file_path = self.path / descriptor.location
        if not file_path.exists():
            return

        with open(file_path, encoding=descriptor.encoding, newline="") as f:
            # Skip header lines if specified
            for _ in range(descriptor.ignore_header_lines):
                next(f, None)

            reader = csv.reader(f, delimiter=descriptor.fields_terminated_by)
            yield from reader

    def _get_field_value(
        self, row: list[str], fields: list[FieldDefinition], field_name: str
    ) -> str:
        """Get a field value from a row by field name."""
        for field_def in fields:
            if field_def.name == field_name:
                if field_def.index < len(row):
                    return row[field_def.index]
                return ""
        return ""

    @property
    def core_descriptor(self) -> FileDescriptor | None:
        """Get the core file descriptor."""
        return self._core

    @property
    def extension_descriptors(self) -> dict[str, FileDescriptor]:
        """Get all extension file descriptors."""
        return self._extensions

    def iter_taxa(self) -> Iterator[Taxon]:
        """Iterate over all taxa in the archive.

        Yields:
            Taxon objects for each record in the core taxon file.
        """
        if self._core is None:
            return

        for row in self._iter_rows(self._core):
            # Get field values by name
            gv = lambda name: self._get_field_value(row, self._core.fields, name)

            # Get the ID from the id index
            taxon_id = row[self._core.id_index] if self._core.id_index is not None else ""

            yield Taxon(
                id=taxon_id,
                references=gv("references"),
                modified=gv("modified"),
                scientific_name=gv("scientificName"),
                scientific_name_authorship=gv("scientificNameAuthorship"),
                rank=gv("taxonRank"),
                verbatim_rank=gv("verbatimTaxonRank"),
                kingdom=gv("kingdom"),
                phylum=gv("phylum"),
                class_=gv("class"),
                order=gv("order"),
                family=gv("family"),
                genus=gv("genus"),
                subgenus=gv("subgenus"),
                taxon_remarks=gv("taxonRemarks"),
                trend=gv("trend"),
                fossil_range=gv("fossilRange"),
                taxobox=gv("taxobox"),
                accepted_name_usage=gv("acceptedNameUsage"),
                accepted_name_usage_id=gv("acceptedNameUsageID"),
                taxonomic_status=gv("taxonomicStatus"),
            )

    def iter_vernacular_names(self) -> Iterator[VernacularName]:
        """Iterate over all vernacular names in the archive.

        Yields:
            VernacularName objects for each record.
        """
        row_type = "http://rs.gbif.org/terms/1.0/VernacularName"
        if row_type not in self._extensions:
            return

        desc = self._extensions[row_type]
        for row in self._iter_rows(desc):
            gv = lambda name: self._get_field_value(row, desc.fields, name)
            taxon_id = row[desc.coreid_index] if desc.coreid_index is not None else ""

            is_preferred_str = gv("isPreferredName").lower()
            is_preferred = is_preferred_str in ("true", "yes", "1")

            yield VernacularName(
                taxon_id=taxon_id,
                is_preferred=is_preferred,
                language=gv("language"),
                name=gv("vernacularName"),
            )

    def iter_species_profiles(self) -> Iterator[SpeciesProfile]:
        """Iterate over all species profiles in the archive.

        Yields:
            SpeciesProfile objects for each record.
        """
        row_type = "http://rs.gbif.org/terms/1.0/SpeciesProfile"
        if row_type not in self._extensions:
            return

        desc = self._extensions[row_type]
        for row in self._iter_rows(desc):
            gv = lambda name: self._get_field_value(row, desc.fields, name)
            taxon_id = row[desc.coreid_index] if desc.coreid_index is not None else ""

            is_extinct_str = gv("isExtinct").lower()
            is_extinct = is_extinct_str in ("true", "yes", "1")

            yield SpeciesProfile(
                taxon_id=taxon_id,
                is_extinct=is_extinct,
                living_period=gv("livingPeriod"),
            )

    def iter_multimedia(self) -> Iterator[Multimedia]:
        """Iterate over all multimedia records in the archive.

        Yields:
            Multimedia objects for each record.
        """
        row_type = "http://rs.gbif.org/terms/1.0/Multimedia"
        if row_type not in self._extensions:
            return

        desc = self._extensions[row_type]
        for row in self._iter_rows(desc):
            gv = lambda name: self._get_field_value(row, desc.fields, name)
            taxon_id = row[desc.coreid_index] if desc.coreid_index is not None else ""

            yield Multimedia(
                taxon_id=taxon_id,
                title=gv("title"),
                created=gv("created"),
                type=gv("type"),
                identifier=gv("identifier"),
                creator=gv("creator"),
                references=gv("references"),
                description=gv("description"),
                publisher=gv("publisher"),
                license=gv("license"),
                source=gv("source"),
            )

    def iter_descriptions(self) -> Iterator[Description]:
        """Iterate over all description records in the archive.

        Yields:
            Description objects for each record.
        """
        row_type = "http://rs.gbif.org/terms/1.0/Description"
        if row_type not in self._extensions:
            return

        desc = self._extensions[row_type]
        for row in self._iter_rows(desc):
            gv = lambda name: self._get_field_value(row, desc.fields, name)
            taxon_id = row[desc.coreid_index] if desc.coreid_index is not None else ""

            yield Description(
                taxon_id=taxon_id,
                language=gv("language"),
                type=gv("type"),
                description=gv("description"),
                references=gv("references"),
                license=gv("license"),
            )

    def iter_type_specimens(self) -> Iterator[TypeSpecimen]:
        """Iterate over all type specimen records in the archive.

        Yields:
            TypeSpecimen objects for each record.
        """
        row_type = "http://rs.gbif.org/terms/1.0/TypesAndSpecimen"
        if row_type not in self._extensions:
            return

        desc = self._extensions[row_type]
        for row in self._iter_rows(desc):
            gv = lambda name: self._get_field_value(row, desc.fields, name)
            taxon_id = row[desc.coreid_index] if desc.coreid_index is not None else ""

            yield TypeSpecimen(
                taxon_id=taxon_id,
                scientific_name=gv("scientificName"),
                type_status=gv("typeStatus"),
            )

    def get_vernacular_names_by_taxon(self) -> dict[str, list[VernacularName]]:
        """Build a mapping from taxon ID to vernacular names.

        Returns:
            Dictionary mapping taxon IDs to lists of vernacular names.
        """
        result: dict[str, list[VernacularName]] = {}
        for vn in self.iter_vernacular_names():
            if vn.taxon_id not in result:
                result[vn.taxon_id] = []
            result[vn.taxon_id].append(vn)
        return result

    def get_species_profiles_by_taxon(self) -> dict[str, SpeciesProfile]:
        """Build a mapping from taxon ID to species profile.

        Returns:
            Dictionary mapping taxon IDs to species profiles.
        """
        return {sp.taxon_id: sp for sp in self.iter_species_profiles()}

    def count_taxa(self) -> int:
        """Count the total number of taxa in the archive."""
        return sum(1 for _ in self.iter_taxa())

    def get_rank_distribution(self) -> dict[str, int]:
        """Get the distribution of taxonomic ranks.

        Returns:
            Dictionary mapping rank names to counts.
        """
        distribution: dict[str, int] = {}
        for taxon in self.iter_taxa():
            rank = taxon.rank or "unknown"
            distribution[rank] = distribution.get(rank, 0) + 1
        return distribution

