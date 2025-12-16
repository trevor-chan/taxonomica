# Taxonomica

A taxonomy-based guessing game that lets you explore the tree of life through a 20-questions style experience focused on taxonomic groupings.

## Overview

Taxonomica uses data from Wikipedia's species pages to create an interactive game where players guess organisms by navigating through taxonomic classifications (Kingdom → Phylum → Class → Order → Family → Genus → Species).

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

