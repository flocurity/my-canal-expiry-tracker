# myCANAL Expiry Tracker

A small personal Python tool that reads manually exported myCANAL playlists,
retrieves public content details, and regenerates a sortable Excel availability
report. Requires Python 3.11 or newer and `uv`.

## Setup and usage

Install `uv` if necessary (on macOS, `brew install uv`; other platforms:
<https://docs.astral.sh/uv/getting-started/installation/>), then run:

```sh
uv sync
uv run python main.py
```

Place all playlist page responses in `input/` as `.json` files. These files are
**manually retrieved from your own myCANAL account using browser DevTools**.
See [**Retrieving the playlist inputs**](#retrieving-the-playlist-inputs)
The program does not retrieve the authenticated playlist or attempt to bypass
playlist authentication. Personal exports, cache files, and generated workbooks
are ignored by Git; `uv.lock` is intended to be versioned.

All JSON files must contain a top-level object with a `contents` array. Minified
JSON is accepted. Every file is validated before any API calls or output changes;
invalid files produce a clear error and exit code 1. Inputs are never rewritten.
An empty array is valid; no JSON files is an error.

Pages are read in filename order. Usable items need a nonempty `onClick.URLPage`.
The first usable occurrence of each `contentID` wins. Items without an ID are
retained individually but not cached. Missing optional metadata stays blank.
Movies, TV movies, documentaries, shows, and seasons are retained without
assuming that `VoD` means a theatrical movie. Non-object entries and entries
without detail URLs are skipped with a warning.

## Retrieving the playlist inputs

The tracker does not authenticate to myCANAL itself. Playlist responses must be
retrieved manually from your own myCANAL session using your browser's DevTools.

1. Sign in to myCANAL in your browser and open the **Mes Vidéos** page containing
   your playlist.
2. Open the browser DevTools (`F12` or `Ctrl+Shift+I` / `Cmd+Option+I`).
3. Open the **Network** tab.
4. Reload the **Mes Vidéos** page if necessary to capture its network requests.
5. Filter the requests for `hodor` and locate the request returning the playlist
   contents as JSON (usually named `<digits>.json`). JSON should contain
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

`cache/details.json` stores successful extracted dates (including unknown dates),
retrieval timestamps, effective request URLs and statuses for 24 hours. HTTP/parsing failures
are not cached. A changed URL invalidates the cached item, which matters when a
series points to a different season. Corrupt entries are treated as misses.
This also distinguishes `detailV5` from legacy responses: an older entry is reused
only if its URL matches the requested representation. Unaffected entries retain
their existing TTL and refresh behavior; no cache migration is needed.
Cache read/write failures are logged and do not prevent reporting. Cache writes
use a temporary file and atomic replacement. Run one exporter at a time.

```sh
uv run python main.py --refresh
```

`--refresh` ignores existing entries and updates the cache after successful
retrievals. Configure the default delay in `src/canal_api.py` and cache lifetime
in `src/cache.py`. All paths are relative to the project, even when invoked from
another working directory.

## Excel output

The regenerated file is `output/ma-liste-canal.xlsx`, with one `Ma liste` sheet:

- A native Excel Table with filters, frozen header and bounded column widths.
- French date formatting (`dd/mm/yyyy`), integer days remaining and clickable links.
- Content IDs retained in a hidden column, and `Oui`/`Non` offer membership.
- Soonest availability dates first, with unknown dates and errors at the end.
- Entire rows colored red for past dates or 0–2 days, orange for 3–7 days,
  yellow for 8–30 days, and no urgency color beyond 30 days or for unknown dates.

The first columns are `Titre`, `Catégorie`, `Sous-genre`, `Service`.
`Catégorie` still comes from playlist metadata. `Sous-genre` uses `detail.subgenre`
first, falling back to `tracking.dataLayer.subgenre` when the first value is missing,
null, non-string, empty or whitespace-only. The selected string is preserved unchanged,
even when it duplicates `Catégorie`; if neither value is usable, it stays blank. It is cached alongside
the date without extra requests. Older cache entries stay valid and leave this
column blank until their normal expiration or an explicit `--refresh`.

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

A show/season may lack its own availability date: it is then `Date inconnue`.
V1 does not crawl episodes or infer a series expiration from episode dates.
An empty playlist generates a Table with one blank data row (required by Excel).
Close the workbook in Excel before regenerating it if your platform locks open files.


### Duration and absolute availability text

`Durée` uses the observed detailV5 `detail.duration` integer in minutes only when
`detail.genre` is `Cinéma`. For example, 107 becomes `1 h 47 min`; 60 becomes
`1 h 00 min`, and 47 becomes `47 min`. Series and unrecognized schemas stay blank;
no episode aggregation or additional duration requests are made. Missing, non-integer,
boolean and nonpositive durations stay blank. Legacy duration fields have not been
verified and are not guessed.

`Disponible jusqu’au` uses the same canonical timestamp selected for the date,
interpreted as Unix milliseconds and explicitly converted to `Europe/Paris`.
French weekday/month names are independent of system locale; the label has no year
and uses a 24-hour clock with `h` (for example `mercredi 30 septembre 23h59`).
This follows the required exact example rather than a colon separator.
Relative API labels are never copied. Without a valid timestamp, including a
label-only date fallback, this field stays blank. `Fin de disponibilité` remains
a real Excel date.

Both new fields are cached alongside the date. Older cache entries remain valid
and leave these fields blank until normal expiry or `--refresh`.

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
