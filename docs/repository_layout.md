# Repository Layout

This repo is organized around the terminal game and the taxonomy data loaders it needs.

## Primary Code

- `play.py` is the source-checkout launcher for the game.
- `src/taxonomica/` contains the installable Python package.
- `src/taxonomica/game/` contains the command-line game runtime.
- `src/taxonomica/game/engine.py` owns the terminal game state and gameplay loop.
- `src/taxonomica/game/cli.py` loads local datasets and starts rounds.
- `src/taxonomica/game/text.py`, `selection.py`, `prompts.py`, and `titles.py` hold reusable game helpers.
- `src/taxonomica/game/resources/rank_titles.json` contains score title data used by the game.
- `src/taxonomica/coldp.py` reads Catalogue of Life Data Package archives.
- `src/taxonomica/coldp_profile.py` provides memory-light streaming summaries for large ColDP archives.
- `src/taxonomica/coldp_sqlite.py` builds and queries lazy SQLite indexes for ColDP archives.
- `src/taxonomica/coldp_tree.py` builds experimental trees from ColDP parent IDs.
- `src/taxonomica/candidate_tree.py` builds derived gameplay-tree SQLite files from Wikidata ColDP and GBIF.

## Runnable Scripts

- `examples/` contains exploratory and demo scripts.
- `examples/taxonomica_game.py` is kept as a compatibility launcher, but new docs should point to `python play.py`.
- `examples/build_coldp_tree.py` streams a ColDP profile by default, with an opt-in full tree mode.
- `examples/build_candidate_tree.py` assembles and summarizes the initial article-backed seven-rank candidate tree.
- `examples/explore_coldp_sqlite.py` browses a ColDP SQLite index lazily.
- After `pip install -e .`, `taxonomica` and `python -m taxonomica.game` also launch the game from the current working directory.
- `utilities/` contains data-building and analysis utilities, especially scripts that fetch or process external datasets.
- `web/` contains the experimental Flask interface. It is not the main development focus right now, but it should keep importing shared game helpers where practical.

## Data Directories

- `backbone/` should contain the extracted GBIF Backbone Taxonomy files.
- `wikipedia-en-dwca/` should contain the extracted Wikipedia DwC-A files.
- `data/coldp/` can contain downloaded ColDP ZIP archives such as `wikidata.zip` and `wikispecies.zip`.
- `data/candidate_trees/` contains generated SQLite candidate trees for coverage audits.
- `data/` and `utilities/data/` contain generated or downloaded support data for utility scripts.

Large downloaded datasets are expected to live outside the package code and are loaded from the repository root when running `play.py`.

## Development Conventions

- Put reusable package logic under `src/taxonomica/`.
- Keep one-off exploration under `examples/`.
- Keep dataset-building scripts under `utilities/`.
- Prefer adding small helpers under `src/taxonomica/game/` instead of growing the launcher or CLI module.
- Keep `web/` changes light unless web development becomes active again.
