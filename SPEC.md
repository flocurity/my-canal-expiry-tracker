# Project: myCANAL Expiry Tracker

I want to create a small Python tool that generates an Excel file from my myCANAL playlist so I can see which content will soon leave the platform.

## General principle

The API used to retrieve my playlist directly requires authentication and currently returns HTTP 403 when called outside the browser.

For this first version, I deliberately do NOT want to automate this part.

I will manually retrieve the JSON responses for my playlist from the browser DevTools and place them in an `input/` directory.

There may be multiple JSON files corresponding to multiple playlist pages (no limit, can be 1 or 10)

The program must automatically read all `.json` files present in `input/`.

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

Do not modify, reformat, or overwrite the input files.

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

Prefer `download.availabilityEndDate`.

If this field is missing, try to retrieve a usable date from the other availabilities, particularly `stream`, and then optionally parse a label such as:

    Dispo. jusqu'au DD/MM/YYYY

Do not fail if no date is available.

In that case, store `None` as the expiration date and set the corresponding status.

Convert timestamps to the `Europe/Paris` local timezone, then use the resulting calendar date for display and for calculating the number of remaining days.

## Remaining days calculation

Calculate:

    days_remaining = end_date - current_date

The calculation must be performed every time the Excel file is generated.

Do not use the myCANAL `lastDays` field to determine urgency. It appears much too late, and the purpose of this tool is specifically to anticipate that information.

## Final data

Build a pandas DataFrame ideally containing the following columns:

- `Titre`
- `Catégorie`
- `Sous-genre`
- `Service`
- `Fin de disponibilité`
- `Jours restants`
- `Dans l'offre`
- `URL myCANAL`
- `Content ID`
- `Statut`

`Catégorie` may use `subtitle` when available.

`Sous-genre` prefers `detail.subgenre`, falling back to `tracking.dataLayer.subgenre`
when the first value is missing, null, non-string, empty or whitespace-only.
Preserve the selected string unchanged; if neither is usable, keep it empty.
It may duplicate `Catégorie`, which
continues to use playlist metadata. Cache this value with the extracted date;
older cache entries without it remain valid and export an empty value.

`Service` corresponds to `altLogoChannel`.

For `URL myCANAL`, prefer a user-facing URL built from `onClick.path` if this produces a directly usable myCANAL web link. Otherwise, keep the available URL.

`Statut` should distinguish cases such as:

- `OK`
- `Date inconnue`
- `Erreur HTTP`
- `Erreur parsing`

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

- 0 to 2 days inclusive: red
- 3 to 7 days inclusive: orange
- 8 to 30 days inclusive: yellow
- more than 30 days: no special color

Do not color items with an unknown expiration date.

If an item has an expiration date in the past, also use red or another clearly identifiable rule.

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

The cache may be indexed by `contentID`.

Store:

- retrieval date/time;
- useful response data or extracted information;
- extracted expiration date.

Use a configurable cache lifetime, for example 24 hours.

Bind cache entries to the effective request URL, including feature toggles. A legacy
URL must not satisfy a newly requested `detailV5` representation. Existing cache
entries remain usable when their URL still matches; TTL and refresh rules stay unchanged.

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

Real API access should remain limited to the explicitly marked integration tests and the manual API/rate-limit tooling.

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

The README must clearly state that the playlist JSON files are manually retrieved from my own myCANAL account and that the program does not attempt to bypass playlist authentication.

## First step

Start by examining the example JSON files present in `input/` rather than assuming their exact structure.

Then implement the complete V1.

Once the code is written, run the tests and then run the program against the example JSON files if the environment allows it.
