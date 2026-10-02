# Project: myCANAL Expiry Tracker

I want to create a small Python tool that generates an Excel file from my myCANAL playlist so I can see which content will soon leave the platform.

## General principle

The report reads raw playlist responses from `input/*.json`. Manual DevTools
exports remain supported; optional `--getinfo` acquires them using transient
request context copied from the user's authenticated browser session. The
application implements no login or authentication bypass.

## Optional raw acquisition (`--getinfo`)

Use a native `prompt_toolkit.prompt(..., multiline=True)` for Firefox Copy-as-cURL
from Mes Vidéos. Submit with Esc, then Enter; pass the returned text unchanged to
the existing parser.
Parse it with shell-style tokenization only; never execute shell code or curl.
Accept a GET HTTPS Hodor `/api/v2/mycanal/page/<token>/103412.json` request,
currently validating the observed 32 hexadecimal character token shape. Require
nonempty case-insensitive `tokenPass` and `xx-profile-id` headers. Reject
ambiguous URLs/required headers, unsupported options or request contexts before
network or filesystem changes. Ignore other copied headers/cookies; retain only
the required in-memory context. Do not store or log the pasted text, credentials
or extracted path token. Per user clarification, API-returned tokenized URLs
remain untouched inside raw exports. Refuse bodies echoing authentication
headers/values rather than modifying them.

Use the existing Hodor client transport, Firefox User-Agent, gzip/deflate,
timeouts, pacing and retries, with request-scoped authentication headers and no
redirects. Request page 103412 with `maxContentRemaining=500`, `get=100`,
`featureToggles=detailLight`. First request has no `after`; subsequent requests
use exactly the preceding top-level `paging.idEnd`. Require a top-level
`contents` array and boolean `paging.hasNextPage`. Stop on false; reject
missing/invalid/repeated cursors, malformed responses, more than 100 entries per
page, more than 500 entries total, or a fifth page still indicating continuation.
Never derive cursors or query an authenticated progression endpoint.

Hold all original decompressed response bytes in memory until complete. Do not
merge, reconstruct, normalize or reserialize them. Save one file per response,
with a common Europe/Paris timestamp: `YYYY-MM-DD.HH-MM.json`,
`YYYY-MM-DD.HH-MM.page2.json`, etc. Stage all files before archiving existing
active `*.json` as `.json.bak`. Existing backups are ignored as inputs and never
overwritten: a backup collision aborts with a safe error. Publication uses
same-filesystem no-overwrite moves and rollback on ordinary I/O errors; it cannot
promise atomicity across a process crash or failed rollback. Run one exporter at
a time. Acquisition/validation failure makes no changes to the old active inputs.
No detail/season cache or report is touched by acquisition.

Log page numbers/counts and safe failure categories, never sensitive request
data or response contents. The command exits with code 1 on failure and 0 on
success. Normal tests use synthetic requests and mocked HTTP only. The page ID,
cursor layout and five-page limit follow user-observed API behavior; there is no
live API validation in the offline tests.

## Desired structure

Create a simple structure such as:

    canal-expiry/
    ├── input/
    │   ├── playlist-page-1.json
    │   └── playlist-page-2.json
    ├── output/
    │   └── ma-liste-canal.xlsx
    ├── src/
    │   ├── playlist.py
    │   ├── canal_api.py
    │   └── excel.py
    ├── main.py
    ├── pyproject.toml
    ├── uv.lock
    └── README.md

No need to over-engineer this. It is a small personal tool.

## Playlist JSON format

Each JSON notably contains a `contents` array.

Each item may look like this:

    {
        "type": "VoD",
        "contentID": "29699735_50001",
        "title": "Evanouis",
        "subtitle": "Film Horreur",
        "altLogoChannel": "CANAL+",
        "isInOffer": true,
        "onClick": {
            "displayTemplate": "detailPage",
            "displayName": "Evanouis",
            "path": "/cinema/evanouis/h/29699735_50001",
            "URLPage": "https://hodor.canalplus.pro/api/v2/mycanal/detail/.../29699735_50001.json?detailType=detailPage&objectType=unit&dsp=detailPage&sdm=show&displayLogo=true"
        }
    }

The JSON files may also contain series with `type: "folder"` and `URLPage` values using `detailShow` or `detailSeason`.

Do not assume that `type == "VoD"` necessarily means a theatrical movie. It may also correspond to a TV movie, documentary, etc.

For V1, keep all usable content that has an `onClick.URLPage`.

