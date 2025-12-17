#!/usr/bin/env python3
"""Demonstration of the Taxonomica game mechanics.

This script shows the full workflow:
1. Load GBIF taxonomy tree
2. Find a species and get its Wikipedia description
3. Apply redaction based on taxonomic level
4. Simulate progressive reveal as player guesses correctly

Run with: python examples/game_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.gbif_backbone import GBIFBackbone
from taxonomica.gbif_tree import GBIFTaxonomyTree
from taxonomica.wikipedia import WikipediaData
from taxonomica.redaction import Redactor, build_redaction_terms_from_node, build_redaction_terms_manual


def print_section(title: str) -> None:
    """Print a section header."""
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


def wrap_text(text: str, width: int = 76) -> str:
    """Simple word wrap."""
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 > width:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
        else:
            current_line.append(word)
            current_length += len(word) + 1
    
    if current_line:
        lines.append(" ".join(current_line))
    
    return "\n".join(lines)


def demo_with_gbif(species_name: str = "Panthera leo") -> None:
    """Demo using GBIF taxonomy tree for automatic term extraction."""
    
    print_section("TAXONOMICA GAME DEMO - GBIF Integration")
    print(f"\n  Target species: {species_name}")
    print("  Loading GBIF taxonomy (this takes a few minutes)...")
    
    # Load GBIF tree
    backbone_path = Path(__file__).parent.parent / "backbone"
    if not backbone_path.exists():
        print(f"  ERROR: GBIF backbone not found at {backbone_path}")
        print("  Falling back to manual demo...")
        demo_manual()
        return
    
    backbone = GBIFBackbone(backbone_path)
    tree = GBIFTaxonomyTree.from_backbone(backbone, accepted_only=True)
    
    # Load vernacular names
    print("\n  Loading vernacular names...")
    tree.add_vernacular_names(backbone)
    
    # Find the species (case-insensitive search)
    print(f"\n  Searching for '{species_name}'...")
    matches = tree.find_by_name(species_name, case_sensitive=False)
    
    if not matches:
        print(f"  Species '{species_name}' not found in GBIF tree.")
        return
    
    # Use the first match
    species_node = matches[0]
    print(f"  Found: {species_node.name} ({species_node.rank})")
    
    # Show the taxonomy path
    print("\n  Taxonomic hierarchy:")
    path = species_node.get_path_to_root()
    for node in reversed(path):
        if node.rank != "root":
            vn = f' "{node.vernacular_names[0]}"' if node.vernacular_names else ""
            print(f"    [{node.rank.upper()}] {node.name}{vn}")
    
    # Load Wikipedia description
    wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    wiki = WikipediaData(wiki_path)
    
    print(f"\n  Searching Wikipedia for '{species_node.name}'...")
    wiki_species = wiki.match_gbif_taxon(species_node.name)
    
    if not wiki_species:
        print("  No Wikipedia entry found. Using placeholder description.")
        description = f"The {species_node.name} is a species in the family..."
    else:
        print(f"  Found: {wiki_species.scientific_name}")
        description = wiki_species.get_abstract() or "No abstract available."
    
    # Build redaction terms from the GBIF node
    print("\n  Building redaction terms from taxonomy...")
    terms = build_redaction_terms_from_node(species_node)
    
    # Show terms by rank
    print("\n  Terms to redact by rank:")
    for rank in ["kingdom", "phylum", "class", "order", "family", "genus", "species"]:
        if rank in terms.terms_by_rank:
            rank_terms = sorted(terms.terms_by_rank[rank])[:5]
            more = len(terms.terms_by_rank[rank]) - 5
            suffix = f"... (+{more} more)" if more > 0 else ""
            print(f"    {rank.upper()}: {', '.join(rank_terms)}{suffix}")
    
    # Create redactor
    redactor = Redactor(terms, use_variable_length=True)
    
    # Simulate progressive reveal
    print_section("GAME SIMULATION - Progressive Reveal")
    
    reveal_sequence = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
    
    for i, reveal_rank in enumerate(reveal_sequence):
        print(f"\n  --- Player correctly guesses: {reveal_rank.upper()} ---")
        redactor.reveal_rank(reveal_rank)
        
        redacted = redactor.redact(description)
        redaction_count = redactor.count_redactions(description)
        
        print(f"  Remaining redactions: {redaction_count}")
        print()
        print(wrap_text(redacted[:500]))
        if len(redacted) > 500:
            print("...")
        
        if i < len(reveal_sequence) - 1:
            input("\n  Press Enter to continue...")
    
    print_section("SPECIES REVEALED!")
    print(f"\n  The answer was: {species_node.name}")
    if wiki_species and wiki_species.vernacular_names:
        print(f"  Common name: {wiki_species.vernacular_names[0]}")


def demo_manual() -> None:
    """Demo using manual taxonomy specification (no GBIF needed)."""
    
    print_section("TAXONOMICA GAME DEMO - Manual Mode")
    
    # Define taxonomy manually (for testing without GBIF)
    scientific_hierarchy = {
        "kingdom": "Animalia",
        "phylum": "Chordata", 
        "class": "Mammalia",
        "order": "Carnivora",
        "family": "Felidae",
        "genus": "Felis",
        "species": "Felis catus",
    }
    
    vernacular_names = {
        "species": ["cat", "cats", "domestic cat", "house cat", "housecat", "kitty", "kitten", "kittens"],
        "family": ["feline", "felines", "felid", "felids"],
    }
    
    print("\n  Target species: Felis catus (Domestic Cat)")
    print("\n  Taxonomy:")
    for rank, name in scientific_hierarchy.items():
        vns = vernacular_names.get(rank, [])
        vn_str = f' ({", ".join(vns[:2])})' if vns else ""
        print(f"    [{rank.upper()}] {name}{vn_str}")
    
    # Load Wikipedia description
    wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    
    try:
        wiki = WikipediaData(wiki_path)
        wiki_species = wiki.find_by_name("Felis catus") or wiki.find_by_name("Cat")
        
        if wiki_species:
            description = wiki_species.get_abstract() or ""
            print(f"\n  Loaded Wikipedia description: {len(description)} chars")
        else:
            description = get_fallback_cat_description()
            print("\n  Using fallback description")
    except FileNotFoundError:
        description = get_fallback_cat_description()
        print("\n  Wikipedia data not found, using fallback description")
    
    # Build redaction terms
    terms = build_redaction_terms_manual(scientific_hierarchy, vernacular_names)
    
    # Create redactor
    redactor = Redactor(terms, use_variable_length=True)
    
    # Show fully redacted version
    print_section("FULLY REDACTED (Game Start)")
    
    redacted = redactor.redact(description)
    print()
    print(wrap_text(redacted[:600]))
    if len(redacted) > 600:
        print("...")
    
    print(f"\n  Total redactions: {redactor.count_redactions(description)}")
    
    # Simulate guessing
    print_section("PROGRESSIVE REVEAL")
    
    reveal_order = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
    
    for rank in reveal_order:
        input(f"\n  Press Enter to reveal {rank.upper()}...")
        redactor.reveal_rank(rank)
        
        redacted = redactor.redact(description)
        remaining = redactor.count_redactions(description)
        
        print(f"\n  [{rank.upper()} REVEALED] - {remaining} redactions remaining")
        print()
        print(wrap_text(redacted[:400]))
        if len(redacted) > 400:
            print("...")
    
    print_section("ANSWER: Felis catus - Domestic Cat")


def get_fallback_cat_description() -> str:
    """Fallback description if Wikipedia data not available."""
    return """The cat is a domestic species of small carnivorous mammal. It is the only 
