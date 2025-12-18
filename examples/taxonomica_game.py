#!/usr/bin/env python3
"""Taxonomica - A taxonomy guessing game.

Navigate the tree of life to identify a mystery species from its
redacted Wikipedia description. Wrong guesses cost points!

Usage:
    python examples/taxonomica_game.py

Controls:
    a-z         Select a choice on current page (lowercase)
    N / P       Next / Previous page (uppercase)
    S           Cycle sort mode (uppercase)
    Q           Quit game (uppercase)
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taxonomica.gbif_backbone import GBIFBackbone
from taxonomica.gbif_tree import GBIFTaxonomyTree, TaxonomyNode
from taxonomica.wikipedia import WikipediaData
from taxonomica.redaction import Redactor, build_redaction_terms_from_node
from taxonomica.popularity import PopularityIndex
from taxonomica.ui import (
    clear_screen,
    wrap_text,
    format_rank,
    get_sorted_children,
    display_node_list,
    get_user_choice,
    NodeListDisplay,
    SortMode,
    SORT_MODE_NAMES,
)


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences for progressive reveal.
    
    Uses a simple heuristic: split on '. ' followed by uppercase or end of text.
    This preserves abbreviations like 'Dr.' or 'U.S.' better than naive splitting.
    
    Note: This has issues with name abbreviations (e.g., "Andrew S. Urquhart").
    Consider using split_into_lines() for more consistent chunk sizes.
    """
    import re
    
    # Split on sentence-ending punctuation followed by space and capital letter
    # or end of string
    pattern = r'(?<=[.!?])\s+(?=[A-Z])'
    sentences = re.split(pattern, text)
    
    # Filter out very short "sentences" (likely fragments)
    result = [s.strip() for s in sentences if s.strip()]
    
    # Ensure we have at least one sentence
    if not result and text.strip():
        result = [text.strip()]
    
    return result


def split_into_lines(text: str, line_width: int = 90) -> list[str]:
    """Split text into wrapped lines for progressive reveal.
    
    This provides more consistent chunk sizes than sentences, since each
    line contains roughly the same amount of text/information.
    
    Args:
        text: The text to split.
        line_width: Target width for each line (in characters).
        
    Returns:
        List of lines, each approximately line_width characters.
    """
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        word_len = len(word)
        # +1 for the space between words
        if current_length + word_len + (1 if current_line else 0) > line_width:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = word_len
        else:
            current_line.append(word)
            current_length += word_len + (1 if len(current_line) > 1 else 0)
    
    # Don't forget the last line
    if current_line:
        lines.append(" ".join(current_line))
    
    return lines