## Input validation

Before processing playlist data, validate every `.json` file found in `input/`.

For each file:

- verify that it contains valid JSON;
- verify that the top-level structure is compatible with the expected playlist format;
- verify that `contents` exists and is an array;
- report invalid or unusable files clearly.

A formatting style such as minified one-line JSON is valid and must be accepted as-is.

Normal report generation must not modify, reformat, or overwrite input files.

If any input file is invalid or structurally unusable, fail clearly before making API calls or generating the Excel file.

## Playlist merging

Read all `.json` files present in `input/`.

Merge their `contents` arrays.

Deduplicate items using `contentID`.

Keep at least the following fields for each item:

- `contentID`
- `title`
- `subtitle`
- `type`
- `altLogoChannel`
- `isInOffer`
- raw `duration` in milliseconds when present and usable
- literal boolean `isCompleted` (only true excludes the matched series episode);
- `seasonID`, `episodeID`, numeric `seasonNumber`/`episodeNumber` when present,
  and `userProgress` (never used to prorate backlog duration)
- `onClick.path`
- `onClick.URLPage`
- whether `onClick.parameters` declares `detailV5` in a string-array `enum` for
  `{"in": "parameters", "id": "featureToggles"}`

The program must continue gracefully if some optional fields are missing.

## Retrieving content details

For each item, directly call:

    onClick.URLPage

Preserve this source URL. If the item's valid `featureToggles` descriptor declares
`detailV5`, add only `detailV5` to the request query using URL parsing/encoding.
Preserve any toggles explicitly present in the source URL, adding `detailV5` only
if missing and consolidating repeated `featureToggles` keys into one parameter.
Do not copy other enum values. Without a valid declaration, leave the URL unchanged.

These `/detail/` endpoints are publicly accessible without authentication in my tests.

Use `requests` or `httpx`.

Set a reasonable explicit User-Agent.

Network timeout: approximately 10 seconds.

Do not launch hundreds of requests concurrently.

Add a configurable minimum delay of 180 ms between requests by default,
with up to 150 ms of random jitter.
This value must be defined in an easily configurable constant or setting.

Use `requests.Session()` or equivalent to reuse HTTP connections.

## Rate limiting and error handling

The HTTP client must be robust.

For HTTP 429:

1. Check whether the `Retry-After` header is present.
2. If present, respect its value.
3. Otherwise, use exponential backoff with jitter.

Example backoff:

    attempt 1: ~1 second
    attempt 2: ~2 seconds
    attempt 3: ~4 seconds
    attempt 4: ~8 seconds

Add a small random jitter to avoid perfectly synchronized retries.

Also retry on:

- HTTP 502
- HTTP 503
- HTTP 504
- network timeout
- transient connection errors

Do not automatically retry:

- HTTP 400
- HTTP 401
- HTTP 403
- HTTP 404

Limit the number of attempts, for example to 4.

Log errors clearly without aborting the entire process. If one item fails, keep it in the result with an appropriate error status and continue processing the remaining items.

## Expiration date extraction

In the `/detail` JSON response, the exact availability end date has already been observed at:

    detail
      -> informations
      -> contentAvailability
      -> availabilities
      -> download
      -> availabilityEndDate

`availabilityEndDate` is a Unix timestamp expressed in milliseconds.

Real example:

    1793660340000

The response may also contain:

    detail
      -> informations
      -> contentAvailability
      -> availabilities
      -> stream
      -> label

For example:

    "Dispo. jusqu'au 02/11/2026"

Prefer `detail.availabilityEndDate` for detailV5, then
`download.availabilityEndDate` for legacy responses.

If this field is missing, try to retrieve a usable date from the other availabilities, particularly `stream`, and then optionally parse a label such as:

    Dispo. jusqu'au DD/MM/YYYY

Do not fail if no date is available.

In that case, store `None` as the expiration date and set the corresponding status.

Convert timestamps to the `Europe/Paris` local timezone, then use the resulting calendar date for display and for calculating the number of remaining days.

## Remaining days calculation

`Jours restants` is an Excel Table calculated column:

    =IF([@[Fin de disponibilité]]="","",[@[Fin de disponibilité]]-TODAY())

Use English function names and commas in XlsxWriter. Excel recalculates on opening;
`TODAY()` follows the Excel environment's current date. Unknown dates produce an
empty string; zero and negative days remain numeric. Python may supply an initial
cached preview, but the workbook value and row colors must update on recalculation.

