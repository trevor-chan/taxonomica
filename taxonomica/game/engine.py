"""Terminal game engine for Taxonomica."""

from taxonomica.game.text import split_into_lines, split_into_sentences
from taxonomica.game.titles import get_rank_title
from taxonomica.redaction import Redactor, build_redaction_terms_from_node
from taxonomica.runtime_db import RuntimeTaxonomyData
from taxonomica.taxonomy import TaxonNode, TaxonomyTree
from taxonomica.ui import (
    NodeListDisplay,
    SORT_MODE_NAMES,
    SortMode,
    clear_screen,
    display_node_list,
    get_sorted_children,
    wrap_text,
)


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
        tree: TaxonomyTree,
        runtime_data: RuntimeTaxonomyData,
        target_species: TaxonNode,
        description: str,
        initial_chunks: int = DEFAULT_INITIAL_CHUNKS,
        chunks_per_guess: int = DEFAULT_CHUNKS_PER_GUESS,
        reveal_mode: str = DEFAULT_REVEAL_MODE,
        end_at_genus: bool = DEFAULT_END_AT_GENUS,
        difficulty: str | None = None,
        seed_string: str | None = None,
        round_number: int | None = None,
    ):
        self.tree = tree
        self.runtime_data = runtime_data
        self.target = target_species
        self.description = description
        self.end_at_genus = end_at_genus
        self.difficulty = difficulty or "random"
        self.seed_string = seed_string  # For competitive play
        self.round_number = round_number  # Round number for seeded games
        
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
        self.score = 0  # Total score (lower is better)
        self.wrong_guesses = 0  # Number of wrong guesses
        self.penalty_points = 0  # Penalty points from guess cap
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
    
    def get_correct_child(self) -> TaxonNode | None:
        """Get the correct child node at the current level."""
        current_rank = self.get_current_rank()
        for node in self.correct_path:
            if node.rank == current_rank:
                return node
        return None
    
    def get_choices(self) -> list[TaxonNode]:
        """Get the available choices at the current level."""
        target_rank = self.get_current_rank()
        if target_rank == "complete":
            return []
        
        # Use the shared sorting function, but filter to target rank
        self.display_config.filter_rank = target_rank
        choices = get_sorted_children(
            self.current_node,
            sort_mode=self.display_config.sort_mode,
            filter_complete_paths=True,
            filter_rank=target_rank,
        )
        
        # For non-species levels, exclude leaf nodes (they can never be correct)
        # since the target is always a species with a complete path
        if target_rank != "species":
            choices = [c for c in choices if c.children]
        
        return choices
    
    def make_guess(self, choice: TaxonNode) -> bool:
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
            self.wrong_guesses += 1
            self.level_wrong_guesses += 1
            return False
    
    def _advance_to_next_level(self, node: TaxonNode) -> None:
        """Advance to the next level after correct guess or guess cap."""
        self.revealed_ranks.add(self.get_current_rank())
        self.redactor.reveal_rank(self.get_current_rank())
        self.current_node = node
        self.current_rank_index += 1
        self.display_config.page = 0  # Reset page for new level
        self.level_wrong_guesses = 0  # Reset level counter
    
    def apply_guess_cap_penalty(self) -> TaxonNode | None:
        """Apply penalty and auto-advance when guess cap is reached.
        
        Returns:
            The correct node that we're advancing to.
        """
        self.score += self.GUESS_CAP_PENALTY
        self.penalty_points += self.GUESS_CAP_PENALTY
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
    
    def display(self) -> list[TaxonNode]:
        """Display the current game state. Returns available choices."""
        clear_screen()
        
        # Header
        print("=" * 100)
        difficulty_label = f"[{self.difficulty.upper()}]" if self.difficulty != "random" else ""
        if self.seed_string and self.round_number:
            seed_label = f" | Seed: \"{self.seed_string}\" Round {self.round_number}"
        elif self.seed_string:
            seed_label = f" | Seed: \"{self.seed_string}\""
        else:
            seed_label = ""
        print(f"  🌿 TAXONOMICA - Guess the Species! {difficulty_label}{seed_label} 🌿")
        print("=" * 100)
        
        # Score and progress
        print(
            f"\n  Score: {self.score} wrong guesses | "
            f"Progress: {self.current_rank_index}/{len(self.game_ranks)} ranks"
        )
        
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
        print(
            "  MYSTERY SPECIES DESCRIPTION:  "
            f"(showing {self.visible_chunks}/{total_chunks} {chunk_label})"
        )
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
            print(
                f"\n  Choose the correct {current_rank.upper()}:  "
                f"({guesses_left} guesses left, sorted: {sort_name})"
            )
            
            choices = self.get_choices()
            
            # Use shared display function
            display_node_list(
                choices,
                self.display_config,
                header=f"Options ({len(choices)} total):",
            )
            
            # Command bar
            print("-" * 100)
            print(
                "  [a-z] select | [I] or [I+letter] info | "
                "[N]ext/[P]rev page | [S] sort | [Q] quit"
            )
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
        # Show detailed score breakdown
        if self.penalty_points > 0:
            print(
                f"\n  Final Score: {self.score} "
                f"({self.wrong_guesses} wrong + {self.penalty_points} penalty) "
                f"out of {self.guesses} guesses"
            )
        else:
            print(
                f"\n  Final Score: {self.score} wrong guesses out of "
                f"{self.guesses} total guesses"
            )
        if self.score == 0:
            print("  🏆 PERFECT GAME!")
        elif self.score <= 7:
            print("  ⭐ Excellent taxonomy knowledge!")
        elif self.score <= 14:
            print("  👍 Good job!")
        else:
            print("  📚 Keep studying taxonomy!")
        
        # Get a fun rank title based on score and taxon
        rank_title = get_rank_title(self.score, self.target)
        if rank_title:
            print(f"\n  🎖️  You've attained the rank of: {rank_title}")
        
        # Show seed for competitive play comparison
        if self.seed_string:
            round_info = f" | Round {self.round_number}" if self.round_number else ""
            print(
                f"\n  🎮 Seed: \"{self.seed_string}\"{round_info} | "
                f"Difficulty: {self.difficulty.upper()}"
            )
        
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
    
    def _handle_input(
        self,
        choice: str,
        choices: list[TaxonNode],
    ) -> tuple[str, TaxonNode | None]:
        """Handle user input and return (action, selected_node)."""
        from taxonomica.ui import label_to_index
        
        if not choice:
            return ("invalid", None)
        
        # Quit
        if choice == 'Q':
            return ("quit", None)
        
        # Pagination
        if choice == 'N':
            if self.display_config.next_page(len(choices)):
                return ("refresh", None)
            return ("invalid", None)
        
        if choice == 'P':
            if self.display_config.prev_page():
                return ("refresh", None)
            return ("invalid", None)
        
        # Sort
        if choice == 'S':
            self.display_config.cycle_sort()
            return ("refresh", None)
        
        # Selection (a-z)
        choice_lower = choice.lower()
        if len(choice_lower) == 1:
            page_idx = label_to_index(choice_lower)
            if 0 <= page_idx < 26:
                absolute_idx = self.display_config.page * self.display_config.page_size + page_idx
                if 0 <= absolute_idx < len(choices):
                    return ("select", choices[absolute_idx])
        
        return ("invalid", None)
    
    def show_taxon_info(self, node: TaxonNode) -> None:
        """Display Wikipedia information about a taxon."""
        clear_screen()
        
        print("=" * 100)
        print(f"  📖 INFORMATION: {node.name}")
        print("=" * 100)
        
        if node.vernacular_names:
            print(f"\n  Common name: {node.vernacular_names[0]}")
        print(f"  Rank: {node.rank}")
        print(f"  Descendants: {node.count_descendants():,}")
        
        # Try to get Wikipedia description
        description_entry = self.runtime_data.match_taxon_key(node.id)
        if description_entry and description_entry.description:
            description = description_entry.description
            print("\n" + "-" * 100)
            print("  WIKIPEDIA DESCRIPTION:")
            print("-" * 100)
            print(wrap_text(description[:3000], width=94))
            if len(description) > 3000:
                print(f"\n  ... and {len(description) - 3000:,} more characters ...")
            print("-" * 100)
        else:
            print("\n  (No Wikipedia entry found for this taxon)")
        
        print("\n" + "=" * 100)
        input("  Press Enter to return to the game...")
    
    def run(self) -> None:
        """Run the game loop."""
        while not self.is_complete():
            choices = self.display()
            
            if not choices:
                print("\n  No valid choices available!")
                break
            
            # Get player input
            try:
                choice_input = input("\n  Your choice: ").strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n  Game ended. The species was: {self.target.name}")
                return
            
            # Check for info command: [I] for current node, [I+letter] for choice
            # Note: Only uppercase 'I' triggers info; lowercase 'i' selects taxon at index 8
            if choice_input == 'I':
                # Show info about the current node (where we are now)
                self.show_taxon_info(self.current_node)
                continue
            
            if len(choice_input) == 2 and choice_input[0] == 'I':
                # Block info on choices at species level (would reveal the answer)
                current_rank = self.game_ranks[self.current_rank_index]
                if current_rank == "species":
                    print("  Info not available for species choices.")
                    input("  Press Enter to continue...")
                    continue
                
                letter = choice_input[1].lower()
                if 'a' <= letter <= 'z':
                    idx = ord(letter) - ord('a')
                    absolute_idx = self.display_config.page * self.display_config.page_size + idx
                    if 0 <= absolute_idx < len(choices):
                        self.show_taxon_info(choices[absolute_idx])
                        continue
                    else:
                        print("  Invalid choice.")
                        input("  Press Enter to continue...")
                        continue
            
            # Handle standard commands using shared function
            # We need to simulate the input since we already read it
            action, selected = self._handle_input(choice_input, choices)
            
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
