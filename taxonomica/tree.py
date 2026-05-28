"""Taxonomy tree construction from Darwin Core Archive data.

This module builds a hierarchical tree structure from taxonomic data,
enabling navigation through the tree of life.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from taxonomica.dwca import DarwinCoreArchive, Taxon


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
]

# Major taxonomic ranks that define a "complete" path
# A complete path should have these ranks in sequence without gaps
MAJOR_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]

# Rank priority for sorting (lower number = higher in hierarchy)
RANK_PRIORITY = {rank: i for i, rank in enumerate(RANK_ORDER)}

# Mapping from Latin taxobox keys to normalized rank names
TAXOBOX_RANK_MAP = {
    "domain": "domain",
    "superregnum": "superkingdom",
    "regnum": "kingdom",
    "subregnum": "subkingdom",
    "superphylum": "superphylum",
    "phylum": "phylum",
    "subphylum": "subphylum",
    "infraphylum": "infraphylum",
    "superclassis": "superclass",
    "classis": "class",
    "subclassis": "subclass",
    "infraclassis": "infraclass",
    "superordo": "superorder",
    "ordo": "order",
    "subordo": "suborder",
    "infraordo": "infraorder",
    "superfamilia": "superfamily",
    "familia": "family",
    "subfamilia": "subfamily",
    "tribus": "tribe",
    "subtribus": "subtribe",
    "genus": "genus",
    "subgenus": "subgenus",
    "species": "species",
    "subspecies": "subspecies",
    # Also handle unranked_ prefixed versions
    "unranked_superregnum": "superkingdom",
    "unranked_regnum": "kingdom",
    "unranked_subregnum": "subkingdom",
    "unranked_superphylum": "superphylum",
    "unranked_phylum": "phylum",
    "unranked_subphylum": "subphylum",
    "unranked_superclassis": "superclass",
    "unranked_classis": "class",
    "unranked_subclassis": "subclass",
    "unranked_superordo": "superorder",
    "unranked_ordo": "order",
    "unranked_subordo": "suborder",
    "unranked_superfamilia": "superfamily",
    "unranked_familia": "family",
    "unranked_subfamilia": "subfamily",
    "unranked_tribus": "tribe",
    "unranked_genus": "genus",
    # Also handle English names
    "kingdom": "kingdom",
    "class": "class",
    "order": "order",
    "family": "family",
}


def parse_taxobox(taxobox: str) -> dict[str, str]:
    """Parse a taxobox string into a dictionary of field=value pairs.

    Args:
        taxobox: Raw taxobox string from the archive.

    Returns:
        Dictionary mapping field names to values.
    """
    if not taxobox:
        return {}

    taxobox = taxobox.strip()
    if taxobox.startswith("{") and taxobox.endswith("}"):
        taxobox = taxobox[1:-1]

    result = {}
    parts = re.split(r",\s*(?=\w+=)", taxobox)

    for part in parts:
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()

    return result


def clean_wiki_markup(text: str) -> str:
    """Remove Wikipedia markup from text.

    Handles:
    - [[Link]] -> Link
    - [[Page|Display]] -> Display
    - ''italic'' -> italic
    - '''bold''' -> bold
    - <ref>...</ref> tags
    - HTML entities

    Args:
        text: Text possibly containing Wikipedia markup.

    Returns:
        Cleaned text.
    """
    if not text:
        return ""

    # Remove ref tags and their contents
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/>", "", text)

    # Remove other HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove wiki links: [[Page|Display]] -> Display, [[Link]] -> Link
    text = re.sub(r"\[\[([^|\]]+\|)?([^\]]+)\]\]", r"\2", text)

    # Remove italic/bold markers
    text = re.sub(r"'{2,}", "", text)

    # Remove any remaining brackets
    text = re.sub(r"[\[\]]", "", text)

    # Clean up HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")

    # Clean up extra whitespace
    text = " ".join(text.split())

    return text.strip()


def extract_hierarchy_from_taxobox(taxobox: str) -> dict[str, str]:
    """Extract the taxonomic hierarchy from a taxobox.

    Args:
        taxobox: Raw taxobox string from the archive.

    Returns:
        Dictionary mapping normalized rank names to taxon names.
    """
    parsed = parse_taxobox(taxobox)
    hierarchy: dict[str, str] = {}

    for key, value in parsed.items():
        key_lower = key.lower()
        if key_lower in TAXOBOX_RANK_MAP:
            rank = TAXOBOX_RANK_MAP[key_lower]
            cleaned = clean_wiki_markup(value)
            if cleaned:
                hierarchy[rank] = cleaned

    return hierarchy


@dataclass
class TaxonomyNode:
    """A node in the taxonomy tree.

    Attributes:
        name: The scientific name of this taxon.
        rank: The taxonomic rank (e.g., 'species', 'genus', 'family').
        parent: Reference to the parent node (None for root).
        children: Dictionary mapping child names to child nodes.
        taxon_ids: Set of DwC-A taxon IDs that map to this node.
        wikipedia_url: URL to the Wikipedia article (if available).
    """

    name: str
    rank: str
    parent: TaxonomyNode | None = None
    children: dict[str, TaxonomyNode] = field(default_factory=dict)
    taxon_ids: set[str] = field(default_factory=set)
    wikipedia_url: str = ""

    def add_child(self, child: TaxonomyNode) -> None:
        """Add a child node."""
        child.parent = self
        self.children[child.name] = child

    def get_ancestors(self) -> list[TaxonomyNode]:
        """Get all ancestors from this node to the root.

        Returns:
            List of ancestors from immediate parent to root.
        """
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_path_to_root(self) -> list[TaxonomyNode]:
        """Get the path from this node to the root.

        Returns:
            List starting with this node and ending at the root.
        """
        return [self] + self.get_ancestors()

    def iter_descendants(self) -> Iterator[TaxonomyNode]:
        """Iterate over all descendants in depth-first order."""
        for child in self.children.values():
            yield child
            yield from child.iter_descendants()

    def get_rank_priority(self) -> int:
        """Get the rank priority (lower = higher in taxonomy hierarchy)."""
        return RANK_PRIORITY.get(self.rank, 999)

    def has_complete_path(self) -> bool:
        """Check if this node has a complete taxonomic path.

        A complete path means the ancestors include all major ranks
        (kingdom, phylum, class, order, family, genus) without gaps,
        appropriate to this node's rank.

        Returns:
            True if the path is complete, False otherwise.
        """
        if self.rank == "root":
            return True

        # Get ranks present in the path (excluding root)
        path_ranks = set()
        for node in self.get_path_to_root():
            if node.rank and node.rank != "root":
                path_ranks.add(node.rank)

        # Determine which major ranks should be present based on this node's rank
        if self.rank not in MAJOR_RANKS:
            # For non-major ranks (like subfamily, tribe), check up to the next major rank
            # Find the closest major rank above this one
            my_priority = RANK_PRIORITY.get(self.rank, 999)
            required_major_ranks = [r for r in MAJOR_RANKS if RANK_PRIORITY.get(r, 999) < my_priority]
        else:
            # For major ranks, all ranks above should be present
            my_idx = MAJOR_RANKS.index(self.rank)
            required_major_ranks = MAJOR_RANKS[:my_idx]

        # Check if all required major ranks are present
        for required_rank in required_major_ranks:
            if required_rank not in path_ranks:
                return False

        return True

    def get_path_completeness(self) -> tuple[int, int]:
        """Get the completeness of the taxonomic path.

        Returns:
            Tuple of (present_major_ranks, required_major_ranks).
        """
        if self.rank == "root":
            return (0, 0)

        path_ranks = set()
        for node in self.get_path_to_root():
            if node.rank and node.rank != "root":
                path_ranks.add(node.rank)

        my_priority = RANK_PRIORITY.get(self.rank, 999)
        required_major_ranks = [r for r in MAJOR_RANKS if RANK_PRIORITY.get(r, 999) < my_priority]
        present = sum(1 for r in required_major_ranks if r in path_ranks)

        return (present, len(required_major_ranks))

    def count_descendants(self) -> int:
        """Count all descendants of this node."""
        return sum(1 for _ in self.iter_descendants())

    def get_species_descendants(self) -> Iterator[TaxonomyNode]:
        """Iterate over all species-level descendants."""
        for desc in self.iter_descendants():
            if desc.rank == "species":
                yield desc

    def __repr__(self) -> str:
        return f"TaxonomyNode({self.name!r}, rank={self.rank!r}, children={len(self.children)})"


class TaxonomyTree:
    """A tree representing the taxonomic hierarchy.

    This class builds and manages a tree structure from Darwin Core Archive
    data, allowing navigation through the tree of life.
    """

    def __init__(self) -> None:
        """Initialize an empty taxonomy tree."""
        # Root node representing "Life" or the top of the tree
        self.root = TaxonomyNode(name="Life", rank="root")

        # Index for fast lookup by name and rank
        self._nodes_by_name: dict[str, list[TaxonomyNode]] = {}
        self._nodes_by_name_rank: dict[tuple[str, str], TaxonomyNode] = {}

        # Index by taxon ID
        self._nodes_by_taxon_id: dict[str, TaxonomyNode] = {}

        # Statistics
        self.stats: dict[str, int] = {
            "taxa_processed": 0,
            "taxa_with_hierarchy": 0,
            "nodes_created": 0,
            "nodes_linked": 0,
        }

    def _register_node(self, node: TaxonomyNode, taxon_id: str | None = None) -> None:
        """Register a node in the lookup indices."""
        if node.name not in self._nodes_by_name:
            self._nodes_by_name[node.name] = []
        if node not in self._nodes_by_name[node.name]:
            self._nodes_by_name[node.name].append(node)

        # Also register by (name, rank) tuple for precise lookups
        key = (node.name, node.rank)
        if key not in self._nodes_by_name_rank:
            self._nodes_by_name_rank[key] = node

        if taxon_id:
            node.taxon_ids.add(taxon_id)
            self._nodes_by_taxon_id[taxon_id] = node

    def find_by_name(self, name: str) -> list[TaxonomyNode]:
        """Find all nodes with the given name.

        Args:
            name: The taxon name to search for.

        Returns:
            List of matching nodes (may be empty).
        """
        return self._nodes_by_name.get(name, [])

    def find_by_name_and_rank(self, name: str, rank: str) -> TaxonomyNode | None:
        """Find a node by name and rank.

        Args:
            name: The taxon name.
            rank: The taxonomic rank.

        Returns:
            The matching node, or None if not found.
        """
        return self._nodes_by_name_rank.get((name, rank))

    def find_by_taxon_id(self, taxon_id: str) -> TaxonomyNode | None:
        """Find a node by its Darwin Core Archive taxon ID.

        Args:
            taxon_id: The taxon ID from the archive.

        Returns:
            The matching node, or None if not found.
        """
        return self._nodes_by_taxon_id.get(taxon_id)

    @classmethod
    def from_archive(
        cls,
        archive: DarwinCoreArchive,
        *,
        progress_interval: int = 50000,
    ) -> TaxonomyTree:
        """Build a taxonomy tree from a Darwin Core Archive.

        Uses a two-pass approach:
        1. First pass: Create all nodes and collect hierarchy info
        2. Second pass: Link nodes by matching parent names

        Args:
            archive: The DarwinCoreArchive to read from.
            progress_interval: Print progress every N taxa.

        Returns:
            A populated TaxonomyTree.
        """
        tree = cls()

        # First pass: collect all taxa and their parent info
        print("  Pass 1: Collecting taxa and hierarchy info...")
        taxa_info: list[tuple[str, str, str, dict[str, str], str]] = []
        # (taxon_id, name, rank, hierarchy_dict, wikipedia_url)

        for i, taxon in enumerate(archive.iter_taxa(), 1):
            tree.stats["taxa_processed"] += 1

            # Skip synonyms
            if taxon.taxonomic_status == "synonym":
                continue

            if not taxon.scientific_name:
                continue

            # Extract hierarchy from taxobox
            hierarchy = extract_hierarchy_from_taxobox(taxon.taxobox)

            # Also check standard DwC fields as fallback/supplement
            if taxon.kingdom and "kingdom" not in hierarchy:
                hierarchy["kingdom"] = taxon.kingdom
            if taxon.phylum and "phylum" not in hierarchy:
                hierarchy["phylum"] = taxon.phylum
            if taxon.class_ and "class" not in hierarchy:
                hierarchy["class"] = taxon.class_
            if taxon.order and "order" not in hierarchy:
                hierarchy["order"] = taxon.order
            if taxon.family and "family" not in hierarchy:
                hierarchy["family"] = taxon.family
            if taxon.genus and "genus" not in hierarchy:
                hierarchy["genus"] = taxon.genus

            rank = (taxon.rank or "").lower()
            if rank not in RANK_ORDER:
                rank = ""

            taxa_info.append((
                taxon.id,
                taxon.scientific_name,
                rank,
                hierarchy,
                taxon.references or "",
            ))

            if progress_interval and i % progress_interval == 0:
                print(f"    Collected {i:,} taxa...")

        print(f"    Total collected: {len(taxa_info):,} taxa")

        # Second pass: Create nodes for taxa that have their own Wikipedia page
        print("  Pass 2: Creating nodes...")
        for taxon_id, name, rank, hierarchy, url in taxa_info:
            if not rank:
                continue

            # Create or find the node for this taxon
            existing = tree.find_by_name_and_rank(name, rank)
            if existing:
                existing.taxon_ids.add(taxon_id)
                tree._nodes_by_taxon_id[taxon_id] = existing
                if url and not existing.wikipedia_url:
                    existing.wikipedia_url = url
            else:
                node = TaxonomyNode(name=name, rank=rank, wikipedia_url=url)
                node.taxon_ids.add(taxon_id)
                tree.root.add_child(node)  # Temporarily attach to root
                tree._register_node(node, taxon_id)
                tree.stats["nodes_created"] += 1

        print(f"    Created {tree.stats['nodes_created']:,} nodes")

        # Third pass: Link nodes using hierarchy info
        print("  Pass 3: Linking nodes to parents...")
        linked = 0

        for taxon_id, name, rank, hierarchy, _ in taxa_info:
            if not rank:
                continue

            node = tree.find_by_taxon_id(taxon_id)
            if not node or node.parent != tree.root:
                continue  # Already linked or not found

            # Find the best parent from hierarchy
            parent_node = tree._find_best_parent(node, hierarchy)
            if parent_node and parent_node != tree.root:
                # Re-parent the node
                if node.name in tree.root.children:
                    del tree.root.children[node.name]
                parent_node.add_child(node)
                linked += 1

        tree.stats["nodes_linked"] = linked
        print(f"    Linked {linked:,} nodes to parents")

        # Fourth pass: Create implicit parent nodes from hierarchy
        print("  Pass 4: Creating implicit parent nodes from hierarchy...")
        implicit_created = 0

        for taxon_id, name, rank, hierarchy, _ in taxa_info:
            if not hierarchy:
                continue

            # Sort hierarchy by rank order
            sorted_items = sorted(
                [(r, n) for r, n in hierarchy.items() if r in RANK_ORDER],
                key=lambda x: RANK_ORDER.index(x[0]),
            )

            # Walk through hierarchy creating/linking nodes
            prev_node: TaxonomyNode | None = None
            for h_rank, h_name in sorted_items:
                existing = tree.find_by_name_and_rank(h_name, h_rank)
                if not existing:
                    # Create implicit node
                    existing = TaxonomyNode(name=h_name, rank=h_rank)
                    if prev_node:
                        prev_node.add_child(existing)
                    else:
                        tree.root.add_child(existing)
                    tree._register_node(existing)
                    implicit_created += 1
                elif existing.parent == tree.root and prev_node:
                    # Re-parent existing node
                    if existing.name in tree.root.children:
                        del tree.root.children[existing.name]
                    prev_node.add_child(existing)
                    tree.stats["nodes_linked"] += 1

                prev_node = existing

        print(f"    Created {implicit_created:,} implicit nodes")
        tree.stats["nodes_created"] += implicit_created

        # Fifth pass: Link orphaned species to genera by name prefix
        print("  Pass 5: Linking species to genera by name...")
        species_linked = 0

        for node in list(tree.root.children.values()):
            if node.rank != "species":
                continue

            # Try to find genus from species name (binomial: "Genus species")
            parts = node.name.split()
            if len(parts) >= 2:
                genus_name = parts[0]
                genus_node = tree.find_by_name_and_rank(genus_name, "genus")
                if genus_node and genus_node != node.parent:
                    del tree.root.children[node.name]
                    genus_node.add_child(node)
                    species_linked += 1

        print(f"    Linked {species_linked:,} species to genera by name")
        tree.stats["nodes_linked"] += species_linked

        # Sixth pass: Propagate hierarchy from species to orphaned genera
        print("  Pass 6: Propagating hierarchy from species to genera...")

        # Collect hierarchy info from species for each genus
        genus_hierarchy: dict[str, dict[str, str]] = {}
        for taxon_id, name, rank, hierarchy, _ in taxa_info:
            if rank != "species" or not hierarchy:
                continue

            # Get genus name from hierarchy or species name
            genus_name = hierarchy.get("genus")
            if not genus_name and name:
                parts = name.split()
                if len(parts) >= 2:
                    genus_name = parts[0]

            if not genus_name:
                continue

            # Collect hierarchy above genus level
            if genus_name not in genus_hierarchy:
                genus_hierarchy[genus_name] = {}
            for h_rank, h_name in hierarchy.items():
                if h_rank != "genus" and h_rank != "species" and h_rank != "subspecies":
                    genus_hierarchy[genus_name][h_rank] = h_name

        # Now link orphaned genera using collected hierarchy
        genera_linked = 0
        for node in list(tree.root.children.values()):
            if node.rank != "genus":
                continue

            if node.name not in genus_hierarchy:
                continue

            hierarchy = genus_hierarchy[node.name]
            parent_node = tree._find_best_parent(node, hierarchy)
            if parent_node and parent_node != tree.root:
                del tree.root.children[node.name]
                parent_node.add_child(node)
                genera_linked += 1

        print(f"    Linked {genera_linked:,} genera using species hierarchy")
        tree.stats["nodes_linked"] += genera_linked

        # Report orphan stats
        orphans = len(tree.root.children)
        print(f"    Remaining orphans (direct children of root): {orphans:,}")

        return tree

    def _find_best_parent(
        self, node: TaxonomyNode, hierarchy: dict[str, str]
    ) -> TaxonomyNode | None:
        """Find the best parent node for a given node based on hierarchy info.

        Looks for the closest ancestor rank that has a matching node.
        """
        if not hierarchy:
            return None

        node_rank_idx = RANK_ORDER.index(node.rank) if node.rank in RANK_ORDER else -1
        if node_rank_idx <= 0:
            return None

        # Look for parent ranks in order from closest to furthest
        for i in range(node_rank_idx - 1, -1, -1):
            parent_rank = RANK_ORDER[i]
            if parent_rank in hierarchy:
                parent_name = hierarchy[parent_rank]
                parent_node = self.find_by_name_and_rank(parent_name, parent_rank)
                if parent_node:
                    return parent_node

        return None

    def get_rank_counts(self) -> dict[str, int]:
        """Get the count of nodes at each rank.

        Returns:
            Dictionary mapping rank names to counts.
        """
        counts: dict[str, int] = {}
        for node in self.root.iter_descendants():
            rank = node.rank
            counts[rank] = counts.get(rank, 0) + 1
        return counts

    def get_depth_stats(self) -> dict[str, int | float]:
        """Get statistics about tree depth.

        Returns:
            Dictionary with min, max, and average depth.
        """
        depths = []
        for node in self.root.iter_descendants():
            if not node.children:  # Leaf node
                depths.append(len(node.get_ancestors()))

        if not depths:
            return {"min_depth": 0, "max_depth": 0, "avg_depth": 0.0}

        return {
            "min_depth": min(depths),
            "max_depth": max(depths),
            "avg_depth": sum(depths) / len(depths),
            "leaf_count": len(depths),
        }

    def print_subtree(
        self,
        node: TaxonomyNode | None = None,
        *,
        max_depth: int = 3,
        max_children: int = 5,
        indent: str = "",
    ) -> None:
        """Print a subtree for debugging/visualization.

        Args:
            node: Starting node (defaults to root).
            max_depth: Maximum depth to print.
            max_children: Maximum children to show per node.
            indent: Current indentation string.
        """
        if node is None:
            node = self.root

        print(f"{indent}{node.name} ({node.rank}) [{len(node.children)} children]")

        if max_depth <= 0:
            return

        children = list(node.children.values())
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

