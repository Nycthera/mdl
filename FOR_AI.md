# MDL project context for AI assistants

Updated 2026-09-21 after the code review documented in [CODE_REVIEW.md](CODE_REVIEW.md).
Treat source code and the dependency lockfile as authoritative when documentation differs.

MDL is a Python CLI for downloading manga from direct image hosts, the MangaDex API,
and browser-based sources. The application version is **3.5.1**, defined in both
`src/__init__.py` and `pyproject.toml`. It requires Python 3.13+ and uses GPL-3.0-only
licensing. There is no application dashboard or Node.js API server in this checkout.

Runtime dependencies are aiohttp, Rich, Playwright, and playwright-stealth.
Development dependencies are pytest, pytest-asyncio, and Ruff. Exact versions are
resolved in `uv.lock`; use `uv sync --locked` to create the environment. Chromium is
needed for browser sources and can be installed with `uv run playwright install chromium`.

| File | Responsibility |
| --- | --- |
| `main.py` | CLI orchestration, source routing, global output/stop state, summaries, DB auto-update |
| `src/cli.py` | Arguments and numeric CLI validation |
| `src/config.py` | Configuration defaults, validation, atomic saves |
| `src/downloader.py` | Concurrent image downloads, retry handling, batch results, progress, DB tracking |
| `src/http.py` | Shared timeouts, session builder, failure classification, backoff, HTTP helpers |
| `src/rate_limiter.py` | Async API request throttling |
| `src/cbz.py` | Atomic archive updates that preserve existing entries and source folders |
| `src/utils.py` | Title/filename sanitization, slug handling, cancellation helpers |
| `src/database/manga_db.py` | SQLite schema, legacy migration, chapter tracking |
| `src/scrapers/__init__.py` | Direct-host page probing and mirror selection |
| `src/scrapers/generic.py` | Integer/decimal chapter discovery on direct image hosts |
| `src/scrapers/mangadex.py` | MangaDex metadata, chapter list, image URLs, downloads |
| `src/scrapers/weebcentral.py` | Browser extraction of image URLs and title |
| `src/scrapers/webtoons.py` | Browser extraction of episode links/images and episode folder names |
| `src/system_utils.py` | Dependency update command and credits |
| `install_single.py` | Single-file builder and macOS/Linux command installation |
| `scripts/bundle.py` | CLI wrapper around the module-preserving installation builder |
| `scripts/release.py` | Version checks, release assets, isolated executable checks, checksums |
| `test/` | Core, regression, standalone installation, and release tests |

Source routing matches parsed hostnames against known domains and their subdomains.
MangaDex title URLs use the API. WeebCentral URLs download the images extracted from
the requested page into a folder based on its chapter ID. Webtoons places episode
folders under the sanitized series title and supplies the required Referer header.
Other manga inputs use the generic direct-image hosts. Available mirrors are selected
in configured priority order, with one URL per page filename.

The downloader uses asyncio tasks, a worker semaphore, and aiohttp connection pools.
Workers default to 10; the CLI accepts 1–100. HTTP failures use classified retry
policies for rate limits, origin errors, retryable errors, and permanent errors.
Default retry attempts are 5 and the default request timeout is 30 seconds. HEAD
probes use a separate short timeout. Cancellation cleans up batch worker tasks before
closing the session. Image writes use pending files followed by atomic replacement.

`download_all_pages()` returns a `DownloadResult` with `successful_pages`,
`total_pages`, `completed_folders`, and a `complete` property. Successful counts include
already-downloaded files. `completed_folders` is the contiguous completed prefix of
the queue, not every independently completed folder. Use these results instead of
assuming that queued pages were downloaded. MangaDex progress must not advance across
an incomplete chapter. Automatic CBZ creation requires a completed batch and no stop signal.

CBZ updates merge older archive entries with new files into a temporary archive,
then atomically replace the destination. They exclude other CBZ files, pending files,
and symlinks. Source chapter folders are retained for recovery and resuming downloads;
this increases disk usage. Do not restore the old truncate-and-delete implementation.

Configuration is stored in `~/.config/manga_downloader/config.json`. Path lookup does
not create directories during import. Missing configs are created when loaded;
malformed JSON or invalid setting types/ranges fail with an explanatory error.
Saves use a temporary file and atomic replacement. CLI help/version are parsed before
configuration is loaded. The default configuration is:

