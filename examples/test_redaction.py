#!/usr/bin/env python3
"""Test redaction of taxonomic information from Wikipedia descriptions.

This script demonstrates how to hide identifying information from species
descriptions, which is core to the Taxonomica game mechanic.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Redaction marker - could be customized
REDACTED = "█████"


def get_cat_taxonomy() -> dict[str, list[str]]:
    """Get the full taxonomic hierarchy for domestic cat with vernacular names.
    
    In the real game, this would be looked up from GBIF/Wikipedia data.
    For this test, we hardcode the cat's taxonomy.
    """
    return {
        # Scientific names at each rank
        "species": ["Felis catus", "Felis silvestris catus"],
        "genus": ["Felis"],
        "family": ["Felidae"],
        "order": ["Carnivora"],
        "class": ["Mammalia"],
        "phylum": ["Chordata"],
        "kingdom": ["Animalia"],
        
        # Vernacular names and common terms
        "vernacular_species": ["cat", "cats", "domestic cat", "house cat", "housecat", "kitty", "kitten", "kittens"],
        "vernacular_genus": ["small cats"],  # Felis = small cats
        "vernacular_family": ["feline", "felines", "felid", "felids", "cat family"],
        "vernacular_order": ["carnivore", "carnivores", "carnivoran", "carnivorans"],
        "vernacular_class": ["mammal", "mammals", "mammalian"],
        "vernacular_phylum": ["chordate", "chordates", "vertebrate", "vertebrates"],
        "vernacular_kingdom": ["animal", "animals"],
    }


def build_redaction_patterns(taxonomy: dict[str, list[str]], redact_levels: set[str]) -> list[tuple[re.Pattern, str]]:
    """Build regex patterns for redaction.
    
    Args:
        taxonomy: Dictionary of taxonomic terms to redact
        redact_levels: Set of levels to redact (e.g., {"species", "genus", "family"})
    
    Returns:
        List of (pattern, replacement) tuples
    """
    patterns = []
    
    for level in redact_levels:
        # Scientific names
        if level in taxonomy:
            for term in taxonomy[level]:
                # Word boundary matching, case-insensitive
                # Use word boundaries to avoid matching "cat" in "category"
                pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
                patterns.append((pattern, REDACTED))
        
        # Vernacular names
        vernacular_key = f"vernacular_{level}"
        if vernacular_key in taxonomy:
            for term in taxonomy[vernacular_key]:
                pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
                patterns.append((pattern, REDACTED))
    
    # Sort by length (longest first) to avoid partial replacements
    patterns.sort(key=lambda x: -len(x[0].pattern))
    
    return patterns


def redact_text(text: str, patterns: list[tuple[re.Pattern, str]]) -> str:
    """Apply redaction patterns to text."""
    result = text
    for pattern, replacement in patterns:
        result = pattern.sub(replacement, result)
    return result


def get_cat_description() -> str:
    """Load the cat description from Wikipedia data."""
    wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    desc_file = wiki_path / "description.txt"
    
    # Cat taxon ID is 6678
    taxon_id = "6678"
    
    with open(desc_file, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 4 and parts[0] == taxon_id:
                section_type = parts[2]
                if section_type == "Abstract":
                    return parts[3]
    
    return ""


def main():
    print("=" * 80)
    print("TAXONOMICA REDACTION TEST")
    print("=" * 80)
    
    # Get the cat's taxonomy
    taxonomy = get_cat_taxonomy()
    
    # Get the cat description
    description = get_cat_description()
    
    if not description:
        print("Error: Could not load cat description")
        return
    
    # Clean up HTML tags for readability
    description = re.sub(r'<br\s*/?>', '\n', description)
    description = re.sub(r'<[^>]+>', '', description)
    
    print("\n" + "-" * 80)
    print("ORIGINAL DESCRIPTION (first 800 chars):")
    print("-" * 80)
    print(description[:800])
    print("..." if len(description) > 800 else "")
    
    # Test different redaction levels
    redaction_scenarios = [
        {
            "name": "Species only (scientific + vernacular)",
            "levels": {"species"},
        },
        {
            "name": "Species + Genus",
            "levels": {"species", "genus"},
        },
        {
            "name": "Species + Genus + Family",
            "levels": {"species", "genus", "family"},
        },
        {
            "name": "Full hierarchy (all levels)",
            "levels": {"species", "genus", "family", "order", "class", "phylum", "kingdom"},
        },
    ]
    
    for scenario in redaction_scenarios:
        print("\n" + "=" * 80)
        print(f"REDACTION LEVEL: {scenario['name']}")
        print("=" * 80)
        
        patterns = build_redaction_patterns(taxonomy, scenario["levels"])
        redacted = redact_text(description, patterns)
        
        # Count redactions
        redaction_count = redacted.count(REDACTED)
        print(f"Redactions applied: {redaction_count}")
        print("-" * 80)
        print(redacted[:800])
        print("..." if len(redacted) > 800 else "")
    
    # Show what terms would be redacted at full level
    print("\n" + "=" * 80)
    print("TERMS BEING REDACTED (full hierarchy):")
    print("=" * 80)
    
    all_levels = {"species", "genus", "family", "order", "class", "phylum", "kingdom"}
    for level in ["species", "genus", "family", "order", "class", "phylum", "kingdom"]:
        terms = taxonomy.get(level, []) + taxonomy.get(f"vernacular_{level}", [])
        if terms:
            print(f"  {level.upper()}: {', '.join(terms)}")


if __name__ == "__main__":
    main()

