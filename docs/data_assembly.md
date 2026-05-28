# Data Assembly Workflow

This document records the current source data and repeatable steps used to
build Taxonomica's derived gameplay database.

## Goals

The derived dataset should favor gameplay quality over raw taxonomy coverage:

- Species should have a complete seven-rank path:
  `kingdom -> phylum -> class -> order -> family -> genus -> species`.
- Species should have an English Wikipedia article target.
- Parent taxa should stay in the tree only when they lead to playable species.
- Article text should be extracted from a recent English Wikipedia dump.
- Richness signals such as word count, description length, multimedia count,
  and pageviews should be stored for future difficulty heuristics.

For now, matched articles are considered usable regardless of word count. The
quality fields are stored so later difficulty and culling rules can be changed
without re-reading the full Wikipedia dump.

## Raw Data Sources

### GBIF Backbone

Source:

```text
https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c
```

Download the GBIF Backbone Taxonomy in Simple format, extract it, and place the
files under:

```text
assets/raw/gbif-backbone/
```

Main file used:

```text
assets/raw/gbif-backbone/Taxon.tsv
```

Role:

- Supplies accepted species records.
- Supplies the seven major ranks used for navigation.
- Resolves some candidate rows through `acceptedNameUsageID`.

### Wikidata ColDP

Source/tooling:

```text
https://github.com/CatalogueOfLife/coldp-generator
```

Expected local path:

```text
assets/raw/coldp/wikidata.zip
```

Role:

- Supplies Wikidata taxon rows.
- Supplies English Wikipedia article URLs from ColDP `remarks`.
- Supplies GBIF IDs from ColDP `alternativeID`.

The candidate build scans `NameUsage.tsv` inside this archive and keeps
accepted species rows with English Wikipedia article URLs.

### Wikispecies ColDP

Expected local path:

```text
assets/raw/coldp/wikispecies.zip
```

Role:

- Useful for taxonomy experiments and comparing source coherence.
- Not currently used for the final candidate gameplay tree because the local
  archive does not expose English Wikipedia article URLs.

### English Wikipedia Dump

Current dump date:

```text
20260501
```

Download URLs:

```text
https://dumps.wikimedia.org/enwiki/20260501/enwiki-20260501-pages-articles-multistream.xml.bz2
https://dumps.wikimedia.org/enwiki/20260501/enwiki-20260501-pages-articles-multistream-index.txt.bz2
https://dumps.wikimedia.org/enwiki/20260501/enwiki-20260501-md5sums.txt
```

Expected local paths:

```text
assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream.xml.bz2
assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream-index.txt.bz2
assets/raw/wikipedia-dumps/enwiki-20260501-md5sums.txt
```

Relevant checksums from `assets/raw/wikipedia-dumps/enwiki-20260501-md5sums.txt`:

```text
91ebaa5ef7a221897300c64dc33a0754  enwiki-20260501-pages-articles-multistream.xml.bz2
ad73b5495de935b74df4fb97416b9cd6  enwiki-20260501-pages-articles-multistream-index.txt.bz2
```

Verify downloads on macOS with:

```bash
md5 -r assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream.xml.bz2
md5 -r assets/raw/wikipedia-dumps/enwiki-20260501-pages-articles-multistream-index.txt.bz2
```

### Optional Popularity Metrics

Local path:

```text
assets/raw/legacy/species.db
```

Role:

- Supplies legacy article `pageview_count` values.
- Also has a `backlink_count` column, but the current local copy stores zeros.

The description database builder indexes both underscore and space-normalized
versions of each title for matching, so the number of title keys printed during
assembly is larger than the number of source rows.

## Generated Artifacts

### Candidate Tree

Build or summarize the current candidate tree:

```bash
python build_tree/build_candidate_tree.py --force
python build_tree/build_candidate_tree.py
```

Output:

```text
assets/generated/candidate_trees/wikidata-gbif-candidates.sqlite
```

Current summary:

```text
Complete species paths:      308,995
Parent taxa nodes:            54,381
Total playable nodes:        363,376
Path-keyed tree nodes:       357,231
Unique taxon labels:         356,852
Candidate edges:             357,223
Unique accepted species:     302,850
```

Notes:

- `Complete species paths` counts candidate rows with distinct Wikipedia URLs.
- `Unique accepted species` counts accepted GBIF species nodes after synonym or
  accepted-name redirects are collapsed.
- The candidate tree is path-keyed, so homonymous taxa are not accidentally
  merged across different parent paths.

### Wikipedia Target Titles

Export page titles from the candidate tree:

```bash
python build_tree/export_wikipedia_targets.py
```

Outputs:

```text
assets/generated/wikipedia_targets/enwiki-20260501-candidate-titles.txt
assets/generated/wikipedia_targets/enwiki-20260501-candidate-pages.jsonl
assets/generated/wikipedia_targets/enwiki-20260501-candidate-manifest.json
```

