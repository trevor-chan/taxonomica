"""Wikipedia species data loader.

This module provides access to Wikipedia species descriptions from the
Darwin Core Archive export, including matching species between GBIF
and Wikipedia datasets.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Increase CSV field size limit for large descriptions
csv.field_size_limit(sys.maxsize)


@dataclass
class WikipediaDescription:
    """A description section from a Wikipedia species page."""
    
    taxon_id: str
    section_type: str  # e.g., "Abstract", "Behavior", "Evolution"
    language: str
    text: str
    source_url: str = ""
    license: str = ""
    
    def clean_text(self) -> str:
        """Return text with HTML tags removed."""
        text = re.sub(r'<br\s*/?>', '\n', self.text)
        text = re.sub(r'<[^>]+>', '', text)
        return text


@dataclass
class WikipediaSpecies:
    """A species entry from the Wikipedia DwC-A export."""
    
    taxon_id: str
    scientific_name: str
    canonical_name: str = ""
    rank: str = ""
    wikipedia_url: str = ""
    descriptions: list[WikipediaDescription] = field(default_factory=list)
    vernacular_names: list[str] = field(default_factory=list)
    
    def get_abstract(self) -> str | None:
        """Get the abstract/summary description."""
        for desc in self.descriptions:
            if desc.section_type.lower() == "abstract":
                return desc.clean_text()
        return None
    
    def get_section(self, section_type: str) -> str | None:
        """Get a specific section by type."""
        for desc in self.descriptions:
            if desc.section_type.lower() == section_type.lower():
                return desc.clean_text()
        return None
    
    def get_all_text(self) -> str:
        """Get all description text concatenated."""
        return "\n\n".join(desc.clean_text() for desc in self.descriptions)


class WikipediaData:
    """Loader for Wikipedia species data from DwC-A export.
    
    This class provides methods to:
    - Load species by taxon ID
    - Search for species by scientific name
    - Match species between Wikipedia and GBIF datasets
    
    Example:
        >>> wiki = WikipediaData("wikipedia-en-dwca")
        >>> species = wiki.find_by_name("Felis catus")
        >>> if species:
        ...     print(species.get_abstract())
    """
    
    def __init__(self, archive_path: str | Path) -> None:
        """Initialize the Wikipedia data loader.
        
        Args:
            archive_path: Path to the Wikipedia DwC-A directory.
        """
        self.path = Path(archive_path)
        
        # Verify required files exist
        self.taxon_file = self.path / "taxon.txt"
        self.description_file = self.path / "description.txt"
        self.vernacular_file = self.path / "vernacularname.txt"
        
        if not self.taxon_file.exists():
            raise FileNotFoundError(f"taxon.txt not found in {self.path}")
        
        # Build indices on first access
        self._name_to_id: dict[str, list[str]] | None = None
        self._id_to_taxon: dict[str, dict] | None = None
    
    def _build_taxon_index(self) -> None:
        """Build index mapping names to taxon IDs."""
        if self._name_to_id is not None:
            return
        
        self._name_to_id = {}
        self._id_to_taxon = {}
        
        with open(self.taxon_file, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                # File format: taxon_id, wikipedia_url, date, scientific_name, authorship, rank, ...
                if len(parts) >= 4:
                    taxon_id = parts[0]
                    wikipedia_url = parts[1] if len(parts) > 1 else ""
                    scientific_name = parts[3] if len(parts) > 3 else ""
                    rank = parts[5] if len(parts) > 5 else ""
                    
                    # Skip synonym entries (they have "-syn" in ID)
                    if "-syn" in taxon_id:
                        continue
                    
                    # Store basic taxon info
                    self._id_to_taxon[taxon_id] = {
                        "id": taxon_id,
                        "scientific_name": scientific_name,
                        "rank": rank,
                        "wikipedia_url": wikipedia_url,
                    }
                    
                    # Index by name (lowercase for case-insensitive lookup)
                    name_key = scientific_name.lower()
                    if name_key not in self._name_to_id:
                        self._name_to_id[name_key] = []
                    self._name_to_id[name_key].append(taxon_id)
    
    def _load_descriptions(self, taxon_id: str) -> list[WikipediaDescription]:
        """Load all descriptions for a taxon ID."""
        descriptions = []
        
        if not self.description_file.exists():
            return descriptions
        
        with open(self.description_file, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 4 and parts[0] == taxon_id:
                    descriptions.append(WikipediaDescription(
                        taxon_id=parts[0],
                        language=parts[1] if len(parts) > 1 else "",
                        section_type=parts[2] if len(parts) > 2 else "",
                        text=parts[3] if len(parts) > 3 else "",
                        source_url=parts[4] if len(parts) > 4 else "",
                        license=parts[5] if len(parts) > 5 else "",
                    ))
        
        return descriptions
    
    def _load_vernacular_names(self, taxon_id: str) -> list[str]:
        """Load vernacular names for a taxon ID."""
        names = []
        
        if not self.vernacular_file.exists():
            return names
        
        with open(self.vernacular_file, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2 and parts[0] == taxon_id:
                    name = parts[1] if len(parts) > 1 else ""
                    if name:
                        names.append(name)
        
        return names
    
    def find_by_id(self, taxon_id: str) -> WikipediaSpecies | None:
        """Find a species by its Wikipedia taxon ID.
        
        Args:
            taxon_id: The Wikipedia taxon ID.
            
        Returns:
            WikipediaSpecies object or None if not found.
        """
        self._build_taxon_index()
        
        if taxon_id not in self._id_to_taxon:
            return None
        
        taxon_info = self._id_to_taxon[taxon_id]
        
        return WikipediaSpecies(
            taxon_id=taxon_id,
            scientific_name=taxon_info["scientific_name"],
            rank=taxon_info["rank"],
            wikipedia_url=taxon_info["wikipedia_url"],
            descriptions=self._load_descriptions(taxon_id),
            vernacular_names=self._load_vernacular_names(taxon_id),
        )
    
    def find_by_name(self, name: str) -> WikipediaSpecies | None:
        """Find a species by scientific name.
        
        Args:
            name: The scientific name to search for.
            
        Returns:
            WikipediaSpecies object or None if not found.
        """
        self._build_taxon_index()
        
        name_key = name.lower()
        
        if name_key not in self._name_to_id:
            return None
        
        # Return the first match
        taxon_id = self._name_to_id[name_key][0]
        return self.find_by_id(taxon_id)
    
    def search_by_name(self, query: str, limit: int = 10) -> list[WikipediaSpecies]:
        """Search for species by partial name match.
        
        Args:
            query: The search query.
            limit: Maximum number of results.
            
        Returns:
            List of matching WikipediaSpecies objects.
        """
        self._build_taxon_index()
        
        query_lower = query.lower()
        results = []
        
        for name, taxon_ids in self._name_to_id.items():
            if query_lower in name:
                for taxon_id in taxon_ids:
                    species = self.find_by_id(taxon_id)
                    if species:
                        results.append(species)
                    if len(results) >= limit:
                        return results
        
        return results
    
    def match_gbif_taxon(self, gbif_name: str, gbif_rank: str = "") -> WikipediaSpecies | None:
        """Try to match a GBIF taxon to a Wikipedia entry.
        
        Attempts several matching strategies:
        1. Exact scientific name match
        2. Canonical name (without authorship)
        3. Fuzzy matching for common variations
        
        Args:
            gbif_name: The scientific name from GBIF.
            gbif_rank: Optional rank to help with matching.
            
        Returns:
            WikipediaSpecies object or None if no match found.
        """
        # Try exact match first
        species = self.find_by_name(gbif_name)
        if species:
            return species
        
        # Try without authorship (take first two words for species)
        parts = gbif_name.split()
        if len(parts) >= 2:
            canonical = " ".join(parts[:2])
            species = self.find_by_name(canonical)
            if species:
                return species
        
        # Try just the first word (genus name)
        if len(parts) >= 1:
            species = self.find_by_name(parts[0])
            if species:
                return species
        
        return None

