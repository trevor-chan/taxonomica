"""Taxonomy tree construction from ColDP data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from taxonomica.coldp import ColdPArchive, ColdPNameUsage

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


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
    "section",
    "species",
    "subspecies",
    "variety",
    "form",
]

MAJOR_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
RANK_PRIORITY = {rank: i for i, rank in enumerate(RANK_ORDER)}

RANK_ALIASES = {
    "superregnum": "superkingdom",
    "regnum": "kingdom",
    "subregnum": "subkingdom",
    "superdivisio": "superphylum",
    "divisio": "phylum",
    "subdivisio": "subphylum",
    "infradivisio": "infraphylum",
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
    "supersectio": "section",
    "sectio": "section",
    "subsectio": "section",
    "species": "species",
    "subspecies": "subspecies",
    "varietas": "variety",
    "subvarietas": "variety",
    "forma": "form",
}


def normalize_rank(rank: str) -> str:
    """Normalize ColDP/Wikispecies rank spellings."""
    rank = (rank or "").strip().lower()
    return RANK_ALIASES.get(rank, rank)


@dataclass
class ColdPTaxonomyNode:
    """A node in a taxonomy tree built from ColDP name usages."""

    id: str
    name: str
    rank: str
    parent: ColdPTaxonomyNode | None = None
    children: dict[str, ColdPTaxonomyNode] = field(default_factory=dict)
    scientific_name: str = ""
    authorship: str = ""
    status: str = ""
    link: str = ""
    wikipedia_url: str = ""
    alternative_id: str = ""
    vernacular_names: list[str] = field(default_factory=list)

    def add_child(self, child: ColdPTaxonomyNode) -> None:
        """Add a child node."""
        child.parent = self
        self.children[child.id] = child

    def get_ancestors(self) -> list[ColdPTaxonomyNode]:
        """Get all ancestors from this node to the root."""
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_path_to_root(self) -> list[ColdPTaxonomyNode]:
        """Get the path from this node to the root."""
        return [self] + self.get_ancestors()

    def iter_descendants(self) -> Iterator[ColdPTaxonomyNode]:
        """Iterate over all descendants in depth-first order."""
        for child in self.children.values():
            yield child
            yield from child.iter_descendants()

    def count_descendants(self) -> int:
        """Count all descendants of this node."""
        return sum(1 for _ in self.iter_descendants())

    def get_rank_priority(self) -> int:
        """Get the rank priority, with higher ranks sorted first."""
        return RANK_PRIORITY.get(self.rank, 999)

    def has_complete_path(self) -> bool:
        """Return whether this node has the expected major-rank ancestors."""
        if self.rank == "root":
            return True

        if self.rank in {"domain", "superkingdom", "kingdom"}:
            return True

        path_ranks = {
            node.rank
            for node in self.get_path_to_root()
            if node.rank and node.rank != "root"
        }

        if self.rank in MAJOR_RANKS:
            my_idx = MAJOR_RANKS.index(self.rank)
            required_major_ranks = MAJOR_RANKS[:my_idx]
        else:
            my_priority = RANK_PRIORITY.get(self.rank, 999)
            required_major_ranks = [
                rank
                for rank in MAJOR_RANKS
                if RANK_PRIORITY.get(rank, 999) < my_priority
            ]

        return all(rank in path_ranks for rank in required_major_ranks)

    def __repr__(self) -> str:
        return (
            f"ColdPTaxonomyNode({self.name!r}, rank={self.rank!r}, "
            f"children={len(self.children)})"
        )


class ColdPTaxonomyTree:
    """A taxonomy tree built from ColDP ``NameUsage.tsv`` parent IDs."""

    def __init__(self) -> None:
        self.root = ColdPTaxonomyNode(id="0", name="Life", rank="root")
        self._nodes_by_id: dict[str, ColdPTaxonomyNode] = {"0": self.root}
        self._nodes_by_name: dict[str, list[ColdPTaxonomyNode]] = {}

        self.stats: dict[str, int] = {
            "taxa_processed": 0,
            "accepted_taxa": 0,
            "taxa_skipped": 0,
            "nodes_created": 0,
            "duplicate_ids": 0,
            "self_parent_links": 0,
            "nodes_linked": 0,
            "missing_parent_links": 0,
            "root_children": 0,
            "root_orphans": 0,
        }

    def _register_node(self, node: ColdPTaxonomyNode) -> None:
        self._nodes_by_id[node.id] = node
        self._nodes_by_name.setdefault(node.name, []).append(node)

    def find_by_id(self, taxon_id: str) -> ColdPTaxonomyNode | None:
        """Find a node by ColDP ID."""
        return self._nodes_by_id.get(taxon_id)

    def find_by_name(
        self, name: str, *, case_sensitive: bool = True
    ) -> list[ColdPTaxonomyNode]:
        """Find nodes by scientific name."""
        if case_sensitive:
            return self._nodes_by_name.get(name, [])

        name_lower = name.lower()
        results = []
        for stored_name, nodes in self._nodes_by_name.items():
            if stored_name.lower() == name_lower:
                results.extend(nodes)
        return results

    def iter_nodes(self, *, include_root: bool = False) -> Iterator[ColdPTaxonomyNode]:
        """Iterate over all nodes in the tree index."""
        for node in self._nodes_by_id.values():
            if include_root or node is not self.root:
                yield node

    @classmethod
    def from_archive(
        cls,
        archive: ColdPArchive,
        *,
        accepted_only: bool = True,
        progress_interval: int = 500000,
        limit: int | None = None,
    ) -> ColdPTaxonomyTree:
        """Build a tree from a ColDP archive."""
        tree = cls()
        pending_links: list[tuple[str, str]] = []

        print("  Pass 1: Creating nodes from NameUsage.tsv...")
        for usage in archive.iter_name_usages():
            tree.stats["taxa_processed"] += 1

            if accepted_only and not usage.is_accepted:
                tree.stats["taxa_skipped"] += 1
                continue

            if not usage.id or not usage.scientific_name:
                tree.stats["taxa_skipped"] += 1
                continue

            if usage.id in tree._nodes_by_id:
                tree.stats["duplicate_ids"] += 1
                continue

            if usage.is_accepted:
                tree.stats["accepted_taxa"] += 1

            node = ColdPTaxonomyNode(
                id=usage.id,
                name=usage.display_name,
                rank=normalize_rank(usage.rank),
                scientific_name=usage.scientific_name,
                authorship=usage.authorship,
                status=usage.status,
                link=usage.link,
                wikipedia_url=usage.wikipedia_url,
            )
            tree._register_node(node)
            tree.stats["nodes_created"] += 1

            if usage.parent_id:
                pending_links.append((usage.id, usage.parent_id))

            if progress_interval and tree.stats["taxa_processed"] % progress_interval == 0:
                print(f"    Processed {tree.stats['taxa_processed']:,} name usages...")

            if limit and tree.stats["taxa_processed"] >= limit:
                break

        print(f"    Created {tree.stats['nodes_created']:,} nodes")

        print("  Pass 2: Linking nodes to parents...")
        linked_ids: set[str] = set()
        for child_id, parent_id in pending_links:
            child = tree._nodes_by_id.get(child_id)
            parent = tree._nodes_by_id.get(parent_id)

            if child is None:
                continue

            if child_id == parent_id:
                tree.stats["self_parent_links"] += 1
                continue

            if parent is None:
                tree.root.add_child(child)
                linked_ids.add(child_id)
                tree.stats["missing_parent_links"] += 1
                continue

            parent.add_child(child)
            linked_ids.add(child_id)
            tree.stats["nodes_linked"] += 1

        for node in tree.iter_nodes():
            if node.id not in linked_ids and node.parent is None:
                tree.root.add_child(node)

        tree.stats["root_children"] = len(tree.root.children)
        tree.stats["root_orphans"] = sum(
            1
            for node in tree.root.children.values()
            if node.rank not in {"domain", "superkingdom", "kingdom"}
        )
        print(f"    Linked {tree.stats['nodes_linked']:,} nodes")
        print(f"    Missing parent links: {tree.stats['missing_parent_links']:,}")
        print(f"    Root children: {tree.stats['root_children']:,}")

        return tree

    def add_vernacular_names(
        self,
        archive: ColdPArchive,
        *,
        languages: Iterable[str] = ("en", "eng", ""),
    ) -> int:
        """Attach vernacular names from ``VernacularName.tsv`` to matching nodes."""
        language_set = {language.lower() for language in languages}
        added = 0

        for vernacular in archive.iter_vernacular_names():
            if language_set and vernacular.language.lower() not in language_set:
                continue

            node = self._nodes_by_id.get(vernacular.taxon_id)
            if not node or not vernacular.name:
                continue

            if vernacular.name not in node.vernacular_names:
                node.vernacular_names.append(vernacular.name)
                added += 1

        return added

    def get_rank_counts(self) -> dict[str, int]:
        """Get node counts grouped by normalized rank."""
        counts: dict[str, int] = {}
        for node in self.iter_nodes():
            rank = node.rank or "unknown"
            counts[rank] = counts.get(rank, 0) + 1
        return counts

    def get_quality_stats(self) -> dict[str, int | float]:
        """Summarize tree completeness and useful metadata coverage."""
        leaf_count = 0
        min_depth: int | None = None
        max_depth = 0
        depth_total = 0
        species_count = 0
        complete_species_count = 0
        wikipedia_url_count = 0

        for node in self.iter_nodes():
            if node.wikipedia_url:
                wikipedia_url_count += 1

            if not node.children:
                leaf_count += 1
                depth = len(node.get_ancestors())
                depth_total += depth
                min_depth = depth if min_depth is None else min(min_depth, depth)
                max_depth = max(max_depth, depth)

            if node.rank == "species":
                species_count += 1
                if node.has_complete_path():
                    complete_species_count += 1

        avg_depth = depth_total / leaf_count if leaf_count else 0.0
        complete_species_ratio = (
            complete_species_count / species_count if species_count else 0.0
        )

        return {
            "leaf_count": leaf_count,
            "min_depth": min_depth or 0,
            "max_depth": max_depth,
            "avg_depth": avg_depth,
            "species_count": species_count,
            "complete_species_count": complete_species_count,
            "complete_species_ratio": complete_species_ratio,
            "wikipedia_url_count": wikipedia_url_count,
        }

    def print_subtree(
        self,
        node: ColdPTaxonomyNode | None = None,
        *,
        max_depth: int = 3,
        max_children: int = 5,
        indent: str = "",
    ) -> None:
        """Print a compact subtree for debugging."""
        if node is None:
            node = self.root

        print(f"{indent}{node.name} ({node.rank}) [{len(node.children)} children]")
        self._print_subtree_children(
            node,
            max_depth=max_depth,
            max_children=max_children,
            indent=indent,
        )

    def _print_subtree_children(
        self,
        node: ColdPTaxonomyNode,
        *,
        max_depth: int,
        max_children: int,
        indent: str,
    ) -> None:
        if max_depth <= 0:
            return

        children = sorted(
            node.children.values(),
            key=lambda child: (child.get_rank_priority(), child.name.lower()),
        )
        shown_children = children[:max_children]
        for index, child in enumerate(shown_children):
            is_last = index == len(shown_children) - 1 and len(children) <= max_children
            prefix = "`-- " if is_last else "|-- "
            child_indent = indent + ("    " if is_last else "|   ")
            print(
                f"{indent}{prefix}{child.name} "
                f"({child.rank}) [{len(child.children)} children]"
            )
            self._print_subtree_children(
                child,
                max_depth=max_depth - 1,
                max_children=max_children,
                indent=child_indent,
            )

        if len(children) > max_children:
            print(f"{indent}    ... and {len(children) - max_children} more")


def summarize_usage_for_debug(usage: ColdPNameUsage) -> str:
    """Return a compact one-line summary of a ColDP name usage."""
    rank = normalize_rank(usage.rank) or "unknown"
    return f"{usage.id}: {usage.display_name} [{rank}] parent={usage.parent_id or '-'}"
