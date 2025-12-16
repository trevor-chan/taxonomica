#!/usr/bin/env python3
"""Explore the taxobox field to understand how to extract taxonomy hierarchy."""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.dwca import DarwinCoreArchive


def parse_taxobox(taxobox: str) -> dict[str, str]:
    """Parse a taxobox string into a dictionary of field=value pairs."""
    if not taxobox:
        return {}

    # Remove outer braces if present
    taxobox = taxobox.strip()
    if taxobox.startswith("{") and taxobox.endswith("}"):
        taxobox = taxobox[1:-1]

    result = {}
    # Split on comma followed by word=
    # Pattern: key=value pairs separated by commas
    parts = re.split(r",\s*(?=\w+=)", taxobox)

    for part in parts:
        if "=" in part:
            key, _, value = part.partition("=")
            key = key.strip()
            value = value.strip()
            result[key] = value

    return result


def main() -> None:
    archive_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    archive = DarwinCoreArchive(archive_path)

    print("Exploring taxobox structure...\n")

    # Collect all unique taxobox keys
    all_keys: Counter[str] = Counter()
    taxonomy_keys: Counter[str] = Counter()

    # Sample taxoboxes by rank
    samples: dict[str, list[tuple[str, str, dict]]] = {}

    count = 0
    for taxon in archive.iter_taxa():
        if not taxon.taxobox:
            continue

        parsed = parse_taxobox(taxon.taxobox)
        for key in parsed:
            all_keys[key] += 1
            # Track keys that look like taxonomy hierarchy
            if any(
                x in key.lower()
                for x in [
                    "kingdom",
                    "phylum",
                    "class",
                    "order",
                    "family",
                    "genus",
                    "species",
                    "domain",
                    "clade",
                    "unranked",
                    "regnum",
                    "divisio",
                    "taxon",
                    "parent",
                ]
            ):
                taxonomy_keys[key] += 1

        # Collect samples
        rank = taxon.rank or "unknown"
        if rank not in samples:
            samples[rank] = []
        if len(samples[rank]) < 2:
            samples[rank].append((taxon.scientific_name, taxon.references, parsed))

        count += 1

    print(f"Analyzed {count:,} taxa with taxobox data\n")

    print("=" * 70)
    print("MOST COMMON TAXOBOX KEYS (top 50)")
    print("=" * 70)
    for key, cnt in all_keys.most_common(50):
        print(f"  {key}: {cnt:,}")

    print("\n" + "=" * 70)
    print("TAXONOMY-RELATED KEYS")
    print("=" * 70)
    for key, cnt in taxonomy_keys.most_common(50):
        print(f"  {key}: {cnt:,}")

    print("\n" + "=" * 70)
    print("SAMPLE TAXOBOXES")
    print("=" * 70)

    interesting_ranks = ["Species", "Genus", "Family", "Order", "Class", "Phylum"]
    for rank in interesting_ranks:
        if rank in samples:
            print(f"\n--- {rank} ---")
            for name, url, parsed in samples[rank][:1]:
                print(f"\n  {name}")
                print(f"  {url}")
                print(f"  Taxobox fields:")
                for k, v in sorted(parsed.items()):
                    # Truncate long values
                    if len(v) > 80:
                        v = v[:77] + "..."
                    print(f"    {k} = {v}")


if __name__ == "__main__":
    main()

