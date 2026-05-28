"""Runtime SQLite dataset loading for the playable Taxonomica game."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from taxonomica.gbif_tree import GBIFTaxonomyTree, TaxonomyNode

if TYPE_CHECKING:
    from collections.abc import Iterator


RUNTIME_DB_GLOB = "taxonomica-runtime-*.sqlite"
COMPRESSED_RUNTIME_DB_GLOB = "taxonomica-runtime-*.sqlite.gz"


@dataclass(frozen=True)
class RuntimeDescription:
    """A lightweight description record shaped like the old Wikipedia entry."""

    taxon_key: str
    scientific_name: str
    title: str
    description: str

    def get_useful_text(self) -> str:
        """Return the playable description text."""
        return self.description

    def get_abstract(self) -> str:
        """Return the best short description available."""
        return self.description


@dataclass(frozen=True)
class RuntimePopularityMetrics:
    """Difficulty metrics loaded from the runtime database."""

    taxon_id: str
    scientific_name: str
    description_length: int
    section_count: int
    multimedia_count: int
    pageview_count: int
    backlink_count: int
    popularity_score: float

    @property
    def difficulty_tier(self) -> str:
        """Get the exclusive difficulty tier for summary counts."""
        if self.popularity_score >= 55:
            return "easy"
        if self.popularity_score >= 49:
            return "medium"
        if self.popularity_score >= 24:
            return "hard"
        return "expert"


class RuntimePopularityIndex:
    """Popularity lookup compatible with the game selection helper."""

    def __init__(self) -> None:
        self._by_id: dict[str, RuntimePopularityMetrics] = {}
        self._by_name: dict[str, str] = {}

    def add(self, metrics: RuntimePopularityMetrics) -> None:
        """Add one metrics row."""
        self._by_id[metrics.taxon_id] = metrics
        self._by_name.setdefault(metrics.scientific_name.lower(), metrics.taxon_id)

    def get_by_name(self, name: str) -> RuntimePopularityMetrics | None:
        """Get metrics by scientific name."""
        taxon_id = self._by_name.get(name.lower())
        if taxon_id is None:
            return None
        return self._by_id.get(taxon_id)

    def get_stats(self) -> dict[str, int]:
        """Get exclusive counts by difficulty tier."""
        stats = {"easy": 0, "medium": 0, "hard": 0, "expert": 0}
        for metrics in self._by_id.values():
            stats[metrics.difficulty_tier] += 1
        return stats


class RuntimeTaxonomyData:
    """Loaded runtime tree plus description and popularity indexes."""

    def __init__(
        self,
        *,
        db_path: Path,
        tree: GBIFTaxonomyTree,
        descriptions_by_key: dict[str, RuntimeDescription],
        descriptions_by_name: dict[str, RuntimeDescription],
        popularity_index: RuntimePopularityIndex,
    ) -> None:
        self.db_path = db_path
        self.tree = tree
        self._descriptions_by_key = descriptions_by_key
        self._descriptions_by_name = descriptions_by_name
        self.popularity_index = popularity_index

    @classmethod
    def from_default(cls, project_root: Path | None = None) -> RuntimeTaxonomyData:
        """Load the default runtime database under ``assets/game``."""
        root = project_root or Path.cwd()
        return cls.from_sqlite(resolve_runtime_db_path(root))

    @classmethod
    def from_sqlite(cls, db_path: str | Path) -> RuntimeTaxonomyData:
        """Load a runtime SQLite database."""
        path = Path(db_path)
        tree = GBIFTaxonomyTree()
        descriptions_by_key: dict[str, RuntimeDescription] = {}
        descriptions_by_name: dict[str, RuntimeDescription] = {}
        popularity_index = RuntimePopularityIndex()

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row

            for row in conn.execute(
                """
                SELECT taxon_key, rank, scientific_name, common_name
                FROM runtime_taxa
                ORDER BY length(taxon_key), taxon_key
                """
            ):
                if row["taxon_key"] == tree.root.id:
                    continue
                common_name = row["common_name"]
                vernacular_names = [common_name] if common_name else []
                node = TaxonomyNode(
                    id=row["taxon_key"],
                    name=row["scientific_name"],
                    rank=row["rank"],
                    scientific_name=row["scientific_name"],
                    vernacular_names=vernacular_names,
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
                    d.description_length,
                    d.section_count,
                    d.multimedia_count,
                    d.pageview_count,
                    d.backlink_count,
                    d.difficulty_score
                FROM runtime_descriptions d
                JOIN runtime_taxa t ON t.taxon_key = d.taxon_key
                """
            ):
                description = RuntimeDescription(
                    taxon_key=row["taxon_key"],
                    scientific_name=row["scientific_name"],
                    title=row["title"],
                    description=row["description"],
                )
                descriptions_by_key[row["taxon_key"]] = description
                descriptions_by_name.setdefault(row["scientific_name"].lower(), description)
                popularity_index.add(
                    RuntimePopularityMetrics(
                        taxon_id=row["taxon_key"],
                        scientific_name=row["scientific_name"],
                        description_length=row["description_length"],
                        section_count=row["section_count"],
                        multimedia_count=row["multimedia_count"],
                        pageview_count=row["pageview_count"] or 0,
                        backlink_count=row["backlink_count"] or 0,
                        popularity_score=row["difficulty_score"],
                    )
                )

        tree.stats["nodes_created"] = len(tree._nodes_by_id) - 1
        tree.stats["nodes_linked"] = sum(1 for _ in _iter_edges(tree.root))
        return cls(
            db_path=path,
            tree=tree,
            descriptions_by_key=descriptions_by_key,
            descriptions_by_name=descriptions_by_name,
            popularity_index=popularity_index,
        )

    def match_gbif_taxon(self, name: str) -> RuntimeDescription | None:
        """Return the description for a scientific name, if available."""
        return self._descriptions_by_name.get(name.lower())

    def match_taxon_key(self, taxon_key: str) -> RuntimeDescription | None:
        """Return the description for a runtime taxon key, if available."""
        return self._descriptions_by_key.get(taxon_key)


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


def _iter_edges(root: TaxonomyNode) -> Iterator[tuple[TaxonomyNode, TaxonomyNode]]:
    for child in root.children.values():
        yield root, child
        yield from _iter_edges(child)
