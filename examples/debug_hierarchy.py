#!/usr/bin/env python3
"""Debug hierarchy extraction for specific taxa."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.dwca import DarwinCoreArchive
from taxonomica.tree import extract_hierarchy_from_taxobox, parse_taxobox


def main() -> None:
    archive_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    archive = DarwinCoreArchive(archive_path)

    # Find some well-known species
    targets = {
        "Homo sapiens",
        "Canis lupus",
        "Felis catus",
        "Mammalia",
        "Animalia",
        "Aves",
        "Corvus corax",
    }

    print("Analyzing hierarchy data for specific taxa...\n")

    found = 0
    for taxon in archive.iter_taxa():
        if taxon.scientific_name in targets:
            found += 1
            print("=" * 70)
            print(f"Taxon: {taxon.scientific_name}")
            print(f"Rank: {taxon.rank}")
            print(f"Wikipedia: {taxon.references}")
            print(f"Status: {taxon.taxonomic_status or 'accepted'}")

            # Show standard DwC fields
            print(f"\nStandard DwC hierarchy fields:")
            for field, value in [
                ("kingdom", taxon.kingdom),
                ("phylum", taxon.phylum),
                ("class", taxon.class_),
                ("order", taxon.order),
                ("family", taxon.family),
                ("genus", taxon.genus),
            ]:
                if value:
                    print(f"  {field}: {value}")

            # Parse taxobox
            print(f"\nTaxobox fields:")
            parsed = parse_taxobox(taxon.taxobox)
            for key, value in sorted(parsed.items()):
                # Truncate long values
                if len(value) > 60:
                    value = value[:57] + "..."
                print(f"  {key}: {value}")

            # Extract hierarchy
            print(f"\nExtracted hierarchy:")
            hierarchy = extract_hierarchy_from_taxobox(taxon.taxobox)
            for rank, name in sorted(
                hierarchy.items(),
                key=lambda x: [
                    "domain", "kingdom", "phylum", "class", "order",
                    "family", "genus", "species"
                ].index(x[0]) if x[0] in [
                    "domain", "kingdom", "phylum", "class", "order",
                    "family", "genus", "species"
                ] else 99
            ):
                print(f"  {rank}: {name}")

            print()

        if found >= len(targets):
            break


if __name__ == "__main__":
    main()

