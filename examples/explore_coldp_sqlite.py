#!/usr/bin/env python3
"""Interactive explorer for a ColDP SQLite index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.coldp_sqlite import (
    ColdPSQLiteStore,
    ColdPSQLiteTaxon,
    default_sqlite_path,
)


def index_to_label(index: int) -> str:
    """Convert a numeric index to a letter label."""
    if 0 <= index < 26:
        return chr(ord("a") + index)
    return ""


def label_to_index(label: str) -> int:
    """Convert a letter label back to a numeric index."""
    label = label.lower().strip()
    if len(label) == 1 and "a" <= label <= "z":
        return ord(label) - ord("a")
    return -1


def clear_screen() -> None:
    """Clear the terminal screen."""
    print("\033[2J\033[H", end="")


def format_rank(rank: str) -> str:
    """Format a rank name for display."""
    return rank.capitalize() if rank else "Unknown"


def format_path(path: list[ColdPSQLiteTaxon]) -> str:
    """Format a SQLite parent path from root-ish ancestor to current node."""
    if not path:
        return "Life"
    return " -> ".join(taxon.scientific_name for taxon in reversed(path))


class SQLiteTreeExplorer:
    """Lazy ColDP tree explorer backed by SQLite queries."""

    def __init__(self, store: ColdPSQLiteStore, *, page_size: int = 26) -> None:
        self.store = store
        self.current: ColdPSQLiteTaxon | None = None
        self.history: list[ColdPSQLiteTaxon | None] = []
        self.page = 0
        self.page_size = page_size

    def get_page_children(self) -> tuple[list[ColdPSQLiteTaxon], bool]:
        """Fetch one page of children plus whether another page exists."""
        offset = self.page * self.page_size
        limit = self.page_size + 1

        if self.current is None:
            children = self.store.get_root_candidates(
                limit=limit,
                offset=offset,
                sort_by="rank",
            )
        else:
            children = self.store.get_children(self.current.id, limit=limit, offset=offset)

        has_next = len(children) > self.page_size
        return children[: self.page_size], has_next

    def get_breadcrumb(self) -> str:
        """Get a breadcrumb for the current node."""
        if self.current is None:
            return "Life"
        return format_path(self.store.get_path_to_root(self.current.id))

    def display(self) -> None:
        """Display the current page."""
        clear_screen()
        children, has_next = self.get_page_children()

        print("=" * 100)
        print("  COLDP SQLITE TREE EXPLORER")
        print("=" * 100)
        print()
        print(f"  Path: {self.get_breadcrumb()}")
        print()

        if self.current is None:
            print("  Current: Life (synthetic root candidates)")
        else:
            common_names = self.store.get_vernacular_names(self.current.id, limit=3)
            print(
                f"  Current: [{format_rank(self.current.rank)}] "
                f"{self.current.scientific_name}"
            )
            print(f"  ID: {self.current.id}")
            print(f"  Children: {self.current.child_count:,}")
            if common_names:
                print(f"  Common: {', '.join(common_names)}")
            if self.current.wikipedia_url:
                print(f"  Wikipedia: {self.current.wikipedia_url}")
            if self.current.link:
                print(f"  Source: {self.current.link}")

        print()
        print("-" * 100)

        if not children:
            print("\n  (No children on this page)\n")
        else:
            print("\n  Children:\n")
            for index, child in enumerate(children):
                label = index_to_label(index)
                common_names = self.store.get_vernacular_names(child.id, limit=1)
                common = f'"{common_names[0][:22]}"' if common_names else ""
                child_info = (
                    f"({child.child_count:,})" if child.child_count else "(leaf)"
                )
                name = child.scientific_name[:34]
                rank = f"[{child.rank}]" if child.rank else ""
                print(
                    f"  ({label}) {name:<34} {common:<24} "
                    f"{rank:<14} {child_info:>12}"
                )

        print()
        nav = []
        if self.page > 0:
            nav.append("[P]rev")
        if has_next:
            nav.append("[N]ext")
        if nav:
            print(f"  Page {self.page + 1}   {'  '.join(nav)}")

        print("-" * 100)
        print("  [a-z] select | [<] back | [/] search | [N/P] page | [Q] quit")
        print("=" * 100)

    def search(self) -> None:
        """Prompt for a search query and navigate to a selected result."""
        print("\n  Search scientific name: ", end="")
        query = input().strip()
        if not query:
            return

        results = self.store.find_by_name(query, exact=True, limit=20)
        if not results:
            results = self.store.find_by_name(query, exact=False, limit=20)

        if not results:
            print(f"\n  No results found for {query!r}")
            input("  Press Enter to continue...")
            return

        clear_screen()
        print(f"\n  Search results for {query!r}:\n")
        for index, taxon in enumerate(results[:20]):
            label = index_to_label(index)
            path = format_path(self.store.get_path_to_root(taxon.id))
            print(f"    ({label}) [{format_rank(taxon.rank)}] {taxon.scientific_name}")
            print(f"         ID: {taxon.id}")
            print(f"       Path: {path}")
            print()

        print("  Enter letter to navigate, or press Enter to cancel: ", end="")
        choice = input().strip().lower()
        idx = label_to_index(choice)
        if 0 <= idx < len(results):
            self.history.append(self.current)
            self.current = results[idx]
            self.page = 0

    def run(self) -> None:
        """Run the interactive explorer."""
        while True:
            self.display()

            try:
                choice = input("\n  > ").strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not choice:
                continue
            if choice == "Q":
                break
            if choice == "/":
                self.search()
                continue
            if choice in {"<", "\x7f"}:
                if self.history:
                    self.current = self.history.pop()
                    self.page = 0
                elif self.current is not None:
                    self.current = None
                    self.page = 0
                continue
            if choice == "N":
                _, has_next = self.get_page_children()
                if has_next:
                    self.page += 1
                continue
            if choice == "P":
                if self.page > 0:
                    self.page -= 1
                continue

            idx = label_to_index(choice)
            if 0 <= idx < self.page_size:
                children, _ = self.get_page_children()
                if idx < len(children):
                    self.history.append(self.current)
                    self.current = children[idx]
                    self.page = 0

        print("\n  Goodbye!\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        default="wikispecies",
        help="ColDP source name under data/coldp, or a direct SQLite path",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Explicit SQLite database path",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "coldp",
        help="Directory containing ColDP SQLite indexes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Use the default limited-index filename for this row limit",
    )
    return parser


def resolve_db_path(args: argparse.Namespace) -> Path:
    """Resolve a source name or explicit SQLite path."""
    if args.db:
        return args.db

    source_path = Path(args.source)
    if source_path.exists():
        return source_path

    return default_sqlite_path(args.data_dir, args.source, limit=args.limit)


def main() -> None:
    args = build_parser().parse_args()
    db_path = resolve_db_path(args)

    if not db_path.exists():
        raise FileNotFoundError(
            f"{db_path} not found. Build it with: "
            f"python examples/build_coldp_tree.py {args.source} --mode sqlite"
        )

    with ColdPSQLiteStore(db_path) as store:
        explorer = SQLiteTreeExplorer(store)
        explorer.run()


if __name__ == "__main__":
    main()
