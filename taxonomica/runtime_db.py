"""Runtime SQLite dataset loading for the playable Taxonomica game."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

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
    ) -> None:
        self.db_path = db_path
        self.tree = tree
        self._descriptions_by_key = descriptions_by_key
        self._descriptions_by_name = descriptions_by_name
        self.playable_species_nodes = [
            node
            for taxon_key in sorted(descriptions_by_key)
            if (node := tree.find_by_id(taxon_key)) is not None and node.rank == "species"
        ]

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
                    playable_species_count
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

        tree.root.playable_species_count = sum(
            child.playable_species_count for child in tree.root.children.values()
        )
        tree.stats["nodes_created"] = len(tree._nodes_by_id) - 1
        tree.stats["nodes_linked"] = sum(len(node.children) for node in tree._nodes_by_id.values())
        tree.stats["playable_species"] = sum(
            1
            for key in descriptions_by_key
            if (node := tree.find_by_id(key)) is not None and node.rank == "species"
        )
        return cls(
            db_path=path,
            tree=tree,
            descriptions_by_key=descriptions_by_key,
            descriptions_by_name=descriptions_by_name,
        )

    @property
    def playable_species_count(self) -> int:
        """Return the number of selectable species."""
        return len(self.playable_species_nodes)

    def match_taxon_name(self, name: str) -> RuntimeDescription | None:
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
