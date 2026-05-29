"""Core taxonomy tree model used by the playable Taxonomica runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


RANK_ORDER = [
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]
MAJOR_RANKS = RANK_ORDER.copy()
RANK_PRIORITY = {rank: index for index, rank in enumerate(RANK_ORDER)}


@dataclass(eq=False)
class TaxonNode:
    """One path-keyed node in the playable taxonomy tree."""

    id: str
    name: str
    rank: str
    parent: TaxonNode | None = None
    children: dict[str, TaxonNode] = field(default_factory=dict)
    scientific_name: str = ""
    vernacular_names: list[str] = field(default_factory=list)
    playable_species_count: int = 0
    tree_species_count: int = 0
    easy_species_count: int = 0
    medium_species_count: int = 0
    hard_species_count: int = 0
    expert_target_species_count: int = 0
    target_difficulty: str = ""
    description_length: int = 0
    article_length: int = 0
    pageview_count: int = 0
    difficulty_score: float = 0.0
    pageview_score: float = 0.0
    article_score: float = 0.0
    vernacular_score: float = 0.0
    category_score: float = 0.0
    category_modifier: int = 0
    target_rank: int = 0
    tree_rank: int = 0

    def add_child(self, child: TaxonNode) -> None:
        """Attach a child node."""
        child.parent = self
        self.children[child.id] = child

    def get_ancestors(self) -> list[TaxonNode]:
        """Return ancestors from parent to root."""
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_path_to_root(self) -> list[TaxonNode]:
        """Return this node followed by its ancestors."""
        return [self] + self.get_ancestors()

    def iter_descendants(self) -> Iterator[TaxonNode]:
        """Iterate over descendants in depth-first order."""
        for child in self.children.values():
            yield child
            yield from child.iter_descendants()

    def count_descendants(self) -> int:
        """Return playable species below this node without walking the tree."""
        if self.rank == "species":
            return 0
        return self.playable_species_count

    def get_rank_priority(self) -> int:
        """Return sort priority for this node's rank."""
        return RANK_PRIORITY.get(self.rank, 999)

    def has_complete_path(self) -> bool:
        """Return whether the node has all required major ranks above it."""
        if self.rank == "root":
            return True
        if self.rank not in MAJOR_RANKS:
            return False

        path_ranks = {
            node.rank
            for node in self.get_path_to_root()
            if node.rank and node.rank != "root"
        }
        required = MAJOR_RANKS[: MAJOR_RANKS.index(self.rank) + 1]
        return all(rank in path_ranks for rank in required)

    def __repr__(self) -> str:
        return f"TaxonNode({self.name!r}, rank={self.rank!r}, children={len(self.children)})"


class TaxonomyTree:
    """In-memory playable taxonomy tree loaded from the runtime SQLite asset."""

    def __init__(self) -> None:
        self.root = TaxonNode(id="0", name="Life", rank="root")
        self._nodes_by_id: dict[str, TaxonNode] = {"0": self.root}
        self._nodes_by_name: dict[str, list[TaxonNode]] = {}
        self.stats: dict[str, int] = {
            "nodes_created": 0,
            "nodes_linked": 0,
            "playable_species": 0,
        }

    def _register_node(self, node: TaxonNode) -> None:
        """Register a node in lookup indexes."""
        self._nodes_by_id[node.id] = node
        self._nodes_by_name.setdefault(node.name, []).append(node)

    def find_by_id(self, taxon_id: str) -> TaxonNode | None:
        """Find a node by runtime taxon key."""
        return self._nodes_by_id.get(taxon_id)

    def find_by_name(self, name: str, *, case_sensitive: bool = True) -> list[TaxonNode]:
        """Find nodes by scientific name."""
        if case_sensitive:
            return self._nodes_by_name.get(name, [])

        name_lower = name.lower()
        return [
            node
            for stored_name, nodes in self._nodes_by_name.items()
            if stored_name.lower() == name_lower
            for node in nodes
        ]

    def iter_nodes(self, *, include_root: bool = False) -> Iterator[TaxonNode]:
        """Iterate over registered nodes."""
        if include_root:
            yield self.root
        for node_id, node in self._nodes_by_id.items():
            if node_id != self.root.id:
                yield node
