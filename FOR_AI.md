# MDL project context for AI assistants

Updated 2026-09-21 after the code review documented in [CODE_REVIEW.md](CODE_REVIEW.md).
Treat source code and the dependency lockfile as authoritative when documentation differs.

MDL is a Python CLI for downloading manga from direct image hosts, the MangaDex API,
and browser-based sources. The application version is **3.6.0**, defined in both
`src/__init__.py` and `pyproject.toml`. It requires Python 3.13+ and uses GPL-3.0-only
licensing. There is no application dashboard or Node.js API server in this checkout.

Runtime dependencies are aiohttp, BeautifulSoup, Pillow, Rich, Playwright, and playwright-stealth.
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
| `src/cbz.py` | Combined books and optional chapter CBZs with ComicInfo, archive indexing and atomic updates |
| `src/library.py` | Saved library list/status views |
| `src/utils.py` | Title/filename sanitization, slug handling, cancellation helpers |
| `src/database/manga_db.py` | Source-aware SQLite library, run/page history, migrations |
| `src/verification.py` | Dependency-free image integrity checks and history-backed repair |
| `src/scrapers/__init__.py` | Direct-host page probing and mirror selection |
| `src/scrapers/generic.py` | Integer/decimal chapter discovery on direct image hosts |
| `src/scrapers/mangadex.py` | MangaDex metadata, chapter list, image URLs, downloads |
| `src/scrapers/weebcentral.py` | Browser extraction of image URLs and title |
| `src/scrapers/webtoons.py` | Browser extraction of episode links/images and episode folder names |
| `src/scrapers/mangapill.py` | HTML chapter/series extraction for MangaPill |
| `src/scrapers/manganato.py` | HTML chapter/series extraction for Manganato-family hosts |
| `src/scrapers/html_common.py` | Bounded concurrent chapter discovery, retries and cancellation cleanup |
| `src/system_utils.py` | Dependency update command and credits |
| `install_single.py` | Single-file builder and macOS/Linux command installation |
| `scripts/bundle.py` | CLI wrapper around the module-preserving installation builder |
| `scripts/release.py` | Version checks, release assets, isolated executable checks, checksums |
| `test/` | Core, regression, standalone installation, and release tests |

Source routing matches parsed hostnames against known domains and their subdomains.
MangaDex title URLs use the API. WeebCentral URLs download the images extracted from
the requested page into a folder based on its chapter ID. Webtoons places episode
folders under the sanitized series title and supplies the required Referer header.
Other manga inputs use the generic direct-image hosts. Discovery starts with the first
mirror that confirms a chapter, falls back to the other mirrors at page gaps, and keeps
one URL per page filename.

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

CLI CBZ output defaults to `--cbz-layout series`: one combined book per series with
ComicInfo.xml metadata. `create_cbz_for_all()` merges loose pages, the existing book,
and MDL chapter archives in chapter/page order. Chapter archives are removed only
after the combined book is validated; their metadata is retained inside chapter paths.
`--cbz-layout chapter` creates separate chapter archives with images at each archive's
root and retains any existing combined book. `create_cbz_per_chapter()` returns created
archive paths; the output dispatcher returns their parent directory for summaries.
Both layouts merge existing entries into a temporary archive, check its CRC, then
atomically replace the destination. Source folders are removed only when every file
was included; pending files, excluded sidecars and symlinks keep their folders intact.
Empty chapter folders are pruned even when packaging has no new pages. Direct-host
discovery does not create directories; the downloader creates them when pages are needed.
The downloader's `skip_archived` option recognizes both layouts and is enabled only
for CBZ output. Verification indexes both layouts and repair preserves ComicInfo fields.

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
  "output_format": "cbz",
  "cbz_layout": "series",
  "reading_direction": "auto",
  "clean_output": false,
  "md_language": "en",
  "credits_shown": false
}
```

The SQLite database defaults to
`~/.config/manga_downloader/manga_collection.db`; `MANGA_DB_PATH` overrides its path.
Rows store manga name, last-checked time, latest local chapter, and latest recorded
MangaDex chapter. The database uses WAL mode, a 10-second busy timeout, transactional
versioned migrations, and case-insensitive `(source_type, source_key)` identities.
Updates retain the highest recorded chapter values. Auto-update routes source-aware
rows through their scraper and uses generic probing for migrated legacy rows.
See [DB_AUTO_UPDATE.md](DB_AUTO_UPDATE.md) for operational details.

`library list` and `library status TITLE_OR_ID` show saved state without querying
sources. `library update TITLE_OR_ID` updates exactly one row through the same source
path as full-library updates and reuses its saved output folder, including MangaDex.
Selectors are exact case-insensitive titles or explicit `id:NUMBER`; ambiguous titles
fail with a list of matching IDs. Library commands do not require `-M`.
MangaPill and Manganato routes preserve source URLs, history, Referer headers, clean
output, stop state, retry counts and timeouts. Series discovery failures abort instead
of silently advancing progress across gaps. Their `--start-chapter` filter runs before
fetching chapter manifests; a single chapter URL downloads that chapter.

Useful CLI examples (the long manga flag is `--manga`, not `--manga-name`):

```bash
uv run python main.py --help
uv run python main.py -M "one-piece" --workers 10 --max-retries 5 --timeout 30
uv run python main.py -M "one-piece" --start-chapter 10 --max-pages 100
uv run python main.py -M "one-piece" --no-cbz
uv run python main.py -M "one-piece" --output-format epub
uv run python main.py -M "one-piece" --output-format pdf
uv run python main.py -M "https://mangadex.org/title/<manga-uuid>" --md-lang en
uv run python main.py --auto-update-db --dev
uv run python main.py library list
uv run python main.py library status "One Piece"
uv run python main.py library update id:3 --cbz-layout chapter
uv run python main.py --clean-output --version
```

`--cbz` and `--no-cbz` override the configured archive preference. `--start-page` and
`--max-pages` control generic page probing, not a universal limit across all sources.
`--output-format` selects `cbz`, `epub`, or `pdf`; it overrides the configured
`output_format` value. `--no-cbz` disables packaging unless an explicit output format
is supplied.
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

- Schema v3 stores source identity, output locations, run summaries, and page outcomes.
  Migrated legacy rows remain generic because their original sources are unknowable.
- `--verify` performs dependency-free image signature checks, not full pixel decoding.
  `--repair` can only redownload pages that have a URL in page history.
- Webtoons series discovery reads one rendered list page. Completeness across
  paginated series is not established, and browser behavior needs live verification.
- The helper named `download_image_streaming()` accumulates chunks in memory.
  Do not describe it as bounded-memory disk streaming.
- Adaptive host caps are enforced by `AdaptiveHostLimiter` in the download scheduler.
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