Current summary:

```text
Candidate rows:              308,995
Target page titles:          308,995
Invalid URL rows:                  0
Duplicate title groups:            0
```

`candidate-titles.txt` contains one MediaWiki dump title per line, using spaces
as they appear in XML `<title>` elements. `candidate-pages.jsonl` stores the
join metadata needed to connect extracted article text back to Wikidata IDs,
GBIF IDs, accepted species, and seven-rank paths.

### Description Extraction Spot Checks

Run a small extraction check against the Wikipedia dump:

```bash
python build_tree/extract_wikipedia_descriptions.py \
  --output assets/generated/wikipedia_targets/spot-check-descriptions.jsonl
```

For a deterministic sample from the target list:

```bash
python build_tree/extract_wikipedia_descriptions.py --sample 25
```

For hand-picked titles:

```bash
python build_tree/extract_wikipedia_descriptions.py \
  --title "Canis lupus" \
  --title "Wolf" \
  --title "Escherichia coli"
```

For a mixed random audit of species plus parent taxa:

```bash
python build_tree/tests/spot_check_wikipedia_matching.py \
  --total 100 \
  --balanced-parent-ranks \
  --output assets/generated/wikipedia_targets/random-taxa-spot-check.jsonl
```

The spot-check tools use the multistream index to seek directly to the bzip2
member containing each requested page, rather than scanning the full 25 GB dump.
The parent-taxon audit uses exact title matching plus conservative aliases such
as `Firmicutes_D -> Firmicutes`.

The cleaner is intentionally lightweight for now. It removes infoboxes,
references, categories, and basic wikitext markup, and preserves useful simple
templates such as `convert` and `gloss`. The assembled database stores raw lead
wikitext alongside cleaned text so cleaning rules can be improved later without
re-reading the full dump.

### Full Description Database

Dry-run the full matching plan:

```bash
python build_tree/build_wikipedia_description_db.py --dry-run
```

The dry run loads all candidate species and parent taxa, scans the compressed
Wikipedia multistream index once, resolves exact and alias page-title matches,
and reports how many bzip2 stream offsets a full extraction would touch.

Current dry-run summary:

```text
Targets loaded:              363,376
Matched targets:             360,954  (99.3%)
Unmatched targets:             2,422
Alias-matched targets:            29
Unique matched page titles:  358,935
Unique extraction offsets:   107,835
Offset coverage:               42.1%
Matched-title popularity rows: 232,695
```

Build the assembled SQLite database:

```bash
python build_tree/build_wikipedia_description_db.py --force
```

Output:

```text
assets/generated/assembled/taxonomica-20260501.sqlite
```

The database contains:

- `metadata`: source files, dump date, target counts, and index counts.
- `taxon_targets`: species and parent taxa, title matches, path metadata,
  optional pageview/backlink counts.
- `wikipedia_pages`: extracted page text, revision metadata, word count,
  description length, multimedia count, redirect metadata, optional popularity
  counts.
- `taxon_descriptions`: final target-to-description mapping.

Current assembled database summary:

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

The full extraction touched `107,835` unique bzip2 stream offsets out of
`255,907` offsets in the multistream index. Each offset represents one
compressed member containing many pages, so this is the number of compressed
chunks read, not the number of matched pages.

### Runtime Game Database

Derive the slim tree and description database used by `python play.py`:

```bash
python build_tree/build_runtime_db.py --force
```

Outputs:

```text
assets/generated/runtime/taxonomica-runtime-20260501.sqlite
assets/game/taxonomica-runtime-20260501.sqlite.gz
```

The runtime database is built from the assembled `build_tree` output. It omits
build-only fields such as raw wikitext and dump offsets, and keeps only the
pruned playable tree, species descriptions, and difficulty signals needed by
the game.

## Rebuild Checklist

1. Download or regenerate `assets/raw/coldp/wikidata.zip`.
2. Download the GBIF Backbone Simple archive and place `Taxon.tsv` under
   `assets/raw/gbif-backbone/`.
3. Download the matching English Wikipedia XML dump, multistream index, and
   checksum file.
4. Verify the Wikipedia dump checksums.
5. Run `python build_tree/build_candidate_tree.py --force`.
6. Run `python build_tree/export_wikipedia_targets.py`.
7. Optionally run extraction and random-matching spot checks.
8. Run `python build_tree/build_wikipedia_description_db.py --dry-run`.
9. Run `python build_tree/build_wikipedia_description_db.py --force`.
10. Run `python build_tree/build_runtime_db.py --force`.
11. Inspect assembled and runtime counts before using the database for gameplay.

## Open Questions

- Whether to keep the best article per accepted GBIF species or allow multiple
  synonym/article targets until gameplay selection.
- Whether parent taxa descriptions should eventually be resolved through
  Wikidata sitelinks rather than exact-title lookup.
- What description quality thresholds should be used before culling species or
  weighting difficulty.
