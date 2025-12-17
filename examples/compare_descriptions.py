#!/usr/bin/env python3
"""Compare descriptions from GBIF Backbone and Wikipedia datasets."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Increase CSV field size limit
csv.field_size_limit(sys.maxsize)


def find_gbif_descriptions(backbone_path: Path, search_names: list[str]) -> None:
    """Find descriptions for taxa in GBIF backbone."""
    print("=" * 80)
    print("GBIF BACKBONE DESCRIPTIONS")
    print("=" * 80)
    
    # First, find the taxon IDs for the search names
    taxon_file = backbone_path / "Taxon.tsv"
    taxon_ids: dict[str, str] = {}  # name -> id
    
    print(f"\nSearching for taxa: {search_names}")
    
    with open(taxon_file, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            canonical = row.get("canonicalName", "")
            scientific = row.get("scientificName", "")
            for name in search_names:
                if name.lower() in canonical.lower() or name.lower() in scientific.lower():
                    taxon_id = row.get("taxonID", "")
                    if taxon_id and name not in taxon_ids:
                        taxon_ids[canonical or scientific] = taxon_id
                        print(f"  Found: {canonical or scientific} (ID: {taxon_id})")
    
    if not taxon_ids:
        print("  No matching taxa found in GBIF backbone")
        return
    
    # Now find descriptions for these taxon IDs
    desc_file = backbone_path / "Description.tsv"
    if not desc_file.exists():
        print("\n  Description.tsv not found")
        return
    
    print(f"\nSearching descriptions...")
    found_any = False
    
    with open(desc_file, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            taxon_id = row.get("taxonID", "")
            if taxon_id in taxon_ids.values():
                found_any = True
                # Find the name for this ID
                name = [k for k, v in taxon_ids.items() if v == taxon_id][0]
                desc_type = row.get("type", "unknown")
                language = row.get("language", "?")
                description = row.get("description", "")[:500]  # Truncate
                source = row.get("source", "")[:80]
                
                print(f"\n--- {name} ---")
                print(f"Type: {desc_type} | Language: {language}")
                print(f"Source: {source}")
                print(f"Description:\n{description}")
                if len(row.get("description", "")) > 500:
                    print("... [truncated]")
    
    if not found_any:
        print("  No descriptions found for these taxa")


def find_wikipedia_descriptions(wiki_path: Path, search_names: list[str]) -> None:
    """Find descriptions for taxa in Wikipedia DwC-A."""
    print("\n" + "=" * 80)
    print("WIKIPEDIA DESCRIPTIONS")
    print("=" * 80)
    
    # First, find the taxon IDs for the search names
    taxon_file = wiki_path / "taxon.txt"
    taxon_ids: dict[str, str] = {}  # name -> id
    
    print(f"\nSearching for taxa: {search_names}")
    
    with open(taxon_file, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                taxon_id = parts[0]
                scientific_name = parts[1] if len(parts) > 1 else ""
                for name in search_names:
                    if name.lower() in scientific_name.lower():
                        if name not in taxon_ids:
                            taxon_ids[scientific_name] = taxon_id
                            print(f"  Found: {scientific_name} (ID: {taxon_id})")
    
    if not taxon_ids:
        print("  No matching taxa found in Wikipedia dataset")
        return
    
    # Now find descriptions for these taxon IDs
    desc_file = wiki_path / "description.txt"
    if not desc_file.exists():
        print("\n  description.txt not found")
        return
    
    print(f"\nSearching descriptions...")
    found_count = 0
    max_per_taxon = 2  # Limit to 2 descriptions per taxon
    shown: dict[str, int] = {}
    
    with open(desc_file, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                taxon_id = parts[0]
                if taxon_id in taxon_ids.values():
                    # Find the name for this ID
                    name = [k for k, v in taxon_ids.items() if v == taxon_id][0]
                    
                    if shown.get(name, 0) >= max_per_taxon:
                        continue
                    shown[name] = shown.get(name, 0) + 1
                    
                    desc_type = parts[1] if len(parts) > 1 else "unknown"
                    language = parts[2] if len(parts) > 2 else "?"
                    description = parts[3][:800] if len(parts) > 3 else ""
                    
                    print(f"\n--- {name} (description {shown[name]}) ---")
                    print(f"Type: {desc_type} | Language: {language}")
                    print(f"Description:\n{description}")
                    if len(parts) > 3 and len(parts[3]) > 800:
                        print("... [truncated]")
                    
                    found_count += 1
                    if found_count >= 6:  # Limit total output
                        print("\n... (more descriptions available)")
                        return
    
    if found_count == 0:
        print("  No descriptions found for these taxa")


def main():
    backbone_path = Path(__file__).parent.parent / "backbone"
    wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    
    # Search for domestic cat and related taxa
    search_names = ["Felis catus", "Felis silvestris catus", "domestic cat", "Cat"]
    
    if backbone_path.exists():
        find_gbif_descriptions(backbone_path, search_names)
    else:
        print(f"GBIF backbone not found at {backbone_path}")
    
    if wiki_path.exists():
        find_wikipedia_descriptions(wiki_path, search_names)
    else:
        print(f"Wikipedia dataset not found at {wiki_path}")


if __name__ == "__main__":
    main()

