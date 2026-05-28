"""Taxonomy tree construction from GBIF Backbone data.

This module builds a hierarchical tree structure from the GBIF Backbone
Taxonomy, which has explicit parent-child relationships via parentNameUsageID.

This is much more efficient than the Wikipedia parser because:
1. Parent relationships are explicit (no inference needed)
2. Hierarchy is complete and consistent
3. Single pass construction is possible
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from taxonomica.gbif_backbone import GBIFBackbone, GBIFTaxon


# Standard taxonomic ranks in hierarchical order (high to low)
RANK_ORDER = [
    "domain",
    "superkingdom",
    "kingdom",
    "subkingdom",
    "superphylum",
    "phylum",
    "subphylum",
    "infraphylum",
    "superclass",
    "class",
    "subclass",
    "infraclass",
    "superorder",
    "order",
    "suborder",
    "infraorder",
    "superfamily",
    "family",
    "subfamily",
    "tribe",
    "subtribe",
    "genus",
    "subgenus",
    "species",
    "subspecies",
    "variety",
    "form",
]

# Major taxonomic ranks that define a "complete" path
MAJOR_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]

# Rank priority for sorting (lower number = higher in hierarchy)
RANK_PRIORITY = {rank: i for i, rank in enumerate(RANK_ORDER)}


@dataclass
class TaxonomyNode:
    """A node in the taxonomy tree.

    Attributes:
        id: The GBIF taxon ID.
        name: The canonical/scientific name of this taxon.
        rank: The taxonomic rank (e.g., 'species', 'genus', 'family').
        parent: Reference to the parent node (None for root).
        children: Dictionary mapping child IDs to child nodes.
        scientific_name: Full scientific name with authorship.
        vernacular_names: List of common names (populated separately).
    """

    id: str
    name: str
    rank: str
    parent: TaxonomyNode | None = None
    children: dict[str, TaxonomyNode] = field(default_factory=dict)
    scientific_name: str = ""
    vernacular_names: list[str] = field(default_factory=list)

    def add_child(self, child: TaxonomyNode) -> None:
        """Add a child node."""
        child.parent = self
        self.children[child.id] = child

    def get_ancestors(self) -> list[TaxonomyNode]:
        """Get all ancestors from this node to the root."""
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_path_to_root(self) -> list[TaxonomyNode]:
        """Get the path from this node to the root."""
        return [self] + self.get_ancestors()

    def iter_descendants(self) -> Iterator[TaxonomyNode]:
        """Iterate over all descendants in depth-first order."""
        for child in self.children.values():
            yield child
            yield from child.iter_descendants()

    def count_descendants(self) -> int:
        """Count all descendants of this node."""
        return sum(1 for _ in self.iter_descendants())

    def get_rank_priority(self) -> int:
        """Get the rank priority (lower = higher in taxonomy hierarchy)."""
        return RANK_PRIORITY.get(self.rank, 999)

    def has_complete_path(self) -> bool:
        """Check if this node has a complete taxonomic path.

        A complete path means the ancestors include all major ranks
        (kingdom, phylum, class, order, family, genus) without gaps,
        appropriate to this node's rank.

        Kingdoms at the root level are always considered complete.
        """
        if self.rank == "root":
            return True

        # Kingdoms at root are complete (they are the top of their tree)
        if self.rank == "kingdom" and self.parent and self.parent.rank == "root":
            return True

        # Get ranks present in the path (excluding root)
        path_ranks = set()
        for node in self.get_path_to_root():
            if node.rank and node.rank != "root":
                path_ranks.add(node.rank)

        # For major ranks, all ranks above should be present
        if self.rank in MAJOR_RANKS:
            my_idx = MAJOR_RANKS.index(self.rank)
            required_major_ranks = MAJOR_RANKS[:my_idx]
        else:
            # For non-major ranks, check up to the closest major rank
            my_priority = RANK_PRIORITY.get(self.rank, 999)
            required_major_ranks = [
                r for r in MAJOR_RANKS if RANK_PRIORITY.get(r, 999) < my_priority
            ]

        for required_rank in required_major_ranks:
            if required_rank not in path_ranks:
                return False

        return True

    def __repr__(self) -> str:
        return f"TaxonomyNode({self.name!r}, rank={self.rank!r}, children={len(self.children)})"


class GBIFTaxonomyTree:
    """A tree representing the GBIF Backbone taxonomic hierarchy.

    This tree is built using explicit parent-child relationships from
    the GBIF Backbone, ensuring complete and accurate hierarchies.
    """

    def __init__(self) -> None:
        """Initialize an empty taxonomy tree."""
        self.root = TaxonomyNode(id="0", name="Life", rank="root")

        # Index for fast lookup by ID
        self._nodes_by_id: dict[str, TaxonomyNode] = {"0": self.root}

        # Index by name for search
        self._nodes_by_name: dict[str, list[TaxonomyNode]] = {}

        # Statistics
        self.stats: dict[str, int] = {
            "taxa_processed": 0,
            "accepted_taxa": 0,
            "nodes_created": 0,
            "nodes_linked": 0,
        }

    def _register_node(self, node: TaxonomyNode) -> None:
        """Register a node in the lookup indices."""
        self._nodes_by_id[node.id] = node

        if node.name not in self._nodes_by_name:
            self._nodes_by_name[node.name] = []
        self._nodes_by_name[node.name].append(node)

    def find_by_id(self, taxon_id: str) -> TaxonomyNode | None:
        """Find a node by its GBIF taxon ID."""
        return self._nodes_by_id.get(taxon_id)

    def find_by_name(self, name: str, case_sensitive: bool = True) -> list[TaxonomyNode]:
        """Find all nodes with the given name.
        
        Args:
            name: The name to search for.
            case_sensitive: If False, performs case-insensitive matching.
            
        Returns:
            List of matching nodes.
        """
        if case_sensitive:
            return self._nodes_by_name.get(name, [])
        
        # Case-insensitive search
        name_lower = name.lower()
        results = []
        for stored_name, nodes in self._nodes_by_name.items():
            if stored_name.lower() == name_lower:
                results.extend(nodes)
        return results

    @classmethod
    def from_backbone(
        cls,
        backbone: GBIFBackbone,
        *,
        accepted_only: bool = True,
        progress_interval: int = 500000,
    ) -> GBIFTaxonomyTree:
        """Build a taxonomy tree from the GBIF Backbone.

        Uses a two-pass approach:
        1. First pass: Create all nodes
        2. Second pass: Link nodes to parents

        Args:
            backbone: The GBIFBackbone instance to read from.
            accepted_only: If True, only include accepted taxa.
            progress_interval: Print progress every N taxa.

        Returns:
            A populated GBIFTaxonomyTree.
        """
        tree = cls()

        # First pass: Create all nodes
        print("  Pass 1: Creating nodes...")
        pending_links: list[tuple[str, str]] = []  # (child_id, parent_id)

        for taxon in backbone.iter_taxa(accepted_only=accepted_only):
            tree.stats["taxa_processed"] += 1

            if taxon.is_accepted:
                tree.stats["accepted_taxa"] += 1

            # Create node
            node = TaxonomyNode(
                id=taxon.id,
                name=taxon.canonical_name or taxon.scientific_name,
                rank=taxon.rank.lower() if taxon.rank else "",
                scientific_name=taxon.scientific_name,
            )
            tree._register_node(node)
            tree.stats["nodes_created"] += 1

            # Record parent link for second pass
            if taxon.parent_id:
                pending_links.append((taxon.id, taxon.parent_id))

            if progress_interval and tree.stats["taxa_processed"] % progress_interval == 0:
                print(f"    Processed {tree.stats['taxa_processed']:,} taxa...")

        print(f"    Created {tree.stats['nodes_created']:,} nodes")

        # Second pass: Link nodes to parents
        print("  Pass 2: Linking nodes to parents...")

        linked_ids = set()
        for child_id, parent_id in pending_links:
            child_node = tree._nodes_by_id.get(child_id)
            parent_node = tree._nodes_by_id.get(parent_id)

            if child_node and parent_node:
                parent_node.add_child(child_node)
                tree.stats["nodes_linked"] += 1
                linked_ids.add(child_id)
            elif child_node:
                # Parent not found (might be filtered out), attach to root
                tree.root.add_child(child_node)
                linked_ids.add(child_id)

        # Attach any unlinked nodes (no parent ID) to root
        for node_id, node in tree._nodes_by_id.items():
            if node_id != "0" and node_id not in linked_ids and node.parent is None:
                tree.root.add_child(node)

        print(f"    Linked {tree.stats['nodes_linked']:,} nodes")

        # Count orphans (direct children of root that aren't kingdoms/domains)
        orphans = sum(
            1
            for n in tree.root.children.values()
            if n.rank not in ("kingdom", "domain", "superkingdom")
        )
        print(f"    Orphans at root level: {orphans:,}")

        return tree

    def get_rank_counts(self) -> dict[str, int]:
        """Get the count of nodes at each rank."""
        counts: dict[str, int] = {}
        for node in self._nodes_by_id.values():
            if node.rank and node.rank != "root":
                counts[node.rank] = counts.get(node.rank, 0) + 1
        return counts

    def print_subtree(
        self,
        node: TaxonomyNode | None = None,
        *,
        max_depth: int = 3,
        max_children: int = 5,
        indent: str = "",
    ) -> None:
        """Print a subtree for debugging/visualization."""
        if node is None:
            node = self.root

        print(f"{indent}{node.name} ({node.rank}) [{len(node.children)} children]")

        if max_depth <= 0:
            return

        children = sorted(node.children.values(), key=lambda n: n.name)
        for i, child in enumerate(children[:max_children]):
            is_last = i == min(len(children), max_children) - 1
            prefix = "└── " if is_last else "├── "
            child_indent = indent + ("    " if is_last else "│   ")
            self.print_subtree(
                child,
                max_depth=max_depth - 1,
                max_children=max_children,
                indent=indent + prefix,
            )

        if len(children) > max_children:
            print(f"{indent}    ... and {len(children) - max_children} more")

    def add_vernacular_names(self, backbone: GBIFBackbone) -> int:
        """Add vernacular names to nodes from the backbone.

        Args:
            backbone: The GBIFBackbone instance to read from.

        Returns:
            Number of names added.
        """
        count = 0
        for vn in backbone.iter_vernacular_names():
            node = self._nodes_by_id.get(vn.taxon_id)
            if node and vn.name:
                # Prefer English names
                if vn.language in ("en", "eng", ""):
                    node.vernacular_names.insert(0, vn.name)
                else:
                    node.vernacular_names.append(vn.name)
                count += 1
        return count

