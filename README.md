# myCANAL Expiry Tracker

Acquire a myCANAL playlist, enrich its contents and generate a sortable Excel
availability report. Shared HTTP/authentication infrastructure lives in Core.

## Setup and usage

```sh
uv sync
uv run python main.py --auth set
uv run python main.py
```

Normal execution uses Core's shared native-keyring entry `mycanal-catalog` / `passId`.
Expiry and Catalog retain independent profile preferences; selection/confirmation
and successful authentication precede preference updates. Network/authentication
failure cannot invalidate the saved preference.

```sh
uv run python main.py --curl
uv run python main.py --from-cache
```

`--curl` supplies an explicit browser authentication context and its profile through
Core's inert parser. Both network modes acquire the entire playlist in memory and
fetch every necessary enrichment again. Neither reads previous cache contents.
There is no silent cURL/cache fallback. Playlist acquisition allows one passId
recovery after 401/403, without periodic rotation; cURL cannot renew credentials.

`--from-cache` reads only the latest active snapshot: no authentication, HTTP,
enrichment or cache writes. Missing/incompatible/invalid latest data is an explicit
error. `--refresh` and `--getinfo` are removed. `--delay` controls HTTP pacing and
cannot accompany `--from-cache` or `--auth`. `--auth set/delete` manages credentials
only and cannot accompany reporting mode flags.

`--data-dir` locates cache/output, not keyring/profile preferences. The installed
command defaults to the current directory; `main.py` defaults to the checkout.
Runtime never reads/writes `input/`. Old input files and legacy `cache/details.json`
are left untouched and ignored; no automatic migration is provided.

## HTTP behavior

Only the playlist acquisition carries authentication headers. Supplied public detail
and episode URLs are used in memory; their host/resource is validated in Core and
redirects are rejected. A validated detailV5 declaration adds that feature toggle
without enabling unrelated advertised flags. Requests remain sequential, with a
10-second timeout, 180 ms minimum delay and up to 150 ms jitter by default.

```sh
uv run python main.py --delay 0.5
```

Existing Core retry/backoff behavior applies to transient HTTP/network failures.
Individual enrichment errors remain report rows, and processing continues. Exit
code 0 means snapshot and Excel publication succeeded, even with partial enrichment;
status counts appear in the final log.

## Offline report snapshots

Each normal execution stores only final business rows in
`cache/YYYY-MM-DD.HH-MM.cache.json`, using a Paris timestamp. The versioned object
contains `schema_version` and `rows`: identity/title/service, subgenre/category/offer
flag, public URL, expiration and sorting timestamp, availability text, resume label,
remaining count, effective duration and status. No HTTP response, full catalog,
credential, Hodor token or technical URL is saved. There is no TTL, incremental
merge, refresh, resume or reuse of earlier enrichment.

Data destined for JSON/Excel is validated for credentials and Hodor tokens. Links
are validated public myCANAL URLs, without Hodor fallback. Core log redaction stays
enabled. Personal snapshots and workbooks remain excluded from Git.

New publication archives all previous active files to `.cache.json.bak`; backups
are never overwritten or read automatically. Filename/backup collisions abort
explicitly, including two runs in the same minute. Staging and rollback preserve
previous snapshots on ordinary publication failure. Run one exporter at a time.

Offline mode selects the latest active file by its filename timestamp; an invalid
latest file does not fall back to older actives or backups. It reproduces stored
partial results and error rows without retrying. Removing `input/` has no effect.
Days remaining, formulas and colors evolve normally with the current day.

Authentication/acquisition failure or interruption before publication preserves
previous files. Enrichment errors still produce a new snapshot. Snapshot publication
precedes Excel: an Excel failure returns an error but leaves the snapshot available
for `--from-cache`. Excel also uses staged replacement to preserve the old workbook
on failure. Snapshot write failure is explicit and prevents Excel publication.

## Excel output

The regenerated file is `output/ma-liste-canal.xlsx`, with one `Ma liste` sheet:

