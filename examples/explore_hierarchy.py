#!/usr/bin/env python3
"""Explore the hierarchical structure available in the Darwin Core Archive.

This script analyzes what taxonomic hierarchy information is available
to help us understand how to build a tree structure.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.dwca import DarwinCoreArchive


def main() -> None:
    archive_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    archive = DarwinCoreArchive(archive_path)

    print("Analyzing hierarchical information in the dataset...\n")

    # Track statistics
    rank_counts: Counter[str] = Counter()
    has_kingdom: Counter[str] = Counter()
    has_phylum: Counter[str] = Counter()
    has_class: Counter[str] = Counter()
    has_order: Counter[str] = Counter()
    has_family: Counter[str] = Counter()
    has_genus: Counter[str] = Counter()

    # Sample taxa at different ranks
    samples_by_rank: dict[str, list] = {}

    for taxon in archive.iter_taxa():
        rank = taxon.rank or "unknown"
        rank_counts[rank] += 1

        # Track which hierarchy fields are populated
        if taxon.kingdom:
            has_kingdom[rank] += 1
        if taxon.phylum:
            has_phylum[rank] += 1
        if taxon.class_:
            has_class[rank] += 1
        if taxon.order:
            has_order[rank] += 1
        if taxon.family:
            has_family[rank] += 1
        if taxon.genus:
            has_genus[rank] += 1

        # Collect samples
        if rank not in samples_by_rank:
            samples_by_rank[rank] = []
        if len(samples_by_rank[rank]) < 3:
            samples_by_rank[rank].append(taxon)

    # Report findings
    print("=" * 70)
    print("RANK DISTRIBUTION")
    print("=" * 70)
    for rank, count in rank_counts.most_common():
        print(f"  {rank}: {count:,}")

    print("\n" + "=" * 70)
    print("HIERARCHY FIELD AVAILABILITY BY RANK")
    print("=" * 70)
    print(f"{'Rank':<20} {'Total':>10} {'Kingdom':>10} {'Phylum':>10} {'Class':>10} {'Order':>10} {'Family':>10} {'Genus':>10}")
    print("-" * 100)

    for rank, count in rank_counts.most_common(15):
        k = has_kingdom.get(rank, 0)
        p = has_phylum.get(rank, 0)
        c = has_class.get(rank, 0)
        o = has_order.get(rank, 0)
        f = has_family.get(rank, 0)
        g = has_genus.get(rank, 0)
        print(f"{rank:<20} {count:>10,} {k:>10,} {p:>10,} {c:>10,} {o:>10,} {f:>10,} {g:>10,}")

    print("\n" + "=" * 70)
    print("SAMPLE TAXA BY RANK (showing hierarchy fields)")
    print("=" * 70)

    interesting_ranks = ["Species", "Genus", "Family", "Order", "Class", "Phylum", "Kingdom"]
    for rank in interesting_ranks:
        if rank in samples_by_rank:
            print(f"\n--- {rank} ---")
            for t in samples_by_rank[rank][:2]:
                print(f"\n  [{t.id}] {t.scientific_name}")
                print(f"    Wikipedia: {t.references}")
                hierarchy = []
                if t.kingdom:
                    hierarchy.append(f"K:{t.kingdom}")
                if t.phylum:
                    hierarchy.append(f"P:{t.phylum}")
                if t.class_:
                    hierarchy.append(f"C:{t.class_}")
                if t.order:
                    hierarchy.append(f"O:{t.order}")
                if t.family:
                    hierarchy.append(f"F:{t.family}")
                if t.genus:
                    hierarchy.append(f"G:{t.genus}")
                if hierarchy:
                    print(f"    Hierarchy: {' > '.join(hierarchy)}")
                else:
                    print(f"    Hierarchy: (none in standard fields)")

                # Check if taxobox has more info
                if t.taxobox and "=" in t.taxobox:
                    # Count fields in taxobox
                    fields = t.taxobox.count("=")
                    print(f"    Taxobox: {fields} fields present")

    # Check for parent-child relationships via acceptedNameUsage
    print("\n" + "=" * 70)
    print("SYNONYM/ACCEPTED NAME RELATIONSHIPS")
    print("=" * 70)

    synonym_count = 0
    accepted_count = 0
    for taxon in archive.iter_taxa():
        if taxon.taxonomic_status == "synonym":
            synonym_count += 1
        if taxon.accepted_name_usage_id:
            accepted_count += 1

    print(f"  Taxa with 'synonym' status: {synonym_count:,}")
    print(f"  Taxa with acceptedNameUsageID: {accepted_count:,}")


if __name__ == "__main__":
    main()