Do not use the myCANAL `lastDays` field to determine urgency. It appears much too late, and the purpose of this tool is specifically to anticipate that information.

## Final data

Build a pandas DataFrame ideally containing the following columns:

- `Titre`
- `Sous-genre`
- `Service`
- `Jours restants`
- `Disponible jusqu'au`
- `Épisode à reprendre`
- `Épisodes restants`
- `Durée`
- `Catégorie`
- `Dans l'offre`
- `URL myCANAL`
- `Content ID` (hidden)
- `Fin de disponibilité`
- `Statut`

`Catégorie` may use `subtitle` when available.

`Sous-genre` prefers `detail.subgenre`, falling back to `tracking.dataLayer.subgenre`
when the first value is missing, null, non-string, empty or whitespace-only.
Preserve the selected string unchanged; if neither is usable, keep it empty.
It may duplicate `Catégorie`, which
uses playlist metadata except for series expiration groups, whose seasons it describes. Cache this value with the raw timestamp;
raw cache entries without this optional field remain valid and export an empty value.

`Service` corresponds to `altLogoChannel`.

For `URL myCANAL`, prefer a user-facing URL built from `onClick.path` if this produces a directly usable myCANAL web link. Otherwise, keep the available URL.

`Statut` should distinguish cases such as:

- `OK`
- `Date inconnue`
- `Erreur HTTP`
- `Erreur parsing`


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
and 47 becomes `0 h 47 min`. Series use the remaining-episode duration described
below. No per-episode detail request is made for duration. Missing, non-integer,
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

## V1.2 series backlog

Folder entries use the fresh playlist `seasonID` and `episodeID` as the authoritative
resume point. Trustworthy episode numbers are a fallback for matching within the
identified season; array position and catalog `isCompleted` are not progression sources.
A matching stable episode ID takes precedence over an episode number. A complete
but unmatchable playlist point is not replaced by conflicting detail metadata.
When playlist resume information is incomplete, use detailV5 primary-action
`onClick.contentID`, the `seasonID` query parameter in `URLEpisodesList`, and
structured `seasonNumber`/`episodeNumber` in action tracking (including nested
tracking). Conflicting partial playlist/detail coordinates are left unresolved.
No `/me`, `URLPerso`, tokenPass or authenticated progression endpoint is used.

`Épisode à reprendre` is `S{seasonNumber}E{episodeNumber}` for the safely matched
catalog episode (or the first remaining episode when that episode is completed).
It is immediately followed by numeric `Épisodes restants`, then
`Durée`. Both new columns are blank for movies. Existing movie sourcing, numeric
durations, expiration handling, Excel formulas and formatting are unchanged.

Include the resume episode in full unless the current playlist explicitly has
literal boolean `isCompleted: true`; then exclude only that matched episode.
Missing, false, null or malformed values mean not completed. `userProgress`
never determines completion or prorates duration. Include all numerically later
episodes in that season and every episode in every later season.
Completion is current playlist state, never cached; changing it takes effect on
fresh catalog cache hits without extra requests. Only remaining episodes contribute
to expiration groups. If none remain after complete validation, retain one playlist
row with blank resume/expiration fields, `Date inconnue`, zero remaining episodes
and numeric zero duration. When completion excludes the matched episode, use the first actual remaining
episode by season/episode number as the resume label, repeated on every group row. Ignore
earlier seasons and episodes without fetching earlier catalogs to verify viewing
history. Season and episode ordering uses structured numbers, not contiguous IDs,
array order or descriptions. Duplicate/contradictory identities are rejected.

The public `/episodes` endpoint returns `episodes.contents`, `episodes.paging`
and a top-level `selector`. Selector entries expose `contentID`, `seasonNumber`
and `onClick.URLPage`; use those URLs for later seasons. Structured
`detail.seasons` or `parentShow.seasons` can supply a selector fallback when absent.
They do not themselves supply a resume episode. Detail tabs can supply an episodes
URL when a playlist resume point is already known. A legacy response without any
usable episodes URL remains unsupported rather than triggering speculative requests.

Use the existing client, Firefox-like User-Agent, compression, timeout, pacing,
jitter and retries for all requests. Never append detailV5 to an episodes URL.
If the playlist season differs from the action's season, replace only the existing
`seasonID` query parameter on the API-provided episodes endpoint. The same limited
substitution can recover a missing/stale season's URL after URLs were deliberately
excluded from the cache. Other selector URLs are used as supplied. No endpoints are
constructed from tokens, no per-episode requests are made, and traversal stops with
an explicit incomplete result if it would exceed 100 seasons.

