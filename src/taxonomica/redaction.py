"""Taxonomy-based text redaction for the Taxonomica game.

This module provides functionality to redact taxonomic information from
species descriptions, which is core to the game mechanic where players
progressively guess the taxonomy to reveal more information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from taxonomica.gbif_tree import TaxonomyNode

# Standard taxonomic ranks in order from highest to lowest
TAXONOMIC_RANKS = [
    "kingdom",
    "phylum", 
    "class",
    "order",
    "family",
    "genus",
    "species",
    "subspecies",
]

# Common vernacular equivalents for taxonomic terms
# These are added automatically based on scientific names
VERNACULAR_MAPPINGS: dict[str, list[str]] = {
    # Kingdom-level
    "Animalia": ["animal", "animals"],
    "Plantae": ["plant", "plants"],
    "Fungi": ["fungus", "fungi", "mushroom", "mushrooms"],
    "Bacteria": ["bacterium", "bacteria"],
    "Archaea": ["archaea", "archaeon"],
    "Chromista": ["chromist", "chromists"],
    "Protozoa": ["protozoan", "protozoans", "protozoa"],
    "Viruses": ["virus", "viruses", "viral"],
    
    # Phylum-level (common ones)
    "Chordata": ["chordate", "chordates", "vertebrate", "vertebrates"],
    "Arthropoda": ["arthropod", "arthropods"],
    "Mollusca": ["mollusk", "mollusks", "mollusc", "molluscs"],
    "Annelida": ["annelid", "annelids", "worm", "worms"],
    "Cnidaria": ["cnidarian", "cnidarians"],
    "Echinodermata": ["echinoderm", "echinoderms"],
    "Nematoda": ["nematode", "nematodes", "roundworm", "roundworms"],
    "Platyhelminthes": ["flatworm", "flatworms"],
    
    # Class-level (common ones)
    "Mammalia": ["mammal", "mammals", "mammalian"],
    "Aves": ["bird", "birds", "avian"],
    "Reptilia": ["reptile", "reptiles", "reptilian"],
    "Amphibia": ["amphibian", "amphibians"],
    "Actinopterygii": ["fish", "fishes", "ray-finned fish"],
    "Chondrichthyes": ["shark", "sharks", "ray", "rays", "cartilaginous fish"],
    "Insecta": ["insect", "insects"],
    "Arachnida": ["arachnid", "arachnids", "spider", "spiders"],
    "Crustacea": ["crustacean", "crustaceans"],
    "Gastropoda": ["snail", "snails", "slug", "slugs"],
    "Bivalvia": ["bivalve", "bivalves", "clam", "clams", "mussel", "mussels"],
    
    # Order-level (common ones)
    "Carnivora": ["carnivore", "carnivores", "carnivoran", "carnivorans"],
    "Primates": ["primate", "primates"],
    "Rodentia": ["rodent", "rodents"],
    "Chiroptera": ["bat", "bats"],
    "Cetacea": ["whale", "whales", "dolphin", "dolphins", "cetacean", "cetaceans"],
    "Artiodactyla": ["ungulate", "ungulates", "even-toed ungulate"],
    "Perissodactyla": ["odd-toed ungulate"],
    "Proboscidea": ["elephant", "elephants"],
    "Lagomorpha": ["rabbit", "rabbits", "hare", "hares"],
    "Squamata": ["lizard", "lizards", "snake", "snakes"],
    "Testudines": ["turtle", "turtles", "tortoise", "tortoises"],
    "Crocodilia": ["crocodile", "crocodiles", "alligator", "alligators", "crocodilian", "crocodilians"],
    "Passeriformes": ["songbird", "songbirds", "passerine", "passerines"],
    "Coleoptera": ["beetle", "beetles"],
    "Lepidoptera": ["butterfly", "butterflies", "moth", "moths"],
    "Hymenoptera": ["ant", "ants", "bee", "bees", "wasp", "wasps"],
    "Diptera": ["fly", "flies"],
    
    # Family-level (common ones)
    "Felidae": ["feline", "felines", "felid", "felids", "cat family"],
    "Canidae": ["canine", "canines", "canid", "canids", "dog family"],
    "Ursidae": ["bear", "bears", "ursid", "ursids"],
    "Hominidae": ["great ape", "great apes", "hominid", "hominids"],
    "Bovidae": ["bovid", "bovids"],
    "Equidae": ["equid", "equids", "horse family"],
    "Cervidae": ["deer", "cervid", "cervids"],
    "Elephantidae": ["elephant", "elephants"],
    "Delphinidae": ["dolphin", "dolphins"],
    "Accipitridae": ["hawk", "hawks", "eagle", "eagles"],
    "Strigidae": ["owl", "owls"],
    "Corvidae": ["crow", "crows", "raven", "ravens", "corvid", "corvids"],
}


@dataclass
class RedactionTerms:
    """Collection of terms to redact at each taxonomic level."""
    
    # Terms indexed by rank
    terms_by_rank: dict[str, set[str]] = field(default_factory=dict)
    
    def add_term(self, rank: str, term: str) -> None:
        """Add a term to redact at a given rank."""
        if rank not in self.terms_by_rank:
            self.terms_by_rank[rank] = set()
        self.terms_by_rank[rank].add(term)
    
    def add_terms(self, rank: str, terms: list[str]) -> None:
        """Add multiple terms to redact at a given rank."""
        for term in terms:
            self.add_term(rank, term)
    
    def get_terms_for_ranks(self, ranks: set[str]) -> set[str]:
        """Get all terms for the specified ranks."""
        terms = set()
        for rank in ranks:
            if rank in self.terms_by_rank:
                terms.update(self.terms_by_rank[rank])
        return terms
    
    def get_all_terms(self) -> set[str]:
        """Get all terms across all ranks."""
        terms = set()
        for rank_terms in self.terms_by_rank.values():
            terms.update(rank_terms)
        return terms


def build_redaction_terms_from_node(node: TaxonomyNode) -> RedactionTerms:
    """Build redaction terms from a GBIF taxonomy node.
    
    This extracts the full taxonomic hierarchy and builds a set of
    terms to redact at each level, including:
    - Scientific names
    - Vernacular names (from GBIF data)
    - Common vernacular equivalents (from mappings)
    
    Args:
        node: A TaxonomyNode from the GBIF tree.
        
    Returns:
        RedactionTerms object with all terms organized by rank.
    """
    terms = RedactionTerms()
    
    # Get the path from this node to the root
    path = node.get_path_to_root()
    
    for ancestor in path:
        if ancestor.rank == "root":
            continue
        
        rank = ancestor.rank
        name = ancestor.name
        
        # Add scientific name
        terms.add_term(rank, name)
        
        # Add parts of binomial names
        name_parts = name.split()
        for part in name_parts:
            if len(part) > 2:  # Skip very short parts
                terms.add_term(rank, part)
        
        # Add vernacular names from GBIF data
        if hasattr(ancestor, 'vernacular_names') and ancestor.vernacular_names:
            for vn in ancestor.vernacular_names:
                terms.add_term(rank, vn)
                # Also add lowercase version
                terms.add_term(rank, vn.lower())
                # Split into component words
                for part in vn.split():
                    if len(part) > 2:
                        terms.add_term(rank, part)
                        terms.add_term(rank, part.lower())
        
        # Add common vernacular mappings
        if name in VERNACULAR_MAPPINGS:
            for vn in VERNACULAR_MAPPINGS[name]:
                terms.add_term(rank, vn)
                # Split into component words
                for part in vn.split():
                    if len(part) > 2:
                        terms.add_term(rank, part)
    
    return terms


def build_redaction_terms_manual(
    scientific_hierarchy: dict[str, str],
    vernacular_names: dict[str, list[str]] | None = None,
) -> RedactionTerms:
    """Build redaction terms from manual taxonomy specification.
    
    This is useful when you don't have a full GBIF node but know
    the taxonomy.
    
    Args:
        scientific_hierarchy: Dict mapping rank to scientific name.
            e.g., {"kingdom": "Animalia", "species": "Felis catus"}
        vernacular_names: Optional dict mapping rank to vernacular names.
            e.g., {"species": ["cat", "domestic cat"]}
    
    Returns:
        RedactionTerms object with all terms organized by rank.
    """
    terms = RedactionTerms()
    
    for rank, name in scientific_hierarchy.items():
        # Add scientific name
        terms.add_term(rank, name)
        
        # Add parts of name
        for part in name.split():
            if len(part) > 2:
                terms.add_term(rank, part)
        
        # Add vernacular mappings
        if name in VERNACULAR_MAPPINGS:
            for vn in VERNACULAR_MAPPINGS[name]:
                terms.add_term(rank, vn)
                # Split into component words
                for part in vn.split():
                    if len(part) > 2:
                        terms.add_term(rank, part)
    
    # Add custom vernacular names
    if vernacular_names:
        for rank, names in vernacular_names.items():
            for name in names:
                terms.add_term(rank, name)
                # Split into component words
                for part in name.split():
                    if len(part) > 2:
                        terms.add_term(rank, part)
                        terms.add_term(rank, part.lower())
    
    return terms


@dataclass
class Redactor:
    """Applies redaction to text based on taxonomic level.
    
    The redactor tracks which taxonomic levels have been "revealed"
    (correctly guessed) and only redacts terms from unrevealed levels.
    
    Example:
        >>> redactor = Redactor(terms)
        >>> redactor.reveal_rank("kingdom")  # Player guessed kingdom
        >>> text = redactor.redact(description)  # Kingdom terms visible
    """
    
    terms: RedactionTerms
    revealed_ranks: set[str] = field(default_factory=set)
    redaction_marker: str = "█████"
    use_variable_length: bool = False  # If True, marker length matches term
    
    def reveal_rank(self, rank: str) -> None:
        """Mark a rank as revealed (correctly guessed)."""
        self.revealed_ranks.add(rank)
    
    def hide_rank(self, rank: str) -> None:
        """Mark a rank as hidden again."""
        self.revealed_ranks.discard(rank)
    
    def reset(self) -> None:
        """Hide all ranks."""
        self.revealed_ranks.clear()
    
    def reveal_all(self) -> None:
        """Reveal all ranks."""
        self.revealed_ranks.update(self.terms.terms_by_rank.keys())
    
    def get_hidden_ranks(self) -> set[str]:
        """Get the set of ranks that are still hidden."""
        all_ranks = set(self.terms.terms_by_rank.keys())
        return all_ranks - self.revealed_ranks
    
    def _build_patterns(self) -> list[tuple[re.Pattern, str]]:
        """Build regex patterns for currently hidden terms.
        
        Uses substring matching (no word boundaries) to catch compound
        words like "housecat" when redacting "cat". This may cause some
        over-redaction (e.g., "cat" in "catch") which is acceptable for
        the game's purposes.
        """
        hidden_ranks = self.get_hidden_ranks()
        hidden_terms = self.terms.get_terms_for_ranks(hidden_ranks)
        
        patterns = []
        for term in hidden_terms:
            if not term or len(term) < 3:
                continue
            
            # Substring matching (no word boundaries) - catches compound words
            # Case-insensitive matching
            try:
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                
                if self.use_variable_length:
                    # Make marker length proportional to term length
                    marker = "█" * max(3, len(term))
                else:
                    marker = self.redaction_marker
                
                patterns.append((pattern, marker))
            except re.error:
                # Skip invalid patterns
                continue
        
        # Sort by length (longest first) to avoid partial replacements
        # This ensures "domestic cat" is replaced before "cat"
        patterns.sort(key=lambda x: -len(x[0].pattern))
        
        return patterns
    
    def redact(self, text: str) -> str:
        """Apply redaction to text based on current revealed ranks.
        
        Args:
            text: The text to redact.
            
        Returns:
            Text with hidden terms replaced by redaction markers.
        """
        patterns = self._build_patterns()
        
        result = text
        for pattern, marker in patterns:
            result = pattern.sub(marker, result)
        
        return result
    
    def count_redactions(self, text: str) -> int:
        """Count how many redactions would be applied to text."""
        patterns = self._build_patterns()
        
        count = 0
        for pattern, _ in patterns:
            count += len(pattern.findall(text))
        
        return count
    
    def get_redaction_preview(self, text: str, max_length: int = 200) -> str:
        """Get a preview of the redacted text."""
        redacted = self.redact(text)
        if len(redacted) > max_length:
            return redacted[:max_length] + "..."
        return redacted

