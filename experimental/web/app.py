#!/usr/bin/env python3
"""Bare-bones terminal-style web wrapper for Taxonomica.

Run locally with:
    python experimental/web/app.py

Then visit http://localhost:8080
"""

from __future__ import annotations

import io
import os
import re
import secrets
import socket
import sys
import time
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from flask import Flask, jsonify, render_template, request
from flask import session as browser_session

# Add repository root to path for source checkouts.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from taxonomica.game.engine import TaxonomicaGame  # noqa: E402
from taxonomica.game.selection import get_seed_from_string, select_playable_species  # noqa: E402
from taxonomica.runtime_db import RuntimeTaxonomyData  # noqa: E402
from taxonomica.taxonomy import TaxonNode  # noqa: E402
from taxonomica.ui import wrap_text  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("TAXONOMICA_SECRET_KEY", "taxonomica-terminal-dev-key")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

application = app

WEB_IN_MEMORY_DB = os.environ.get("TAXONOMICA_WEB_IN_MEMORY_DB", "1").lower() not in {
    "0",
    "false",
    "no",
}

DIFFICULTY_CHOICES = {
    "1": "easy",
    "easy": "easy",
    "e": "easy",
    "2": "medium",
    "medium": "medium",
    "m": "medium",
    "3": "hard",
    "hard": "hard",
    "h": "hard",
    "4": "expert",
    "expert": "expert",
    "x": "expert",
}

SESSION_TTL_SECONDS = 2 * 60 * 60
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

T = TypeVar("T")

runtime_data: RuntimeTaxonomyData | None = None
difficulty_data: dict[str, RuntimeTaxonomyData] = {}
terminal_sessions: dict[str, TerminalSession] = {}


