"""Playable Taxonomica game package."""

from taxonomica.game.engine import TaxonomicaGame
from taxonomica.game.selection import get_seed_from_string, select_playable_species
from taxonomica.game.text import split_into_lines, split_into_sentences
from taxonomica.game.titles import get_rank_title, load_rank_titles

__all__ = [
    "TaxonomicaGame",
    "get_rank_title",
    "get_seed_from_string",
    "load_rank_titles",
    "select_playable_species",
    "split_into_lines",
    "split_into_sentences",
]
