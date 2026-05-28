# Data Assembly Workflow

This document records the current data sources and repeatable steps used to
build Taxonomica's derived gameplay data.

## Goals

The derived dataset should favor gameplay quality over raw taxonomy coverage:

- Species must have a complete seven-rank path:
  `kingdom -> phylum -> class -> order -> family -> genus -> species`.
- Species must have an English Wikipedia article target.
- Species without usable extracted article text will be culled later.
- Parent taxa should stay in the tree only when they lead to playable species.

## Source Data

### GBIF Backbone

Local path:

```text
backbone/
```

Main file used:

```text
backbone/Taxon.tsv
```

Role:

- Supplies accepted species records.
- Supplies the seven major ranks used for navigation.
- Resolves some candidate rows through `acceptedNameUsageID`.

### Wikidata ColDP

Local path:

```text
data/coldp/wikidata.zip
```

Role:

- Supplies Wikidata taxon rows.
- Supplies English Wikipedia article URLs from ColDP `remarks`.
- Supplies GBIF IDs from ColDP `alternativeID`.

The current candidate build scans `NameUsage.tsv` inside this archive and keeps
accepted species rows with English Wikipedia article URLs.

### Wikispecies ColDP

Local path:

```text
data/coldp/wikispecies.zip
```

Role:

- Useful for taxonomy experiments and comparing source coherence.
- Not currently used for the candidate gameplay tree because the local ColDP
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
data/enwiki-20260501-pages-articles-multistream.xml.bz2
data/enwiki-20260501-pages-articles-multistream-index.txt.bz2
data/enwiki-20260501-md5sums.txt
```

Relevant checksums from `data/enwiki-20260501-md5sums.txt`:

```text
91ebaa5ef7a221897300c64dc33a0754  enwiki-20260501-pages-articles-multistream.xml.bz2
ad73b5495de935b74df4fb97416b9cd6  enwiki-20260501-pages-articles-multistream-index.txt.bz2
```

Verify downloads on macOS with:

```bash
md5 -r data/enwiki-20260501-pages-articles-multistream.xml.bz2
md5 -r data/enwiki-20260501-pages-articles-multistream-index.txt.bz2
```

## Generated Artifacts

### Candidate Tree

Build or summarize the current candidate tree:

```bash
python examples/build_candidate_tree.py --force
python examples/build_candidate_tree.py
```

Output:

```text
data/candidate_trees/wikidata-gbif-candidates.sqlite
```

Current summary:

```text
Article-backed rows:           308,995
Unique accepted species:       302,850
Duplicate species rows:          6,145
Parent taxa nodes:              54,381
Total tree nodes:              357,231
Candidate edges:               357,223
```

Notes:

- `Article-backed rows` counts candidate rows with distinct Wikipedia URLs.
- `Unique accepted species` counts accepted GBIF species nodes after synonym or
  accepted-name redirects are collapsed.
- The candidate tree is path-keyed, so homonymous taxa are not accidentally
  merged across different parent paths.

### Wikipedia Target Titles

Export page titles from the candidate tree:

```bash
python utilities/export_wikipedia_targets.py
```

Outputs:

```text
data/wikipedia_targets/enwiki-20260501-candidate-titles.txt
data/wikipedia_targets/enwiki-20260501-candidate-pages.jsonl
data/wikipedia_targets/enwiki-20260501-candidate-manifest.json
```

Current summary:

```text
Candidate rows:                308,995
Target page titles:            308,995
Invalid URL rows:                    0
Duplicate title groups:              0
```

`candidate-titles.txt` contains one MediaWiki dump title per line, using spaces
as they appear in XML `<title>` elements. `candidate-pages.jsonl` stores the
join metadata needed to connect extracted article text back to Wikidata IDs,
GBIF IDs, accepted species, and seven-rank paths.

We preserve all article-backed rows at this stage, even when multiple candidate
rows collapse to the same accepted GBIF species. The extraction and quality
filtering phase can decide which article, if any, should represent that species.

## Remaining Steps

### Description Extraction

Spot-check extraction from the Wikipedia dump:

```bash
python utilities/extract_wikipedia_descriptions.py \
  --output data/wikipedia_targets/spot-check-descriptions.jsonl