- A native Excel Table with filters, frozen header and bounded column widths.
- French date formatting (`dd/mm/yyyy`), integer days remaining and clickable links.
- Content IDs retained in a hidden column, and `Oui`/`Non` offer membership.
- Soonest availability dates first, with unknown dates and errors at the end.
- Entire rows use dark gray with light gray text for expired content (< 0 days),
  dark red with white text for the last day (0), red for 1–2 days, orange for
  3–7 days and yellow for 8–30 days. Values above 30, blank or non-numeric
  values retain normal Table formatting.

Column order: `Titre`, `Sous-genre`, `Service`, `Jours restants`,
`Disponible jusqu'au`, `Épisode à reprendre`, `Épisodes restants`, `Durée`, `Catégorie`, `Dans l'offre`, `URL myCANAL`,
`Content ID` (hidden), `Fin de disponibilité`, `Statut`.
`Catégorie` comes from playlist metadata except for series groups, where it describes
the represented seasons. `Sous-genre` uses `detail.subgenre`
first, falling back to `tracking.dataLayer.subgenre` when the first value is missing,
null, non-string, empty or whitespace-only. The selected string is preserved unchanged,
even when it duplicates `Catégorie`; if neither value is usable, it stays blank.
The final displayed subgenre is stored in the snapshot.

The date comes first from `detail.availabilityEndDate` (detailV5), then
`download.availabilityEndDate`, then another availability
timestamp (preferring `stream`), then a `Dispo. jusqu'au DD/MM/YYYY` label.
Timestamps are milliseconds and are converted to `Europe/Paris` before extracting
the calendar date. `Jours restants` is an Excel Table formula based on `TODAY()`,
so it updates when Excel opens/recalculates the workbook. It returns blank for an
unknown date, and can become zero or negative. Whole-row conditional formatting
references this dynamic value with an `ISNUMBER` guard, preserving the thresholds
above. Excel's `TODAY()` uses the date of the Excel environment. Python supplies
only an initial cached preview. `lastDays`
is never used. Text from the source is written as text, not Excel formulas.

For series, `Épisode à reprendre` shows the matched resume episode (for example
`S3E3`), and `Épisodes restants` counts that episode and every later episode/season.
Fresh playlist resume metadata wins over conflicting detail actions. The current
episode counts in full when partially watched; `userProgress` never determines
completion or prorates duration. Only literal playlist `isCompleted: true` excludes
the matched episode and advances the resume label to the first actual remaining
episode, repeated on every expiration-group row. The resolved resume label is saved in the report snapshot. If nothing remains,
the series keeps one row with blank resume/expiration fields and numeric zero count
and duration. Series produce one row per
distinct remaining-episode expiration timestamp, plus one unknown-expiration row
when needed. The title and series resume label repeat; `Épisodes restants` and
numeric `Durée` cover only that row's episodes. A missing duration blanks only its
group's sum. `Catégorie` describes the represented seasons (for example `Saison 3`,
`Saisons 4 à 5`, or `Saisons 3, 5`). Exact timestamps remain separate even on the
same date. Groups use catalogs fetched during this execution without per-episode requests or stored display
state; incomplete backlogs still produce no partial totals.

Catalogs use public `/episodes` URLs and the existing paced HTTP client, with
fresh requests for each necessary season in normal mode and no per-episode
requests. Offline mode reuses validated catalogs and saved resume fallbacks
without any TTL; explicit playlist state always takes priority.
No authenticated progression endpoint is used. Technical URLs and progression inputs remain in memory; final backlog values are saved in the snapshot. Incomplete paging,
missing navigation or an unmatched resume point produces blank uncertain values and
`Série incomplète`; HTTP errors retain their existing status. A safely matched resume
label is retained if a later-season fetch fails. See SPEC.md for exact report and
completeness semantics.
An empty playlist generates a Table with one blank data row (required by Excel).
Close the workbook in Excel before regenerating it if your platform locks open files.


### Duration and absolute availability text

`Durée` prefers the current playlist's positive integer `duration` in milliseconds
for `VoD` movies identified by a `Film ` subtitle. For example, `5880000` becomes
`1 h 38 min`. Excel stores `Durée` numerically as minutes / 1440, with format
`[h]" h "mm" min"`, so sums/subtotals work beyond 24 hours. The
effective duration is saved in the snapshot. Whole minutes are used (any residual
seconds are omitted); values below one minute are unusable for this display.

