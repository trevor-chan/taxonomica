#!/usr/bin/env python3
"""Explore the GBIF Backbone Taxonomy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.gbif_backbone import GBIFBackbone
from taxonomica.gbif_tree import GBIFTaxonomyTree


def main() -> None:
    backbone_path = Path(__file__).parent.parent / "backbone"

    print("Loading GBIF Backbone...")
    backbone = GBIFBackbone(backbone_path)

    print("\nBuilding taxonomy tree (accepted taxa only)...")
    tree = GBIFTaxonomyTree.from_backbone(backbone, accepted_only=True)

    # Statistics
    print("\n" + "=" * 70)
    print("TREE STATISTICS")
    print("=" * 70)
    print(f"  Taxa processed: {tree.stats['taxa_processed']:,}")
    print(f"  Accepted taxa: {tree.stats['accepted_taxa']:,}")
    print(f"  Nodes created: {tree.stats['nodes_created']:,}")
    print(f"  Nodes linked: {tree.stats['nodes_linked']:,}")

    print("\n" + "=" * 70)
    print("NODES BY RANK")
    print("=" * 70)
    rank_counts = tree.get_rank_counts()
    for rank in ["kingdom", "phylum", "class", "order", "family", "genus", "species", "subspecies"]:
        if rank in rank_counts:
            print(f"  {rank}: {rank_counts[rank]:,}")

    # Show other ranks
    main_ranks = {"kingdom", "phylum", "class", "order", "family", "genus", "species", "subspecies", "root"}
    other_ranks = {k: v for k, v in rank_counts.items() if k not in main_ranks}
    if other_ranks:
        print("\n  Other ranks:")
        for rank, count in sorted(other_ranks.items(), key=lambda x: -x[1])[:10]:
            print(f"    {rank}: {count:,}")

    # Show top of tree
    print("\n" + "=" * 70)
    print("TREE STRUCTURE (top levels)")
    print("=" * 70)
    tree.print_subtree(max_depth=3, max_children=6)

    # Test specific lookups
    print("\n" + "=" * 70)
    print("SAMPLE LOOKUPS")
    print("=" * 70)

    test_names = ["Homo sapiens", "Canis lupus", "Felis catus", "Animalia", "Mammalia", "Escherichia coli"]
    for name in test_names:
        nodes = tree.find_by_name(name)
        if nodes:
            node = nodes[0]
            path = " → ".join(n.name for n in reversed(node.get_path_to_root()[:-1]))
            complete = "✓" if node.has_complete_path() else "✗"
            print(f"\n  {complete} {name}:")
            print(f"    Rank: {node.rank}")
            print(f"    Path: {path}")
            print(f"    Children: {len(node.children)}")
        else:
            print(f"\n  {name}: NOT FOUND")

    # Show sample paths
    print("\n" + "=" * 70)
    print("SAMPLE COMPLETE PATHS")
    print("=" * 70)

    # Find a species with a nice complete path
    for node in tree.root.iter_descendants():
        if node.rank == "species" and node.has_complete_path():
            ancestors = node.get_ancestors()
            if len(ancestors) >= 7:
                print(f"\n  Path for '{node.name}':")
                for ancestor in reversed(node.get_path_to_root()):
                    indent = "    " * (len(node.get_path_to_root()) - len(ancestor.get_path_to_root()))
                    name = ancestor.name[:50] + "..." if len(ancestor.name) > 50 else ancestor.name
                    print(f"  {indent}[{ancestor.rank}] {name}")
                break


if __name__ == "__main__":
    main()

