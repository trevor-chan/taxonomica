#!/usr/bin/env python3
"""Build and explore the taxonomy tree from the Wikipedia DwC-A."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.dwca import DarwinCoreArchive
from taxonomica.tree import TaxonomyTree


def main() -> None:
    archive_path = Path(__file__).parent.parent / "wikipedia-en-dwca"

    print("Loading Darwin Core Archive...")
    archive = DarwinCoreArchive(archive_path)

    print("\nBuilding taxonomy tree...")
    tree = TaxonomyTree.from_archive(archive, progress_interval=100000)

    # Report statistics
    print("\n" + "=" * 70)
    print("TREE STATISTICS")
    print("=" * 70)
    print(f"  Taxa processed: {tree.stats['taxa_processed']:,}")
    print(f"  Taxa with hierarchy: {tree.stats['taxa_with_hierarchy']:,}")
    print(f"  Nodes created: {tree.stats['nodes_created']:,}")

    print("\n" + "=" * 70)
    print("NODES BY RANK")
    print("=" * 70)
    rank_counts = tree.get_rank_counts()
    for rank in [
        "domain",
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "species",
        "subspecies",
    ]:
        if rank in rank_counts:
            print(f"  {rank}: {rank_counts[rank]:,}")

    # Show other ranks
    other_ranks = {k: v for k, v in rank_counts.items() if k not in [
        "domain", "kingdom", "phylum", "class", "order", "family", "genus", "species", "subspecies"
    ]}
    if other_ranks:
        print("\n  Other ranks:")
        for rank, count in sorted(other_ranks.items(), key=lambda x: -x[1]):
            print(f"    {rank}: {count:,}")

    print("\n" + "=" * 70)
    print("DEPTH STATISTICS")
    print("=" * 70)
    depth_stats = tree.get_depth_stats()
    print(f"  Leaf nodes: {depth_stats['leaf_count']:,}")
    print(f"  Min depth: {depth_stats['min_depth']}")
    print(f"  Max depth: {depth_stats['max_depth']}")
    print(f"  Avg depth: {depth_stats['avg_depth']:.2f}")

    # Show top of the tree
    print("\n" + "=" * 70)
    print("TREE STRUCTURE (top levels)")
    print("=" * 70)
    tree.print_subtree(max_depth=4, max_children=6)

    # Find some specific taxa
    print("\n" + "=" * 70)
    print("SAMPLE LOOKUPS")
    print("=" * 70)

    test_names = ["Homo sapiens", "Canis lupus", "Felis catus", "Animalia", "Mammalia"]
    for name in test_names:
        nodes = tree.find_by_name(name)
        if nodes:
            node = nodes[0]
            path = " → ".join(n.name for n in reversed(node.get_path_to_root()[:-1]))
            print(f"\n  {name}:")
            print(f"    Rank: {node.rank}")
            print(f"    Path: {path}")
            print(f"    Children: {len(node.children)}")
            if node.wikipedia_url:
                print(f"    Wikipedia: {node.wikipedia_url}")
        else:
            print(f"\n  {name}: not found")

    # Show sample paths from species to root
    print("\n" + "=" * 70)
    print("SAMPLE PATHS (species with deepest hierarchies)")
    print("=" * 70)

    # Find species with the deepest paths
    deep_species = []
    for node in tree.root.iter_descendants():
        if node.rank == "species":
            depth = len(node.get_ancestors())
            if depth >= 6:
                deep_species.append((depth, node))

    deep_species.sort(key=lambda x: -x[0])  # Sort by depth descending

    for depth, node in deep_species[:3]:
        print(f"\n  Path for '{node.name}' (depth={depth}):")
        for ancestor in reversed(node.get_path_to_root()):
            indent = "    " * (
                len(node.get_path_to_root()) - len(ancestor.get_path_to_root())
            )
            # Truncate long names
            name = ancestor.name[:50] + "..." if len(ancestor.name) > 50 else ancestor.name
            print(f"  {indent}[{ancestor.rank}] {name}")


if __name__ == "__main__":
    main()