Parse duration labels such as `57 min`, `1h02`, `1h31` (also accepting spaces around
units) into canonical whole minutes. Partition the complete remaining backlog by
exact canonical raw `availabilityEndDate`, across seasons. Different timestamps
remain separate even on the same Paris date; missing/invalid timestamps form one
unknown group with blank expiration fields and `Date inconnue`.

Emit one report row per group, keeping the title and series-level
`Épisode à reprendre` identical. `Épisodes restants` and `Durée` describe only that
group: each episode belongs to exactly one row. One unusable duration blanks only
its group's duration. Excel stores sums as minutes / 1440 with
`[h]" h "mm" min"` formatting. `Catégorie` describes actual structured season
numbers: `Saison 3`, `Saisons 4 à 5`, or `Saisons 3, 5` for non-contiguous seasons.
Rows sort by expiration, including exact timestamps within a date, unknowns last.

Reuse Europe/Paris conversion and the dynamic `Jours restants` formula. No relative
label or series-level date replaces missing episode timestamps. Groups are derived
only after complete catalog validation, never cached, and require no extra requests.
Movie rows, fallback-resume caching and conservative incomplete results are unchanged.

### Catalog completeness and cache

Inspected paging contains `hasNextPage`, `hasPreviousPage`, `idStart`, `idEnd` and
`nbContents`. Both page flags must be false, and a supplied numeric `nbContents`
must match the returned count. No continuation URL was observed. Cursor semantics
have not been verified, so a paginated/partial response produces `Série incomplète`
with blank totals rather than speculative paging or a misleading partial backlog.
The same applies to unknown resume coordinates, missing selectors, malformed
coordinates or conflicting catalogs. HTTP failures retain their existing error
status. If the resume episode was safely matched before a later catalog failed,
keep that label, but leave remaining count, duration and expiration blank. Preserve
trustworthy playlist metadata and subgenre and log structured, URL-free reasons.

Extend the existing `cache/details.json` and its atomic writes/24-hour TTL with
entries keyed `season:{playlist_content_id}:{season_id}`. Each entry contains:

- `kind: "season"`, `brand_id`, `retrieved_at`;
- `catalog.season`: stable `content_id` and `number`;
- `catalog.seasons`: the selector's stable season IDs/numbers, without URLs;
- `catalog.episodes`: `content_id`, `number`, nullable canonical `duration_minutes`
  and nullable raw `availability_end_date` milliseconds.

Store only validated complete catalogs, independently per season. Never persist
playlist resume state, progress, completion flags, action metadata, Hodor URLs/tokens,
credentials or derived totals/display strings. Cache loading validates and
whitelists catalog fields; invalid catalogs are misses. Existing movie entries
remain compatible. Scalar series subgenre entries no longer need a season-bound
resource discriminator; older resource-bound entries can be refreshed when needed.
Failed refreshes preserve prior raw entries without presenting stale data as a
successful fresh result. Complete seasons fetched before another season fails
remain reusable.

A fresh playlist resume change immediately recalculates the backlog against cached
catalogs, including when the resume moves into a cached later season. With usable
playlist resume state and all needed catalogs fresh, no network request is required.
Otherwise fetch approximately one catalog per missing/expired required season, plus
at most one detail request to obtain current navigation. Without usable playlist
resume state, reuse `resume_fallback` in the brand-level detail entry. It contains
only `season_id`, `episode_id` and optional `season_number`/`episode_number` from
detail navigation; it shares the entry's existing `retrieved_at` and 24-hour TTL.
Usable explicit playlist state always wins. Missing/expired fallback requires detail;
`--refresh` bypasses and replaces it. No separate TTL, fingerprint or invalidation
rule is added. Old entries without fallback remain valid and acquire it when detail
is needed. Fully cached catalogs plus fresh fallback need no network request; a
catalog miss may still require fresh detail navigation because URLs are not cached.
`--refresh` also continues to bypass catalog and scalar caches. Selectors refresh with their catalog TTL, so newly published
seasons may require expiry or `--refresh` to become visible.

Schema observations were verified with a small number of public detail/episodes
requests. Default tests remain fully mocked. Fixtures preserve observed nesting
but use synthetic titles, IDs, tokens and progression. Provider-wide coverage and
multi-page navigation remain based on limited observations, not a public API contract.