class TaxonomicaGame:
    """The main game class."""
    
    # All taxonomic ranks (in order)
    ALL_RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
    
    # Progressive reveal defaults
    DEFAULT_INITIAL_CHUNKS = 3  # Lines or sentences to show initially
    DEFAULT_CHUNKS_PER_GUESS = 1  # Additional chunks per guess
    DEFAULT_REVEAL_MODE = "lines"  # "lines" or "sentences"
    DEFAULT_END_AT_GENUS = False  # Go all the way to species level
    
    # Guess cap settings
    MAX_GUESSES_PER_LEVEL = 5  # Max wrong guesses before auto-advance
    GUESS_CAP_PENALTY = 3  # Score penalty when guess cap is reached
    
    def __init__(
        self,
        tree: GBIFTaxonomyTree,
        wiki: WikipediaData,
        target_species: TaxonomyNode,
        description: str,
        initial_chunks: int = DEFAULT_INITIAL_CHUNKS,
        chunks_per_guess: int = DEFAULT_CHUNKS_PER_GUESS,
        reveal_mode: str = DEFAULT_REVEAL_MODE,
        end_at_genus: bool = DEFAULT_END_AT_GENUS,
        difficulty: str | None = None,
    ):
        self.tree = tree
        self.wiki = wiki
        self.target = target_species
        self.description = description
        self.end_at_genus = end_at_genus
        self.difficulty = difficulty or "random"
        
        # Determine which ranks to play through
        if end_at_genus:
            self.game_ranks = ["kingdom", "phylum", "class", "order", "family", "genus"]
        else:
            self.game_ranks = self.ALL_RANKS.copy()
        
        # Progressive reveal configuration
        self.initial_chunks = initial_chunks
        self.chunks_per_guess = chunks_per_guess
        self.reveal_mode = reveal_mode
        
        # Split description into chunks for progressive reveal
        if reveal_mode == "lines":
            self.chunks = split_into_lines(description)
            self.chunk_name = "line"
        else:
            self.chunks = split_into_sentences(description)
            self.chunk_name = "sentence"
        
        # Start with initial chunks, but don't exceed total available
        self.visible_chunks = min(initial_chunks, len(self.chunks))
        
        # Build the correct path from root to target
        self.correct_path = list(reversed(target_species.get_path_to_root()))
        
        # Current position in the tree
        self.current_node = tree.root
        self.current_rank_index = 0
        
        # Game state
        self.score = 0  # Wrong guesses (lower is better)
        self.guesses = 0  # Total guesses made
        self.revealed_ranks: set[str] = set()
        self.level_wrong_guesses = 0  # Wrong guesses at current level
        
        # Build redaction
        self.terms = build_redaction_terms_from_node(target_species)
        self.redactor = Redactor(self.terms, use_variable_length=True)
        
        # Display configuration
        self.display_config = NodeListDisplay(
            page=0,
            page_size=26,
            sort_mode=SortMode.BY_RANK,
            filter_complete_paths=True,
            show_complete_marker=False,  # Not needed in game mode
        )
    
    def get_current_rank(self) -> str:
        """Get the current rank we're guessing."""
        if self.current_rank_index < len(self.game_ranks):
            return self.game_ranks[self.current_rank_index]
        return "complete"
    
    def get_correct_child(self) -> TaxonomyNode | None:
        """Get the correct child node at the current level."""
        current_rank = self.get_current_rank()
        for node in self.correct_path:
            if node.rank == current_rank:
                return node
        return None
    
    def get_choices(self) -> list[TaxonomyNode]:
        """Get the available choices at the current level."""
        target_rank = self.get_current_rank()
        if target_rank == "complete":
            return []
        
        # Use the shared sorting function, but filter to target rank
        self.display_config.filter_rank = target_rank
        return get_sorted_children(
            self.current_node,
            sort_mode=self.display_config.sort_mode,
            filter_complete_paths=True,
            filter_rank=target_rank,
        )
    
    def make_guess(self, choice: TaxonomyNode) -> bool:
        """Make a guess. Returns True if correct."""
        self.guesses += 1
        correct_child = self.get_correct_child()
        
        # Progressive reveal: add more chunks with each guess
        self.visible_chunks = min(
            self.visible_chunks + self.chunks_per_guess,
            len(self.chunks)
        )
        
        if choice == correct_child:
            # Correct! Reveal this rank and advance
            self._advance_to_next_level(choice)
            return True
        else:
            # Wrong! Increment score and level counter
            self.score += 1
            self.level_wrong_guesses += 1
            return False
    
    def _advance_to_next_level(self, node: TaxonomyNode) -> None:
        """Advance to the next level after correct guess or guess cap."""
        self.revealed_ranks.add(self.get_current_rank())
        self.redactor.reveal_rank(self.get_current_rank())
        self.current_node = node
        self.current_rank_index += 1
        self.display_config.page = 0  # Reset page for new level
        self.level_wrong_guesses = 0  # Reset level counter
    
    def apply_guess_cap_penalty(self) -> TaxonomyNode:
        """Apply penalty and auto-advance when guess cap is reached.
        
        Returns:
            The correct node that we're advancing to.
        """
        self.score += self.GUESS_CAP_PENALTY
        correct_child = self.get_correct_child()
        if correct_child:
            self._advance_to_next_level(correct_child)
        return correct_child
    
    def is_at_guess_cap(self) -> bool:
        """Check if player has reached the guess cap for this level."""
        return self.level_wrong_guesses >= self.MAX_GUESSES_PER_LEVEL
    
    def is_complete(self) -> bool:
        """Check if the game is complete."""
        return self.current_rank_index >= len(self.game_ranks)
    
    def get_visible_text(self) -> str:
        """Get the currently visible portion of the description."""
        visible = self.chunks[:self.visible_chunks]
        # For lines, join with newlines; for sentences, join with spaces
        if self.reveal_mode == "lines":
            return "\n".join(visible)
        return " ".join(visible)
    
    def get_redacted_description(self) -> str:
        """Get the visible description with current redaction level."""
        visible_text = self.get_visible_text()
        return self.redactor.redact(visible_text)
    
    def display(self) -> list[TaxonomyNode]:
        """Display the current game state. Returns available choices."""
        clear_screen()
        
        # Header
        print("=" * 100)
        difficulty_label = f"[{self.difficulty.upper()}]" if self.difficulty != "random" else ""
        print(f"  🌿 TAXONOMICA - Guess the Species! {difficulty_label} 🌿")
        print("=" * 100)
        
        # Score and progress
        print(f"\n  Score: {self.score} wrong guesses | Progress: {self.current_rank_index}/{len(self.game_ranks)} ranks")
        
        # Current path (revealed portions only)
        if self.revealed_ranks:
            path_parts = []
            for node in self.correct_path[1:]:  # Skip root
                if node.rank in self.revealed_ranks:
                    vn = f' "{node.vernacular_names[0]}"' if node.vernacular_names else ""
                    path_parts.append(f"{node.name}{vn}")
                else:
                    break
            if path_parts:
                print(f"  Path: {' → '.join(path_parts)}")
        
        # Redacted description with progressive reveal info
        total_chunks = len(self.chunks)
        chunk_label = f"{self.chunk_name}s" if total_chunks != 1 else self.chunk_name
        print("\n" + "-" * 100)
        print(f"  MYSTERY SPECIES DESCRIPTION:  (showing {self.visible_chunks}/{total_chunks} {chunk_label})")
        print("-" * 100)
        redacted = self.get_redacted_description()
        # For lines mode, text is already line-broken; for sentences, wrap it
        if self.reveal_mode == "lines":
            # Add indent to each line
            for line in redacted.split("\n"):
                print(f"  {line}")
        else:
            print(wrap_text(redacted, width=94))
        # Show ellipsis if more content available
        if self.visible_chunks < total_chunks:
            print("  ...")
        print("-" * 100)
        
        # Current guessing level
        current_rank = self.get_current_rank()
        choices = []
        
        if current_rank != "complete":
            sort_name = SORT_MODE_NAMES[self.display_config.sort_mode]
            guesses_left = self.MAX_GUESSES_PER_LEVEL - self.level_wrong_guesses
            print(f"\n  Choose the correct {current_rank.upper()}:  ({guesses_left} guesses left, sorted: {sort_name})")
            
            choices = self.get_choices()
            
            # Use shared display function
            display_node_list(
                choices,
                self.display_config,
                header=f"Options ({len(choices)} total):",
            )
            
            # Command bar
            print("-" * 100)
            print("  [a-z] select | [N]ext page | [P]rev page | [S] sort | [Q] quit")
            print("=" * 100)
        
        return choices
    
    def display_victory(self) -> None:
        """Display the victory screen."""
        clear_screen()
        
        print("=" * 100)
        if self.end_at_genus:
            print("  🎉 CONGRATULATIONS! You identified the genus! 🎉")
        else:
            print("  🎉 CONGRATULATIONS! You identified the species! 🎉")
        print("=" * 100)
        
        # Final score
        print(f"\n  Final Score: {self.score} wrong guesses out of {self.guesses} total guesses")
        if self.score == 0:
            print("  🏆 PERFECT GAME! 🏆")
        elif self.score <= 3:
            print("  ⭐ Excellent taxonomy knowledge!")
        elif self.score <= 7:
            print("  👍 Good job!")
        else:
            print("  📚 Keep studying taxonomy!")
        
        # Reveal the species
        print(f"\n  The species was: {self.target.name}")
        if self.target.vernacular_names:
            print(f"  Common name: {self.target.vernacular_names[0]}")
        
        # Show full path (including ranks not guessed)
        print("\n  Complete taxonomy:")
        for node in self.correct_path[1:]:  # Skip root
            if node.rank in self.ALL_RANKS:
                vn = f' "{node.vernacular_names[0]}"' if node.vernacular_names else ""
                # Mark if this rank was guessed or revealed
                if node.rank in self.game_ranks:
                    print(f"  ✓ [{node.rank.upper():<8}] {node.name}{vn}")
                else:
                    print(f"    [{node.rank.upper():<8}] {node.name}{vn}")
        
        # Show more of the description (since we have much more content now)
        print("\n" + "-" * 100)
        print("  FULL DESCRIPTION (excerpt):")
        print("-" * 100)
        print(wrap_text(self.description[:2000], width=94))
        if len(self.description) > 2000:
            print(f"\n  ... and {len(self.description) - 2000:,} more characters ...")
        print("-" * 100)
    
    def run(self) -> None:
        """Run the game loop."""
        while not self.is_complete():
            choices = self.display()
            
            if not choices:
                print("\n  No valid choices available!")
                break
            
            # Get player input using shared function
            action, selected = get_user_choice(
                choices,
                self.display_config,
                prompt="\n  Your choice: ",
                allow_navigation=True,
                allow_sort=True,
                allow_filter=False,  # No filter toggle in game
            )
            
            if action == "quit":
                print(f"\n  Game ended. The species was: {self.target.name}")
                if self.target.vernacular_names:
                    print(f"  Common name: {self.target.vernacular_names[0]}")
                return
            
            if action == "refresh":
                # Sort or page changed, just redisplay
                continue
            
            if action == "invalid":
                continue
            
            if action == "select" and selected:
                # Track chunks before guess for feedback
                chunks_before = self.visible_chunks
                
                correct = self.make_guess(selected)
                
                # Check if new content was revealed
                new_chunks = self.visible_chunks - chunks_before
                reveal_msg = ""
                if new_chunks > 0:
                    chunk_word = self.chunk_name + ("s" if new_chunks > 1 else "")
                    reveal_msg = f" (+{new_chunks} new {chunk_word} revealed!)"
                
                if correct:
                    print(f"\n  ✓ Correct! {selected.name} is right!{reveal_msg}")
                    if selected.vernacular_names:
                        print(f"    Common name: {selected.vernacular_names[0]}")
                    input("  Press Enter to continue...")
                else:
                    # Check if guess cap reached
                    if self.is_at_guess_cap():
                        correct_node = self.apply_guess_cap_penalty()
                        print(f"\n  ✗ Out of guesses for this level!{reveal_msg}")
                        print(f"    The answer was: {correct_node.name}")
                        if correct_node.vernacular_names:
                            print(f"    Common name: {correct_node.vernacular_names[0]}")
                        print(f"    (+{self.GUESS_CAP_PENALTY} penalty, advancing to next level)")
                        input("  Press Enter to continue...")
                    else:
                        guesses_remaining = self.MAX_GUESSES_PER_LEVEL - self.level_wrong_guesses
                        print(f"\n  ✗ Wrong!{reveal_msg} ({guesses_remaining} guesses left)")
                        print(f"    (The correct answer is still among the choices)")
                        input("  Press Enter to try again...")
        
        # Victory!
        self.display_victory()
        input("\n  Press Enter to exit...")


