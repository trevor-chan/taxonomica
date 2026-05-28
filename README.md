# Taxonomica

Explore the tree of life.

## Overview

Taxonomica is an interactive game where you identify a mystery species by navigating through the taxonomic tree of life. Starting from a redacted Wikipedia description, you work your way through Kingdom → Phylum → Class → Order → Family → Genus → Species to discover the hidden organism.

## Repository Layout

The main game lives in the installable package under `taxonomica/game/`, with
`play.py` as the source-checkout launcher. Reproducible data-building scripts
live in `build_tree/`, raw and generated data live under `assets/`, and
exploratory scripts, auxiliary utilities, and the Flask interface live in
`experimental/`.

See [docs/repository_layout.md](docs/repository_layout.md) for the working directory map and development conventions.

## Gameplay

When a game begins:

1. **A mystery species is selected** from the derived gameplay tree
2. **A redacted description appears** — all references to the species name, common name, and taxonomic groups are blocked out
3. **You navigate the tree** — starting at Kingdom (Animalia? Plantae? Fungi?) and working down through each taxonomic level
4. **More clues are revealed** — with each guess (right or wrong), additional lines of the description appear
5. **Your score is tracked** — wrong guesses add to your score (lower is better!)

## Installation

### Prerequisites

You'll need:
- **Python 3.11 or newer** — [Download Python](https://www.python.org/downloads/)
- The packaged runtime database under `assets/game/`, or raw assets if you want
  to rebuild the data pipeline

### Step 1: Download the Code

Open your terminal (Terminal on Mac, Command Prompt or PowerShell on Windows) and run:

```bash
# Clone the repository
git clone https://github.com/yourusername/taxonomica.git

# Navigate into the folder
cd taxonomica
```

Or download and extract the ZIP file from GitHub.

### Step 2: Install the Package in a project environment

It's recommended to first create a python environment to run the code in.

Conda: https://www.anaconda.com/docs/getting-started/miniconda/install
uv: https://github.com/astral-sh/uv 

Once in an environment, run
```bash
# Install taxonomica and its dependencies
pip install -e .
```

If you get a "pip not found" error, try `pip3 install -e .` instead.

### Step 3: Check Runtime Assets

Normal play uses the slim runtime database in `assets/game/`. If the asset is
compressed, the game decompresses it on first run into `assets/generated/runtime/`.

The playable folder structure should include:

```
taxonomica/
├── play.py
├── taxonomica/
├── assets/
│   └── game/
│       └── taxonomica-runtime-YYYYMMDD.sqlite.gz
├── build_tree/
├── experimental/
└── ...
```

Raw source datasets are only needed for rebuilds. Put downloaded GBIF,
Wikipedia dump, and ColDP inputs under `assets/raw/`; generated intermediate
outputs go under `assets/generated/`.

## Running the Game

Once everything is installed, start the game:

```bash
python play.py
```

If you installed the package in editable mode, you can also run `taxonomica` or
`python -m taxonomica.game` from the repository root. The older compatibility
launcher now lives at `python experimental/examples/taxonomica_game.py`.


### Controls

| Key | Action |
|-----|--------|
| `a-z` | Select an option (lowercase) |
| `I` + letter | View info about a taxon (e.g., `Ia` for info on option a) |
| `N` | Next page |
| `P` | Previous page |
| `S` | Cycle sort mode (by descendants / alphabetical / by rank) |
| `Q` | Quit game |

## Difficulty Levels

| Level | Description |
|-------|-------------|
| **Easy** | Placeholder; currently selects from all playable species |
| **Medium** | Placeholder; currently selects from all playable species |
| **Hard** | Placeholder; currently selects from all playable species |
| **Expert** | Placeholder; currently selects from all playable species |

The prompt remains in place so difficulty can be reintroduced once the new
runtime tree has its own ratings.

## Example Gameplay

```
====================================================================================================
  🌿 TAXONOMICA - Guess the Species! [EASY] 🌿
====================================================================================================

  Score: 2 wrong guesses | Progress: 3/7 ranks

----------------------------------------------------------------------------------------------------
  MYSTERY SPECIES DESCRIPTION:  (showing 5/42 lines)
----------------------------------------------------------------------------------------------------
  The ████████ is a large ███ native to the forests of central Africa. It is the closest
  living relative to humans, sharing approximately 98% of our DNA. Known for their
  intelligence, they use tools, have complex social structures, and can learn sign language.
  ...
----------------------------------------------------------------------------------------------------

  Choose the correct ORDER:  (5 guesses left, sorted: by rank)

    (a) Primates                       "Primates"               [order]       (741)
    (b) Carnivora                      "Carnivorans"            [order]       (612)
    (c) Rodentia                       "Rodents"                [order]       (495)
    ...
```

## Exploring the Tree (Without Playing)

Want to just browse the taxonomy tree? Run:

```bash
python experimental/examples/explore_gbif_tree.py
```

This opens an interactive explorer where you can navigate through all kingdoms, phyla, classes, and more.

To inspect the newer Catalogue of Life Data Package downloads, place
`wikidata.zip` and/or `wikispecies.zip` under `assets/raw/coldp/` and run:

```bash
python build_tree/tests/build_coldp_tree.py wikispecies
python build_tree/tests/build_coldp_tree.py wikidata
```

The default ColDP path is experimental and memory-light: it streams
`NameUsage.tsv`, reports parent-link health, and does not build a full in-memory
tree. Use `--mode tree` only for smaller archives or limited tests. See
[docs/coldp_data.md](docs/coldp_data.md) for the current workflow.

To build a lazy SQLite index for tree exploration:

```bash
python build_tree/tests/build_coldp_tree.py wikidata --mode sqlite
python build_tree/tests/explore_coldp_sqlite.py wikidata
```

To assemble the first article-backed, seven-rank candidate gameplay tree from
Wikidata ColDP plus the GBIF Backbone:

```bash
python build_tree/build_candidate_tree.py --force
```

This writes `assets/generated/candidate_trees/wikidata-gbif-candidates.sqlite` and reports
how many species have complete `kingdom -> phylum -> class -> order -> family ->
genus -> species` paths.

To assemble the current candidate description database from the English
Wikipedia multistream dump:

```bash
python build_tree/build_wikipedia_description_db.py --force
```

This writes `assets/generated/assembled/taxonomica-20260501.sqlite`.

To derive the slim playable runtime database and compressed game asset:

```bash
python build_tree/build_runtime_db.py --force
```

This writes `assets/game/taxonomica-runtime-20260501.sqlite.gz`.

Data-source and rebuild notes are tracked in
[docs/data_assembly.md](docs/data_assembly.md).

## Troubleshooting

### "ModuleNotFoundError: No module named 'taxonomica'"
Make sure you ran `pip install -e .` from the `taxonomica` directory.

### "No runtime database found"
Build or restore `assets/game/taxonomica-runtime-YYYYMMDD.sqlite.gz`, or run
`python build_tree/build_runtime_db.py --force` after building the assembled DB.

### "No species found with Wikipedia entries"
The runtime database may be missing playable description rows. Rebuild it from
the assembled DB and check the build summary.

### Game is slow to start
The first run may decompress the packaged runtime database. Subsequent runs use
the cached SQLite file under `assets/generated/runtime/`.

## Data Sources

- **[GBIF Backbone Taxonomy](https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c)**: Comprehensive taxonomic classification of all known species
- **[Wikipedia Species Pages](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Tree_of_Life)**: Descriptions, common names, and multimedia from Wikipedia
- **[Catalogue of Life Data Package](https://catalogueoflife.github.io/coldp/)**: Experimental newer taxonomy metadata from Wikidata and Wikispecies

## License

MIT

## Contributing

Contributions welcome! Feel free to:
- Add new rank titles to `taxonomica/game/resources/rank_titles.json`
- Report bugs or suggest features via GitHub Issues
- Submit pull requests for improvements
