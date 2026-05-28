"""Command-line entry point for the Taxonomica game."""

from __future__ import annotations

from pathlib import Path

from taxonomica.game.engine import TaxonomicaGame
from taxonomica.game.prompts import prompt_for_seed, select_difficulty
from taxonomica.game.selection import find_species_with_wikipedia
from taxonomica.runtime_db import RuntimeTaxonomyData


def main(project_root: Path | None = None) -> None:
    """Load datasets and run one or more Taxonomica rounds."""
    root = project_root or Path.cwd()

    print("\n" + "=" * 100)
    print("  🌿 TAXONOMICA - Loading... 🌿")
    print("=" * 100)

    print("\n  Loading Taxonomica runtime database...")
    try:
        data = RuntimeTaxonomyData.from_default(root)
    except FileNotFoundError as exc:
        print(f"\n  ERROR: {exc}")
        return

    tree = data.tree
    popularity_index = data.popularity_index
    stats = popularity_index.get_stats()
    print(f"    Runtime DB: {data.db_path}")
    print(f"    Easy: {stats['easy']:,} | Medium: {stats['medium']:,} | Hard: {stats['hard']:,}")

    seed_string, base_seed = prompt_for_seed()

    if seed_string:
        print(f"\n  Using seed: \"{seed_string}\"")

    difficulty = select_difficulty()

    round_number = 1
    cumulative_score = 0
    round_scores: list[tuple[int, str]] = []

    while True:
        if base_seed is not None:
            round_seed = base_seed + round_number
            print(f"\n  Round {round_number} - Loading...")
        else:
            round_seed = None
            print("\n  Loading...")

        result = find_species_with_wikipedia(
            tree,
            data,
            popularity_index,
            difficulty,
            seed=round_seed,
        )

        if not result:
            print("  ERROR: Could not find a species with Wikipedia entry.")
            print("  Please check that the Wikipedia data is properly loaded.")
            return

        target_node, description = result
        game = TaxonomicaGame(
            tree,
            data,
            target_node,
            description,
            difficulty=difficulty,
            seed_string=seed_string,
            round_number=round_number if seed_string else None,
        )

        print("\n  Ready to play!")
        input("  Press Enter to start...")

        game.run()

        if seed_string:
            round_scores.append((game.score, target_node.name))
            cumulative_score += game.score

            print("\n" + "-" * 60)
            print(f"  📊 CUMULATIVE SCORE after {round_number} round(s): {cumulative_score}")
            print("-" * 60)

        print("\n" + "=" * 100)
        try:
            again = input("  Play again? (y/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            again = "n"

        if again != "y":
            if seed_string and len(round_scores) > 1:
                print("\n" + "=" * 60)
                print("  🏆 FINAL SESSION SUMMARY")
                print(f"     Seed: \"{seed_string}\" | Difficulty: {difficulty.upper()}")
                print("=" * 60)
                for i, (score, species) in enumerate(round_scores, 1):
                    print(f"  Round {i}: {score:3d} pts - {species}")
                print("-" * 60)
                print(f"  TOTAL: {cumulative_score} points across {len(round_scores)} rounds")
                avg = cumulative_score / len(round_scores)
                print(f"  AVERAGE: {avg:.1f} points per round")
                print("=" * 60)

            print("\n  Thanks for playing Taxonomica! 🌿\n")
            break

        round_number += 1


if __name__ == "__main__":
    main()
