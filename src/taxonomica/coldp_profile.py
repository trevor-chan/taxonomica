"""Streaming profile helpers for ColDP archives.

The profile path intentionally avoids building a full Python object graph.
It scans ``NameUsage.tsv`` in one or two passes and keeps only compact summary
state, so it is safe to use with the large Wikidata ColDP archive.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from taxonomica.coldp import ColdPArchive
from taxonomica.coldp_tree import normalize_rank

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class ColdPProfileRecord:
    """Compact row information kept for sample lookups."""

    id: str
    parent_id: str
    status: str
    rank: str
    scientific_name: str
    link: str = ""
    wikipedia_url: str = ""


@dataclass
class ColdPProfile:
    """Summary of a ColDP ``NameUsage.tsv`` scan."""

    rows_seen: int = 0
    rows_included: int = 0
    rows_skipped: int = 0
    accepted_rows: int = 0
    missing_id_rows: int = 0
    missing_name_rows: int = 0
    duplicate_ids: int = 0
    wikipedia_url_count: int = 0
    parent_links: int = 0
    parentless_rows: int = 0
    linked_parent_rows: int = 0
    missing_parent_links: int = 0
    self_parent_links: int = 0
    status_counts: Counter[str] = field(default_factory=Counter)
    rank_counts: Counter[str] = field(default_factory=Counter)
    root_candidate_rank_counts: Counter[str] = field(default_factory=Counter)
    sample_matches: dict[str, list[ColdPProfileRecord]] = field(default_factory=dict)

    @property
    def root_candidate_rows(self) -> int:
        """Rows that would attach to the synthetic root in a simple tree."""
        return self.parentless_rows + self.missing_parent_links + self.self_parent_links

    @property
    def parent_link_coverage(self) -> float:
        """Fraction of parent links whose parent row is present."""
        if not self.parent_links:
            return 0.0
        return self.linked_parent_rows / self.parent_links

    @property
    def wikipedia_url_ratio(self) -> float:
        """Fraction of included rows with English Wikipedia URLs."""
        if not self.rows_included:
            return 0.0
        return self.wikipedia_url_count / self.rows_included


def profile_archive(
    archive: ColdPArchive,
    *,
    accepted_only: bool = True,
    progress_interval: int = 500000,
    limit: int | None = None,
    sample_names: Iterable[str] = (),
    max_sample_matches: int = 5,
) -> ColdPProfile:
    """Build a memory-light profile of a ColDP archive.

    The function stores only the included taxon IDs plus small counters. It does
    not build nodes, child lists, or descendant counts.
    """
    profile = ColdPProfile()
    included_ids: set[str] = set()
    sample_lookup = {name.casefold(): name for name in sample_names}
    profile.sample_matches = {name: [] for name in sample_lookup.values()}

    print("  Pass 1: Counting rows and collecting taxon IDs...")
    for usage in archive.iter_name_usages():
        if limit and profile.rows_seen >= limit:
            break

        profile.rows_seen += 1

        if progress_interval and profile.rows_seen % progress_interval == 0:
            print(f"    Scanned {profile.rows_seen:,} name usages...")

        if accepted_only and not usage.is_accepted:
            profile.rows_skipped += 1
            continue

        if not usage.id:
            profile.rows_skipped += 1
            profile.missing_id_rows += 1
            continue

        if not usage.scientific_name:
            profile.rows_skipped += 1
            profile.missing_name_rows += 1
            continue

        if usage.id in included_ids:
            profile.rows_skipped += 1
            profile.duplicate_ids += 1
            continue

        included_ids.add(usage.id)
        profile.rows_included += 1

        if usage.is_accepted:
            profile.accepted_rows += 1

        status = usage.status.strip().lower() or "blank"
        rank = normalize_rank(usage.rank) or "unknown"
        profile.status_counts[status] += 1
        profile.rank_counts[rank] += 1

        if usage.wikipedia_url:
            profile.wikipedia_url_count += 1

        sample_name = sample_lookup.get(usage.scientific_name.casefold())
        if sample_name and len(profile.sample_matches[sample_name]) < max_sample_matches:
            profile.sample_matches[sample_name].append(
                ColdPProfileRecord(
                    id=usage.id,
                    parent_id=usage.parent_id,
                    status=status,
                    rank=rank,
                    scientific_name=usage.scientific_name,
                    link=usage.link,
                    wikipedia_url=usage.wikipedia_url,
                )
            )

    print(f"    Included {profile.rows_included:,} rows")

    print("  Pass 2: Checking parent IDs against included rows...")
    seen_ids: set[str] | None = set() if profile.duplicate_ids else None
    rows_checked = 0

    for usage in archive.iter_name_usages():
        if limit and rows_checked >= limit:
            break

        rows_checked += 1

        if accepted_only and not usage.is_accepted:
            continue

        if usage.id not in included_ids:
            continue

        if seen_ids is not None:
            if usage.id in seen_ids:
                continue
            seen_ids.add(usage.id)

        rank = normalize_rank(usage.rank) or "unknown"

        if not usage.parent_id:
            profile.parentless_rows += 1
            profile.root_candidate_rank_counts[rank] += 1
            continue

        profile.parent_links += 1

        if usage.parent_id == usage.id:
            profile.self_parent_links += 1
            profile.root_candidate_rank_counts[rank] += 1
        elif usage.parent_id in included_ids:
            profile.linked_parent_rows += 1
        else:
            profile.missing_parent_links += 1
            profile.root_candidate_rank_counts[rank] += 1

        if progress_interval and rows_checked % progress_interval == 0:
            print(f"    Checked {rows_checked:,} parent links...")

    return profile
