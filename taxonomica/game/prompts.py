"""Terminal prompts used during game setup."""

from __future__ import annotations

from taxonomica.game.selection import get_seed_from_string


def prompt_for_seed() -> tuple[str | None, int | None]:
    """Prompt the player for an optional competitive-play seed."""
    print("\n" + "=" * 60)
    print("  🎮 GAME SETUP")
    print("=" * 60)
    print()
    print("  For competitive play, enter a seed word/phrase.")
    print("  Players with the same seed get the same species.")
    print("  Difficulty changes both the target pool and the visible tree.")
    print()
    print("  Leave blank for a random species.")
    print()

    try:
        seed_input = input("  Seed (or press Enter to skip): ").strip()
    except (KeyboardInterrupt, EOFError):
        return None, None

    if seed_input:
        return seed_input, get_seed_from_string(seed_input)

    return None, None


def select_difficulty() -> str:
    """Prompt the player to select a difficulty tier."""
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
        if choice == "2":
            return "medium"
        if choice == "3":
            return "hard"
        if choice == "4":
            return "expert"

        print("  Invalid choice. Please enter 1, 2, 3, or 4.")
