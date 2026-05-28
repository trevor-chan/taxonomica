# ColDP Data Experiments

Taxonomica can now read Catalogue of Life Data Package archives as an
experimental replacement candidate for the older Wikipedia DwC-A taxonomy
metadata.

## Expected Files

Put downloaded archives under:

```text
data/coldp/
├── wikidata.zip
└── wikispecies.zip
```

The reader also accepts extracted folders, as long as they contain
`NameUsage.tsv`.

## Quick Checks

Build a streaming report for the smaller Wikispecies archive:

```bash
python examples/build_coldp_tree.py wikispecies
```

Build a streaming report for the larger Wikidata archive:

```bash
python examples/build_coldp_tree.py wikidata
```

The default mode does not create a full tree. It scans `NameUsage.tsv`, counts
ranks and statuses, and checks whether parent IDs resolve to rows in the same
filtered dataset.

For a quick parser smoke test without reading a whole archive:

```bash
python examples/build_coldp_tree.py wikidata --limit 100000
```

For small archives, or intentionally limited tests, you can still build the
full in-memory tree:

```bash
python examples/build_coldp_tree.py wikispecies --mode tree
python examples/build_coldp_tree.py wikidata --mode tree --limit 100000 --no-vernacular
```

Avoid full `--mode tree` runs on the complete Wikidata archive until we have a
SQLite-backed or otherwise lazy tree explorer.

## SQLite Index

Build or inspect a lazy SQLite index:

```bash
python examples/build_coldp_tree.py wikidata --mode sqlite
```

For a bounded test index:

```bash
python examples/build_coldp_tree.py wikidata --mode sqlite --limit 100000
```

By default, limited indexes use names like
`data/coldp/wikidata-limit-100000.sqlite` so they are not confused with a full
`data/coldp/wikidata.sqlite` index. Indexes built with `--include-non-accepted`
use an `-all` suffix by default. Pass `--force` to rebuild an existing index.

The SQLite backend stores compact `taxa`, `vernacular_names`, and optional
`media` tables. Tree exploration should query immediate children and parent
paths from SQLite instead of constructing a full Python object graph.

Browse an existing index:

```bash
python examples/explore_coldp_sqlite.py wikispecies
python examples/explore_coldp_sqlite.py wikidata --limit 100000
```

Measure whether species lineages reach the major gameplay ranks:

```bash
python examples/build_coldp_tree.py wikispecies --mode sqlite --connectedness
```

This reports how many species reach each major rank and how many have a full
`kingdom -> phylum -> class -> order -> family -> genus` path. A high
parent-link resolution score does not necessarily mean high major-rank
connectedness, because many ColDP paths pass through unranked clades such as
`Monocots`, `Feloidea`, or `Bacteria`.

## Candidate Gameplay Tree

The first derived gameplay-tree script combines two sources:

- Wikidata ColDP contributes accepted species that already have English
  Wikipedia article URLs.
- GBIF Backbone contributes the complete seven-rank classification used for
  game navigation.

Build the candidate tree:

```bash
python examples/build_candidate_tree.py --force
```

This writes:

```text
data/candidate_trees/wikidata-gbif-candidates.sqlite
```

The database contains:

- `candidate_species`: selected species with a complete GBIF path and an English
  Wikipedia URL.
- `candidate_taxa`: path-keyed tree nodes. Node identity includes the full path
  so homonymous taxa are not accidentally merged.
- `candidate_edges`: parent/child links with descendant species counts.
- `rejection_summary`: reasons article-backed species were not selected.

To inspect an existing candidate database without rebuilding it:

```bash
python examples/build_candidate_tree.py
```

Useful smoke-test options:

```bash
python examples/build_candidate_tree.py --coldp-limit 10000 --force
python examples/build_candidate_tree.py --coldp-limit 10000 --gbif-limit 200000 --force
```

The output summary distinguishes article-backed rows, unique accepted species,
duplicate accepted-species mappings, parent taxa nodes, path-keyed tree nodes,
and unique taxon labels.

## What To Look For

- `Parent links resolved` should be high if the source has a coherent tree under the selected filters.
- `Root candidates` should be low relative to included rows.
- `ROOT CANDIDATES BY RANK` shows whether missing links are mostly harmless top-level clades or many low-level taxa.
- `LINEAGE CONNECTEDNESS` is the main game-readiness signal for the seven-rank navigation path.
- `Nodes with English Wikipedia URLs` currently comes from Wikidata remarks and is the likely bridge to article text.
- `build_candidate_tree.py` is the better early estimate of playable coverage,
  because it uses Wikidata for article URLs and GBIF for complete major-rank
  paths.

The ColDP archives do not include full Wikipedia prose descriptions. If the tree
quality is good, the next step is a separate article-text pipeline keyed by the
English Wikipedia URLs exposed by the Wikidata archive.