def find_species_with_wikipedia(
    tree: GBIFTaxonomyTree,
    wiki: WikipediaData,
    popularity_index: PopularityIndex | None = None,
    difficulty: str = "expert",
    max_attempts: int = 200,
) -> tuple[TaxonomyNode, str] | None:
    """Find a random species that has a Wikipedia entry with description.
    
    Args:
        tree: The GBIF taxonomy tree.
        wiki: The Wikipedia data loader.
        popularity_index: Optional popularity index for difficulty filtering.
        difficulty: Difficulty tier ("easy", "medium", "hard", "expert").
                   Tiers are inclusive: medium includes easy, hard includes medium, etc.
        max_attempts: Maximum number of species to try.
    
    Returns:
        Tuple of (node, description) or None if not found.
    """
    # Difficulty thresholds (inclusive - each tier includes easier tiers)
    DIFFICULTY_THRESHOLDS = {
        "easy": 55,    # Top 1%
        "medium": 49,  # Top 5%
        "hard": 24,    # Top 25%
        "expert": 0,   # All species
    }
    
    min_score = DIFFICULTY_THRESHOLDS.get(difficulty, 0)
    
    # Pre-filter: Build list of candidate species names from popularity index
    # This is MUCH faster than random sampling when filtering by difficulty
    candidate_names: set[str] | None = None
    if difficulty != "expert" and popularity_index and min_score > 0:
        print(f"  Pre-filtering for difficulty: {difficulty.upper()} (score >= {min_score})...")
        candidate_names = set()
        for metrics in popularity_index._by_id.values():
            if metrics.popularity_score >= min_score and metrics.section_count >= 2:
                candidate_names.add(metrics.scientific_name.lower())
        print(f"    Found {len(candidate_names):,} candidates in popularity index")
    
    # Get species nodes, optionally filtered by difficulty candidates
    species_nodes = []
    for node in tree._nodes_by_id.values():
        if node.rank == "species" and node.has_complete_path():
            # If filtering by difficulty, only include candidates
            if candidate_names is not None:
                if node.name.lower() not in candidate_names:
                    continue
            species_nodes.append(node)
    
    print(f"  Found {len(species_nodes):,} eligible species")
    
    if not species_nodes:
        return None
    
    # Try random species until we find one with a Wikipedia entry
    attempts = 0
    tried = set()
    
    while attempts < max_attempts and len(tried) < len(species_nodes):
        node = random.choice(species_nodes)
        if node.id in tried:
            continue
        tried.add(node.id)
        attempts += 1
        
        # Progress indicator
        if attempts % 50 == 0:
            print(f"    Searching... ({attempts} attempts)")
        
        # Try to find Wikipedia entry
        wiki_species = wiki.match_gbif_taxon(node.name)
        if wiki_species:
            # Use useful text (excludes species lists, galleries, etc.)
            full_text = wiki_species.get_useful_text()
            if full_text and len(full_text) > 400:  # Require substantive description
                # Check we have enough lines for progressive reveal
                lines = split_into_lines(full_text)
                if len(lines) >= 12:  # Need enough lines for many guesses
                    print(f"  Found a species after {attempts} attempts!")
                    return node, full_text
    
    return None


