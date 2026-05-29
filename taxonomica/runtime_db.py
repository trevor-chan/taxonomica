"""Runtime SQLite dataset loading for the playable Taxonomica game."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from taxonomica.difficulty import (
    normalize_difficulty,
    target_allowed_for_difficulty,
    tree_count_field_for_difficulty,
)
from taxonomica.taxonomy import TaxonNode, TaxonomyTree


RUNTIME_DB_GLOB = "taxonomica-runtime-*.sqlite"
COMPRESSED_RUNTIME_DB_GLOB = "taxonomica-runtime-*.sqlite.gz"


@dataclass(frozen=True)
class RuntimeDescription:
    """A lightweight description record shaped like the old Wikipedia entry."""

    taxon_key: str
    scientific_name: str
    title: str
    description: str
    word_count: int
    description_length: int
    multimedia_count: int
    pageview_count: int
    backlink_count: int


class RuntimeTaxonomyData:
    """Loaded runtime tree plus description and popularity indexes."""

    def __init__(
        self,
        *,
        db_path: Path,
        tree: TaxonomyTree,
        descriptions_by_key: dict[str, RuntimeDescription],
        descriptions_by_name: dict[str, RuntimeDescription],
        target_species_keys: set[str] | None = None,
        difficulty: str | None = None,
        tree_species_count: int | None = None,
        source_data: RuntimeTaxonomyData | None = None,
    ) -> None:
        self.db_path = db_path
        self.tree = tree
        self._descriptions_by_key = descriptions_by_key
        self._descriptions_by_name = descriptions_by_name
        self._source_data = source_data
        self.difficulty = normalize_difficulty(difficulty)
        if target_species_keys is None:
            target_species_keys = {
                key
                for key in descriptions_by_key
                if (node := tree.find_by_id(key)) is not None
                and node.rank == "species"
                and node.target_difficulty
            }
        self.target_species_keys = target_species_keys
        self.playable_species_nodes = [
            node
            for taxon_key in sorted(target_species_keys)
            if (node := tree.find_by_id(taxon_key)) is not None and node.rank == "species"
        ]
        self.tree_species_count = (
            tree_species_count
            if tree_species_count is not None
            else tree.root.playable_species_count
        )

    @classmethod
    def from_default(cls, project_root: Path | None = None) -> RuntimeTaxonomyData:
        """Load the default runtime database under ``assets/game``."""
        root = project_root or Path.cwd()
        return cls.from_sqlite(resolve_runtime_db_path(root))

    @classmethod
    def from_sqlite(cls, db_path: str | Path) -> RuntimeTaxonomyData:
        """Load a runtime SQLite database."""
        path = Path(db_path)
        tree = TaxonomyTree()
        descriptions_by_key: dict[str, RuntimeDescription] = {}
        descriptions_by_name: dict[str, RuntimeDescription] = {}

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row

            for row in conn.execute(
                """
                SELECT
                    taxon_key,
                    rank,
                    scientific_name,
                    common_name,
                    difficulty_level,
                    description_length,
                    article_length,
                    pageview_count,
                    difficulty_score,
                    pageview_score,
                    article_score,
                    vernacular_score,
                    category_score,
                    category_modifier,
                    target_rank,
                    tree_rank,
                    playable_species_count,
                    tree_species_count,
                    easy_species_count,
                    medium_species_count,
                    hard_species_count,
                    expert_target_species_count
                FROM runtime_taxa
                ORDER BY length(taxon_key), taxon_key
                """
            ):
                if row["taxon_key"] == tree.root.id:
                    continue
                common_name = row["common_name"]
                vernacular_names = [common_name] if common_name else []
                node = TaxonNode(
                    id=row["taxon_key"],
                    name=row["scientific_name"],
                    rank=row["rank"],
                    scientific_name=row["scientific_name"],
                    vernacular_names=vernacular_names,
                    playable_species_count=row["playable_species_count"],
                    tree_species_count=row["tree_species_count"],
                    easy_species_count=row["easy_species_count"],
                    medium_species_count=row["medium_species_count"],
                    hard_species_count=row["hard_species_count"],
                    expert_target_species_count=row["expert_target_species_count"],
                    target_difficulty=row["difficulty_level"],
                    description_length=row["description_length"],
                    article_length=row["article_length"],
                    pageview_count=row["pageview_count"],
                    difficulty_score=row["difficulty_score"],
                    pageview_score=row["pageview_score"],
                    article_score=row["article_score"],
                    vernacular_score=row["vernacular_score"],
                    category_score=row["category_score"],
                    category_modifier=row["category_modifier"],
                    target_rank=row["target_rank"],
                    tree_rank=row["tree_rank"],
                )
                tree._register_node(node)

            for row in conn.execute(
                """
                SELECT parent_key, child_key
                FROM runtime_edges
                ORDER BY parent_key, child_key
                """
            ):
                parent = tree.find_by_id(row["parent_key"])
                child = tree.find_by_id(row["child_key"])
                if parent is not None and child is not None:
                    parent.add_child(child)

            for row in conn.execute(
                """
                SELECT
                    d.taxon_key,
                    t.scientific_name,
                    d.title,
                    d.description,
                    d.word_count,
                    d.description_length,
                    d.multimedia_count,
                    d.pageview_count,
                    d.backlink_count
                FROM runtime_descriptions d
                JOIN runtime_taxa t ON t.taxon_key = d.taxon_key
                """
            ):
                description = RuntimeDescription(
                    taxon_key=row["taxon_key"],
                    scientific_name=row["scientific_name"],
                    title=row["title"],
                    description=row["description"],
                    word_count=row["word_count"],
                    description_length=row["description_length"],
                    multimedia_count=row["multimedia_count"],
                    pageview_count=row["pageview_count"] or 0,
                    backlink_count=row["backlink_count"] or 0,
                )
                descriptions_by_key[row["taxon_key"]] = description
                descriptions_by_name.setdefault(row["scientific_name"].lower(), description)

        tree.root.tree_species_count = sum(
            child.tree_species_count for child in tree.root.children.values()
        )
        tree.root.easy_species_count = sum(
            child.easy_species_count for child in tree.root.children.values()
        )
        tree.root.medium_species_count = sum(
            child.medium_species_count for child in tree.root.children.values()
        )
        tree.root.hard_species_count = sum(
            child.hard_species_count for child in tree.root.children.values()
        )
        tree.root.expert_target_species_count = sum(
            child.expert_target_species_count for child in tree.root.children.values()
        )
        tree.root.playable_species_count = tree.root.tree_species_count
        tree.stats["nodes_created"] = len(tree._nodes_by_id) - 1
        tree.stats["nodes_linked"] = sum(len(node.children) for node in tree._nodes_by_id.values())
        target_species_keys = {
            node.id
            for node in tree.iter_nodes()
            if node.rank == "species" and node.target_difficulty
        }
        tree.stats["playable_species"] = tree.root.tree_species_count
        tree.stats["target_species"] = len(target_species_keys)
        return cls(
            db_path=path,
            tree=tree,
            descriptions_by_key=descriptions_by_key,
            descriptions_by_name=descriptions_by_name,
            target_species_keys=target_species_keys,
            difficulty="expert",
            tree_species_count=tree.root.tree_species_count,
        )

    @property
    def playable_species_count(self) -> int:
        """Return the number of species in the active visible tree."""
        return self.tree_species_count

    @property
    def target_species_count(self) -> int:
        """Return the number of selectable target species."""
        return len(self.playable_species_nodes)

    def for_difficulty(self, difficulty: str | None) -> RuntimeTaxonomyData:
        """Return a runtime view whose tree is pruned for a difficulty mode."""
        normalized = normalize_difficulty(difficulty)
        if self._source_data is not None and normalized != self.difficulty:
            return self._source_data.for_difficulty(normalized)
        if normalized == self.difficulty:
            return self

        count_field = tree_count_field_for_difficulty(normalized)
        included_keys = {
            node.id
            for node in self.tree.iter_nodes()
            if _node_species_count(node, count_field) > 0
        }
        target_species_keys = {
            node.id
            for node in self.tree.iter_nodes()
            if node.rank == "species"
            and node.id in included_keys
            and target_allowed_for_difficulty(node.target_difficulty, normalized)
        }

        filtered_tree = TaxonomyTree()
        clones: dict[str, TaxonNode] = {}
        for source_node in self.tree.iter_nodes():
            if source_node.id not in included_keys:
                continue
            clone = _clone_node_for_difficulty(source_node, count_field)
            filtered_tree._register_node(clone)
            clones[source_node.id] = clone

        for source_id, clone in clones.items():
            source_node = self.tree.find_by_id(source_id)
            if source_node is None or source_node.parent is None:
                continue
            parent = (
                filtered_tree.root
                if source_node.parent.id == self.tree.root.id
                else clones.get(source_node.parent.id)
            )
            if parent is not None:
                parent.add_child(clone)

        filtered_tree.root.playable_species_count = _node_species_count(
            self.tree.root,
            count_field,
        )
        filtered_tree.root.tree_species_count = self.tree.root.tree_species_count
        filtered_tree.root.easy_species_count = self.tree.root.easy_species_count
        filtered_tree.root.medium_species_count = self.tree.root.medium_species_count
        filtered_tree.root.hard_species_count = self.tree.root.hard_species_count
        filtered_tree.root.expert_target_species_count = (
            self.tree.root.expert_target_species_count
        )
        filtered_tree.stats["nodes_created"] = len(filtered_tree._nodes_by_id) - 1
        filtered_tree.stats["nodes_linked"] = sum(
            len(node.children) for node in filtered_tree._nodes_by_id.values()
        )
        filtered_tree.stats["playable_species"] = filtered_tree.root.playable_species_count
        filtered_tree.stats["target_species"] = len(target_species_keys)

        filtered_descriptions = {
            key: description
            for key, description in self._descriptions_by_key.items()
            if key in filtered_tree._nodes_by_id
        }
        filtered_names: dict[str, RuntimeDescription] = {}
        for description in filtered_descriptions.values():
            filtered_names.setdefault(description.scientific_name.lower(), description)

        return RuntimeTaxonomyData(
            db_path=self.db_path,
            tree=filtered_tree,
            descriptions_by_key=filtered_descriptions,
            descriptions_by_name=filtered_names,
            target_species_keys=target_species_keys,
            difficulty=normalized,
            tree_species_count=filtered_tree.root.playable_species_count,
            source_data=self._source_data or self,
        )

    def match_taxon_name(self, name: str) -> RuntimeDescription | None:
        """Return the description for a scientific name, if available."""
        return self._descriptions_by_name.get(name.lower())

    def match_taxon_key(self, taxon_key: str) -> RuntimeDescription | None:
        """Return the description for a runtime taxon key, if available."""
        return self._descriptions_by_key.get(taxon_key)


def _node_species_count(node: TaxonNode, count_field: str) -> int:
    return int(getattr(node, count_field))


def _clone_node_for_difficulty(
    node: TaxonNode,
    count_field: str,
) -> TaxonNode:
    return TaxonNode(
        id=node.id,
        name=node.name,
        rank=node.rank,
        scientific_name=node.scientific_name,
        vernacular_names=list(node.vernacular_names),
        playable_species_count=_node_species_count(node, count_field),
        tree_species_count=node.tree_species_count,
        easy_species_count=node.easy_species_count,
        medium_species_count=node.medium_species_count,
        hard_species_count=node.hard_species_count,
        expert_target_species_count=node.expert_target_species_count,
        target_difficulty=node.target_difficulty,
        description_length=node.description_length,
        article_length=node.article_length,
        pageview_count=node.pageview_count,
        difficulty_score=node.difficulty_score,
        pageview_score=node.pageview_score,
        article_score=node.article_score,
        vernacular_score=node.vernacular_score,
        category_score=node.category_score,
        category_modifier=node.category_modifier,
        target_rank=node.target_rank,
        tree_rank=node.tree_rank,
    )


def resolve_runtime_db_path(project_root: Path) -> Path:
    """Resolve the default runtime DB, decompressing a packaged asset if needed."""
    assets_dir = project_root / "assets"
    game_dir = assets_dir / "game"
    runtime_dir = assets_dir / "generated" / "runtime"

    sqlite_candidates = sorted(game_dir.glob(RUNTIME_DB_GLOB), reverse=True)
    if sqlite_candidates:
        return sqlite_candidates[0]

    compressed_candidates = sorted(game_dir.glob(COMPRESSED_RUNTIME_DB_GLOB), reverse=True)
    if not compressed_candidates:
        raise FileNotFoundError(
            "No runtime database found. Build one with "
            "`python build_tree/build_runtime_db.py --force`."
        )

    compressed_path = compressed_candidates[0]
    runtime_dir.mkdir(parents=True, exist_ok=True)
    output_path = runtime_dir / compressed_path.name.removesuffix(".gz")
    if not output_path.exists() or compressed_path.stat().st_mtime > output_path.stat().st_mtime:
        with gzip.open(compressed_path, "rb") as source:
            with open(output_path, "wb") as target:
                shutil.copyfileobj(source, target)
    return output_path
