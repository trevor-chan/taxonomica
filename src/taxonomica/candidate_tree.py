"""Build a candidate seven-rank playable tree from ColDP and GBIF data."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from taxonomica.coldp import ColdPArchive
from taxonomica.coldp_tree import normalize_rank

if TYPE_CHECKING:
    from collections.abc import Iterable


csv.field_size_limit(sys.maxsize)

GBIF_ID_RE = re.compile(r"(?:^|,)gbif:([^,]+)")
MAJOR_PARENT_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus"]
MAJOR_RANKS = [*MAJOR_PARENT_RANKS, "species"]
MATCH_TYPE_PRIORITY = {
    "gbif_id": 0,
    "gbif_accepted_id": 1,
    "name_exact": 2,
}
RankPair = tuple[str, str]
NodePath = tuple[RankPair, ...]
EdgePath = tuple[NodePath, NodePath]


@dataclass
class CandidateSpecies:
    """A Wikidata/ColDP species row that may become playable."""

    index: int
    wikidata_id: str
    scientific_name: str
    wikipedia_url: str
    gbif_ids: tuple[str, ...]


@dataclass(frozen=True)
class MajorRankPath:
    """A complete seven-rank path from a backbone source."""

    kingdom: str
    phylum: str
    class_name: str
    order: str
    family: str
    genus: str
    species: str

    def as_rank_pairs(self) -> list[tuple[str, str]]:
        """Return path as ordered ``(rank, name)`` pairs."""
        return [
            ("kingdom", self.kingdom),
            ("phylum", self.phylum),
            ("class", self.class_name),
            ("order", self.order),
            ("family", self.family),
            ("genus", self.genus),
            ("species", self.species),
        ]

    def key(self) -> tuple[str, ...]:
        """Return a hashable path key."""
        return (
            self.kingdom,
            self.phylum,
            self.class_name,
            self.order,
            self.family,
            self.genus,
            self.species,
        )


@dataclass
class CandidateMatch:
    """A candidate species matched to a backbone path."""

    candidate_index: int
    gbif_id: str
    match_type: str
    path: MajorRankPath


@dataclass
class CandidateTreeBuildResult:
    """Summary from a candidate-tree build."""

    output_path: Path
    stats: Counter[str]
    rejection_counts: Counter[str]
    node_counts: Counter[NodePath]
    edge_counts: Counter[EdgePath]
    selected_matches: list[CandidateMatch]


def extract_gbif_ids(alternative_id: str) -> tuple[str, ...]:
    """Extract GBIF IDs from a ColDP ``alternativeID`` field."""
    seen = set()
    ids = []
    for match in GBIF_ID_RE.finditer(alternative_id or ""):
        gbif_id = match.group(1).strip()
        if gbif_id and gbif_id not in seen:
            seen.add(gbif_id)
            ids.append(gbif_id)
    return tuple(ids)


def build_candidate_tree(
    *,
    coldp_archive_path: str | Path,
    gbif_backbone_path: str | Path,
    output_path: str | Path,
    include_name_fallback: bool = True,
    force: bool = False,
    coldp_limit: int | None = None,
    gbif_limit: int | None = None,
    progress_interval: int = 500000,
) -> CandidateTreeBuildResult:
    """Build a candidate seven-rank tree and write it to SQLite."""
    output_path = Path(output_path)
    if output_path.exists() and not force:
        raise FileExistsError(f"{output_path} already exists; pass --force to rebuild it")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    stats: Counter[str] = Counter()
    rejection_counts: Counter[str] = Counter()

    archive = ColdPArchive(coldp_archive_path)

    print("Pass 1: Collecting article-backed Wikidata species candidates...")
    candidates, candidates_by_gbif_id, candidates_by_name = _collect_candidates(
        archive,
        stats=stats,
        rejection_counts=rejection_counts,
        include_name_fallback=include_name_fallback,
        limit=coldp_limit,
        progress_interval=progress_interval,
    )
    print(f"  Candidate species: {len(candidates):,}")
    gbif_id_candidate_count = len(
        {idx for ids in candidates_by_gbif_id.values() for idx in ids}
    )
    print(f"  Candidates with GBIF IDs: {gbif_id_candidate_count:,}")

    print("Pass 2: Matching candidates to GBIF backbone paths...")
    matches_by_candidate: dict[int, list[CandidateMatch]] = defaultdict(list)
    accepted_id_requests = _scan_gbif_for_direct_and_name_matches(
        gbif_backbone_path,
        candidates,
        candidates_by_gbif_id,
        candidates_by_name if include_name_fallback else {},
        matches_by_candidate,
        stats=stats,
        rejection_counts=rejection_counts,
        limit=gbif_limit,
        progress_interval=progress_interval,
    )

    if accepted_id_requests:
        print(f"Pass 3: Resolving {len(accepted_id_requests):,} accepted GBIF IDs...")
        _scan_gbif_for_accepted_id_matches(
            gbif_backbone_path,
            accepted_id_requests,
            matches_by_candidate,
            stats=stats,
            rejection_counts=rejection_counts,
            limit=gbif_limit,
            progress_interval=progress_interval,
        )

    print("Pass 4: Selecting one path per candidate and assembling tree...")
    selected_matches = _select_matches(
        candidates,
        matches_by_candidate,
        rejection_counts=rejection_counts,
    )
    node_counts, edge_counts = _count_tree_nodes_and_edges(selected_matches)

    stats["selected_article_backed_rows"] = len(selected_matches)
    stats["candidate_path_nodes"] = len(node_counts)
    stats["candidate_unique_taxon_labels"] = len(
        {_node_rank_name(node_path) for node_path in node_counts}
    )
    stats["candidate_edges"] = len(edge_counts)
    stats["candidate_species_nodes"] = len(
        [
            node_path
            for node_path in node_counts
            if _node_rank_name(node_path)[0] == "species"
        ]
    )
    stats["candidate_parent_nodes"] = len(
        [
            node_path
            for node_path in node_counts
            if _node_rank_name(node_path)[0] != "species"
        ]
    )
    stats["candidate_total_playable_nodes"] = len(node_counts)
    stats["candidate_duplicate_species_rows"] = (
        stats["selected_article_backed_rows"] - stats["candidate_species_nodes"]
    )

    print(f"  Selected article-backed rows: {stats['selected_article_backed_rows']:,}")
    print(f"  Unique accepted species nodes: {stats['candidate_species_nodes']:,}")
    print(f"  Duplicate accepted-species rows: {stats['candidate_duplicate_species_rows']:,}")
    print(f"  Candidate parent nodes: {stats['candidate_parent_nodes']:,}")
    print(f"  Candidate total playable nodes: {stats['candidate_total_playable_nodes']:,}")
    print(f"  Path-keyed tree nodes: {stats['candidate_path_nodes']:,}")
    print(f"  Unique taxon labels: {stats['candidate_unique_taxon_labels']:,}")
    print(f"  Candidate edges: {stats['candidate_edges']:,}")

    print(f"Pass 5: Writing candidate tree SQLite: {output_path}")
    _write_candidate_database(
        output_path,
        candidates,
        selected_matches,
        node_counts,
        edge_counts,
        stats,
        rejection_counts,
        source_coldp=str(coldp_archive_path),
        source_gbif=str(gbif_backbone_path),
    )

    return CandidateTreeBuildResult(
        output_path=output_path,
        stats=stats,
        rejection_counts=rejection_counts,
        node_counts=node_counts,
        edge_counts=edge_counts,
        selected_matches=selected_matches,
    )


def _collect_candidates(
    archive: ColdPArchive,
    *,
    stats: Counter[str],
    rejection_counts: Counter[str],
    include_name_fallback: bool,
    limit: int | None,
    progress_interval: int,
) -> tuple[
    list[CandidateSpecies],
    dict[str, list[int]],
    dict[str, list[int]],
]:
    candidates: list[CandidateSpecies] = []
    candidates_by_gbif_id: dict[str, list[int]] = defaultdict(list)
    candidates_by_name: dict[str, list[int]] = defaultdict(list)

    for usage in archive.iter_name_usages():
        if limit and stats["coldp_rows_scanned"] >= limit:
            break

        stats["coldp_rows_scanned"] += 1
        if progress_interval and stats["coldp_rows_scanned"] % progress_interval == 0:
            print(f"  Scanned {stats['coldp_rows_scanned']:,} ColDP rows...")

        if normalize_rank(usage.rank) != "species":
            continue

        stats["coldp_species_rows"] += 1

        if not usage.is_accepted:
            rejection_counts["coldp_non_accepted_species"] += 1
            continue

        if not usage.wikipedia_url:
            rejection_counts["missing_english_wikipedia_url"] += 1
            continue

        stats["article_backed_species_rows"] += 1

        gbif_ids = extract_gbif_ids(usage.alternative_id)
        if not gbif_ids:
            rejection_counts["missing_gbif_id"] += 1

        candidate = CandidateSpecies(
            index=len(candidates),
            wikidata_id=usage.id,
            scientific_name=usage.scientific_name,
            wikipedia_url=usage.wikipedia_url,
            gbif_ids=gbif_ids,
        )
        candidates.append(candidate)

        for gbif_id in gbif_ids:
            candidates_by_gbif_id[gbif_id].append(candidate.index)

        if include_name_fallback:
            candidates_by_name[usage.scientific_name.casefold()].append(candidate.index)

    return candidates, candidates_by_gbif_id, candidates_by_name


def _scan_gbif_for_direct_and_name_matches(
    gbif_backbone_path: str | Path,
    candidates: list[CandidateSpecies],
    candidates_by_gbif_id: dict[str, list[int]],
    candidates_by_name: dict[str, list[int]],
    matches_by_candidate: dict[int, list[CandidateMatch]],
    *,
    stats: Counter[str],
    rejection_counts: Counter[str],
    limit: int | None,
    progress_interval: int,
) -> dict[str, list[int]]:
    accepted_id_requests: dict[str, list[int]] = defaultdict(list)
    name_match_paths: dict[int, dict[tuple[str, ...], CandidateMatch]] = defaultdict(dict)

    for row in _iter_gbif_rows(gbif_backbone_path, limit=limit):
        stats["gbif_rows_scanned"] += 1
        if progress_interval and stats["gbif_rows_scanned"] % progress_interval == 0:
            print(f"  Scanned {stats['gbif_rows_scanned']:,} GBIF rows...")

        taxon_id = row.get("taxonID", "")
        if taxon_id in candidates_by_gbif_id:
            _handle_direct_gbif_row(
                row,
                candidates_by_gbif_id[taxon_id],
                matches_by_candidate,
                accepted_id_requests,
                stats=stats,
                rejection_counts=rejection_counts,
            )

        if candidates_by_name and _is_accepted_species_row(row):
            name_keys = {
                row.get("canonicalName", "").casefold(),
                row.get("scientificName", "").casefold(),
            }
            for name_key in name_keys:
                if not name_key or name_key not in candidates_by_name:
                    continue

                path = _path_from_gbif_row(row)
                for candidate_index in candidates_by_name[name_key]:
                    if path is None:
                        rejection_counts["name_match_incomplete_path"] += 1
                        continue

                    match = CandidateMatch(
                        candidate_index=candidate_index,
                        gbif_id=taxon_id,
                        match_type="name_exact",
                        path=path,
                    )
                    name_match_paths[candidate_index][path.key()] = match

    for candidate_index, path_matches in name_match_paths.items():
        if len(path_matches) == 1:
            matches_by_candidate[candidate_index].extend(path_matches.values())
            stats["name_matches_unique"] += 1
        elif len(path_matches) > 1:
            rejection_counts["ambiguous_name_match"] += 1

    return accepted_id_requests


def _scan_gbif_for_accepted_id_matches(
    gbif_backbone_path: str | Path,
    accepted_id_requests: dict[str, list[int]],
    matches_by_candidate: dict[int, list[CandidateMatch]],
    *,
    stats: Counter[str],
    rejection_counts: Counter[str],
    limit: int | None,
    progress_interval: int,
) -> None:
    remaining_ids = set(accepted_id_requests)
    rows_scanned = 0
    for row in _iter_gbif_rows(gbif_backbone_path, limit=limit):
        rows_scanned += 1
        if progress_interval and rows_scanned % progress_interval == 0:
            print(f"  Scanned {rows_scanned:,} GBIF rows for accepted IDs...")

        taxon_id = row.get("taxonID", "")
        if taxon_id not in remaining_ids:
            continue

        remaining_ids.remove(taxon_id)
        path = _path_from_gbif_row(row)
        if path is None:
            rejection_counts["accepted_gbif_id_incomplete_path"] += len(
                accepted_id_requests[taxon_id]
            )
            continue

        if not _is_accepted_species_row(row):
            rejection_counts["accepted_gbif_id_not_accepted_species"] += len(
                accepted_id_requests[taxon_id]
            )
            continue

        for candidate_index in accepted_id_requests[taxon_id]:
            matches_by_candidate[candidate_index].append(
                CandidateMatch(
                    candidate_index=candidate_index,
                    gbif_id=taxon_id,
                    match_type="gbif_accepted_id",
                    path=path,
                )
            )
            stats["gbif_accepted_id_matches_complete"] += 1

        if not remaining_ids:
            break

    for missing_id in remaining_ids:
        rejection_counts["accepted_gbif_id_not_found"] += len(
            accepted_id_requests[missing_id]
        )


def _handle_direct_gbif_row(
    row: dict[str, str],
    candidate_indexes: Iterable[int],
    matches_by_candidate: dict[int, list[CandidateMatch]],
    accepted_id_requests: dict[str, list[int]],
    *,
    stats: Counter[str],
    rejection_counts: Counter[str],
) -> None:
    candidate_indexes = list(candidate_indexes)

    if _is_accepted_species_row(row):
        path = _path_from_gbif_row(row)
        if path is None:
            rejection_counts["gbif_id_incomplete_path"] += len(candidate_indexes)
            return

        for candidate_index in candidate_indexes:
            matches_by_candidate[candidate_index].append(
                CandidateMatch(
                    candidate_index=candidate_index,
                    gbif_id=row.get("taxonID", ""),
                    match_type="gbif_id",
                    path=path,
                )
            )
            stats["gbif_id_matches_complete"] += 1
        return

    accepted_id = row.get("acceptedNameUsageID", "")
    if accepted_id:
        for candidate_index in candidate_indexes:
            accepted_id_requests[accepted_id].append(candidate_index)
        stats["gbif_id_redirects_to_accepted"] += len(candidate_indexes)
    else:
        rejection_counts["gbif_id_not_accepted_species"] += len(candidate_indexes)


def _select_matches(
    candidates: list[CandidateSpecies],
    matches_by_candidate: dict[int, list[CandidateMatch]],
    *,
    rejection_counts: Counter[str],
) -> list[CandidateMatch]:
    selected = []

    for candidate in candidates:
        matches = matches_by_candidate.get(candidate.index, [])
        if not matches:
            if candidate.gbif_ids:
                rejection_counts["no_complete_gbif_path"] += 1
            else:
                rejection_counts["no_gbif_match"] += 1
            continue

        matches = sorted(
            matches,
            key=lambda match: (
                MATCH_TYPE_PRIORITY.get(match.match_type, 99),
                match.gbif_id,
            ),
        )
        best_priority = MATCH_TYPE_PRIORITY.get(matches[0].match_type, 99)
        best_path_keys = {
            match.path.key()
            for match in matches
            if MATCH_TYPE_PRIORITY.get(match.match_type, 99) == best_priority
        }
        if len(best_path_keys) > 1:
            rejection_counts["multiple_candidate_paths"] += 1
            continue

        selected.append(matches[0])

    return selected


def _count_tree_nodes_and_edges(
    selected_matches: list[CandidateMatch],
) -> tuple[
    Counter[NodePath],
    Counter[EdgePath],
]:
    node_counts: Counter[NodePath] = Counter()
    edge_counts: Counter[EdgePath] = Counter()

    for match in selected_matches:
        pairs = match.path.as_rank_pairs()
        path_nodes = [tuple(pairs[:index]) for index in range(1, len(pairs) + 1)]
        for node_path in path_nodes:
            node_counts[node_path] += 1
        for parent, child in zip(path_nodes, path_nodes[1:]):
            edge_counts[(parent, child)] += 1

    return node_counts, edge_counts


def _path_from_gbif_row(row: dict[str, str]) -> MajorRankPath | None:
    if not _is_accepted_species_row(row):
        return None

    values = {
        "kingdom": row.get("kingdom", "").strip(),
        "phylum": row.get("phylum", "").strip(),
        "class_name": row.get("class", "").strip(),
        "order": row.get("order", "").strip(),
        "family": row.get("family", "").strip(),
        "genus": row.get("genus", "").strip(),
        "species": (row.get("canonicalName", "") or row.get("scientificName", "")).strip(),
    }
    if not all(values.values()):
        return None

    return MajorRankPath(**values)


def _is_accepted_species_row(row: dict[str, str]) -> bool:
    return (
        row.get("taxonomicStatus", "").lower() == "accepted"
        and row.get("taxonRank", "").lower() == "species"
    )


def _iter_gbif_rows(
    gbif_backbone_path: str | Path,
    *,
    limit: int | None = None,
) -> Iterable[dict[str, str]]:
    taxon_path = Path(gbif_backbone_path) / "Taxon.tsv"
    with open(taxon_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for index, row in enumerate(reader, 1):
            if limit and index > limit:
                break
            yield row


def _write_candidate_database(
    output_path: Path,
    candidates: list[CandidateSpecies],
    selected_matches: list[CandidateMatch],
    node_counts: Counter[NodePath],
    edge_counts: Counter[EdgePath],
    stats: Counter[str],
    rejection_counts: Counter[str],
    *,
    source_coldp: str,
    source_gbif: str,
) -> None:
    candidates_by_index = {candidate.index: candidate for candidate in candidates}

    with sqlite3.connect(output_path) as conn:
        conn.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE candidate_species (
                wikidata_id TEXT PRIMARY KEY,
                scientific_name TEXT NOT NULL,
                wikipedia_url TEXT NOT NULL,
                gbif_id TEXT NOT NULL,
                match_type TEXT NOT NULL,
                kingdom TEXT NOT NULL,
                phylum TEXT NOT NULL,
                class_name TEXT NOT NULL,
                order_name TEXT NOT NULL,
                family TEXT NOT NULL,
                genus TEXT NOT NULL,
                species TEXT NOT NULL
            );

            CREATE TABLE candidate_taxa (
                taxon_key TEXT PRIMARY KEY,
                rank TEXT NOT NULL,
                scientific_name TEXT NOT NULL,
                descendant_species_count INTEGER NOT NULL
            );

            CREATE TABLE candidate_edges (
                parent_key TEXT NOT NULL,
                child_key TEXT NOT NULL,
                descendant_species_count INTEGER NOT NULL,
                PRIMARY KEY (parent_key, child_key)
            );

            CREATE TABLE rejection_summary (
                reason TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO candidate_species (
                wikidata_id,
                scientific_name,
                wikipedia_url,
                gbif_id,
                match_type,
                kingdom,
                phylum,
                class_name,
                order_name,
                family,
                genus,
                species
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    candidates_by_index[match.candidate_index].wikidata_id,
                    candidates_by_index[match.candidate_index].scientific_name,
                    candidates_by_index[match.candidate_index].wikipedia_url,
                    match.gbif_id,
                    match.match_type,
                    match.path.kingdom,
                    match.path.phylum,
                    match.path.class_name,
                    match.path.order,
                    match.path.family,
                    match.path.genus,
                    match.path.species,
                )
                for match in selected_matches
            ],
        )

        conn.executemany(
            """
            INSERT INTO candidate_taxa (
                taxon_key,
                rank,
                scientific_name,
                descendant_species_count
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (_taxon_key(node_path), rank, name, count)
                for node_path, count in sorted(node_counts.items())
                for rank, name in [_node_rank_name(node_path)]
            ],
        )

        conn.executemany(
            """
            INSERT INTO candidate_edges (
                parent_key,
                child_key,
                descendant_species_count
            )
            VALUES (?, ?, ?)
            """,
            [
                (_taxon_key(parent), _taxon_key(child), count)
                for (parent, child), count in sorted(edge_counts.items())
            ],
        )

        conn.executemany(
            """
            INSERT INTO rejection_summary (reason, count)
            VALUES (?, ?)
            """,
            sorted(rejection_counts.items()),
        )

        metadata = {
            "source_coldp": source_coldp,
            "source_gbif": source_gbif,
            **{f"stat_{key}": str(value) for key, value in sorted(stats.items())},
        }
        conn.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            metadata.items(),
        )

        conn.executescript(
            """
            CREATE INDEX idx_candidate_species_name
                ON candidate_species(scientific_name COLLATE NOCASE);
            CREATE INDEX idx_candidate_species_gbif_id
                ON candidate_species(gbif_id);
            CREATE INDEX idx_candidate_taxa_rank
                ON candidate_taxa(rank);
            CREATE INDEX idx_candidate_edges_parent
                ON candidate_edges(parent_key);
            CREATE INDEX idx_candidate_edges_child
                ON candidate_edges(child_key);
            """
        )
        conn.commit()


def _node_rank_name(node_path: NodePath) -> RankPair:
    return node_path[-1]


def _taxon_key(node_path: NodePath) -> str:
    return json.dumps(node_path, separators=(",", ":"))