When playlist movie duration is missing/unusable, the verified detailV5 fallback is
`detail.duration` in integer minutes with `detail.genre == "Cinéma"`. That raw value
contributes to the effective snapshot duration; it also identifies a movie when playlist category
metadata is missing. A usable current playlist duration takes priority over this
fallback. For example, 107 minutes becomes `1 h 47 min`, 60 becomes `1 h 00 min`,
and 47 becomes `0 h 47 min`. Series use each row's remaining episode duration as described
above. No per-episode detail requests are made for duration. Missing, non-integer,
boolean and nonpositive values are unusable. Unverified legacy duration fields are
not guessed.

`Disponible jusqu'au` uses the same canonical timestamp selected for the date,
interpreted as Unix milliseconds and explicitly converted to `Europe/Paris`.
French weekday/month names are independent of system locale; the label has no year
and uses a 24-hour clock with `h` (for example `mercredi 30 septembre 23h59`).
This follows the required exact example rather than a colon separator.
Relative API labels are never copied. Without a valid timestamp, including a
label-only date fallback, this field stays blank. `Fin de disponibilité` remains
a real Excel date.

The Excel date, absolute availability text and status are derived at runtime from
fresh enrichment and the final report snapshot. The playlist supplies current
titles, categories, service, offer membership, paths, URLs and duration. None of
that an earlier enrichment is reused.

## Tests

```sh
uv run pytest
# Equivalent explicit exclusion:
uv run pytest -m "not integration"
# Opt in to the few real public API smoke tests:
uv run pytest -m integration
```

Normal tests use local fictional fixtures, mock HTTP, sleep and jitter, and block
real network access. They cover in-memory playlist validation, merging, extraction, Paris date
boundaries, retries, caching, failure isolation, sorting and native workbook XML.

The four integration cases discover a movie, documentary, `detailShow` and
`detailSeason` from current input files. Missing categories/variants are skipped
with a reason; API failures fail the corresponding test. IDs, titles, URLs and
expiration dates are not hardcoded. These tests do not deliberately trigger rate
limiting and do not run by default.

Checks on 2026-09-28 found valid show and season responses without availability
information and a documentary response with an availability timestamp. Some
requests returned HTTP 403: the live suite had three passes and one movie failure.
The full 120-item export contained 59 known dates, 59 unknown dates and two HTTP
errors. No authentication workarounds were attempted. See
`tests/fixtures/README.md` for precise fixture provenance and limitations.

For **manual observation only**, a separate script logs response time, HTTP status,
`Retry-After`, and standard/legacy rate-limit headers:

```sh
uv run python tools/test_rate_limit.py --url "PUBLIC_DETAIL_URL" --count 3 --delay 1
```

It defaults to three requests, caps the count at 20, requires at least one second
between requests, performs no retries, and stops immediately on HTTP 429 or another
HTTP error. It is never invoked by the test suite or normal application.

## Independent projects

Expiry depends on the public `mycanal-hodor-core` package for HTTP, API parsing,
canonical episode models, structured logging and timing. Personal playlist/resume
state, JSON cache policy and Excel reporting remain here. The private Catalog
application also uses Core; neither application depends on the other.

Packages use the `mycanal_expiry_tracker` and `mycanal_hodor_core` namespaces.
During unpublished development, `uv sync` uses the sibling Core checkout through
a local uv source override; each project keeps its own environment and lockfile.
Distribution metadata declares `mycanal-hodor-core>=0.1,<0.2`, without a local path.
To test built wheels before publication, supply the Core wheel alongside Expiry.
No authenticated inputs, cache or generated output are packaged.

Logging is configured explicitly by CLI startup. Importing Core does not configure
global logging; applications may select other structlog processors. The shared
`timeit()` remains synchronous and inclusive, preserving exceptions even when
logging fails. Existing timing placements remain in Expiry.

Failure diagnostics follow the configured structlog DEBUG level. Normal error events stay unchanged; DEBUG adds sanitized HTTP response bodies/context or exception chains without frame locals. INFO and higher suppress these details. Existing console log-level defaults are unchanged.