def capture_output(func: Callable[..., T], *args: Any, **kwargs: Any) -> tuple[T, str]:
    """Run a print-oriented function and return its result plus captured output."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, clean_terminal_text(buffer.getvalue())


def clean_terminal_text(text: str) -> str:
    """Remove terminal control codes that do not belong in a plain HTML pre."""
    return ANSI_RE.sub("", text).strip("\n")


def join_sections(*sections: str | None) -> str:
    return "\n".join(section for section in sections if section)


def get_runtime_data() -> RuntimeTaxonomyData:
    """Load the runtime database once per web process."""
    global runtime_data
    if runtime_data is None:
        runtime_data = RuntimeTaxonomyData.from_default(
            PROJECT_ROOT,
            in_memory=WEB_IN_MEMORY_DB,
        )
    return runtime_data


def get_difficulty_data(difficulty: str) -> RuntimeTaxonomyData:
    """Share difficulty-pruned runtime views across browser sessions."""
    if difficulty not in difficulty_data:
        difficulty_data[difficulty] = get_runtime_data().for_difficulty(difficulty)
    return difficulty_data[difficulty]


@dataclass
class TerminalSession:
    """A small request/response state machine that feels like the CLI."""

    data: RuntimeTaxonomyData
    screen: str = ""
    prompt: str = ""
    state: str = "seed"
    seed_string: str | None = None
    base_seed: int | None = None
    difficulty: str = "medium"
    round_number: int = 1
    cumulative_score: int = 0
    round_scores: list[tuple[int, str]] = field(default_factory=list)
    active_data: RuntimeTaxonomyData | None = None
    game: TaxonomicaGame | None = None
    pause_next_state: str = "game"
    round_finished: bool = False
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Return to the first setup prompt."""
        self.seed_string = None
        self.base_seed = None
        self.difficulty = "medium"
        self.round_number = 1
        self.cumulative_score = 0
        self.round_scores.clear()
        self.active_data = None
        self.game = None
        self.pause_next_state = "game"
        self.round_finished = False
        self.state = "seed"
        self.screen = self._render_seed_prompt()
        self.prompt = "  Seed (or press Enter to skip):"

    def snapshot(self) -> dict[str, str]:
        self.updated_at = time.time()
        return {
            "screen": self.screen,
            "prompt": self.prompt,
            "state": self.state,
        }

    def handle(self, command: str) -> dict[str, str]:
        """Advance the terminal session by one submitted line."""
        if self.state == "seed":
            self._handle_seed(command)
        elif self.state == "difficulty":
            self._handle_difficulty(command)
        elif self.state == "ready":
            self._show_game()
        elif self.state == "game":
            self._handle_game_command(command)
        elif self.state == "pause":
            self._handle_pause()
        elif self.state == "info":
            self._show_game()
        elif self.state == "victory":
            self._show_post_round_prompt()
        elif self.state == "post_round":
            self._handle_post_round(command)
        else:
            self.reset()
        return self.snapshot()

    def _render_seed_prompt(self) -> str:
        return "\n".join(
            [
                "=" * 100,
                "  TAXONOMICA - Web Terminal",
                "=" * 100,
                "",
                "",
                f"  Runtime DB: {self.data.db_path}",
                (
                    f"  Taxa: {len(self.data.tree._nodes_by_id) - 1:,} | "
                    f"Species in full tree: {self.data.playable_species_count:,} | "
                    f"Target species: {self.data.target_species_count:,}"
                ),
                "",
                "-" * 60,
                "  GAME SETUP",
                "-" * 60,
                "",
                "  For competitive play, enter a seed word/phrase.",
                "  Players with the same seed, difficulty, and round get the same species.",
                "",
                "  Leave blank for a random species.",
            ]
        )

    def _handle_seed(self, command: str) -> None:
        seed_input = command.strip()
        if seed_input:
            self.seed_string = seed_input
            self.base_seed = get_seed_from_string(seed_input)
        self.state = "difficulty"
        self.screen = self._render_difficulty_prompt()
        self.prompt = "  Enter choice (1-4):"

    def _render_difficulty_prompt(self, invalid: bool = False) -> str:
        lines = [
            "=" * 40,
            "  SELECT DIFFICULTY",
            "=" * 40,
            "",
            "  (1) EASY",
            "  (2) MEDIUM",
            "  (3) HARD",
            "  (4) EXPERT",
            "",
        ]
        if self.seed_string:
            lines.insert(0, f'  Using seed: "{self.seed_string}"')
            lines.insert(1, "")
        if invalid:
            lines.append("  Invalid choice. Please enter 1, 2, 3, or 4.")
        return "\n".join(lines)

    def _handle_difficulty(self, command: str) -> None:
        choice = command.strip().lower()
        difficulty = DIFFICULTY_CHOICES.get(choice)
        if difficulty is None:
            self.screen = self._render_difficulty_prompt(invalid=True)
            self.prompt = "  Enter choice (1-4):"
            return
        self.difficulty = difficulty
        self._prepare_round()

    def _prepare_round(self) -> None:
        self.active_data = get_difficulty_data(self.difficulty)
        self.round_finished = False
        if self.base_seed is not None:
            round_seed = self.base_seed + self.round_number
            loading_line = f"  Round {self.round_number} - Loading..."
        else:
            round_seed = None
            loading_line = "  Loading..."

        result, selection_output = capture_output(
            select_playable_species,
            self.active_data,
            seed=round_seed,
            difficulty=self.difficulty,
        )
        if not result:
            self.state = "error"
            self.screen = join_sections(
                loading_line,
                selection_output,
                "  ERROR: Could not find a species with Wikipedia entry.",
                "  Press Enter to return to setup.",
            )
            self.prompt = "  Press Enter:"
            return

        target_node, description = result
        self.game = TaxonomicaGame(
            self.active_data.tree,
            self.active_data,
            target_node,
            description,
            difficulty=self.difficulty,
            seed_string=self.seed_string,
            round_number=self.round_number if self.seed_string else None,
        )
        self.state = "ready"
        self.screen = join_sections(
            loading_line,
            selection_output,
            f"  Playing with {self.active_data.playable_species_count:,} species.",
            "",
            "  Ready to play!",
        )
        self.prompt = "  Press Enter to start:"

    def _show_game(self) -> None:
        if self.game is None:
            self.reset()
            return
        if self.game.is_complete():
            self._show_victory()
            return
        _, output = capture_output(self.game.display)
        self.state = "game"
        self.screen = output
        self.prompt = "  Your choice:"

    def _handle_game_command(self, command: str) -> None:
        if self.game is None:
            self.reset()
            return

        choice_input = command.strip()
        choices = self.game.get_choices()
        if not choices:
            self.screen = self._append_to_screen("  No valid choices available!")
            self._show_victory()
            return

        if choice_input == "I":
            self._show_taxon_info(self.game.current_node)
            return

        if len(choice_input) == 2 and choice_input[0] == "I":
            current_rank = self.game.game_ranks[self.game.current_rank_index]
            if current_rank == "species":
                self._enter_pause(
                    ["Info not available for species choices."],
                    next_state="game",
                    prompt="  Press Enter to continue:",
                )
                return

            letter = choice_input[1].lower()
            if "a" <= letter <= "z":
                index = ord(letter) - ord("a")
                absolute_index = (
                    self.game.display_config.page * self.game.display_config.page_size + index
                )
                if 0 <= absolute_index < len(choices):
                    self._show_taxon_info(choices[absolute_index])
                    return

            self._enter_pause(
                ["Invalid info choice."],
                next_state="game",
                prompt="  Press Enter to continue:",
            )
            return

        action, selected = self.game._handle_input(choice_input, choices)

        if action == "quit":
            lines = [f"Game ended. The species was: {self.game.target.name}"]
            if self.game.target.vernacular_names:
                lines.append(f"Common name: {self.game.target.vernacular_names[0]}")
            self._enter_pause(lines, next_state="post_round", prompt="  Press Enter to continue:")
            return

        if action == "refresh":
            self._show_game()
            return

        if action == "invalid":
            self.screen = self._append_to_screen("  Invalid command.")
            self.prompt = "  Your choice:"
            return

        if action == "select" and selected is not None:
            self._handle_selection(selected)

    def _handle_selection(self, selected: TaxonNode) -> None:
        if self.game is None:
            self.reset()
            return

        chunks_before = self.game.visible_chunks
        correct = self.game.make_guess(selected)
        new_chunks = self.game.visible_chunks - chunks_before
        reveal_msg = ""
        if new_chunks > 0:
            chunk_word = self.game.chunk_name + ("s" if new_chunks > 1 else "")
            reveal_msg = f" (+{new_chunks} new {chunk_word} revealed!)"

        if correct:
            lines = [f"Correct! {selected.name} is right!{reveal_msg}"]
            if selected.vernacular_names:
                lines.append(f"Common name: {selected.vernacular_names[0]}")
            next_state = "victory" if self.game.is_complete() else "game"
            self._enter_pause(lines, next_state=next_state, prompt="  Press Enter to continue:")
            return

        if self.game.is_at_guess_cap():
            correct_node = self.game.apply_guess_cap_penalty()
            answer = (
                self.game._format_taxon_name(correct_node)
                if correct_node is not None
                else "unknown"
            )
            lines = [
                f"Out of guesses for this level!{reveal_msg}",
                f"The answer was: {answer}",
                f"(+{self.game.GUESS_CAP_PENALTY} penalty, advancing to next level)",
            ]
            next_state = "victory" if self.game.is_complete() else "game"
            self._enter_pause(lines, next_state=next_state, prompt="  Press Enter to continue:")
            return

        guesses_remaining = self.game.MAX_GUESSES_PER_LEVEL - self.game.level_wrong_guesses
        self._enter_pause(
            [
                f"Wrong!{reveal_msg} ({guesses_remaining} guesses left)",
                "(The correct answer is still among the choices)",
            ],
            next_state="game",
            prompt="  Press Enter to try again:",
        )

    def _enter_pause(self, lines: list[str], next_state: str, prompt: str) -> None:
        self.pause_next_state = next_state
        self.state = "pause"
        formatted = "\n".join(f"  {line}" for line in lines)
        self.screen = self._append_to_screen(formatted)
        self.prompt = prompt

    def _handle_pause(self) -> None:
        if self.pause_next_state == "victory":
            self._show_victory()
        elif self.pause_next_state == "post_round":
            self._show_post_round_prompt()
        else:
            self._show_game()

    def _show_taxon_info(self, node: TaxonNode) -> None:
        if self.active_data is None:
            self.reset()
            return

        lines = [
            "=" * 100,
            f"  INFORMATION: {node.name}",
            "=" * 100,
            "",
        ]
        if node.vernacular_names:
            lines.append(f"  Common name: {node.vernacular_names[0]}")
        lines.extend(
            [
                f"  Rank: {node.rank}",
                f"  Descendants: {node.count_descendants():,}",
            ]
        )

        description_entry = self.active_data.match_taxon_key(node.id)
        if description_entry and description_entry.description:
            lines.extend(
                [
                    "",
                    "-" * 100,
                    "  WIKIPEDIA DESCRIPTION:",
                    "-" * 100,
                    wrap_text(description_entry.description[:3000], width=94),
                ]
            )
            if len(description_entry.description) > 3000:
                remaining = len(description_entry.description) - 3000
                lines.append(f"\n  ... and {remaining:,} more characters ...")
            lines.append("-" * 100)
        else:
            lines.extend(["", "  (No Wikipedia entry found for this taxon)"])

        lines.extend(["", "=" * 100])
        self.state = "info"
        self.screen = "\n".join(lines)
        self.prompt = "  Press Enter to return to the game:"

    def _show_victory(self) -> None:
        if self.game is None:
            self.reset()
            return
        self._finish_round_once()
        _, output = capture_output(self.game.display_victory)
        self.state = "victory"
        self.screen = output
        self.prompt = "  Press Enter to exit:"

    def _finish_round_once(self) -> None:
        if self.round_finished or self.game is None:
            return
        self.round_finished = True
        if self.seed_string:
            self.round_scores.append((self.game.score, self.game.target.name))
            self.cumulative_score += self.game.score

    def _show_post_round_prompt(self) -> None:
        self._finish_round_once()
        lines = ["=" * 100]
        if self.seed_string:
            lines.extend(
                [
                    f"  CUMULATIVE SCORE after {self.round_number} round(s): "
                    f"{self.cumulative_score}",
                    "-" * 100,
                ]
            )
        lines.append("  Play again? (y/n)")
        self.state = "post_round"
        self.screen = "\n".join(lines)
        self.prompt = "  Play again? (y/n):"

    def _handle_post_round(self, command: str) -> None:
        if command.strip().lower() == "y":
            self.round_number += 1
            self._prepare_round()
            return

        lines = []
        if self.seed_string and len(self.round_scores) > 1:
            lines.extend(
                [
                    "=" * 60,
                    "  FINAL SESSION SUMMARY",
                    f'     Seed: "{self.seed_string}" | Difficulty: {self.difficulty.upper()}',
                    "=" * 60,
                ]
            )
            for index, (score, species) in enumerate(self.round_scores, 1):
                lines.append(f"  Round {index}: {score:3d} pts - {species}")
            average = self.cumulative_score / len(self.round_scores)
            lines.extend(
                [
                    "-" * 60,
                    f"  TOTAL: {self.cumulative_score} points across "
                    f"{len(self.round_scores)} rounds",
                    f"  AVERAGE: {average:.1f} points per round",
                    "=" * 60,
                    "",
                ]
            )
        lines.extend(
            [
                "  Thanks for playing Taxonomica!",
                "",
                "  Press Enter to start over.",
            ]
        )
        self.state = "ended"
        self.screen = "\n".join(lines)
        self.prompt = "  Press Enter:"

    def _append_to_screen(self, text: str) -> str:
        return join_sections(self.screen, "", text)


