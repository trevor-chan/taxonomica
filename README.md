# Taxonomica

Explore the tree of life.

## Overview

Taxonomica uses data from Wikipedia's species pages to create an interactive game where players guess organisms by navigating through taxonomic classifications (Kingdom → Phylum → Class → Order → Family → Genus → Species).

## Gameplay

A game of Taxonomica begins with the text (and optionally image) from a species page displayed. Any critical information (the species scientific name, vernacular name, and any taxonomic designations) will initially be redacted. The goal of the player is to make their way up the tree of life, beginning at the domain level, in order to determine the species. As they make their way up the tree, additional information will become available.

## Installation

```bash
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

## Data Source

This project uses a Darwin Core Archive extracted from English Wikipedia species pages. The dataset includes:

- **Taxonomic hierarchy**: Scientific names and classifications
- **Vernacular names**: Common names in multiple languages
- **Descriptions**: Wikipedia article summaries
- **Multimedia**: Images from Wikimedia Commons
- **Species profiles**: Extinction status and temporal ranges

## Usage

```python
from taxonomica.dwca import DarwinCoreArchive

# Load the archive
archive = DarwinCoreArchive("wikipedia-en-dwca")

# Access taxa
for taxon in archive.iter_taxa():
    print(f"{taxon.scientific_name} ({taxon.rank})")
```

## License

MIT

