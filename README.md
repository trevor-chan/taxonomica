# Taxonomica

Explore the tree of life.

## Overview

Taxonomica is an interactive game where you identify a mystery species by navigating through the taxonomic tree of life. Starting from a redacted Wikipedia description, you work your way through Kingdom → Phylum → Class → Order → Family → Genus → Species to discover the hidden organism.

## Repository Layout

The main game now lives in the installable package under `src/taxonomica/game/`, with `play.py` as the source-checkout launcher. Exploratory scripts remain in `examples/`, data-building scripts live in `utilities/`, and the Flask interface in `web/` is currently experimental rather than the main development path.

See [docs/repository_layout.md](docs/repository_layout.md) for the working directory map and development conventions.

## Gameplay

When a game begins:

1. **A mystery species is selected** from over 2 million known organisms
2. **A redacted description appears** — all references to the species name, common name, and taxonomic groups are blocked out
3. **You navigate the tree** — starting at Kingdom (Animalia? Plantae? Fungi?) and working down through each taxonomic level
4. **More clues are revealed** — with each guess (right or wrong), additional lines of the description appear
5. **Your score is tracked** — wrong guesses add to your score (lower is better!)

## Installation

### Prerequisites

You'll need:
- **Python 3.11 or newer** — [Download Python](https://www.python.org/downloads/)
- **About 2GB of disk space** for the taxonomy datasets

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

### Step 3: Download the Datasets

Taxonomica requires two datasets to run:

#### GBIF Backbone Taxonomy (Required)

1. Go to [GBIF Backbone Taxonomy](https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c)
2. Click "Download" and select "Simple" format
3. Extract the downloaded ZIP file
4. Place the extracted folder in the `taxonomica` directory and rename it to `backbone`

Your folder structure should look like:
```
taxonomica/
├── play.py
├── backbone/
│   ├── Taxon.tsv
│   ├── VernacularName.tsv
│   └── ...
├── src/
├── examples/
└── ...
```

#### Wikipedia Species Data (Required)

1. Download the Wikipedia Darwin Core Archive from [Wikipedia Species Pages](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Tree_of_Life/DwC-A)
2. Extract the ZIP file
3. Place the extracted folder in the `taxonomica` directory and rename it to `wikipedia-en-dwca`

Your folder structure should now include:
```
taxonomica/
├── play.py
├── backbone/
├── wikipedia-en-dwca/
│   ├── taxon.txt
│   ├── description.txt
│   └── ...
├── src/
├── examples/
└── ...
```

## Running the Game

Once everything is installed, start the game:

```bash
python play.py
```

If you installed the package in editable mode, you can also run `taxonomica` or `python -m taxonomica.game` from the repository root. The older `python examples/taxonomica_game.py` command still works as a compatibility launcher.


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
| **Easy** | Well-known species (top 1% by popularity) |
| **Medium** | Moderately known species (top 5%) |
| **Hard** | Less common species (top 25%) |
| **Expert** | Any species with a Wikipedia entry |

Popularity is estimated from Wikipedia data: description length, number of sections, presence of common names, and multimedia content.

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
python examples/explore_gbif_tree.py
```

This opens an interactive explorer where you can navigate through all kingdoms, phyla, classes, and more.

## Troubleshooting

### "ModuleNotFoundError: No module named 'taxonomica'"
Make sure you ran `pip install -e .` from the `taxonomica` directory.

### "FileNotFoundError: backbone/Taxon.tsv"
The GBIF Backbone dataset isn't installed. See [Step 3](#step-3-download-the-datasets).

### "No species found with Wikipedia entries"
The Wikipedia dataset isn't installed correctly. Make sure the `wikipedia-en-dwca` folder contains `taxon.txt` and `description.txt`.

### Game is slow to start
The first run loads millions of taxonomy records. This is normal and takes 1-2 minutes. Subsequent runs are faster.

## Data Sources

- **[GBIF Backbone Taxonomy](https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c)**: Comprehensive taxonomic classification of all known species
- **[Wikipedia Species Pages](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Tree_of_Life)**: Descriptions, common names, and multimedia from Wikipedia

## License

MIT

## Contributing

Contributions welcome! Feel free to:
- Add new rank titles to `src/taxonomica/game/resources/rank_titles.json`
- Report bugs or suggest features via GitHub Issues
- Submit pull requests for improvements