## Sorting

Sort the DataFrame by expiration date, from nearest to farthest.

Items with no known expiration date must appear at the end.

Use `Jours restants` as a secondary sorting criterion if necessary.

## Excel generation

Use:

- pandas
- XlsxWriter

I already know and want to keep this pattern:

    with pd.ExcelWriter(
        "output/ma-liste-canal.xlsx",
        engine="xlsxwriter"
    ) as writer:

The file must be completely regenerated on each execution.

There is no need to modify an existing workbook.

## Excel table

The main worksheet should be named something like:

    Ma liste

The data must be converted into a real Excel Table using `worksheet.add_table()`.

I want to be able to immediately:

- filter columns;
- sort columns;
- use the Excel Table menus.

Use a standard, readable Excel Table style.

Freeze the header row.

Adjust column widths intelligently, with a reasonable maximum width so that a very long title does not make the worksheet excessively wide.

Display dates using the French format:

    dd/mm/yyyy

Display `Jours restants` as an integer.

Make links clickable when possible.

The `Content ID` column may be hidden in Excel while remaining present in the file.

## Conditional formatting

Apply formatting to the entire row based on `Jours restants`.

The ranges must be mutually exclusive:

- < 0 days (expired): very dark gray background, light gray text
- 0 days (last day): dark red background, white text
- 1 to 2 days inclusive: red
- 3 to 7 days inclusive: orange
- 8 to 30 days inclusive: yellow
- more than 30 days, blank or non-numeric: normal Table formatting

Do not color items with an unknown expiration date.

Use formula rules referencing the dynamic `Jours restants` cell with an
`ISNUMBER` guard. The color must update when Excel recalculates.

Prefer XlsxWriter conditional-formatting mechanisms instead of manually calculating the color of each cell.

Pay attention to Excel row/column references so that the rules remain correct across the entire Table.

## Logging

The provided `log.py` comes from another personal project.

Reuse it as the project's logging implementation.

The code under:

    if __name__ == "__main__":

is demo/test code from the original project and must not be included.

The `hint()` method is specific to the original project and may be removed if unused.

Add `structlog` as a runtime dependency.

Logging conventions and usage rules are defined in `AGENTS.md`.

## Cache

Add a simple local JSON cache to avoid unnecessarily calling all endpoints again during development.

For example:

    cache/
    └── details.json

`cache/details.json` is keyed by playlist `contentID` and keeps raw detail enrichment
for 24 hours. URL, Hodor-token and feature-toggle changes alone do not invalidate
fresh entries. Scalar detail entries can retain `season_content_id` for resource-bound data.
For V1.2 series, scalar subgenre enrichment is brand-level; season-specific data
lives in independently cached season catalogs. Moving the resume point, changing
a token or changing a detail URL does not invalidate those catalogs.

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

Add a CLI option to ignore the cache:

    python main.py --refresh

The cache is mainly intended to avoid unnecessarily spamming the API during development and testing.

## CLI

Keep V1 simple.

Normal command:

    python main.py

Force fresh retrieval:

    python main.py --refresh

Optionally:

    python main.py --delay 0.5

to temporarily change the delay between requests.

Use `argparse`.

## Testing the API behavior

Also create a small separate script, for example:

    tools/test_rate_limit.py

Its purpose is NOT to hammer the API or attempt to bypass its protections.

It is only intended to observe the behavior of a public `/detail` endpoint.

It should:

- perform a limited number of requests;
- measure response time;
- display the HTTP status;
- inspect headers including:
  - `Retry-After`
  - `RateLimit-Limit`
  - `RateLimit-Remaining`
  - `RateLimit-Reset`
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
- stop immediately if HTTP 429 occurs;
- never attempt to bypass the rate limit.

Provide reasonable CLI parameters such as:

    python tools/test_rate_limit.py --url "..." --count 20 --delay 1

The script must not have aggressive default values.

## Required unit test coverage

Add unit tests for the parts that can easily be tested without network access:

- playlist file parsing;
- merging/deduplication;
- `availabilityEndDate` extraction;
- fallback to `stream.label`;
- `days_remaining` calculation;
- sorting with unknown dates at the end.

## HTTP tests and mocks

For tests concerning HTTP client behavior (`canal_api.py`), mock HTTP responses to cover at least:

