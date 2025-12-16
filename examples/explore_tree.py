#!/usr/bin/env python3
"""Interactive text-based taxonomy tree explorer.

Navigate through the tree of life using keyboard commands.

Controls:
  a-z         Select a child node on current page (lowercase)
  <           Go up one level (parent)
  /           Search for a taxon by name
  S           Cycle sort: alphabetical → by descendants → by rank (uppercase)
  F           Toggle filter: show all vs complete paths only (uppercase)
  N / P       Next / Previous page (uppercase)
  Q           Quit (uppercase)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.dwca import DarwinCoreArchive
from taxonomica.tree import RANK_PRIORITY, TaxonomyNode, TaxonomyTree


def index_to_label(index: int) -> str:
    """Convert a numeric index to a letter label (a, b, ... z, aa, ab, ...)."""
    if index < 26:
        return chr(ord('a') + index)
    else:
        # aa, ab, ..., az, ba, bb, ...
        first = (index // 26) - 1
        second = index % 26
        if first < 0:
            return chr(ord('a') + second)
        return chr(ord('a') + first) + chr(ord('a') + second)


def label_to_index(label: str) -> int:
    """Convert a letter label back to a numeric index."""
    label = label.lower().strip()
    if len(label) == 1:
        return ord(label) - ord('a')
    elif len(label) == 2:
        first = ord(label[0]) - ord('a')
        second = ord(label[1]) - ord('a')
        return (first + 1) * 26 + second
    return -1


def clear_screen() -> None:
    """Clear the terminal screen."""
    print("\033[2J\033[H", end="")


def format_rank(rank: str) -> str:
    """Format a rank name for display."""
    return rank.capitalize() if rank else "Unknown"


class TreeExplorer:
    """Interactive tree exploration interface."""

    # Sort modes
    SORT_ALPHA = 0       # Alphabetical (leaves last)
    SORT_DESCENDANTS = 1  # By descendant count (descending)
    SORT_RANK = 2        # By taxonomic rank (higher ranks first)

    SORT_NAMES = ["alphabetical (leaves last)", "by descendants", "by rank (higher first)"]

    def __init__(self, tree: TaxonomyTree, start_node: TaxonomyNode | None = None) -> None:
        self.tree = tree
        self.current_node = start_node or tree.root
        self.page = 0
        self.page_size = 26  # Full alphabet per page
        self.history: list[TaxonomyNode] = []
        self.sort_mode = self.SORT_RANK  # Default: sort by rank (higher first)
        self.filter_complete_paths = True  # Default: only show complete taxonomy paths

    def get_breadcrumb(self) -> str:
        """Get the breadcrumb trail showing path from root."""
        path = self.current_node.get_path_to_root()
        if len(path) <= 1:
            return "Life"

        parts = []
        for node in reversed(path[:-1]):  # Exclude root
            parts.append(f"{node.name}")

        return " → ".join(parts)

    def get_sorted_children(self) -> list[TaxonomyNode]:
        """Get children sorted according to current sort mode, optionally filtered."""
        children = list(self.current_node.children.values())

        # Apply filter if enabled
        if self.filter_complete_paths:
            children = [c for c in children if c.has_complete_path()]

        # Cache descendant counts to avoid repeated computation
        desc_cache: dict[str, int] = {}
        for child in children:
            desc_cache[child.name] = child.count_descendants()

        def sort_key(node: TaxonomyNode) -> tuple:
            desc_count = desc_cache.get(node.name, 0)

            if self.sort_mode == self.SORT_DESCENDANTS:
                # Sort by: descendants (descending), then name alphabetically for ties
                return (-desc_count, node.name.lower())
            elif self.sort_mode == self.SORT_RANK:
                # Sort by: rank priority (lower = higher rank), then descendants, then name
                rank_priority = node.get_rank_priority()
                return (rank_priority, -desc_count, node.name.lower())
            else:  # SORT_ALPHA
                # Sort by: leaves last (0 = has descendants, 1 = leaf), then name alphabetically
                is_leaf = 0 if desc_count > 0 else 1
                return (is_leaf, node.name.lower())

        return sorted(children, key=sort_key)

    def display(self) -> None:
        """Display the current state."""
        clear_screen()

        children = self.get_sorted_children()
        total_children = len(children)
        total_pages = (total_children + self.page_size - 1) // self.page_size if total_children > 0 else 1
        total_unfiltered = len(self.current_node.children)

        # Header
        print("=" * 70)
        print("  TAXONOMY TREE EXPLORER")
        print("=" * 70)
        print()

        # Breadcrumb / path
        depth = len(self.current_node.get_ancestors())
        print(f"  Level {depth}: {self.get_breadcrumb()}")
        print()

        # Show ancestors context
        ancestors = self.current_node.get_ancestors()
        if ancestors:
            print("  Ancestors:")
            for i, anc in enumerate(reversed(ancestors[-5:])):  # Show last 5
                indent = "    " * (i + 1)
                print(f"  {indent}[{format_rank(anc.rank)}] {anc.name}")
            print()

        # Current node info
        if self.current_node != self.tree.root:
            print(f"  ┌─ Current: [{format_rank(self.current_node.rank)}] {self.current_node.name}")
            if self.current_node.wikipedia_url:
                print(f"  │  Wikipedia: {self.current_node.wikipedia_url}")
            desc_count = self.current_node.count_descendants()
            print(f"  │  Descendants: {desc_count:,}")
            if self.filter_complete_paths and total_children != total_unfiltered:
                print(f"  └─ Children: {total_children:,} shown (of {total_unfiltered:,} total)")
            else:
                print(f"  └─ Children: {total_children:,}")
        else:
            print(f"  Current: Life (root)")
            if self.filter_complete_paths and total_children != total_unfiltered:
                print(f"  Children: {total_children:,} shown (of {total_unfiltered:,} total)")
            else:
                print(f"  Children: {total_children:,}")

        # Show sort mode and filter
        sort_name = self.SORT_NAMES[self.sort_mode]
        filter_status = "complete paths only" if self.filter_complete_paths else "all"
        print(f"  Sorting: {sort_name}  |  Filter: {filter_status}")

        print()
        print("-" * 70)

        # Children list
        if total_children == 0:
            print()
            print("  (No children - this is a leaf node)")
            print()
        else:
            # Pagination
            start_idx = self.page * self.page_size
            end_idx = min(start_idx + self.page_size, total_children)
            page_children = children[start_idx:end_idx]

            print(f"\n  Children:                                      (✓ = complete taxonomic path)")
            print()

            for i, child in enumerate(page_children):
                label = index_to_label(i)  # Use page-relative index (a-z)
                child_desc = child.count_descendants()

                # Format child info with rank
                rank_str = f"[{child.rank}]" if child.rank else ""
                child_info = f"({child_desc:,})" if child_desc > 0 else "(leaf)"

                # Path completeness indicator
                complete_marker = "✓" if child.has_complete_path() else " "

                # Truncate long names
                name_display = child.name[:36] if len(child.name) > 36 else child.name

                print(f"  {complete_marker} ({label}) {name_display:<36} {rank_str:<12} {child_info:>10}")

            print()

            # Pagination info
            if total_pages > 1:
                nav_hints = []
                if self.page > 0:
                    nav_hints.append("[P]rev")
                if self.page < total_pages - 1:
                    nav_hints.append("[N]ext")
                nav_str = "  ".join(nav_hints)
                print(f"  Page {self.page + 1}/{total_pages}   {nav_str}")

        # Footer with controls
        print("-" * 70)
        print("  [a-z] select | [<] back | [/] search | [S] sort | [F] filter | [Q] quit")
        print("=" * 70)

    def search(self, query: str) -> None:
        """Search for a taxon by name."""
        results = self.tree.find_by_name(query)

        if not results:
            # Try partial match
            query_lower = query.lower()
            results = []
            for name, nodes in self.tree._nodes_by_name.items():
                if query_lower in name.lower():
                    results.extend(nodes)
                if len(results) >= 20:
                    break

        if not results:
            print(f"\n  No results found for '{query}'")
            input("  Press Enter to continue...")
            return

        clear_screen()
        print(f"\n  Search results for '{query}':\n")

        for i, node in enumerate(results[:20]):
            label = index_to_label(i)
            path = " → ".join(n.name for n in reversed(node.get_path_to_root()[:-1]))
            print(f"    ({label}) [{format_rank(node.rank)}] {node.name}")
            print(f"         Path: {path}")
            print()

        print(f"\n  Enter letter to navigate, or press Enter to cancel: ", end="")
        choice = input().strip().lower()

        if choice:
            idx = label_to_index(choice)
            if 0 <= idx < len(results):
                self.history.append(self.current_node)
                self.current_node = results[idx]
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

            # Uppercase commands for UI navigation
            if choice == 'Q':
                break

            if choice == '<' or choice == 'backspace' or choice == '\x7f':
                # Go up to parent
                if self.current_node.parent:
                    self.history.append(self.current_node)
                    self.current_node = self.current_node.parent
                    self.page = 0
                continue

            if choice == '/':
                print("\n  Search for taxon: ", end="")
                query = input().strip()
                if query:
                    self.search(query)
                continue

            if choice == 'N':
                # Next page
                children = self.get_sorted_children()
                total_pages = (len(children) + self.page_size - 1) // self.page_size
                if self.page < total_pages - 1:
                    self.page += 1
                continue

            if choice == 'P':
                # Previous page
                if self.page > 0:
                    self.page -= 1
                continue

            if choice == 'S':
                # Cycle through sort modes
                self.sort_mode = (self.sort_mode + 1) % 3
                self.page = 0  # Reset to first page when changing sort
                continue

            if choice == 'F':
                # Toggle filter
                self.filter_complete_paths = not self.filter_complete_paths
                self.page = 0  # Reset to first page when changing filter
                continue

            # Lowercase letters for selection (a-z on current page)
            choice_lower = choice.lower()
            page_idx = label_to_index(choice_lower)

            # Only accept single letters (a-z) for page-relative selection
            if len(choice_lower) == 1 and 0 <= page_idx < 26:
                children = self.get_sorted_children()
                # Convert page-relative index to absolute index
                absolute_idx = self.page * self.page_size + page_idx

                if 0 <= absolute_idx < len(children):
                    self.history.append(self.current_node)
                    self.current_node = children[absolute_idx]
                    self.page = 0

        print("\n  Goodbye!\n")


def main() -> None:
    archive_path = Path(__file__).parent.parent / "wikipedia-en-dwca"

    print("Loading taxonomy tree... (this may take a minute)")
    archive = DarwinCoreArchive(archive_path)
    tree = TaxonomyTree.from_archive(archive, progress_interval=100000)

    print("\nTree loaded! Starting explorer...\n")
    input("Press Enter to begin...")

    explorer = TreeExplorer(tree)
    explorer.run()


if __name__ == "__main__":
    main()

