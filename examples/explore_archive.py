#!/usr/bin/env python3
"""Example script demonstrating the Darwin Core Archive parser.

This script loads the Wikipedia species pages archive and displays
summary statistics and sample data.
"""

import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.dwca import DarwinCoreArchive


def main() -> None:
    # Path to the Darwin Core Archive
    archive_path = Path(__file__).parent.parent / "wikipedia-en-dwca"

    print(f"Loading archive from: {archive_path}")
    archive = DarwinCoreArchive(archive_path)

    # Display archive structure
    print("\n" + "=" * 60)
    print("ARCHIVE STRUCTURE")
    print("=" * 60)

    if archive.core_descriptor:
        core = archive.core_descriptor
        print(f"\nCore file: {core.location}")
        print(f"  Row type: {core.row_type}")
        print(f"  Fields ({len(core.fields)}):")
        for f in core.fields[:10]:
            print(f"    [{f.index}] {f.name}")
        if len(core.fields) > 10:
            print(f"    ... and {len(core.fields) - 10} more")

    print(f"\nExtension files: {len(archive.extension_descriptors)}")
    for row_type, desc in archive.extension_descriptors.items():
        type_name = row_type.rsplit("/", 1)[-1]
        print(f"  - {desc.location} ({type_name})")

    # Sample taxa
    print("\n" + "=" * 60)
    print("SAMPLE TAXA (first 10)")
    print("=" * 60)

    for i, taxon in enumerate(archive.iter_taxa()):
        if i >= 10:
            break
        print(f"\n[{taxon.id}] {taxon.scientific_name}")
        print(f"  Rank: {taxon.rank}")
        if taxon.kingdom:
            print(f"  Kingdom: {taxon.kingdom}")
        if taxon.phylum:
            print(f"  Phylum: {taxon.phylum}")
        if taxon.class_:
            print(f"  Class: {taxon.class_}")
        if taxon.order:
            print(f"  Order: {taxon.order}")
        if taxon.family:
            print(f"  Family: {taxon.family}")
        if taxon.genus:
            print(f"  Genus: {taxon.genus}")
        if taxon.references:
            print(f"  Wikipedia: {taxon.references}")

    # Sample vernacular names
    print("\n" + "=" * 60)
    print("SAMPLE VERNACULAR NAMES (first 15)")
    print("=" * 60)

    for i, vn in enumerate(archive.iter_vernacular_names()):
        if i >= 15:
            break
        preferred = " [preferred]" if vn.is_preferred else ""
        print(f"  [{vn.taxon_id}] {vn.name} ({vn.language}){preferred}")

    # Sample species profiles
    print("\n" + "=" * 60)
    print("SAMPLE SPECIES PROFILES (first 10)")
    print("=" * 60)

    for i, sp in enumerate(archive.iter_species_profiles()):
        if i >= 10:
            break
        extinct = "EXTINCT" if sp.is_extinct else "extant"
        print(f"  [{sp.taxon_id}] {extinct} - {sp.living_period}")

    # Count summary (can be slow for large archives)
    print("\n" + "=" * 60)
    print("QUICK STATS")
    print("=" * 60)

    # Count just a portion to give an idea of size
    taxon_count = 0
    rank_sample: dict[str, int] = {}
    for taxon in archive.iter_taxa():
        taxon_count += 1
        if taxon_count <= 10000:  # Sample first 10k for rank distribution
            rank = taxon.rank or "unknown"
            rank_sample[rank] = rank_sample.get(rank, 0) + 1
        if taxon_count % 100000 == 0:
            print(f"  Counted {taxon_count:,} taxa...")

    print(f"\nTotal taxa: {taxon_count:,}")

    print("\nRank distribution (sampled from first 10,000):")
    for rank, count in sorted(rank_sample.items(), key=lambda x: -x[1]):
        print(f"  {rank}: {count:,}")


if __name__ == "__main__":
    main()

