"""Popularity scoring for Wikipedia species entries.

This module computes a "popularity score" for species based on proxy metrics
from the Wikipedia DwC-A dataset. While we don't have direct page view counts,
these metrics correlate well with species recognition:

- Description length: More popular species have longer, more detailed articles
- Section count: Well-known species have more comprehensive coverage
- Vernacular names: Species with common names are more recognizable
- Multimedia: Popular species tend to have more images

The score can be used to stratify species for different difficulty levels:
- Easy: Well-known species with high scores (lion, dog, rose)
- Medium: Moderately known species
- Hard: Obscure species with minimal Wikipedia coverage
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Increase CSV field size limit
csv.field_size_limit(sys.maxsize)


@dataclass
class PopularityMetrics:
    """Popularity metrics for a Wikipedia taxon entry."""
    
    taxon_id: str
    scientific_name: str = ""
    description_length: int = 0  # Total chars across all sections
    section_count: int = 0  # Number of description sections
    has_vernacular: bool = False  # Has a common name
    vernacular_name: str = ""  # First vernacular name if available
    multimedia_count: int = 0  # Number of images
    
    @property
    def popularity_score(self) -> float:
        """Compute a normalized popularity score (0-100).
        
        The score is a weighted combination of metrics, designed so that
        well-known species like "Lion" or "Oak" score high, while obscure
        species with minimal coverage score low.
        """
        score = 0.0
        
        # Description length (0-40 points)
        # Scale: 100 chars = 1 pt, 1000 chars = 10 pts, 10000+ chars = 40 pts
        if self.description_length > 0:
            import math
            desc_score = min(40, math.log10(self.description_length) * 13)
            score += desc_score
        
        # Section count (0-20 points)
        # 1 section = 2 pts, 5 sections = 10 pts, 10+ sections = 20 pts
        score += min(20, self.section_count * 2)
        
        # Vernacular name (0-25 points)
        # Having a common name is a strong indicator of recognition
        if self.has_vernacular:
            score += 25
        
        # Multimedia (0-15 points)
        # 1 image = 3 pts, 5+ images = 15 pts
        score += min(15, self.multimedia_count * 3)
        
        return min(100, score)
    
    @property
    def difficulty_tier(self) -> str:
        """Get difficulty tier based on popularity score.
        
        Returns:
            "easy", "medium", "hard", or "expert"
        """
        score = self.popularity_score
        if score >= 60:
            return "easy"
        elif score >= 40:
            return "medium"
        elif score >= 20:
            return "hard"
        else:
            return "expert"


class PopularityIndex:
    """Index of popularity scores for Wikipedia taxa.
    
    This class loads and indexes popularity metrics from the Wikipedia
    DwC-A dataset, allowing efficient lookup by taxon ID or scientific name.
    
    Example:
        >>> index = PopularityIndex.from_wikipedia_dwca("wikipedia-en-dwca")
        >>> metrics = index.get_by_name("Panthera leo")
        >>> print(f"Lion popularity: {metrics.popularity_score:.1f}")
        >>> print(f"Difficulty: {metrics.difficulty_tier}")
    """
    
    def __init__(self) -> None:
        self._by_id: dict[str, PopularityMetrics] = {}
        self._by_name: dict[str, list[str]] = {}  # name -> list of taxon_ids
    
    @classmethod
    def from_wikipedia_dwca(cls, path: str | Path) -> PopularityIndex:
        """Build popularity index from Wikipedia DwC-A directory.
        
        Args:
            path: Path to the Wikipedia DwC-A directory.
            
        Returns:
            Populated PopularityIndex.
        """
        path = Path(path)
        index = cls()
        
        # Step 1: Load taxon names
        print("  Loading taxon names...")
        taxon_file = path / "taxon.txt"
        if taxon_file.exists():
            with open(taxon_file, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        taxon_id = parts[0]
                        scientific_name = parts[3] if len(parts) > 3 else ""
                        
                        # Skip synonyms
                        if "-syn" in taxon_id:
                            continue
                        
                        index._by_id[taxon_id] = PopularityMetrics(
                            taxon_id=taxon_id,
                            scientific_name=scientific_name,
                        )
                        
                        # Index by name
                        name_key = scientific_name.lower()
                        if name_key not in index._by_name:
                            index._by_name[name_key] = []
                        index._by_name[name_key].append(taxon_id)
        
        print(f"    Loaded {len(index._by_id):,} taxa")
        
        # Step 2: Load description metrics
        print("  Loading description metrics...")
        desc_file = path / "description.txt"
        if desc_file.exists():
            with open(desc_file, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        taxon_id = parts[0]
                        text = parts[3] if len(parts) > 3 else ""
                        
                        if taxon_id in index._by_id:
                            metrics = index._by_id[taxon_id]
                            metrics.description_length += len(text)
                            metrics.section_count += 1
        
        # Step 3: Load vernacular names
        print("  Loading vernacular names...")
        vn_file = path / "vernacularname.txt"
        if vn_file.exists():
            with open(vn_file, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        taxon_id = parts[0]
                        name = parts[3] if len(parts) > 3 else ""
                        
                        if taxon_id in index._by_id and name:
                            metrics = index._by_id[taxon_id]
                            metrics.has_vernacular = True
                            if not metrics.vernacular_name:
                                metrics.vernacular_name = name
        
        # Step 4: Load multimedia counts
        print("  Loading multimedia counts...")
        mm_file = path / "multimedia.txt"
        if mm_file.exists():
            with open(mm_file, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 1:
                        taxon_id = parts[0]
                        if taxon_id in index._by_id:
                            index._by_id[taxon_id].multimedia_count += 1
        
        return index
    
    def get_by_id(self, taxon_id: str) -> PopularityMetrics | None:
        """Get metrics by taxon ID."""
        return self._by_id.get(taxon_id)
    
    def get_by_name(self, name: str) -> PopularityMetrics | None:
        """Get metrics by scientific name (case-insensitive)."""
        name_key = name.lower()
        if name_key in self._by_name:
            taxon_id = self._by_name[name_key][0]
            return self._by_id.get(taxon_id)
        return None
    
    def iter_by_difficulty(
        self,
        tier: str,
        min_sections: int = 1,
    ) -> Iterator[PopularityMetrics]:
        """Iterate over taxa of a specific difficulty tier.
        
        Args:
            tier: Difficulty tier ("easy", "medium", "hard", "expert")
            min_sections: Minimum number of description sections required
            
        Yields:
            PopularityMetrics for matching taxa
        """
        for metrics in self._by_id.values():
            if metrics.difficulty_tier == tier and metrics.section_count >= min_sections:
                yield metrics
    
    def get_stats(self) -> dict[str, int]:
        """Get count of taxa by difficulty tier."""
        stats = {"easy": 0, "medium": 0, "hard": 0, "expert": 0}
        for metrics in self._by_id.values():
            stats[metrics.difficulty_tier] += 1
        return stats
    
    def get_top_popular(self, n: int = 100) -> list[PopularityMetrics]:
        """Get the top N most popular taxa."""
        return sorted(
            self._by_id.values(),
            key=lambda m: m.popularity_score,
            reverse=True,
        )[:n]