```

This uses the multistream index to seek directly to the bzip2 member containing
each requested page, rather than scanning the entire 25 GB dump. By default it
checks a small mixed set:

```text
Aa achalensis
Homo sapiens
Lion
Monarch butterfly
? Nycticebus linglom
```

The extractor currently:

- Finds page offsets in
  `data/enwiki-20260501-pages-articles-multistream-index.txt.bz2`.
- Decompresses only the relevant multistream chunks from
  `data/enwiki-20260501-pages-articles-multistream.xml.bz2`.
- Extracts page ID, revision ID, timestamp, raw lead wikitext, and cleaned lead
  text.
- Follows one redirect hop by default, so `Homo sapiens` resolves to `Human`
  while retaining the original candidate species metadata.
- Joins extracted pages back to `candidate_species` records, including GBIF ID,
  Wikidata ID, accepted species, and seven-rank path.

For a deterministic sample from the target list:

```bash
python utilities/extract_wikipedia_descriptions.py --sample 25
```

For hand-picked titles:

```bash
python utilities/extract_wikipedia_descriptions.py \
  --title "Canis lupus" \
  --title "Wolf" \
  --title "Escherichia coli"
```

For a mixed random audit of species plus parent taxa:

```bash
python utilities/spot_check_wikipedia_matching.py \
  --total 100 \
  --balanced-parent-ranks \
  --output data/wikipedia_targets/random-taxa-spot-check.jsonl
```

This samples explicit species article targets plus parent taxa that are matched
by exact Wikipedia title. Parent taxa do not yet have Wikidata sitelink targets
in the candidate tree, so this audit measures a weaker name-based matching
strategy for those nodes. The audit also tries a conservative parent-title
alias for GBIF-style suffixes such as `Firmicutes_D -> Firmicutes`; alias
matches are reported separately from exact matches.

The cleaner is intentionally lightweight for now. It removes infoboxes,
references, categories, and basic wikitext markup, and preserves useful simple
templates such as `convert` and `gloss`. A full production pass should still
record raw wikitext alongside cleaned text so that cleaning rules can be
improved without re-reading the full dump.

### Full Description Database

Dry-run the full matching plan:

```bash
python utilities/build_wikipedia_description_db.py --dry-run
```

The dry run loads all candidate species and parent taxa, scans the compressed
Wikipedia multistream index once, resolves exact and alias page-title matches,
and reports how many bzip2 stream offsets a full extraction would touch.

Current dry-run summary:

```text
Targets loaded:                    363,376
Matched targets:                   360,954  (99.3%)
Unmatched targets:                   2,422
Alias-matched targets:                  29
Unique matched page titles:        358,935
Unique extraction offsets:         107,835
Offset coverage:                     42.1%
Matched-title popularity rows:     232,695
```

The script can also build the assembled SQLite database:

```bash
python utilities/build_wikipedia_description_db.py --force
```

Output:

```text
data/assembled/taxonomica-20260501.sqlite
```

Planned tables include:

- `taxon_targets`: species and parent taxa, title matches, path metadata,
  optional pageview/backlink counts.
- `wikipedia_pages`: extracted page text, revision metadata, word count,
  description length, multimedia count, redirect metadata, optional popularity
  counts.
- `taxon_descriptions`: final target-to-description mapping.
- `metadata`: source files, dump date, and assembly counts.

For now, a matched page is considered usable regardless of word count. We still
store word count and description length so future difficulty heuristics can
prefer richer pages without forcing us to re-read the Wikipedia dump.

## Remaining Steps

1. Build the full description extraction pass over
   `enwiki-20260501-pages-articles-multistream.xml.bz2`.
2. Keep pages whose XML title appears in
   `data/wikipedia_targets/enwiki-20260501-candidate-titles.txt`.
3. Store extracted descriptions in a SQLite database keyed by requested title
   and resolved title.
4. Join descriptions back to `candidate_species`.
5. Cull candidate species without usable article text.
6. Write the final playable tree and description database.

Open questions:

- Whether to keep the best article per accepted GBIF species or allow multiple
  synonym/article targets until gameplay selection.
- Whether parent taxa descriptions should be resolved through Wikidata sitelinks,
  English Wikipedia exact-title lookup, or a separate parent-taxon target table.
- What minimum description quality thresholds should be used before culling.
