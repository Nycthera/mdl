# DB Auto-Update Guide

This guide explains how to use the database-backed update workflow.

## What It Does

The auto-update mode reads tracked manga from SQLite and checks each title for new pages.

Command:

```bash
python3 main.py --auto-update-db
```

For each tracked row in `manga_data`, MDL:

1. Reads `manga_name` and `latest_chapter_local`
2. Picks a safe resume chapter (integer part of latest local chapter)
3. Scans for available pages from that point onward
4. Downloads only missing files
5. Updates DB metadata (`date_last_checked`, latest chapters)

## Database Path

Default path:

```text
~/.config/manga_downloader/manga_collection.db
```

Override with environment variable:

```bash
MANGA_DB_PATH=/absolute/path/to/your.db python3 main.py --auto-update-db
```

## Useful Flags

```bash
# Minimal output
python3 main.py --auto-update-db --clean-output

# Higher concurrency
python3 main.py --auto-update-db --workers 20
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

python3 main.py --auto-update-db

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
python3 main.py --auto-update-db --dev
```

Optional environment overrides:

```bash
MANGA_DB_VERBOSE=0 python3 main.py --auto-update-db
MANGA_DB_VERBOSE=1 python3 main.py --auto-update-db
```

## Notes

- The current schema tracks manga by `manga_name` only.
- For best accuracy, keep names consistent with download folder naming.
- MangaDex flow performs one consolidated DB write at the end of the manga run.
