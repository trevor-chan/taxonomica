# Repository Layout

This repo is organized around the terminal game, reusable taxonomy loaders, and
the reproducible data-assembly pipeline used to build gameplay databases.

## Primary Code

- `play.py` is the source-checkout launcher for the game.
- `taxonomica/` contains the installable Python package.
- `taxonomica/game/` contains the command-line game runtime.
- `taxonomica/game/engine.py` owns the terminal game state and gameplay loop.
- `taxonomica/game/cli.py` loads the runtime database and starts rounds.
- `taxonomica/game/text.py`, `selection.py`, `prompts.py`, and `titles.py`
  hold reusable game helpers.
- `taxonomica/game/resources/rank_titles.json` contains score title data
  used by the game.
- `taxonomica/taxonomy.py` contains the game-facing path-keyed tree model.
- `taxonomica/runtime_db.py` loads the slim playable SQLite asset.
- `taxonomica/coldp.py` reads Catalogue of Life Data Package archives.
- `taxonomica/coldp_profile.py` provides memory-light streaming summaries
  for large ColDP archives.
- `taxonomica/coldp_sqlite.py` builds and queries lazy SQLite indexes for
  ColDP archives.
- `taxonomica/coldp_tree.py` builds experimental trees from ColDP parent IDs.
- `taxonomica/candidate_tree.py` builds derived gameplay-tree SQLite files
  from Wikidata ColDP and GBIF.

## Build Tree Pipeline

- `build_tree/` contains the scripts used to construct the current derived data
  products.
- `build_tree/README.md` is the short runbook for the data pipeline.
- `build_tree/build_candidate_tree.py` assembles and summarizes the
  article-backed seven-rank candidate tree.
- `build_tree/export_wikipedia_targets.py` exports candidate English Wikipedia
  page titles for dump extraction.
- `build_tree/extract_wikipedia_descriptions.py` spot-checks description
  extraction from English Wikipedia XML dumps.
- `build_tree/build_wikipedia_description_db.py` assembles the final candidate
  description SQLite database.
- `build_tree/build_runtime_db.py` derives the slim playable runtime database
  and compressed `assets/game/` copy.
- `build_tree/tests/` contains repeatable data audits and source-health checks,
  not package unit tests.
- `build_tree/tests/build_coldp_tree.py` streams ColDP profiles, builds optional
  SQLite indexes, and reports connectedness.
- `build_tree/tests/explore_coldp_sqlite.py` browses a ColDP SQLite index lazily.
- `build_tree/tests/spot_check_wikipedia_matching.py` audits random species and
  parent-taxon Wikipedia matching.

## Experimental Scripts

- `experimental/examples/` contains exploratory and demo scripts unrelated to
  the core data assembly pipeline.
- `experimental/examples/taxonomica_game.py` is kept as a compatibility
  launcher, but new docs should point to `python play.py`.
- After `pip install -e .`, `taxonomica` and `python -m taxonomica.game` also
  launch the game from the current working directory.
- `experimental/utilities/` contains auxiliary or legacy utilities that are not
  part of the main tree-building pipeline.
- `experimental/web/` contains the experimental Flask interface. It is not the
  main development focus right now, but it should keep importing shared game
  helpers where practical.

## Data Directories

- `assets/game/` contains committed playable runtime assets, usually compressed
  SQLite databases.
- `assets/raw/gbif-backbone/` contains extracted GBIF Backbone Taxonomy files.
- `assets/raw/wikipedia-dwca/` contains the older Wikipedia DwC-A files used by
  experimental scripts.
- `assets/raw/coldp/` can contain downloaded ColDP ZIP archives such as
  `wikidata.zip` and `wikispecies.zip`.
- `assets/raw/wikipedia-dumps/` contains English Wikipedia XML dump inputs.
- `assets/raw/legacy/` contains optional legacy support data such as
  `species.db`.
- `assets/generated/candidate_trees/` contains generated SQLite candidate trees
  for coverage audits.
- `assets/generated/wikipedia_targets/` contains generated page-title target
  lists and spot-check outputs for Wikipedia dump extraction.
- `assets/generated/assembled/` contains generated final or near-final SQLite
  data products.
- `assets/generated/runtime/` contains decompressed runtime databases and other
  local runtime outputs.

Large downloaded and generated datasets stay under ignored `assets/raw/` and
`assets/generated/`. The game reads `assets/game/` by default.

## Development Conventions

- Put reusable package logic under `taxonomica/`.
- Keep one-off exploration under `experimental/examples/`.
- Keep reproducible data-assembly scripts under `build_tree/`.
- Keep source-health checks and data audits under `build_tree/tests/`.
- Prefer adding small helpers under `taxonomica/game/` instead of growing
  the launcher or CLI module.
- Keep `experimental/web/` changes light unless web development becomes active
  again.
