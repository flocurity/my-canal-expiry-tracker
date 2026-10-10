# Project: myCANAL Expiry Tracker

I want to create a small Python tool that generates an Excel file from my myCANAL playlist so I can see which content will soon leave the platform.

## General principle

Normal execution authenticates with Core passId by default (shared native keyring
`mycanal-catalog` / `passId`) or explicit `--curl`, acquires the entire playlist in
memory, enriches from zero, saves a report snapshot and generates Excel. Never read
an old snapshot during normal execution. Individual enrichment failures produce
partial results/error rows and are saved; no completeness-management mechanism is
required. No incremental cache, TTL, resume, merge or reuse across executions.

`--from-cache` loads only the latest active timestamped snapshot and generates the
same Excel from its business rows, without authentication, HTTP, enrichment or cache
writes. It does not depend on `input/`. `--refresh` and `--getinfo` are removed.

## Authentication and acquisition

Core owns passId/cURL parsing, renewal, keyring/profile helpers and log redaction.
Expiry retains a separate profile preference from Catalog, selection/confirmation,
and writes the preference only after successful authentication. An invalid remembered
profile has no selection default; network/auth failure cannot delete its preference.
cURL uses the supplied profile and does not update the passId preference.

Validate the exact HTTPS `/api/v2/mycanal/me/<32-hex-token>/lists/playlist` endpoint.
Ignore copied cookies and unrelated headers. Preserve cURL query options except
pagination parameters; use `get=100`, `maxContentRemaining=500`, and server `idEnd`
for `after`. Require valid JSON with unique keys, contents array and boolean
`paging.hasNextPage`. Reject invalid/repeated cursors, >100 items per page, >500 total
or a fifth page still indicating continuation. Acquisition permits only one 401/403
recovery via Core passId and current headers. No periodic rotation; cURL cannot renew.
Keep HodorRuntimeContext immutable. Existing transport pacing/retries remain in Core.

Keep responses and technical navigation URLs in memory only. Never write raw pages
or acquisition profile metadata. Never delete existing `input/` files automatically.
Protect the actual report/snapshot data at persistence boundaries: reject credentials
including token history and Hodor path tokens. Profile IDs are structured auth
metadata, not forbidden substrings in unrelated business text. Retain only validated
HTTPS `www.canalplus.com` URLs without query/fragment; remove Hodor URL fallbacks.
Keep Core's structural redaction rules; profile IDs are excluded from credential
registries used by diagnostics and persistence.

## Project structure and ownership

Three independent projects, with no enclosing uv workspace:

- Public `mycanal-hodor-core`, namespace `mycanal_hodor_core`: conservative Hodor
  transport, URL security, technical errors, JSON decoding, detailV5 transformation,
  raw availability/detail extraction, canonical season/episode models, navigation,
  and shared passId/cURL authentication with native-keyring/profile helpers.
- Public Expiry, namespace `mycanal_expiry_tracker`: acquisition, playlist/personal
  resume state, completion/backlog/groups, report snapshot serialization and offline generation, report
  statuses, Paris/French presentation, Excel and CLI.
- Private Catalog, namespace `mycanal_catalog`: editorial sources/navigation,
  collection traversal/pagination, deduplication, memberships, SQLite and crawl state.

Only the applications depend on Core; Core imports neither application and the
applications never import each other. Shared parsers have one implementation in
Core. Expiry's `canal_api.py` facade retains stricter playlist URL policy and maps
Core technical failures to the existing French report statuses. Report snapshot serialization remains in Expiry. Legacy enrichment caches are ignored.

Each project has its own metadata, environment, lockfile and offline tests. Local
uv source overrides select the unpublished sibling Core during development; wheel
metadata contains only a versioned Core requirement. No runtime data is packaged.
The compatibility root `main.py` retains checkout-relative data paths. The installed
CLI uses the current working directory or explicit `--data-dir` for cache/output,
never the installed package directory.

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

## Playlist validation and merging

Validate acquired JSON pages in memory before enrichment. Require a top-level
object with a `contents` array. Merge page contents and deduplicate by contentID.
Skip malformed entries or entries without a usable onClick.URLPage, preserving
existing graceful handling of optional fields. No file-based playlist loader is
part of runtime behavior.

Retain in memory contentID, title, subtitle, type, altLogoChannel, isInOffer,
duration milliseconds, literal isCompleted, resume season/episode identities and
numbers, onClick.path, onClick.URLPage and validated detailV5 declaration. Progress
is never used to prorate duration. Only the resolved business report values are
persisted; navigation and complete season catalogs are not.

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
uses playlist metadata except for series expiration groups, whose seasons it describes. Save the resulting value in the report snapshot; missing subgenre remains blank.

`Service` corresponds to `altLogoChannel`.

For `URL myCANAL`, build a validated public link from `onClick.path`. Leave the
cell blank when no safe public link is available; never fall back to a Hodor URL.

`Statut` should distinguish cases such as:

- `OK`
- `Date inconnue`
- `Erreur HTTP`
- `Erreur parsing`


### Duration and absolute availability text

`Durée` prefers the current playlist's positive integer `duration` in milliseconds
for `VoD` movies identified by a `Film ` subtitle. For example, `5880000` becomes
`1 h 38 min`. Excel stores `Durée` numerically as minutes / 1440, with format
`[h]" h "mm" min"`, so sums/subtotals work beyond 24 hours. The
effective duration is stored in the report snapshot. Whole minutes are used (any residual
seconds are omitted); values below one minute are unusable for this display.

