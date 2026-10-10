# myCANAL Expiry Tracker

A small personal Python tool that acquires your myCANAL playlist,
retrieves fresh public content details, and regenerates a sortable Excel availability
report. Requires Python 3.11 or newer and `uv`.

## Setup and usage

Install `uv` if necessary (on macOS, `brew install uv`; other platforms:
<https://docs.astral.sh/uv/getting-started/installation/>), then run:

```sh
uv sync
uv run python main.py --auth set
uv run python main.py
```

Normal runs use the shared Core passId authentication, acquire all playlist pages,
fetch fresh enrichment, and generate Excel. The secure keyring entry is
`mycanal-catalog` / `passId`, shared with Catalog; `--auth set` replaces it and
`--auth delete` removes it for both applications. Only supported native secure
keyrings are accepted. There is no silent cURL or cache fallback.

With passId, the profile is explicitly selected/confirmed on every launch. Expiry
remembers only its ID in the OS config directory under
`mycanal-expiry-tracker/profile.json`, independently of Catalog. A missing profile
has no selection default; its obsolete preference is retired after successful
replacement authentication. Network/authentication failures preserve the preference.

`--curl` explicitly uses a browser request instead. `--from-cache` generates
strictly offline, without authentication or HTTP, using the last local playlist
and enrichment. It accepts old data and marks unavailable information as
`Données locales incomplètes`. It cannot be combined with `--curl` or `--refresh`.
`--getinfo` has been removed; acquisition and reporting now form one normal run.
Manual JSON exports in `input/` remain readable with `--from-cache`.
Personal exports, cache files, and workbooks are ignored by Git.

All JSON files must contain a top-level object with a `contents` array. An empty
array is valid; no JSON files is an error. Offline generation never rewrites inputs.

Pages are read in filename order. Usable items need a nonempty `onClick.URLPage`.
The first usable occurrence of each `contentID` wins. Items without an ID are
retained individually but not cached. Missing optional metadata stays blank.
Movies, TV movies, documentaries, shows, and seasons are retained without
assuming that `VoD` means a theatrical movie. Non-object entries and entries
without detail URLs are skipped with a warning.

## Retrieving the playlist inputs

The default passId bootstrap is implemented in Core. For the explicit browser
alternative:

1. Log into myCANAL normally and stay on the [main page](https://www.canalplus.com/)
2. In Firefox DevTools → **Network**, find the authenticated Hodor playlist request
   (the endpoint `/api/v2/mycanal/me/<token>/lists/playlist`). Reload if necessary.
3. Choose **Copy as cURL**.
4. Run `uv run python main.py --curl`.
5. Paste the complete request into the multiline prompt, then press **Esc**, then **Enter**.

**The copied request contains sensitive authentication data. Do not share, commit
or save it.** Paste it only into the running application's prompt, never a shell.
The application parses it as text, sends only the required authentication/profile
headers, and never saves or logs the request or those headers. API-returned
tokenized URLs remain in the raw export; keep these private files out of Git.

Acquisition uses existing pacing/retries and follows server cursors for at most
five pages / 500 entries. passId uses the bootstrap context without browser-only
query options. With cURL, browser query parameters are preserved, with `get=100`,
`maxContentRemaining=500` and server-issued `after` cursors controlled by acquisition. It saves each original decompressed JSON body unchanged
as `input/YYYY-MM-DD.HH-MM.json`, then `.page2.json`, etc., using one Paris
timestamp. It then enriches the playlist and generates the workbook.

Only a complete validated acquisition archives active `*.json` to `.json.bak`.
An existing backup collision aborts without overwriting it; move that backup
yourself before retrying. Fetch/validation failures leave the old export untouched.
The last published profile ID is tracked in `input/.acquisition-profile`, outside
of the enrichment cache. A changed or unknown profile removes the entire `cache/`
directory only as part of successful publication. This metadata and cache removal
participate in publication rollback. Acquisition failure preserves the previous
playlist, cache and workbook. There is no periodic token rotation during pagination;
one recovery after HTTP 401/403 is allowed across the whole passId acquisition.
cURL credentials cannot be renewed automatically.
Publication stages files and rolls back ordinary filesystem failures; it is not
a crash-atomic multi-file transaction. Run one exporter at a time. Responses
echoing authentication data are refused rather than redacted.

Manual DevTools response export remains supported:

1. Sign in to myCANAL in your browser and stay on the [main page](https://www.canalplus.com/)
2. Open the browser DevTools (`F12` or `Ctrl+Shift+I` / `Cmd+Option+I`).
3. Open the **Network** tab.
4. Reload the main page if necessary to capture its network requests.
5. Filter the requests for `hodor` and locate the request returning the playlist
   contents as JSON (usually named `/playlist`). JSON should contain
    ``` json
	"currentPage": {
		"displayName": "Ma Playlist",
		"path": "/mes-videos/my-playlist",
        [...]
	}
    ```
6. Open the response and save its JSON content to a file in `input/`, for example
   `input/page1.json`.
7. If your playlist has grown beyond 100 items, scroll down to load the next page
   and repeat the operation with `input/page2.json`, `input/page3.json`, etc.

The filenames do not matter: every `.json` file in `input/` is loaded and their
`contents` arrays are merged automatically.

Do not commit these files. They come from your personal myCANAL session and may
contain account-specific or private data. Keep `input/` excluded through
`.gitignore`.

Pagination support has been tested in production with a sufficiently enthusiastic
playlist. This was, of course, entirely intentional and not a fortunate consequence
of having more than 100 items saved for later.

## API access and cache

The original `onClick.URLPage` is retained. When `onClick.parameters` contains a
valid `featureToggles` query descriptor whose string-array enum includes `detailV5`,
the request adds only `detailV5`. Other enum values are not enabled. Toggles already
explicit in the source URL are preserved, with `detailV5` added if missing and
repeated `featureToggles` keys consolidated into one. Without that declaration,
the URL is unchanged. No additional request is made.

The client calls the supplied HTTPS `hodor.canalplus.pro/api/v2/mycanal/detail/`
URLs directly, sequentially, without credentials. Other hosts and redirects are
rejected. Connections are reused with a descriptive User-Agent and a 10-second
request timeout. The default minimum delay is 180 ms between requests, including
retries, with up to 150 ms of random jitter. Change the minimum delay for one run
with:

```sh
uv run python main.py --delay 0.5
```

HTTP 429, 502, 503, 504, timeouts and connection errors are retried up to four total
attempts. `Retry-After` seconds and HTTP dates are honored; otherwise exponential
backoff plus jitter applies. HTTP 400/401/403/404 are not retried. Individual
failures remain in the workbook as `Erreur HTTP` or `Erreur parsing`, and the
remaining items are processed. Exit code 0 means the report was written, even
if some rows failed; the final structured log includes status counts.

`cache/details.json` holds raw detail enrichment and validated season catalogs,
keyed by content and season identities, with no profile field and **no TTL**.
Normal runs always rebuild fresh enrichment, including resume fallbacks; the cache
is primarily for offline development and reformatting. `--refresh` remains accepted
for compatibility but normal runs are already fresh.

Entries retain observation timestamps, raw availability, subgenre, durations and
validated season/episode metadata. No credential, API URL or computed report totals
are stored. Invalid/legacy entries are misses. Cache writes use a temporary file
and atomic replacement; offline generation does not rewrite the cache.

```sh
uv run python main.py --from-cache
```

This mode uses every available validated entry regardless of age, never requests
missing details or seasons, and produces explicit partial rows when necessary.
A partial series does not invent episode totals. Expiration/day presentation is
recalculated from the saved raw timestamps. The installed `mycanal-expiry-tracker`
command uses the current directory or `--data-dir DIRECTORY`; `main.py` retains
checkout-relative data paths. Run one exporter at a time.

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
even when it duplicates `Catégorie`; if neither value is usable, it stays blank. It is cached alongside
the raw timestamp without extra requests. Raw cache entries missing only this optional
field remain usable with a blank subgenre.

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
episode, repeated on every expiration-group row. This fresh playlist state is never cached. If nothing remains,
the series keeps one row with blank resume/expiration fields and numeric zero count
and duration. Series produce one row per
distinct remaining-episode expiration timestamp, plus one unknown-expiration row
when needed. The title and series resume label repeat; `Épisodes restants` and
numeric `Durée` cover only that row's episodes. A missing duration blanks only its
group's sum. `Catégorie` describes the represented seasons (for example `Saison 3`,
`Saisons 4 à 5`, or `Saisons 3, 5`). Exact timestamps remain separate even on the
same date. Groups use existing catalogs without extra requests or cached display
state; incomplete backlogs still produce no partial totals.

Catalogs use public `/episodes` URLs and the existing paced HTTP client, with
fresh requests for each necessary season in normal mode and no per-episode
requests. Offline mode reuses validated catalogs and saved resume fallbacks
without any TTL; explicit playlist state always takes priority.
No authenticated progression endpoint is used. URLs, progress and derived backlog values are never cached. Incomplete paging,
missing navigation or an unmatched resume point produces blank uncertain values and
`Série incomplète`; HTTP errors retain their existing status. A safely matched resume
label is retained if a later-season fetch fails. See SPEC.md for exact cache and
completeness semantics.
An empty playlist generates a Table with one blank data row (required by Excel).
Close the workbook in Excel before regenerating it if your platform locks open files.


### Duration and absolute availability text

`Durée` prefers the current playlist's positive integer `duration` in milliseconds
for `VoD` movies identified by a `Film ` subtitle. For example, `5880000` becomes
`1 h 38 min`. Excel stores `Durée` numerically as minutes / 1440, with format
`[h]" h "mm" min"`, so sums/subtotals work beyond 24 hours. Playlist
duration is never copied into the detail cache. Whole minutes are used (any residual
seconds are omitted); values below one minute are unusable for this display.

When playlist movie duration is missing/unusable, the verified detailV5 fallback is
`detail.duration` in integer minutes with `detail.genre == "Cinéma"`. That raw value
may be cached as `duration_minutes`; it also identifies a movie when playlist category
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
raw enrichment on both fresh fetches and cache hits. The playlist supplies current
titles, categories, service, offer membership, paths, URLs and duration. None of
that playlist metadata is duplicated into the detail cache.

## Tests

```sh
uv run pytest
# Equivalent explicit exclusion:
uv run pytest -m "not integration"
# Opt in to the few real public API smoke tests:
uv run pytest -m integration
```

Normal tests use local fictional fixtures, mock HTTP, sleep and jitter, and block
real network access. They cover input validation, merging, extraction, Paris date
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
