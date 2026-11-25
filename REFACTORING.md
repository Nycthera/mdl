# Code Layout

MDL keeps the command-line interface in `main.py` and groups implementation code by responsibility under `src/`.

```text
src/
├── archives/       # CBZ metadata, archive operations, and natural ordering
├── database/       # SQLite connections, schema, manga records, and run history
├── downloads/      # Single-image transfers, scheduling, and download support
├── network/        # URL safety, sessions, retries, and HTTP transfers
└── scrapers/       # Source-specific chapter discovery and image URL extraction
```

## Package responsibilities

- `src/database/core.py` owns database paths, connections, schema constants, and shared record helpers.
- `src/database/schema.py` creates and migrates database tables.
- `src/database/library.py` reads and writes tracked manga records and library entries.
- `src/database/history.py` records download runs and page outcomes.
- `src/network/` separates URL validation, session configuration, retry policy, and HTTP transfers.
- `src/downloads/` separates single-image downloads from batch scheduling and shared result types.
- `src/archives/` handles ComicInfo metadata, CBZ creation and indexing, and cleanup.

The older import paths `src.http`, `src.downloader`, `src.cbz`, and `src.database.manga_db` remain as compatibility facades. New implementation code should import from the focused packages.

## Single-file bundle

`scripts/bundle.py` delegates to `install_single.py`, which embeds every Python module under `src/` while preserving its package name. It checks that the database, network, downloads, and archives packages exist before writing the bundle.

Build and verify a bundle with:

```bash
uv run python scripts/bundle.py --output /tmp/mdl.py
python /tmp/mdl.py --help
```
