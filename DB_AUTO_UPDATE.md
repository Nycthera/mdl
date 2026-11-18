# DB Auto-Update Guide

This guide explains how to use the source-aware database-backed update workflow.

## What It Does

The auto-update mode reads tracked manga from SQLite and checks each title for new pages.

Command:

```bash
uv run python main.py --auto-update-db
```

For each tracked row in `manga_data`, MDL:

1. Reads `manga_name` and `latest_chapter_local`
2. Picks a safe resume chapter (integer part of latest local chapter)
3. Scans for available pages from that point onward
4. Downloads missing files, reusing pages already in CBZ archives when CBZ output is selected
5. Updates DB metadata (`date_last_checked`, latest chapters)

New downloads store their source type, original URL, source ID, language, and output
folder. Auto-update routes MangaDex, WeebCentral, Webtoons, MangaPill, and Manganato records back through
their matching scraper. Migrated legacy rows remain `generic` because their original
source cannot be recovered safely.

## Library Commands

```bash
uv run python main.py library list
uv run python main.py library status "One Piece"
uv run python main.py library update "One Piece" --workers 10
uv run python main.py library update id:3 --cbz-layout chapter
```

`list` and `status` show saved information without querying a source. Status includes
the saved URL and folder, highest completed local chapter, last check time, and most
recent download run's page counts. A saved run is not a live source check or an
integrity check; use `library update` and `--verify` for those operations.

Titles match exactly, ignoring case. When the same title is tracked from multiple
sources, use its `id:NUMBER` from `library list`. No source is selected automatically
for an ambiguous title. Numeric manga titles such as `86` remain title searches.

`update` uses the selected row's source, language, and saved output directory, even
when invoked from another working directory. Update commands return a nonzero exit
code for failed or interrupted updates. Full-library updates continue to the next
title after a source error and report the failed count.

CBZ output defaults to one combined book with ComicInfo metadata. Use
`--cbz-layout chapter` for separate chapter archives, or save `"cbz_layout": "chapter"`
in the config. Combined mode merges existing MDL chapter archives and removes them
after validating the book. Empty chapter folders are cleaned up on repeat downloads.
Switching to chapter mode retains existing combined archives. Both layouts support
verification and repair.

Each run also records page-level outcomes. Inspect them with:

```bash
uv run python main.py --download-history
uv run python main.py --download-history "One Piece"
```

Verify or repair a library folder with:

```bash
uv run python main.py --verify "One Piece"
uv run python main.py --repair "One Piece"
```

## Database Path

Default path:

```text
~/.config/manga_downloader/manga_collection.db
```

Override with environment variable:

```bash
MANGA_DB_PATH=/absolute/path/to/your.db uv run python main.py --auto-update-db
```

## Useful Flags

```bash
# Minimal output
uv run python main.py --auto-update-db --clean-output

# Higher concurrency
uv run python main.py --auto-update-db --workers 20
```

## Manual Test Flow

1. Lower a tracked manga chapter in DB.
2. Run auto-update.
3. Confirm DB values were updated.

Example:

```bash
sqlite3 ~/.config/manga_downloader/manga_collection.db "
UPDATE manga_data
SET latest_chapter_local = 1,
    latest_chapter_from_mangadex = 1,
    date_last_checked = strftime('%s','now') - 86400
WHERE manga_name = 'one piece';
"

uv run python main.py --auto-update-db

sqlite3 ~/.config/manga_downloader/manga_collection.db "
SELECT manga_name, latest_chapter_local, latest_chapter_from_mangadex,
       datetime(date_last_checked,'unixepoch')
FROM manga_data
WHERE manga_name = 'one piece';
"
```

## Logging

DB stage logs are printed when `--dev` is used and are prefixed with `[db]`:

- schema check
- DB connection
- insert/update decision
- commit completion

Enable DB logs:

```bash
uv run python main.py --auto-update-db --dev
```

Optional environment overrides:

```bash
MANGA_DB_VERBOSE=0 uv run python main.py --auto-update-db
MANGA_DB_VERBOSE=1 uv run python main.py --auto-update-db
```

## Notes

- The database uses WAL mode so update reads do not block completed-download writes.
  Writers wait up to 10 seconds for a busy database instead of failing immediately.
- Schema migrations are transactional and versioned. Manga names are trimmed and
  matched case-insensitively, preventing duplicate rows such as `One Piece` and
  `one piece` while retaining the highest recorded chapter values.
- Legacy records without source metadata continue using generic direct-image probing.
- Browser-source updates are limited by what each scraper can discover from its saved URL.
- For best accuracy, keep names consistent with download folder naming.
- MangaDex records page history per chapter and consolidates chapter progress at the end.
