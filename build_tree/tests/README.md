# Build Tree Tests And Audits

These scripts are not unit tests in the package-test sense. They are repeatable
data audits used while evaluating source quality and matching behavior.

```text
build_coldp_tree.py              Profile or index a ColDP archive.
explore_coldp_sqlite.py          Browse a generated ColDP SQLite index.
spot_check_wikipedia_matching.py Sample candidate taxa and test Wikipedia matching.
```

Use these when validating a new raw data download, checking source connectedness,
or spot-checking title and description extraction before rebuilding the full
assembled database.

