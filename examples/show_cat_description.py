#!/usr/bin/env python3
"""Display Wikipedia descriptions for a specific taxon."""

import sys
from pathlib import Path

wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"

# Find taxon ID for "Cat" (ID 6678 based on earlier search)
taxon_id = "6678"

print(f"Wikipedia descriptions for domestic cat (taxonID: {taxon_id}):\n")
print("=" * 80)

desc_file = wiki_path / "description.txt"
with open(desc_file, encoding="utf-8") as f:
    for line in f:
        parts = line.strip().split("\t")
        if len(parts) >= 4 and parts[0] == taxon_id:
            language = parts[1] if len(parts) > 1 else "?"
            section_type = parts[2] if len(parts) > 2 else "unknown"
            description = parts[3] if len(parts) > 3 else ""
            
            print(f"\n[{section_type.upper()}] (Language: {language})")
            print("-" * 40)
            # Pretty print with word wrap
            words = description.split()
            line_len = 0
            for word in words:
                if line_len + len(word) + 1 > 78:
                    print()
                    line_len = 0
                print(word, end=" ")
                line_len += len(word) + 1
            print("\n")