- HTTP 200 with valid JSON;
- HTTP 429 with `Retry-After`;
- HTTP 429 without `Retry-After`, using exponential backoff;
- HTTP 502 / 503 / 504 with retry;
- network timeout;
- transient connection error;
- HTTP 400 / 401 / 403 / 404 without retry;
- stopping after the maximum number of attempts;
- continuing processing when one item fails.

Also mock `sleep` and, if necessary, random jitter so these tests remain fast and deterministic.

### Mock data and fixtures

Use the provided playlist JSON files and a small number of real `/detail` API responses as references when creating the initial mocked test fixtures.

The goal is for mocked responses to remain structurally representative of the real myCANAL API rather than being arbitrary minimal JSON invented solely for the tests.

When initially creating the fixtures:

- inspect the provided playlist JSON files to identify representative content and endpoint types;
- perform only the few real `/detail` calls necessary to obtain representative response structures;
- use those real responses as the structural basis for the mocked fixtures;
- cover at least the relevant movie, series, and documentary cases when available;
- include representative `detailPage`, `detailShow`, and `detailSeason` structures when they differ meaningfully.

Do not store the raw real API responses as test fixtures unchanged.

Create sanitized, reduced fixtures containing only the fields relevant to the application and tests. Replace real content-specific data with clearly fictional values while preserving the actual API structure, field names, data types, nesting, and relevant edge cases.

Feel free to use geek/pop-culture references for fictional test data, for example titles, IDs, or descriptions inspired by science fiction, programming, games, or similar references.

The fictional values must not change the semantics being tested. For example, timestamps, missing fields, availability structures, HTTP statuses, and malformed data should still accurately represent the corresponding test scenario.

Once created, normal unit tests must use these local fixtures/mocks and must not call the real API to regenerate them automatically.

Automated tests access the real API only through explicitly marked integration tests;
normal application requests and manually invoked acquisition/rate-limit tooling are separate.

## A few real API integration tests

Provide a **small number of smoke tests that actually call the public `/detail` endpoints**.

Use the playlist JSON files currently present in `input/` as the source of real content and API URLs for these integration tests.

These JSON files will be manually refreshed from time to time with recent data from my myCANAL playlist, so integration tests should discover suitable test cases from the available input data rather than relying on hardcoded content IDs, titles, or `/detail` URLs.

When running the integration tests:

- inspect the available playlist items;
- select a small number of representative usable entries;
- use their actual `onClick.URLPage` values for the API calls;
- ideally cover at least one movie, one series, and one documentary when such content can be identified from the provided data;
- cover representative endpoint variants such as `detailPage`, `detailShow`, and `detailSeason` when they are present and meaningfully different.

Do not depend on specific titles or content IDs being permanently present in `input/`.

If a particular content category or endpoint variant is not available in the current input dataset, skip that specific integration case with a clear reason rather than failing the entire integration suite.

The purpose of these tests is to periodically verify that the real API still behaves as expected by the application.

They should only verify relatively stable properties of the API contract, for example:

- HTTP 200 response;
- valid JSON response;
- presence of a usable `detail` structure;
- ability of the application code to extract the expected information without raising an exception;
- extraction of an expiration date when the API actually provides one.

Do not make tests depend on a specific hardcoded expiration date because availability information may change over time.

These integration tests must:

- be explicitly marked, for example with `pytest.mark.integration`;
- **not run by default**;
- require an explicit action to run;
- remain very few in number to avoid unnecessary API calls;
- use only public `/detail` endpoints;
- never deliberately attempt to trigger rate limiting.

Therefore:

    pytest -m "not integration"

runs all unit/mocked tests without network access.

And:

    pytest -m integration

runs only the small number of smoke tests against the real API.

Configure pytest so that running:

    pytest

by default excludes integration tests.

The `tools/test_rate_limit.py` script remains separate from the automated integration tests. It is intended only for manually observing the real rate-limiting behavior.


## README

Document:

1. installing `uv` if necessary;
2. setting up/synchronizing the environment with `uv sync`;
3. where to place the playlist JSON files in `input/`;
4. running the application with `uv run python main.py`;
5. how the cache works;
6. the `--refresh` option;
7. where the generated Excel file is written;
8. how the conditional formatting colors work;
9. how to run the normal mocked/unit test suite;
10. how to explicitly run the small real-API integration test suite.

The README must describe manual export and optional `--getinfo` using the user's existing browser session, without login or authentication bypass.

## First step

Start by examining the example JSON files present in `input/` rather than assuming their exact structure.

Then implement the complete V1.

Once the code is written, run the tests and then run the program against the example JSON files if the environment allows it.
