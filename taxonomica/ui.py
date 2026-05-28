"""Shared UI components for Taxonomica.

This module provides reusable terminal UI components for navigating
and displaying taxonomy trees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from taxonomica.gbif_tree import GBIFTaxonomyTree, TaxonomyNode


class SortMode(IntEnum):
    """Sort modes for node lists."""
    ALPHABETICAL = 0
    BY_DESCENDANTS = 1
    BY_RANK = 2


SORT_MODE_NAMES = [
    "alphabetical (leaves last)",
    "by descendants",
    "by rank (higher first)",
]


def clear_screen() -> None:
    """Clear the terminal screen."""
    print("\033[2J\033[H", end="")


def index_to_label(index: int) -> str:
    """Convert a numeric index to a letter label (a, b, ... z)."""
    if 0 <= index < 26:
        return chr(ord('a') + index)
    return ""


def label_to_index(label: str) -> int:
    """Convert a letter label back to a numeric index."""
    label = label.lower().strip()
    if len(label) == 1 and 'a' <= label <= 'z':
        return ord(label) - ord('a')
    return -1


def format_rank(rank: str) -> str:
    """Format a rank name for display."""
    return rank.capitalize() if rank else "Unknown"


def wrap_text(text: str, width: int = 76, indent: str = "  ") -> str:
    """Word wrap text with optional indent."""
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 > width:
            lines.append(indent + " ".join(current_line))
            current_line = [word]
            current_length = len(word)
        else:
            current_line.append(word)
            current_length += len(word) + 1
    
    if current_line:
        lines.append(indent + " ".join(current_line))
    
    return "\n".join(lines)


def get_sorted_children(
    node: TaxonomyNode,
    sort_mode: SortMode = SortMode.BY_RANK,
    filter_complete_paths: bool = True,
    filter_rank: str | None = None,
) -> list[TaxonomyNode]:
    """Get children of a node, sorted and optionally filtered.
    
    Args:
        node: The parent node.
        sort_mode: How to sort the children.
        filter_complete_paths: If True, only include nodes with complete paths.
        filter_rank: If provided, only include nodes of this rank.
        
    Returns:
        Sorted list of child nodes.
    """
    from taxonomica.gbif_tree import RANK_PRIORITY
    
    children = list(node.children.values())
    
    if filter_complete_paths:
        children = [c for c in children if c.has_complete_path()]
    
    if filter_rank:
        children = [c for c in children if c.rank == filter_rank]
    
    # Cache descendant counts for sorting
    desc_cache: dict[str, int] = {}
    for child in children:
        desc_cache[child.id] = child.count_descendants()
    
    def sort_key(n: TaxonomyNode) -> tuple:
        desc_count = desc_cache.get(n.id, 0)
        
        if sort_mode == SortMode.BY_DESCENDANTS:
            return (-desc_count, n.name.lower())
        elif sort_mode == SortMode.BY_RANK:
            rank_priority = RANK_PRIORITY.get(n.rank, 999)
            return (rank_priority, -desc_count, n.name.lower())
        else:  # ALPHABETICAL
            is_leaf = 0 if desc_count > 0 else 1
            return (is_leaf, n.name.lower())
    
    return sorted(children, key=sort_key)


@dataclass
class NodeListDisplay:
    """Configuration for displaying a list of nodes."""
    
    page: int = 0
    page_size: int = 26
    sort_mode: SortMode = SortMode.BY_RANK
    filter_complete_paths: bool = True
    filter_rank: str | None = None
    show_complete_marker: bool = True
    show_vernacular: bool = True
    show_descendants: bool = True
    
    def get_page_children(self, children: list[TaxonomyNode]) -> list[TaxonomyNode]:
        """Get the children for the current page."""
        start_idx = self.page * self.page_size
        end_idx = start_idx + self.page_size
        return children[start_idx:end_idx]
    
    def get_total_pages(self, total_children: int) -> int:
        """Get total number of pages."""
        if total_children == 0:
            return 1
        return (total_children + self.page_size - 1) // self.page_size
    
    def next_page(self, total_children: int) -> bool:
        """Go to next page. Returns True if page changed."""
        total_pages = self.get_total_pages(total_children)
        if self.page < total_pages - 1:
            self.page += 1
            return True
        return False
    
    def prev_page(self) -> bool:
        """Go to previous page. Returns True if page changed."""
        if self.page > 0:
            self.page -= 1
            return True
        return False
    
    def cycle_sort(self) -> None:
        """Cycle through sort modes."""
        self.sort_mode = SortMode((self.sort_mode + 1) % 3)
        self.page = 0
    
    def toggle_filter(self) -> None:
        """Toggle complete paths filter."""
        self.filter_complete_paths = not self.filter_complete_paths
        self.page = 0


def display_node_list(
    children: list[TaxonomyNode],
    config: NodeListDisplay,
    header: str = "Children:",
) -> None:
    """Display a paginated list of nodes.
    
    Args:
        children: The full list of children (already sorted/filtered).
        config: Display configuration.
        header: Header text to show above the list.
    """
    total_children = len(children)
    total_pages = config.get_total_pages(total_children)
    
    if total_children == 0:
        print()
        print("  (No options available)")
        print()
        return
    
    page_children = config.get_page_children(children)
    
    # Header with legend
    if config.show_complete_marker:
        print(f"\n  {header:<60} (✓ = complete path)")
    else:
        print(f"\n  {header}")
    print()
    
    # Display each child
    for i, child in enumerate(page_children):
        label = index_to_label(i)
        
        # Complete marker
        if config.show_complete_marker:
            complete_marker = "✓" if child.has_complete_path() else " "
        else:
            complete_marker = " "
        
        # Name (truncated)
        name_display = child.name[:30] if len(child.name) > 30 else child.name
        
        # Vernacular name
        if config.show_vernacular and child.vernacular_names:
            vn = child.vernacular_names[0][:22]
            vn_display = f'"{vn}"'
        else:
            vn_display = ""
        
        # Rank
        rank_str = f"[{child.rank}]" if child.rank else ""
        
        # Descendants
        if config.show_descendants:
            desc_count = child.count_descendants()
            child_info = f"({desc_count:,})" if desc_count > 0 else "(leaf)"
        else:
            child_info = ""
        
        print(f"  {complete_marker} ({label}) {name_display:<30} {vn_display:<24} {rank_str:<12} {child_info:>12}")
    
    print()
    
    # Pagination
    if total_pages > 1:
        nav_hints = []
        if config.page > 0:
            nav_hints.append("[P]rev")
        if config.page < total_pages - 1:
            nav_hints.append("[N]ext")
        nav_str = "  ".join(nav_hints)
        print(f"  Page {config.page + 1}/{total_pages}   {nav_str}")


def display_command_bar(
    commands: list[tuple[str, str]],
    width: int = 100,
) -> None:
    """Display a command bar at the bottom of the screen.
    
    Args:
        commands: List of (key, description) tuples.
        width: Total width of the bar.
    """
    print("-" * width)
    cmd_str = " | ".join(f"[{key}] {desc}" for key, desc in commands)
    print(f"  {cmd_str}")
    print("=" * width)


def get_user_choice(
    children: list[TaxonomyNode],
    config: NodeListDisplay,
    prompt: str = "  > ",
    allow_navigation: bool = True,
    allow_sort: bool = True,
    allow_filter: bool = True,
    extra_commands: dict[str, Callable[[], bool]] | None = None,
) -> tuple[str, TaxonomyNode | None]:
    """Get user input and handle navigation commands.
    
    Args:
        children: Current list of children.
        config: Display configuration.
        prompt: Input prompt.
        allow_navigation: Allow N/P for pagination.
        allow_sort: Allow S for sorting.
        allow_filter: Allow F for filtering.
        extra_commands: Additional command handlers (return True to refresh display).
        
    Returns:
        Tuple of (action, selected_node):
        - ("quit", None) - User wants to quit
        - ("select", node) - User selected a node
        - ("refresh", None) - Display needs refresh (after sort/filter/page change)
        - ("back", None) - User pressed back
        - ("invalid", None) - Invalid input
    """
    try:
        choice = input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        return ("quit", None)
    
    if not choice:
        return ("invalid", None)
    
    # Quit
    if choice == 'Q':
        return ("quit", None)
    
    # Back
    if choice == '<' or choice == '\x7f':
        return ("back", None)
    
    # Pagination
    if allow_navigation:
        if choice == 'N':
            if config.next_page(len(children)):
                return ("refresh", None)
            return ("invalid", None)
        
        if choice == 'P':
            if config.prev_page():
                return ("refresh", None)
            return ("invalid", None)
    
    # Sort
    if allow_sort and choice == 'S':
        config.cycle_sort()
        return ("refresh", None)
    
    # Filter
    if allow_filter and choice == 'F':
        config.toggle_filter()
        return ("refresh", None)
    
    # Extra commands
    if extra_commands and choice in extra_commands:
        if extra_commands[choice]():
            return ("refresh", None)
        return ("invalid", None)
    
    # Selection (a-z)
    choice_lower = choice.lower()
    if len(choice_lower) == 1:
        page_idx = label_to_index(choice_lower)
        if 0 <= page_idx < 26:
            absolute_idx = config.page * config.page_size + page_idx
            if 0 <= absolute_idx < len(children):
                return ("select", children[absolute_idx])
    
    return ("invalid", None)