def select_difficulty() -> str:
    """Prompt user to select difficulty level.
    
    Returns:
        Difficulty tier string ("easy", "medium", "hard", or "expert").
    """
    print("\n" + "=" * 40)
    print("  SELECT DIFFICULTY")
    print("=" * 40)
    print()
    print("  (1) EASY")
    print("  (2) MEDIUM")
    print("  (3) HARD")
    print("  (4) EXPERT")
    print()
    
    while True:
        try:
            choice = input("  Enter choice (1-4): ").strip()
        except (KeyboardInterrupt, EOFError):
            return "expert"
        
        if choice == "1":
            return "easy"
        elif choice == "2":
            return "medium"
        elif choice == "3":
            return "hard"
        elif choice == "4":
            return "expert"
        else:
            print("  Invalid choice. Please enter 1, 2, 3, or 4.")


def main():
    print("\n" + "=" * 100)
    print("  🌿 TAXONOMICA - Loading... 🌿")
    print("=" * 100)
    
    # Load GBIF tree
    backbone_path = Path(__file__).parent.parent / "backbone"
    wiki_path = Path(__file__).parent.parent / "wikipedia-en-dwca"
    
    if not backbone_path.exists():
        print(f"\n  ERROR: GBIF backbone not found at {backbone_path}")
        print("  Please download the GBIF Backbone Taxonomy first.")
        return
    
    if not wiki_path.exists():
        print(f"\n  ERROR: Wikipedia data not found at {wiki_path}")
        print("  Please download the Wikipedia DwC-A export first.")
        return
    
    print("\n  Loading GBIF Backbone Taxonomy...")
    print("  (This takes a few minutes on first load)\n")
    
    backbone = GBIFBackbone(backbone_path)
    tree = GBIFTaxonomyTree.from_backbone(backbone, accepted_only=True)
    
    print("\n  Loading vernacular names...")
    tree.add_vernacular_names(backbone)
    
    print("\n  Loading Wikipedia data...")
    wiki = WikipediaData(wiki_path)
    
    print("\n  Building popularity index...")
    popularity_index = PopularityIndex.from_wikipedia_dwca(wiki_path)
    stats = popularity_index.get_stats()
    print(f"    Easy: {stats['easy']:,} | Medium: {stats['medium']:,} | Hard: {stats['hard']:,}")
    
    # Game loop - allow replaying
    while True:
        # Select difficulty
        difficulty = select_difficulty()
        
        print(f"\n  Finding a mystery species (difficulty: {difficulty.upper()})...")
        result = find_species_with_wikipedia(tree, wiki, popularity_index, difficulty)
        
        if not result:
            print("  ERROR: Could not find a species with Wikipedia entry.")
            print("  Please check that the Wikipedia data is properly loaded.")
            return
        
        target_node, description = result
        
        # Create and run game
        game = TaxonomicaGame(tree, wiki, target_node, description, difficulty=difficulty)
        
        print("\n  Ready to play!")
        input("  Press Enter to start...")
        
        game.run()
        
        # Play again?
        print("\n" + "=" * 100)
        try:
            again = input("  Play again? (y/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            again = 'n'
        
        if again != 'y':
            print("\n  Thanks for playing Taxonomica! 🌿\n")
            break


if __name__ == "__main__":
    main()
