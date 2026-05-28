"""SQLite-backed ColDP index and lazy query helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from taxonomica.coldp import ColdPArchive
from taxonomica.coldp_tree import MAJOR_RANKS, RANK_PRIORITY, normalize_rank


SCHEMA_VERSION = "1"
DEFAULT_BATCH_SIZE = 50000


@dataclass
class ColdPSQLiteTaxon:
    """A taxon row loaded lazily from the ColDP SQLite index."""

    id: str
    parent_id: str
    status: str
    rank: str
    rank_sort: int
    scientific_name: str
    authorship: str = ""
    link: str = ""
    wikipedia_url: str = ""
    has_english_wikipedia: bool = False
    child_count: int = 0


def default_sqlite_path(data_dir: Path, source: str, *, limit: int | None = None) -> Path:
    """Return a safe default SQLite path for a ColDP source."""
    source_name = Path(source).stem
    if limit:
        return data_dir / f"{source_name}-limit-{limit}.sqlite"
    return data_dir / f"{source_name}.sqlite"


def build_sqlite_index(
    archive: ColdPArchive,
    db_path: str | Path,
    *,
    accepted_only: bool = True,
    include_vernacular: bool = True,
    include_media: bool = False,
    force: bool = False,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_interval: int = 500000,
) -> dict[str, int | str | bool]:
    """Build a SQLite index from a ColDP archive.

    The importer streams rows from the archive and stores only columns needed
    for lazy tree exploration and later Wikipedia article-text joining.
    """
    db_path = Path(db_path)
    if db_path.exists() and not force:
        raise FileExistsError(f"{db_path} already exists; pass --force to rebuild it")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    stats: dict[str, int | str | bool] = {
        "schema_version": SCHEMA_VERSION,
        "accepted_only": accepted_only,
        "include_vernacular": include_vernacular,
        "include_media": include_media,
        "limit": limit or 0,
        "name_usage_rows_seen": 0,
        "taxa_attempted": 0,
        "taxa_inserted": 0,
        "taxa_skipped": 0,
        "duplicate_ids": 0,
        "accepted_rows": 0,
        "wikipedia_url_rows": 0,
        "vernacular_rows_inserted": 0,
        "vernacular_rows_pruned": 0,
        "media_rows_inserted": 0,
        "media_rows_pruned": 0,
    }

    with sqlite3.connect(db_path) as conn:
        _configure_connection_for_import(conn)
        _create_schema(conn)

        print("  Importing NameUsage.tsv into SQLite...")
        pending_taxa: list[tuple[str, str, str, str, int, str, str, str, str, int]] = []

        for usage in archive.iter_name_usages():
            if limit and int(stats["name_usage_rows_seen"]) >= limit:
                break

            stats["name_usage_rows_seen"] = int(stats["name_usage_rows_seen"]) + 1

            if accepted_only and not usage.is_accepted:
                stats["taxa_skipped"] = int(stats["taxa_skipped"]) + 1
                continue

            if not usage.id or not usage.scientific_name:
                stats["taxa_skipped"] = int(stats["taxa_skipped"]) + 1
                continue

            rank = normalize_rank(usage.rank)
            wikipedia_url = usage.wikipedia_url
            status = usage.status.strip().lower() or "blank"

            if usage.is_accepted:
                stats["accepted_rows"] = int(stats["accepted_rows"]) + 1
            if wikipedia_url:
                stats["wikipedia_url_rows"] = int(stats["wikipedia_url_rows"]) + 1

            pending_taxa.append(
                (
                    usage.id,
                    usage.parent_id,
                    status,
                    rank,
                    RANK_PRIORITY.get(rank, 999),
                    usage.scientific_name,
                    usage.authorship,
                    usage.link,
                    wikipedia_url,
                    1 if wikipedia_url else 0,
                )
            )
            stats["taxa_attempted"] = int(stats["taxa_attempted"]) + 1

            if len(pending_taxa) >= batch_size:
                _insert_taxa_batch(conn, pending_taxa, stats)
                pending_taxa.clear()

            rows_seen = int(stats["name_usage_rows_seen"])
            if progress_interval and rows_seen % progress_interval == 0:
                print(f"    Imported {rows_seen:,} name usages...")

        if pending_taxa:
            _insert_taxa_batch(conn, pending_taxa, stats)

        print(f"    Inserted {int(stats['taxa_inserted']):,} taxa")

        if include_vernacular and archive.has_table("VernacularName.tsv"):
            print("  Importing VernacularName.tsv...")
            stats["vernacular_rows_inserted"] = _import_vernacular_names(
                conn,
                archive,
                batch_size=batch_size,
                progress_interval=progress_interval,
            )

        if include_media and archive.has_table("Media.tsv"):
            print("  Importing Media.tsv...")
            stats["media_rows_inserted"] = _import_media(
                conn,
                archive,
                batch_size=batch_size,
                progress_interval=progress_interval,
            )

        if include_vernacular or include_media:
            print("  Pruning related rows without indexed taxa...")
            stats["vernacular_rows_pruned"] = _prune_unmatched_rows(
                conn,
                table_name="vernacular_names",
            )
            stats["media_rows_pruned"] = _prune_unmatched_rows(
                conn,
                table_name="media",
            )
            stats["vernacular_rows_inserted"] = (
                int(stats["vernacular_rows_inserted"])
                - int(stats["vernacular_rows_pruned"])
            )
            stats["media_rows_inserted"] = (
                int(stats["media_rows_inserted"])
                - int(stats["media_rows_pruned"])
            )

        print("  Creating indexes...")
        _create_indexes(conn)
        _write_metadata(conn, archive, stats)
        conn.commit()

    return stats


class ColdPSQLiteStore:
    """Read-only helper for lazy ColDP tree queries."""

    def __init__(self, db_path: str | Path, *, read_only: bool = True) -> None:
        self.path = Path(db_path)
        if not self.path.exists():
            raise FileNotFoundError(f"ColDP SQLite index not found: {self.path}")

        if read_only:
            uri = f"file:{self.path}?mode=ro"
            self.connection = sqlite3.connect(uri, uri=True)
        else:
            self.connection = sqlite3.connect(self.path)

        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the SQLite connection."""
        self.connection.close()

    def __enter__(self) -> ColdPSQLiteStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def get_taxon(self, taxon_id: str) -> ColdPSQLiteTaxon | None:
        """Fetch one taxon by ID."""
        row = self.connection.execute(
            f"""
            SELECT taxa.*, ({_CHILD_COUNT_SQL}) AS child_count
            FROM taxa
            WHERE id = ?
            """,
            (taxon_id,),
        ).fetchone()
        return _taxon_from_row(row) if row else None

    def find_by_name(
        self,
        name: str,
        *,
        exact: bool = True,
        limit: int = 20,
    ) -> list[ColdPSQLiteTaxon]:
        """Find taxa by scientific name."""
        if exact:
            sql = f"""
                SELECT taxa.*, ({_CHILD_COUNT_SQL}) AS child_count
                FROM taxa
                WHERE scientific_name = ? COLLATE NOCASE
                ORDER BY rank_sort, scientific_name COLLATE NOCASE
                LIMIT ?
            """
            params = (name, limit)
        else:
            sql = f"""
                SELECT taxa.*, ({_CHILD_COUNT_SQL}) AS child_count
                FROM taxa
                WHERE scientific_name LIKE ? COLLATE NOCASE
                ORDER BY rank_sort, scientific_name COLLATE NOCASE
                LIMIT ?
            """
            params = (f"%{name}%", limit)

        return [_taxon_from_row(row) for row in self.connection.execute(sql, params)]

    def get_children(
        self,
        parent_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ColdPSQLiteTaxon]:
        """Fetch immediate children for a taxon ID."""
        rows = self.connection.execute(
            f"""
            SELECT taxa.*, ({_CHILD_COUNT_SQL}) AS child_count
            FROM taxa
            WHERE parent_id = ?
            ORDER BY rank_sort, scientific_name COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            (parent_id, limit, offset),
        ).fetchall()
        return [_taxon_from_row(row) for row in rows]

    def count_children(self, parent_id: str) -> int:
        """Count immediate children for a taxon ID."""
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM taxa WHERE parent_id = ?",
            (parent_id,),
        ).fetchone()
        return int(row["count"])

    def get_root_candidates(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "children",
    ) -> list[ColdPSQLiteTaxon]:
        """Fetch taxa that would attach to a synthetic root."""
        if sort_by == "rank":
            order_by = "child.rank_sort, child.scientific_name COLLATE NOCASE"
        else:
            order_by = (
                "child_count DESC, child.rank_sort, child.scientific_name COLLATE NOCASE"
            )

        rows = self.connection.execute(
            f"""
            SELECT child.*, (
                SELECT COUNT(*) FROM taxa grandchild WHERE grandchild.parent_id = child.id
            ) AS child_count
            FROM taxa child
            LEFT JOIN taxa parent ON child.parent_id = parent.id
            WHERE child.parent_id = ''
               OR child.parent_id = child.id
               OR parent.id IS NULL
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [_taxon_from_row(row) for row in rows]

    def get_path_to_root(
        self,
        taxon_id: str,
        *,
        max_depth: int = 100,
    ) -> list[ColdPSQLiteTaxon]:
        """Follow parent IDs from a taxon toward the nearest root candidate."""
        path: list[ColdPSQLiteTaxon] = []
        seen_ids: set[str] = set()
        current_id = taxon_id

        while current_id and current_id not in seen_ids and len(path) < max_depth:
            seen_ids.add(current_id)
            current = self.get_taxon(current_id)
            if current is None:
                break

            path.append(current)
            if not current.parent_id or current.parent_id == current.id:
                break

            current_id = current.parent_id

        return path

    def get_vernacular_names(
        self,
        taxon_id: str,
        *,
        language: str | None = "en",
        limit: int = 10,
    ) -> list[str]:
        """Fetch vernacular names for a taxon."""
        if language is None:
            rows = self.connection.execute(
                """
                SELECT name FROM vernacular_names
                WHERE taxon_id = ?
                ORDER BY name COLLATE NOCASE
                LIMIT ?
                """,
                (taxon_id, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT name FROM vernacular_names
                WHERE taxon_id = ? AND language = ?
                ORDER BY name COLLATE NOCASE
                LIMIT ?
                """,
                (taxon_id, language, limit),
            ).fetchall()

        return [row["name"] for row in rows]

    def get_summary_stats(self) -> dict[str, int | float]:
        """Compute parent-link and Wikipedia coverage stats from SQLite."""
        row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS rows_included,
                SUM(CASE WHEN child.has_english_wikipedia THEN 1 ELSE 0 END)
                    AS wikipedia_url_rows,
                SUM(CASE WHEN child.parent_id <> '' THEN 1 ELSE 0 END) AS parent_links,
                SUM(CASE WHEN child.parent_id = '' THEN 1 ELSE 0 END) AS parentless_rows,
                SUM(
                    CASE
                        WHEN child.parent_id <> '' AND child.parent_id = child.id
                        THEN 1 ELSE 0
                    END
                ) AS self_parent_links,
                SUM(
                    CASE
                        WHEN child.parent_id <> ''
                         AND child.parent_id <> child.id
                         AND parent.id IS NOT NULL
                        THEN 1 ELSE 0
                    END
                ) AS linked_parent_rows,
                SUM(
                    CASE
                        WHEN child.parent_id <> ''
                         AND child.parent_id <> child.id
                         AND parent.id IS NULL
                        THEN 1 ELSE 0
                    END
                ) AS missing_parent_links
            FROM taxa child
            LEFT JOIN taxa parent ON child.parent_id = parent.id
            """
        ).fetchone()

        stats = {key: int(row[key] or 0) for key in row.keys()}
        parent_links = stats["parent_links"]
        stats["parent_link_coverage"] = (
            stats["linked_parent_rows"] / parent_links if parent_links else 0.0
        )
        rows_included = stats["rows_included"]
        stats["wikipedia_url_ratio"] = (
            stats["wikipedia_url_rows"] / rows_included if rows_included else 0.0
        )
        stats["root_candidate_rows"] = (
            stats["parentless_rows"]
            + stats["self_parent_links"]
            + stats["missing_parent_links"]
        )
        return stats

    def get_rank_counts(self, *, limit: int = 20) -> list[tuple[str, int]]:
        """Return rank counts sorted by frequency."""
        rows = self.connection.execute(
            """
            SELECT COALESCE(NULLIF(rank, ''), 'unknown') AS rank, COUNT(*) AS count
            FROM taxa
            GROUP BY rank
            ORDER BY count DESC, rank
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [(row["rank"], int(row["count"])) for row in rows]

    def get_status_counts(self, *, limit: int = 20) -> list[tuple[str, int]]:
        """Return status counts sorted by frequency."""
        rows = self.connection.execute(
            """
            SELECT COALESCE(NULLIF(status, ''), 'blank') AS status, COUNT(*) AS count
            FROM taxa
            GROUP BY status
            ORDER BY count DESC, status
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [(row["status"], int(row["count"])) for row in rows]

    def get_lineage_connectedness(
        self,
        *,
        target_rank: str = "species",
        max_depth: int = 100,
    ) -> dict[str, int | float | str | list[str]]:
        """Measure how well taxa at a rank connect to major ranks.

        This follows parent IDs lazily in SQLite and summarizes whether each
        target taxon reaches standard major ranks such as kingdom, phylum, and
        genus. It is intentionally separate from parent-link health: a dataset
        can resolve most parent IDs while still missing major-rank ancestors.
        """
        target_rank = normalize_rank(target_rank)
        rank_flag_sql = ",\n".join(
            f"""
            MAX(CASE WHEN ancestor_rank = '{rank}' THEN 1 ELSE 0 END)
                AS has_{rank}
            """
            for rank in MAJOR_RANKS
        )
        rank_sum_sql = ",\n".join(
            f"SUM(has_{rank}) AS reaches_{rank}" for rank in MAJOR_RANKS
        )
        required_ranks = _required_major_ranks(target_rank)
        if required_ranks:
            complete_expr = " AND ".join(f"has_{rank} = 1" for rank in required_ranks)
            complete_sql = f"SUM(CASE WHEN {complete_expr} THEN 1 ELSE 0 END)"
        else:
            complete_sql = "COUNT(*)"

        row = self.connection.execute(
            f"""
            WITH RECURSIVE lineage(taxon_id, ancestor_id, ancestor_rank, depth, path) AS (
                SELECT id, id, rank, 0, ',' || id || ','
                FROM taxa
                WHERE rank = ?

                UNION ALL

                SELECT
                    lineage.taxon_id,
                    parent.id,
                    parent.rank,
                    lineage.depth + 1,
                    lineage.path || parent.id || ','
                FROM lineage
                JOIN taxa current ON current.id = lineage.ancestor_id
                JOIN taxa parent ON parent.id = current.parent_id
                WHERE lineage.depth < ?
                  AND current.parent_id <> ''
                  AND current.parent_id <> current.id
                  AND instr(lineage.path, ',' || parent.id || ',') = 0
            ),
            flags AS (
                SELECT
                    taxon_id,
                    MAX(depth) AS max_depth,
                    {rank_flag_sql}
                FROM lineage
                GROUP BY taxon_id
            )
            SELECT
                COUNT(*) AS target_count,
                AVG(max_depth) AS avg_lineage_depth,
                MAX(max_depth) AS max_lineage_depth,
                {rank_sum_sql},
                {complete_sql} AS complete_major_path_count
            FROM flags
            """,
            (target_rank, max_depth),
        ).fetchone()

        target_count = int(row["target_count"] or 0)
        result: dict[str, int | float | str | list[str]] = {
            "target_rank": target_rank,
            "target_count": target_count,
            "avg_lineage_depth": float(row["avg_lineage_depth"] or 0.0),
            "max_lineage_depth": int(row["max_lineage_depth"] or 0),
            "required_ranks": required_ranks,
            "complete_major_path_count": int(row["complete_major_path_count"] or 0),
        }
        result["complete_major_path_ratio"] = (
            int(result["complete_major_path_count"]) / target_count
            if target_count
            else 0.0
        )

        for rank in MAJOR_RANKS:
            count = int(row[f"reaches_{rank}"] or 0)
            result[f"reaches_{rank}_count"] = count
            result[f"reaches_{rank}_ratio"] = count / target_count if target_count else 0.0

        return result

    def find_missing_lineage_rank_samples(
        self,
        *,
        target_rank: str = "species",
        missing_rank: str = "kingdom",
        max_depth: int = 100,
        limit: int = 10,
    ) -> list[ColdPSQLiteTaxon]:
        """Return taxa at ``target_rank`` whose lineage lacks ``missing_rank``."""
        target_rank = normalize_rank(target_rank)
        missing_rank = normalize_rank(missing_rank)
        if missing_rank not in MAJOR_RANKS:
            raise ValueError(f"{missing_rank!r} is not a supported major rank")

        rows = self.connection.execute(
            f"""
            WITH RECURSIVE lineage(taxon_id, ancestor_id, ancestor_rank, depth, path) AS (
                SELECT id, id, rank, 0, ',' || id || ','
                FROM taxa
                WHERE rank = ?

                UNION ALL

                SELECT
                    lineage.taxon_id,
                    parent.id,
                    parent.rank,
                    lineage.depth + 1,
                    lineage.path || parent.id || ','
                FROM lineage
                JOIN taxa current ON current.id = lineage.ancestor_id
                JOIN taxa parent ON parent.id = current.parent_id
                WHERE lineage.depth < ?
                  AND current.parent_id <> ''
                  AND current.parent_id <> current.id
                  AND instr(lineage.path, ',' || parent.id || ',') = 0
            ),
            flags AS (
                SELECT
                    taxon_id,
                    MAX(CASE WHEN ancestor_rank = ? THEN 1 ELSE 0 END) AS has_rank
                FROM lineage
                GROUP BY taxon_id
            )
            SELECT taxa.*, ({_CHILD_COUNT_SQL}) AS child_count
            FROM taxa
            JOIN flags ON flags.taxon_id = taxa.id
            WHERE flags.has_rank = 0
            ORDER BY taxa.scientific_name COLLATE NOCASE
            LIMIT ?
            """,
            (target_rank, max_depth, missing_rank, limit),
        ).fetchall()
        return [_taxon_from_row(row) for row in rows]


_CHILD_COUNT_SQL = "SELECT COUNT(*) FROM taxa child_count WHERE child_count.parent_id = taxa.id"


def _required_major_ranks(target_rank: str) -> list[str]:
    target_priority = RANK_PRIORITY.get(target_rank, 999)
    return [
        rank
        for rank in MAJOR_RANKS
        if RANK_PRIORITY.get(rank, 999) < target_priority
    ]


def _configure_connection_for_import(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE taxa (
            id TEXT PRIMARY KEY,
            parent_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            rank TEXT NOT NULL DEFAULT '',
            rank_sort INTEGER NOT NULL DEFAULT 999,
            scientific_name TEXT NOT NULL,
            authorship TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            wikipedia_url TEXT NOT NULL DEFAULT '',
            has_english_wikipedia INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE vernacular_names (
            taxon_id TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            reference_id TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE media (
            taxon_id TEXT NOT NULL,
            url TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT '',
            format TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT ''
        );
        """
    )


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX idx_taxa_parent_id ON taxa(parent_id);
        CREATE INDEX idx_taxa_rank ON taxa(rank);
        CREATE INDEX idx_taxa_status ON taxa(status);
        CREATE INDEX idx_taxa_scientific_name ON taxa(scientific_name COLLATE NOCASE);
        CREATE INDEX idx_taxa_wikipedia_url ON taxa(wikipedia_url);
        CREATE INDEX idx_vernacular_taxon_language
            ON vernacular_names(taxon_id, language);
        CREATE INDEX idx_media_taxon_id ON media(taxon_id);
        """
    )


def _insert_taxa_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str, int, str, str, str, str, int]],
    stats: dict[str, int | str | bool],
) -> None:
    cursor = conn.executemany(
        """
        INSERT OR IGNORE INTO taxa (
            id,
            parent_id,
            status,
            rank,
            rank_sort,
            scientific_name,
            authorship,
            link,
            wikipedia_url,
            has_english_wikipedia
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    inserted = cursor.rowcount if cursor.rowcount != -1 else len(rows)
    stats["taxa_inserted"] = int(stats["taxa_inserted"]) + inserted
    stats["duplicate_ids"] = int(stats["duplicate_ids"]) + len(rows) - inserted


def _import_vernacular_names(
    conn: sqlite3.Connection,
    archive: ColdPArchive,
    *,
    batch_size: int,
    progress_interval: int,
) -> int:
    rows: list[tuple[str, str, str, str]] = []
    inserted = 0
    for vernacular in archive.iter_vernacular_names():
        if not vernacular.taxon_id or not vernacular.name:
            continue

        rows.append(
            (
                vernacular.taxon_id,
                vernacular.language,
                vernacular.name,
                vernacular.reference_id,
            )
        )

        if len(rows) >= batch_size:
            inserted += _insert_vernacular_batch(conn, rows)
            rows.clear()
            if progress_interval and inserted % progress_interval == 0:
                print(f"    Imported {inserted:,} vernacular names...")

    if rows:
        inserted += _insert_vernacular_batch(conn, rows)

    print(f"    Inserted {inserted:,} vernacular names")
    return inserted


def _insert_vernacular_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str]],
) -> int:
    cursor = conn.executemany(
        """
        INSERT INTO vernacular_names (taxon_id, language, name, reference_id)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    return cursor.rowcount if cursor.rowcount != -1 else len(rows)


def _import_media(
    conn: sqlite3.Connection,
    archive: ColdPArchive,
    *,
    batch_size: int,
    progress_interval: int,
) -> int:
    rows: list[tuple[str, str, str, str, str, str]] = []
    inserted = 0
    for media in archive.iter_media():
        if not media.taxon_id or not media.url:
            continue

        rows.append(
            (
                media.taxon_id,
                media.url,
                media.type,
                media.format,
                media.title,
                media.link,
            )
        )

        if len(rows) >= batch_size:
            inserted += _insert_media_batch(conn, rows)
            rows.clear()
            if progress_interval and inserted % progress_interval == 0:
                print(f"    Imported {inserted:,} media rows...")

    if rows:
        inserted += _insert_media_batch(conn, rows)

    print(f"    Inserted {inserted:,} media rows")
    return inserted


def _insert_media_batch(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str, str, str]],
) -> int:
    cursor = conn.executemany(
        """
        INSERT INTO media (taxon_id, url, type, format, title, link)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return cursor.rowcount if cursor.rowcount != -1 else len(rows)


def _prune_unmatched_rows(conn: sqlite3.Connection, *, table_name: str) -> int:
    cursor = conn.execute(
        f"""
        DELETE FROM {table_name}
        WHERE NOT EXISTS (
            SELECT 1 FROM taxa WHERE taxa.id = {table_name}.taxon_id
        )
        """
    )
    return cursor.rowcount if cursor.rowcount != -1 else 0


def _write_metadata(
    conn: sqlite3.Connection,
    archive: ColdPArchive,
    stats: dict[str, int | str | bool],
) -> None:
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "archive_path": str(archive.path),
        **{key: str(value) for key, value in stats.items()},
    }
    conn.executemany(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        metadata.items(),
    )


def _taxon_from_row(row: sqlite3.Row) -> ColdPSQLiteTaxon:
    return ColdPSQLiteTaxon(
        id=row["id"],
        parent_id=row["parent_id"],
        status=row["status"],
        rank=row["rank"],
        rank_sort=int(row["rank_sort"]),
        scientific_name=row["scientific_name"],
        authorship=row["authorship"],
        link=row["link"],
        wikipedia_url=row["wikipedia_url"],
        has_english_wikipedia=bool(row["has_english_wikipedia"]),
        child_count=int(row["child_count"] or 0),
    )
