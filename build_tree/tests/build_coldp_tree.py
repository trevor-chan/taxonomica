#!/usr/bin/env python3
"""Profile or build a taxonomy tree from a ColDP archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from taxonomica.coldp import ColdPArchive
from taxonomica.coldp_profile import ColdPProfile, profile_archive
from taxonomica.coldp_sqlite import (
    ColdPSQLiteStore,
    ColdPSQLiteTaxon,
    build_sqlite_index,
    default_sqlite_path,
)
from taxonomica.coldp_tree import ColdPTaxonomyNode, ColdPTaxonomyTree


DEFAULT_SAMPLE_NAMES = [
    "Bacteria",
    "Archaea",
    "Animalia",
    "Plantae",
    "Fungi",
    "Homo sapiens",
    "Felis catus",
    "Panthera leo",
    "Escherichia coli",
]


def resolve_archive_path(data_dir: Path, source: str, archive_path: Path | None) -> Path:
    """Resolve a source name or explicit archive path."""
    if archive_path is not None:
        return archive_path

    source_path = Path(source)
    if source_path.exists():
        return source_path

    candidates = [
        data_dir / f"{source}.zip",
        data_dir / source,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not find ColDP source {source!r}. Tried: "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def resolve_sqlite_path(args: argparse.Namespace) -> Path:
    """Resolve the SQLite index path for CLI arguments."""
    if args.db:
        return args.db

    source_name = Path(args.source).stem
    if args.include_non_accepted:
        source_name = f"{source_name}-all"

    return default_sqlite_path(args.data_dir, source_name, limit=args.limit)


def format_path(node: ColdPTaxonomyNode) -> str:
    """Format a node path from root to node."""
    path_nodes = [
        path_node
        for path_node in reversed(node.get_path_to_root())
        if path_node.rank != "root"
    ]
    return " -> ".join(f"{path_node.name} [{path_node.rank}]" for path_node in path_nodes)


def print_rank_counts(tree: ColdPTaxonomyTree, *, limit: int) -> None:
    """Print the largest rank groups."""
    rank_counts = tree.get_rank_counts()
    print("\nRANK COUNTS")
    print("=" * 80)
    for rank, count in sorted(rank_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]:
        print(f"  {rank:<20} {count:>12,}")


def print_profile_counts(
    title: str,
    counts,
    *,
    limit: int,
    total: int | None = None,
) -> None:
    """Print the largest groups from a streaming profile counter."""
    print(f"\n{title}")
    print("=" * 80)
    for name, count in counts.most_common(limit):
        if total:
            print(f"  {name:<24} {count:>12,}  ({count / total:.1%})")
        else:
            print(f"  {name:<24} {count:>12,}")


def print_profile_summary(profile: ColdPProfile, *, limit: int) -> None:
    """Print memory-light ColDP profile output."""
    print("\nPROFILE STATS")
    print("=" * 80)
    print(f"  Rows scanned:                 {profile.rows_seen:>12,}")
    print(f"  Rows included:                {profile.rows_included:>12,}")
    print(f"  Rows skipped:                 {profile.rows_skipped:>12,}")
    print(f"  Accepted rows:                {profile.accepted_rows:>12,}")
    print(f"  Duplicate IDs skipped:        {profile.duplicate_ids:>12,}")
    print(f"  Missing ID rows skipped:      {profile.missing_id_rows:>12,}")
    print(f"  Missing name rows skipped:    {profile.missing_name_rows:>12,}")
    print(
        "  English Wikipedia URLs:      "
        f"{profile.wikipedia_url_count:>12,}  ({profile.wikipedia_url_ratio:.1%})"
    )

    print("\nPARENT LINK HEALTH")
    print("=" * 80)
    print(f"  Rows with parent IDs:         {profile.parent_links:>12,}")
    print(
        "  Parent links resolved:       "
        f"{profile.linked_parent_rows:>12,}  ({profile.parent_link_coverage:.1%})"
    )
    print(f"  Parent links missing:         {profile.missing_parent_links:>12,}")
    print(f"  Self-parent links:            {profile.self_parent_links:>12,}")
    print(f"  Rows without parent IDs:      {profile.parentless_rows:>12,}")
    print(f"  Root candidates:              {profile.root_candidate_rows:>12,}")

    print_profile_counts(
        "RANK COUNTS",
        profile.rank_counts,
        limit=limit,
        total=profile.rows_included,
    )
    print_profile_counts(
        "STATUS COUNTS",
        profile.status_counts,
        limit=limit,
        total=profile.rows_included,
    )
    print_profile_counts(
        "ROOT CANDIDATES BY RANK",
        profile.root_candidate_rank_counts,
        limit=limit,
        total=profile.root_candidate_rows,
    )


def print_profile_samples(profile: ColdPProfile) -> None:
    """Print exact-name sample lookup rows from a streaming profile."""
    print("\nSAMPLE LOOKUPS")
    print("=" * 80)
    for name, matches in profile.sample_matches.items():
        if not matches:
            print(f"  {name}: not found")
            continue

        print(f"\n  {name}:")
        for record in matches:
            print(
                f"    {record.id} [{record.rank or 'unknown'}] "
                f"status={record.status} parent={record.parent_id or '-'}"
            )
            if record.link:
                print(f"      Source link: {record.link}")
            if record.wikipedia_url:
                print(f"      Wikipedia: {record.wikipedia_url}")


def format_sqlite_path(path: list[ColdPSQLiteTaxon]) -> str:
    """Format a lazy SQLite parent path."""
    return " -> ".join(
        f"{taxon.scientific_name} [{taxon.rank or 'unknown'}]"
        for taxon in reversed(path)
    )


def print_sqlite_counts(
    title: str,
    rows: list[tuple[str, int]],
    *,
    total: int | None = None,
) -> None:
    """Print grouped SQLite counts."""
    print(f"\n{title}")
    print("=" * 80)
    for name, count in rows:
        if total:
            print(f"  {name:<24} {count:>12,}  ({count / total:.1%})")
        else:
            print(f"  {name:<24} {count:>12,}")


def print_sqlite_summary(store: ColdPSQLiteStore, *, limit: int) -> None:
    """Print ColDP SQLite index health."""
    stats = store.get_summary_stats()
    rows_included = int(stats["rows_included"])
    root_candidates = int(stats["root_candidate_rows"])

    print("\nSQLITE INDEX STATS")
    print("=" * 80)
    print(f"  Rows indexed:                 {rows_included:>12,}")
    print(
        "  English Wikipedia URLs:      "
        f"{int(stats['wikipedia_url_rows']):>12,}  "
        f"({float(stats['wikipedia_url_ratio']):.1%})"
    )

    print("\nPARENT LINK HEALTH")
    print("=" * 80)
    print(f"  Rows with parent IDs:         {int(stats['parent_links']):>12,}")
    print(
        "  Parent links resolved:       "
        f"{int(stats['linked_parent_rows']):>12,}  "
        f"({float(stats['parent_link_coverage']):.1%})"
    )
    print(f"  Parent links missing:         {int(stats['missing_parent_links']):>12,}")
    print(f"  Self-parent links:            {int(stats['self_parent_links']):>12,}")
    print(f"  Rows without parent IDs:      {int(stats['parentless_rows']):>12,}")
    print(f"  Root candidates:              {root_candidates:>12,}")

    print_sqlite_counts(
        "RANK COUNTS",
        store.get_rank_counts(limit=limit),
        total=rows_included,
    )
    print_sqlite_counts(
        "STATUS COUNTS",
        store.get_status_counts(limit=limit),
        total=rows_included,
    )


def print_sqlite_root_candidates(store: ColdPSQLiteStore, *, limit: int) -> None:
    """Print likely synthetic-root children from SQLite."""
    print("\nROOT CANDIDATES")
    print("=" * 80)
    for taxon in store.get_root_candidates(limit=limit):
        print(
            f"  {taxon.scientific_name:<35} [{taxon.rank or 'unknown':<14}] "
            f"{taxon.child_count:>12,} children"
        )


def print_sqlite_samples(
    store: ColdPSQLiteStore,
    names: list[str],
    *,
    limit: int = 5,
) -> None:
    """Print sample lookup rows from the SQLite index."""
    print("\nSAMPLE LOOKUPS")
    print("=" * 80)
    for name in names:
        matches = store.find_by_name(name, limit=limit)
        if not matches:
            print(f"  {name}: not found")
            continue

        print(f"\n  {name}:")
        for taxon in matches:
            common_names = store.get_vernacular_names(taxon.id, limit=3)
            path = store.get_path_to_root(taxon.id)
            print(
                f"    {taxon.id} [{taxon.rank or 'unknown'}] "
                f"status={taxon.status} parent={taxon.parent_id or '-'} "
                f"children={taxon.child_count:,}"
            )
            if common_names:
                print(f"      Common: {', '.join(common_names)}")
            if taxon.link:
                print(f"      Source link: {taxon.link}")
            if taxon.wikipedia_url:
                print(f"      Wikipedia: {taxon.wikipedia_url}")
            if path:
                print(f"      Path: {format_sqlite_path(path)}")


def print_sqlite_connectedness(
    store: ColdPSQLiteStore,
    *,
    target_rank: str,
    missing_rank: str,
    max_depth: int,
    sample_limit: int,
) -> None:
    """Print major-rank connectedness for a SQLite index."""
    connectedness = store.get_lineage_connectedness(
        target_rank=target_rank,
        max_depth=max_depth,
    )
    target_count = int(connectedness["target_count"])
    required_ranks = connectedness["required_ranks"]

    print("\nLINEAGE CONNECTEDNESS")
    print("=" * 80)
    print(f"  Target rank:                  {connectedness['target_rank']}")
    print(f"  Target rows:                  {target_count:>12,}")
    print(
        "  Lineage depth:               "
        f"avg={float(connectedness['avg_lineage_depth']):.2f} "
        f"max={int(connectedness['max_lineage_depth'])}"
    )
    print(f"  Required major ranks:         {', '.join(required_ranks) or '(none)'}")
    print(
        "  Complete major-rank paths:   "
        f"{int(connectedness['complete_major_path_count']):>12,}  "
        f"({float(connectedness['complete_major_path_ratio']):.1%})"
    )

    print("\nMAJOR RANK REACHABILITY")
    print("=" * 80)
    for rank in ["kingdom", "phylum", "class", "order", "family", "genus", "species"]:
        count = int(connectedness[f"reaches_{rank}_count"])
        ratio = float(connectedness[f"reaches_{rank}_ratio"])
        print(f"  Reaches {rank:<8}            {count:>12,}  ({ratio:.1%})")

    if sample_limit <= 0:
        return

    samples = store.find_missing_lineage_rank_samples(
        target_rank=target_rank,
        missing_rank=missing_rank,
        max_depth=max_depth,
        limit=sample_limit,
    )
    print(f"\nSAMPLES MISSING {missing_rank.upper()}")
    print("=" * 80)
    if not samples:
        print("  (No samples found)")
        return

    for taxon in samples:
        path = store.get_path_to_root(taxon.id, max_depth=max_depth)
        print(f"  {taxon.scientific_name} [{taxon.rank or 'unknown'}] ({taxon.id})")
        if path:
            print(f"    Path: {format_sqlite_path(path)}")


def print_root_children(tree: ColdPTaxonomyTree, *, limit: int) -> None:
    """Print the largest direct children of the synthetic root."""
    root_children = []
    for node in tree.root.children.values():
        root_children.append((node.count_descendants(), node))

    print("\nROOT CHILDREN")
    print("=" * 80)
    for descendants, node in sorted(root_children, key=lambda item: (-item[0], item[1].name))[:limit]:
        orphan_marker = " orphan?" if node.rank not in {"domain", "superkingdom", "kingdom"} else ""
        print(
            f"  {node.name:<35} [{node.rank:<14}] "
            f"{descendants:>12,} descendants{orphan_marker}"
        )


def print_sample_lookups(tree: ColdPTaxonomyTree, names: list[str]) -> None:
    """Print paths for representative taxa."""
    print("\nSAMPLE LOOKUPS")
    print("=" * 80)
    for name in names:
        matches = tree.find_by_name(name, case_sensitive=False)
        if not matches:
            print(f"  {name}: not found")
            continue

        node = sorted(matches, key=lambda match: match.get_rank_priority())[0]
        print(f"\n  {name}:")
        print(f"    ID: {node.id}")
        print(f"    Rank: {node.rank or 'unknown'}")
        print(f"    Children: {len(node.children):,}")
        print(f"    Complete path: {'yes' if node.has_complete_path() else 'no'}")
        if node.vernacular_names:
            print(f"    Common name: {node.vernacular_names[0]}")
        if node.link:
            print(f"    Source link: {node.link}")
        if node.wikipedia_url:
            print(f"    Wikipedia: {node.wikipedia_url}")
        print(f"    Path: {format_path(node)}")


def print_quality_stats(tree: ColdPTaxonomyTree) -> None:
    """Print high-level tree quality metrics."""
    quality = tree.get_quality_stats()

    print("\nTREE QUALITY")
    print("=" * 80)
    print(f"  Leaf nodes: {quality['leaf_count']:,}")
    print(
        "  Leaf depth: "
        f"min={quality['min_depth']} "
        f"max={quality['max_depth']} "
        f"avg={quality['avg_depth']:.2f}"
    )
    print(f"  Species nodes: {quality['species_count']:,}")
    print(
        "  Species with complete major-rank paths: "
        f"{quality['complete_species_count']:,} "
        f"({quality['complete_species_ratio']:.1%})"
    )
    print(f"  Nodes with English Wikipedia URLs: {quality['wikipedia_url_count']:,}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        default="wikispecies",
        help="ColDP source name under assets/raw/coldp, or a direct archive path",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Explicit ColDP ZIP or extracted directory path",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "assets" / "raw" / "coldp",
        help="Directory containing ColDP archives",
    )
    parser.add_argument(
        "--include-non-accepted",
        action="store_true",
        help="Include synonyms and other non-accepted name usages",
    )
    parser.add_argument(
        "--mode",
        choices=["profile", "sqlite", "tree"],
        default="profile",
        help="Profile by default; sqlite builds/queries a lazy index; tree builds an in-memory graph",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="SQLite mode: database path to build or inspect",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="SQLite mode: rebuild an existing database",
    )
    parser.add_argument(
        "--no-vernacular",
        action="store_true",
        help="Tree/SQLite mode: skip importing or loading vernacular names",
    )
    parser.add_argument(
        "--include-media",
        action="store_true",
        help="SQLite mode: import Media.tsv too",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50000,
        help="SQLite mode: insert batch size",
    )
    parser.add_argument(
        "--connectedness",
        action="store_true",
        help="SQLite mode: measure major-rank lineage connectedness",
    )
    parser.add_argument(
        "--connectedness-rank",
        default="species",
        help="SQLite connectedness: target rank to evaluate",
    )
    parser.add_argument(
        "--missing-rank",
        default="kingdom",
        help="SQLite connectedness: rank used for missing-lineage samples",
    )
    parser.add_argument(
        "--connectedness-samples",
        type=int,
        default=5,
        help="SQLite connectedness: number of missing-rank samples to print",
    )
    parser.add_argument(
        "--max-lineage-depth",
        type=int,
        default=100,
        help="SQLite connectedness: maximum parent hops to follow",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Read only the first N NameUsage rows for quick parser checks",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=500000,
        help="Print progress every N NameUsage rows",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of grouped rows to show in reports",
    )
    parser.add_argument(
        "--sample-name",
        action="append",
        dest="sample_names",
        help="Exact scientific name to collect during streaming profile mode",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    archive_path = resolve_archive_path(args.data_dir, args.source, args.archive)

    print(f"Loading ColDP archive: {archive_path}")
    archive = ColdPArchive(archive_path)
    print(f"Available tables: {', '.join(archive.available_tables())}")

    if args.mode == "profile":
        print("\nProfiling ColDP archive with streaming passes...")
        if args.limit:
            print(f"  Limited to first {args.limit:,} NameUsage rows")

        profile = profile_archive(
            archive,
            accepted_only=not args.include_non_accepted,
            progress_interval=args.progress_interval,
            limit=args.limit,
            sample_names=args.sample_names or DEFAULT_SAMPLE_NAMES,
        )
        print_profile_summary(profile, limit=args.top)
        print_profile_samples(profile)
        return

    if args.mode == "sqlite":
        db_path = resolve_sqlite_path(args)
        if db_path.exists() and not args.force:
            print(f"\nUsing existing SQLite index: {db_path}")
            print("  Pass --force to rebuild it.")
        else:
            print(f"\nBuilding SQLite index: {db_path}")
            if args.limit:
                print(f"  Limited to first {args.limit:,} NameUsage rows")

            stats = build_sqlite_index(
                archive,
                db_path,
                accepted_only=not args.include_non_accepted,
                include_vernacular=not args.no_vernacular,
                include_media=args.include_media,
                force=args.force,
                limit=args.limit,
                batch_size=args.batch_size,
                progress_interval=args.progress_interval,
            )
            print("\nIMPORT STATS")
            print("=" * 80)
            for key, value in stats.items():
                print(f"  {key:<26} {value}")

        with ColdPSQLiteStore(db_path) as store:
            print_sqlite_summary(store, limit=args.top)
            print_sqlite_root_candidates(store, limit=args.top)
            if args.connectedness:
                print_sqlite_connectedness(
                    store,
                    target_rank=args.connectedness_rank,
                    missing_rank=args.missing_rank,
                    max_depth=args.max_lineage_depth,
                    sample_limit=args.connectedness_samples,
                )
            print_sqlite_samples(store, args.sample_names or DEFAULT_SAMPLE_NAMES)
        return

    print("\nBuilding ColDP taxonomy tree...")
    print("  Warning: tree mode builds a full in-memory object graph.")
    tree = ColdPTaxonomyTree.from_archive(
        archive,
        accepted_only=not args.include_non_accepted,
        progress_interval=args.progress_interval,
        limit=args.limit,
    )

    if not args.no_vernacular:
        print("\nLoading English vernacular names...")
        vernacular_count = tree.add_vernacular_names(archive)
        print(f"  Added {vernacular_count:,} vernacular names")

    print("\nBUILD STATS")
    print("=" * 80)
    for key, value in tree.stats.items():
        print(f"  {key:<24} {value:>12,}")

    print_rank_counts(tree, limit=args.top)
    print_root_children(tree, limit=args.top)
    print_quality_stats(tree)
    print_sample_lookups(tree, DEFAULT_SAMPLE_NAMES)

    print("\nTREE PREVIEW")
    print("=" * 80)
    tree.print_subtree(max_depth=4, max_children=8)


if __name__ == "__main__":
    main()
