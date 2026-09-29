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

`cache/details.json` is keyed by playlist `contentID` and keeps raw detail enrichment
for 24 hours. URL, Hodor-token and feature-toggle changes alone do not invalidate
fresh entries. A `detailSeason` additionally records `season_content_id`, the stable
endpoint season ID: real playlists use a brand ID as `contentID` while linking to
a particular season. Changing the season, or switching between show and season,
requires a fetch. No other query parameters participate in cache identity.

Entries contain `retrieved_at`, the canonical `availability_end_date` Unix timestamp
in milliseconds (or null), and `subgenre`. Optional `availability_label` retains only
the dated API label fallback when no timestamp exists; it is never a relative label
or a generated display string. Optional `duration_minutes` retains the verified raw
detail movie duration only when playlist movie duration is unavailable. No URLs,
tokens, playlist metadata, formatted dates/durations, days remaining or derived
statuses are stored.

Missing/expired entries and `--refresh` fetch using the **current playlist URL**,
including the existing detailV5 request handling. Successful fetches replace the
entry; HTTP/parsing failures are not cached and leave any previous raw entry intact.
Old presentation-only entries cannot reconstruct the canonical timestamp and are
treated as misses. Loading drops incompatible entries and strips obsolete fields;
the next cache save persists the cleaned format, including for unvisited entries.
This causes a one-time refetch for old entries. Corrupt entries remain safe misses.
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
- Entire rows use dark gray with light gray text for expired content (< 0 days),
  dark red with white text for the last day (0), red for 1–2 days, orange for
  3–7 days and yellow for 8–30 days. Values above 30, blank or non-numeric
  values retain normal Table formatting.

Column order: `Titre`, `Sous-genre`, `Service`, `Jours restants`,
`Disponible jusqu'au`, `Durée`, `Catégorie`, `Dans l'offre`, `URL myCANAL`,
`Content ID` (hidden), `Fin de disponibilité`, `Statut`.
`Catégorie` still comes from playlist metadata. `Sous-genre` uses `detail.subgenre`
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

A show/season may lack its own availability date: it is then `Date inconnue`.
V1 does not crawl episodes or infer a series expiration from episode dates.
An empty playlist generates a Table with one blank data row (required by Excel).
Close the workbook in Excel before regenerating it if your platform locks open files.


### Duration and absolute availability text

`Durée` prefers the current playlist's positive integer `duration` in milliseconds
for `VoD` movies identified by a `Film ` subtitle. For example, `5880000` becomes
`1 h 38 min`. Movie duration is formatted only when building the report; playlist
duration is never copied into the detail cache. Whole minutes are used (any residual
seconds are omitted); values below one minute are unusable for this display.

When playlist movie duration is missing/unusable, the verified detailV5 fallback is
`detail.duration` in integer minutes with `detail.genre == "Cinéma"`. That raw value
may be cached as `duration_minutes`; it also identifies a movie when playlist category
metadata is missing. A usable current playlist duration takes priority over this
fallback. For example, 107 minutes becomes `1 h 47 min`, 60 becomes `1 h 00 min`,
and 47 becomes `47 min`. Folder/series durations remain blank. No extra request is
made for duration, and no episode aggregation is performed. Missing, non-integer,
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