```json
{
  "manga_name": "",
  "start_chapter": 1,
  "start_page": 1,
  "max_pages": 50,
  "workers": 10,
  "cbz": true,
  "clean_output": false,
  "md_language": "en",
  "credits_shown": false
}
```

The SQLite database defaults to
`~/.config/manga_downloader/manga_collection.db`; `MANGA_DB_PATH` overrides its path.
Rows store manga name, last-checked time, latest local chapter, and latest recorded
MangaDex chapter. Updates retain the highest recorded chapter values. Auto-update
always probes the generic hosts, even when cached local/source chapter numbers match.
See [DB_AUTO_UPDATE.md](DB_AUTO_UPDATE.md) for operational details.

Useful CLI examples (the long manga flag is `--manga`, not `--manga-name`):

```bash
uv run python main.py --help
uv run python main.py -M "one-piece" --workers 10 --max-retries 5 --timeout 30
uv run python main.py -M "one-piece" --start-chapter 10 --max-pages 100
uv run python main.py -M "one-piece" --no-cbz
uv run python main.py -M "https://mangadex.org/title/<manga-uuid>" --md-lang en
uv run python main.py --auto-update-db --dev
uv run python main.py --clean-output --version
```

`--cbz` and `--no-cbz` override the configured archive preference. `--start-page` and
`--max-pages` control generic page probing, not a universal limit across all sources.
MangaDex accepts an explicit `--start-chapter`; without one its chapter iteration
starts at zero. `--update` synchronizes locked project dependencies with uv; it does
not download a new application release. Installed bundles instruct users to rebuild
and reinstall when updating.

Validation commands:

```bash
uv sync --locked
uv run python -m pytest -q
uv run ruff check main.py src scripts test install_single.py
uv run ruff format --check main.py src scripts test install_single.py
uv run python scripts/release.py --check-only
uv run python scripts/release.py
```

The review's last completed validation had **82 passing tests**, including **37 added
regression cases**. The original suite had 45 passing tests; the first 15 regression
cases failed against the original code. Ruff lint, formatting, and `git diff --check`
passed. Release assets were built in `/tmp/mdl-review-release`, with standalone
help/version checks outside the checkout. These are recorded results, not a guarantee
for later edits. Test coverage percentage has not been measured. Live manga sites
were not tested during this review.

The single-file build embeds separate Python module namespaces. Do not concatenate
modules or strip internal imports: aliased imports and module globals must remain
independent. Runtime dependencies are installed separately. Release builds validate
matching versions in `src/__init__.py` and `pyproject.toml`, include the versioned
`release-notes/vX.Y.Z.md` as `RELEASE_NOTES.md`, produce checksums, and
smoke-test the bundle. Matching `v` tags trigger publication; manual workflow runs,
PRs, and main-branch pushes test/build without publishing.

Known limitations to preserve in future reviews:

- Database rows lack source URLs, source IDs, and output locations. Generic-host
  auto-update cannot reliably resume MangaDex, WeebCentral, or Webtoons downloads.
  Rerun their original URLs. Reliable source-specific resume needs a schema migration
  and a strategy for ambiguous existing rows.
- Webtoons series discovery reads one rendered list page. Completeness across
  paginated series is not established, and browser behavior needs live verification.
- The helper named `download_image_streaming()` accumulates chunks in memory.
  Do not describe it as bounded-memory disk streaming.
- Adaptive host-cap bookkeeping exists but is not enforced by the download scheduler.
  Do not claim adaptive concurrency is operational based only on that helper.
- Existing downloaded files are counted as successes; the batch completion result
  does not prove image content validity or that source discovery found every page.

When editing, preserve asynchronous request handling, bounded worker concurrency,
classified retry policies, cancellation cleanup, and module-local state. Avoid blocking
the event loop with long filesystem or SQLite operations. Preserve archive/config
atomic replacement and contiguous chapter tracking. Add regression tests for concrete
behavioral bugs and run the checks appropriate to the change. Keep the documentation
honest about tested behavior, remaining limitations, and source-specific flag handling.

Release preparation for v3.5.1 also restored the main-branch installer safeguard
for broken command symlinks and its regression case. The release suite has 83 tests.
Keep `uv.lock` committed and refresh its project version when bumping a release.
The publication workflow uses the bundled patch notes as the GitHub release body.
