# Build Tree Pipeline

This directory contains the scripts used to assemble Taxonomica's current
candidate gameplay dataset from GBIF, Wikidata ColDP, and an English Wikipedia
article dump.

The scripts are intentionally kept together because they form one repeatable
data pipeline. Experimental probes, audits, and source-health checks live in
`build_tree/tests/`.

## Inputs

Expected local inputs from the repository root:

```text
assets/raw/gbif-backbone/Taxon.tsv
assets/raw/coldp/wikidata.zip
assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream.xml.bz2
assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream-index.txt.bz2
assets/raw/wikipedia-dumps/enwiki-20260501-md5sums.txt
assets/raw/legacy/species.db
```

`assets/raw/legacy/species.db` is optional. When present, it contributes legacy
`pageview_count` and `backlink_count` fields. In the current copy, pageviews are
available for many pages while backlink counts are zero.

## Rebuild Steps

Build the seven-rank, article-backed candidate tree:

```bash
python build_tree/build_candidate_tree.py --force
```

Export the candidate species page targets:

```bash
python build_tree/export_wikipedia_targets.py
```

Verify the Wikipedia dump checksums on macOS:

```bash
md5 -r assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream.xml.bz2
md5 -r assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream-index.txt.bz2
```

Dry-run the full target matching plan:

```bash
python build_tree/build_wikipedia_description_db.py --dry-run
```

Build the assembled description database:

```bash
python build_tree/build_wikipedia_description_db.py --force
```

The current default output is:

```text
assets/generated/assembled/taxonomica-20260501.sqlite
```

Build the slim playable runtime database and compressed game asset:

```bash
python build_tree/build_runtime_db.py --force
```

The compressed runtime asset is written to:

```text
assets/game/taxonomica-runtime-20260501.sqlite.gz
```

The runtime database stores the pruned playable tree, playable species
descriptions, and any matched parent-taxon descriptions needed for in-game info
views. Difficulty choices are currently placeholders and do not affect species
selection.

## Useful Audits

Run a small direct extraction spot check:

```bash
python build_tree/extract_wikipedia_descriptions.py --sample 25
```

Run a mixed random audit of species and parent taxa:

```bash
python build_tree/tests/spot_check_wikipedia_matching.py \
  --total 100 \
  --balanced-parent-ranks
```

Profile a ColDP archive without building a full in-memory tree:

```bash
python build_tree/tests/build_coldp_tree.py wikispecies --mode sqlite --connectedness
```

Browse an existing ColDP SQLite index:

```bash
python build_tree/tests/explore_coldp_sqlite.py wikispecies
```

## Current Outputs

The current assembled database was built from the 2026-05-01 English Wikipedia
dump and contains:

```text
Taxon targets:              363,376
Matched targets:            360,954
Unmatched targets:            2,422
Wikipedia pages:            361,818
Extracted pages OK:         361,751
Empty extracted pages:           67
Matched descriptions:       360,887
Pages with multimedia:      290,734
Targets with pageviews:     232,671
```
