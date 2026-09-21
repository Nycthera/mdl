Review completed against the Python CLI, downloader, scrapers, database, configuration, and distribution scripts in this checkout. Findings below are based on code inspection and local regression tests. Live manga sites were not exercised.

| Severity | Finding | Resolution |
| --- | --- | --- |
| Critical | Rebuilding a CBZ discarded older archived chapters after their folders had been deleted. | Preserve existing entries, merge new files, and retain source folders. |
| High | Archive creation truncated the good archive before writes finished; disk errors could destroy it. | Write a temporary archive and replace the destination only on success. |
| High | Archive creation included temporary downloads and other CBZs, then recursively deleted chapter directories. | Exclude pending files, archives, and symlinks; remove automatic directory deletion. |
| High | Failed pages counted as successful MangaDex chapters and could advance database progress across missing chapters. | Return batch results, count successful pages, and stop progress advancement at the first incomplete chapter. |
| High | Callers packaged incomplete download batches. | Require batch completion and no interruption before automatic packaging. |
| High | Webtoons episodes were saved outside their title folder, allowing cross-series collisions and preventing expected packaging. | Nest episode folders under the sanitized title. |
| High | WeebCentral discarded the extracted image URLs and searched unrelated direct-image hosts instead. | Download extracted URLs into a folder based on the requested chapter ID. |
| High | Mirror probes scheduled duplicate page filenames concurrently. | Choose one available mirror per filename using configured source priority. |
| Medium | Cached source/local chapter equality caused auto-update to skip future source checks indefinitely. | Probe the source each run. Source identity limitations remain below. |
| Medium | Downloading older chapters moved saved database progress backward. | Keep the highest recorded local/source chapter numbers. |
| Medium | Shared HTTP session creation passed an unsupported `ttl` connector argument. | Use `keepalive_timeout`; verify session construction against installed dependencies. |
| Medium | The legacy bundler stripped aliased imports and merged conflicting module globals. | Delegate to the existing module-preserving installation builder. |
| Medium | Source detection accepted lookalike hosts and hostnames appearing in URL credentials. | Match the parsed hostname against exact domains or subdomains. |
| Medium | Titles such as `..`, empty sanitized names, control characters, and Windows device names were unsafe filesystem components. | Normalize these to safe nonempty components. |
| Medium | Download filenames included query strings/fragments, breaking image extensions and Windows paths. | Derive the filename from the URL path only. |
| Medium | Retry settings were ignored by several download paths; archive creation could not be disabled from the CLI. | Propagate retry counts and support `--no-cbz`; validate numeric CLI limits. |
| Medium | MangaDex saver URLs used the regular image endpoint. | Use the `data-saver` endpoint for saver filenames. |
| Medium | Cancelling a batch could leave worker tasks running after its HTTP session closed. | Cancel and await workers in a `finally` block. |
| Medium | Config imports created directories, saves truncated existing preferences, and malformed settings reached runtime code. | Make path lookup read-only, save atomically, validate settings, and parse help/version before loading config. |
| Low | Documentation advertised an absent dashboard and unmeasured 95%+ test coverage. | Remove the dashboard claim and replace the coverage claim with the actual test command. |

Validation: the original 45 tests passed before changes. The first 15 new regression cases all failed against the original implementation. The completed suite has 82 passing tests (37 added cases). Ruff lint, Ruff formatting, and `git diff --check` pass. Release assets were built successfully in `/tmp/mdl-review-release`; the release builder checks the standalone executable outside the checkout.

Remaining limitations:

- Database rows contain names and chapter numbers, not source URLs, source IDs, or output locations. Auto-update still uses generic direct-image hosts. Rerun the original URL for MangaDex, WeebCentral, and Webtoons. Reliable cross-source resume needs a database migration and a strategy for existing ambiguous rows.
- Browser scraping was inspected but not tested against live sites. In particular, Webtoons series discovery currently reads one rendered list page; completeness across paginated series is not established.
- HTTP helper performance claims exceed its implementation: the streaming helper accumulates chunks in memory, and adaptive host-cap bookkeeping is not enforced by the download scheduler. This review does not validate those advertised performance properties.
- Retaining chapter folders improves recovery but increases disk usage compared with deleting them after packaging.

This is a concrete bug-fixing review, not a claim that every line or every external integration is correct.