def prune_terminal_sessions() -> None:
    now = time.time()
    expired_ids = [
        session_id
        for session_id, terminal_session in terminal_sessions.items()
        if now - terminal_session.updated_at > SESSION_TTL_SECONDS
    ]
    for session_id in expired_ids:
        del terminal_sessions[session_id]


def current_terminal_session() -> TerminalSession:
    prune_terminal_sessions()
    session_id = browser_session.get("terminal_session_id")
    if not session_id or session_id not in terminal_sessions:
        session_id = secrets.token_urlsafe(16)
        browser_session["terminal_session_id"] = session_id
        terminal_sessions[session_id] = TerminalSession(get_runtime_data())
    return terminal_sessions[session_id]


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/health")
def health() -> Any:
    return jsonify(
        {
            "status": "ok",
            "runtime_loaded": runtime_data is not None,
            "runtime_db_mode": "in-memory" if WEB_IN_MEMORY_DB else "disk",
            "runtime_db_path": str(runtime_data.db_path) if runtime_data is not None else None,
            "difficulty_views_loaded": sorted(difficulty_data),
            "active_terminal_sessions": len(terminal_sessions),
        }
    )


@app.route("/api/session")
def session_snapshot() -> Any:
    return jsonify(current_terminal_session().snapshot())


@app.route("/api/command", methods=["POST"])
def command() -> Any:
    data = request.get_json(silent=True) or {}
    command_text = str(data.get("command", ""))
    return jsonify(current_terminal_session().handle(command_text))


@app.route("/api/reset", methods=["POST"])
def reset() -> Any:
    terminal_session = current_terminal_session()
    terminal_session.reset()
    return jsonify(terminal_session.snapshot())


def find_available_port(host: str, preferred_port: int, attempts: int = 20) -> int:
    """Return the preferred port, or the next open port after it."""
    for port in range(preferred_port, preferred_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"No open port found from {preferred_port} to {preferred_port + attempts - 1}")


if __name__ == "__main__":
    host = os.environ.get("TAXONOMICA_WEB_HOST", "127.0.0.1")
    preferred_port = int(os.environ.get("TAXONOMICA_WEB_PORT", "8080"))
    port = find_available_port(host, preferred_port)

    print("\n" + "=" * 50)
    print("Starting Taxonomica Web Terminal...")
    print("=" * 50)
    if port != preferred_port:
        print(f"Port {preferred_port} is busy; using {port} instead.")
    print(f"Runtime DB mode: {'in-memory' if WEB_IN_MEMORY_DB else 'disk'}")
    print(f"Visit: http://{host}:{port}")
    print(f"Health check: http://{host}:{port}/health")
    print("=" * 50 + "\n")
    app.run(debug=True, port=port, host=host, use_reloader=False)