When playlist movie duration is missing/unusable, the verified detailV5 fallback is
`detail.duration` in integer minutes with `detail.genre == "Cinéma"`. That raw value
contributes to the effective report duration; it also identifies a movie when playlist category
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
fresh enrichment and report snapshots. The playlist supplies current
titles, categories, service, offer membership, paths, URLs and duration. None of
that old enrichment is reused.

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
never determines completion or prorates duration. Include all subsequent units in Hodor list order
in that season and every episode in every later season.
Completion is current playlist state; each normal execution fetches catalogs again
and saves the resolved backlog results. Only remaining episodes contribute
to expiration groups. If none remain after complete validation, retain one playlist
row with blank resume/expiration fields, `Date inconnue`, zero remaining episodes
and numeric zero duration. When completion excludes the matched episode, use the first actual remaining
episode by season number and Hodor list position as the resume label, repeated on every group row. Ignore
earlier seasons and episodes without fetching earlier catalogs to verify viewing
history. Season ordering uses structured season numbers; episode progression uses the
preserved Hodor list order, never editorial episode numbers. Duplicate/contradictory identities are rejected.

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
excluded from the snapshot. Other selector URLs are used as supplied. No endpoints are
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
only after complete catalog validation, saved as final snapshot rows, and require no per-episode requests.
Movie rows, fallback-resume caching and conservative incomplete results are unchanged.

### Catalog validation and partial results

Retain existing completeness, coordinate, identity and selector validation before
computing a series backlog. A later-season failure may retain a safely resolved
resume label, but never publish partial totals as complete. Store the resulting
error row, not partial catalogs. Missing dates/durations remain nullable values.
Selectors, episode order, identities, titles and fallback resume coordinates are
used only during fresh enrichment. No catalog serialization or offline recalculation.

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

Shared logger access, synchronous inclusive `timeit()` and reusable console rendering
live in Core. Importing any Core module must not configure global logging.
Application entry points explicitly choose their configuration; `main()` can also
be embedded with caller-selected processors. Timing preserves function metadata,
return values and original exceptions; logging failure cannot break the operation.
Application-specific timing placement and logging policy remain in Expiry/Catalog.
Root `log.py` is a compatibility import facade with no duplicated implementation.
The console renderer's project-provided provenance is recorded in Core's NOTICE;
applicable MIT notices are preserved.

Logging conventions and usage rules are defined in `AGENTS.md`.

## Report snapshots

Use a single versioned JSON per execution named
`cache/YYYY-MM-DD.HH-MM.cache.json` with a Europe/Paris filename timestamp.
The object contains only `schema_version: 1` and `rows`. Each row stores content_id,
title, subgenre, service, category, nullable in_offer, public_url, nullable ISO
expiration date, nullable availability_end_date sorting timestamp, availability_text,
resume_episode, nullable episodes_remaining, nullable effective duration_minutes,
and status. Keep initial row order for stable sorting. No credentials, Hodor tokens,
raw HTTP, complete catalogs or unnecessary playlist state.

Stage and validate before publication. Archive all existing active snapshots to
`.bak`, without overwriting backups. Abort on timestamp/backup collisions, including
a repeated run within the same minute. Roll back ordinary I/O errors or interruption
during publication. Do not read previous snapshot contents in normal mode. Preserve
them on authentication/acquisition/enrichment interruption; never fall back silently.
Individual enrichment errors are saved in a new snapshot, with their exact statuses.

Offline mode selects the latest validly named active `*.cache.json`, never `.bak`.
Missing/incompatible/invalid latest snapshot is an explicit failure, without fallback.
Offline mode never modifies the snapshot. Legacy `details.json` and old input files
are ignored, not migrated or removed. Publish snapshot before Excel; if Excel fails,
retain the snapshot for offline regeneration. Excel itself uses staged replacement.
Days/formulas may evolve with today's date; all other business values reproduce the
creating execution. Run one exporter at a time.

## CLI

- Default: shared passId authentication, fresh acquisition/enrichment, snapshot, Excel.
- `--curl`: same fresh pipeline using explicit browser authentication.
- `--from-cache`: snapshot-only offline Excel generation.
- `--auth set/delete`: shared credential management only.
- `--delay`: finite nonnegative HTTP pacing, only in network mode.
- `--data-dir`: cache/output location, not keyring/profile preference location.

Reject --from-cache with --curl and --auth with either reporting flag. Reject
explicit --delay with --auth/--from-cache. Removed --refresh/--getinfo are errors.
Validate options before any authentication or filesystem publication.

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

Document setup, authentication, normal/offline commands, snapshots and archival,
partial results, failure behavior, report columns and offline tests. Describe real
API smoke tests as explicit development tools only; never run them by default.

Unnumbered episode units are recognized only when their technical number equals the validated content ID with underscores removed. All seasons use preserved Hodor list order for resume/backlog selection. Distinct content IDs may share a real editorial episode number; number-only resume resolution requires exactly one match. Episode titles are used transiently to resolve the final resume label. Resume labels use the title for unnumbered units, or `Unité non numérotée` with a warning when unavailable, never a technical E-number.

Expiry preserves integer season numbers >= 0, including S0, in acquired playlist data, resume fallback and final report rows. Missing or invalid season numbers are never coerced into zero; episode list order remains Hodor order.

Explicit episode numbers are integers >= 0 (bool and other present invalid types are rejected). Only an absent number uses the positive synthetic identity fallback. Episode zero survives playlist/resume/report handling and follows Hodor list order; current numbered resume labels remain SxE0.