domesticated species in the family Felidae and is often referred to as the domestic cat 
to distinguish it from the wild members of the family. A cat can either be a house cat, 
a farm cat or a feral cat; the latter ranges freely and avoids human contact. Domestic 
cats are valued by humans for companionship and their ability to kill rodents. About 60 
cat breeds are recognized by various cat registries. The cat is similar in anatomy to 
the other felid species: it has a strong flexible body, quick reflexes, sharp teeth and 
retractable claws adapted to killing small prey. Its night vision and sense of smell are 
well developed. Cat communication includes vocalizations like meowing, purring, trilling, 
hissing, growling and grunting as well as cat-specific body language. A predator that is 
most active at dawn and dusk, the cat is a solitary hunter but a social species."""


def main():
    print("\n" + "=" * 80)
    print("  TAXONOMICA - Game Mechanics Demo")
    print("=" * 80)
    print()
    print("  Choose demo mode:")
    print("    1. Quick demo (manual taxonomy, no GBIF loading)")
    print("    2. Full demo (loads GBIF backbone - takes a few minutes)")
    print()
    
    choice = input("  Enter choice (1 or 2): ").strip()
    
    if choice == "2":
        species = input("  Enter species name [default: Panthera leo]: ").strip()
        if not species:
            species = "Panthera leo"
        demo_with_gbif(species)
    else:
        demo_manual()
    
    print("\n  Demo complete!\n")


if __name__ == "__main__":
    main()

