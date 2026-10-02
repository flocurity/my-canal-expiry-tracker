We have now validated a newer and cleaner myCANAL playlist endpoint and want to migrate the acquisition flow to it.

Read AGENTS.md first and inspect the existing implementation/tests before changing anything. Keep changes focused. Do not commit.
Before making any implementation or fixture changes, inspect these four temporary real API captures in `/prompts`:

- `/prompts/test playlist.json`
- `/prompts/new-detailPage.json`
- `/prompts/new-detailShow.json`
- `/prompts/new-detailSeason.json`

They were captured from the new `/me/<HODOR_TOKEN>/lists/playlist` flow and its resulting current detailPage/detailShow/detailSeason URLs on 2026-10-02.

Treat them as the authoritative structural references for the current API. Do not infer the new response structure from old fixtures or from this prompt when these files can answer the question.

Compare them against the existing implementation and synthetic fixtures before editing anything. Identify the structurally relevant differences, especially the fields/nesting actually consumed by playlist, detail, availability, resume and series processing.

Then update the affected fixtures to be small synthetic/sanitized representations of the CURRENT observed structures. Preserve real structure, field names, nesting, types and relevant edge cases, but do not copy production captures wholesale or retain real account-specific data/tokens unnecessarily.

The `/prompts` files are temporary reference material only:
- do not commit them;
- do not make tests depend on them;
- do not copy them into public fixtures unchanged;
- the complete offline suite must still pass after `/prompts` is deleted.

## Goal

Replace the old playlist acquisition based on:

/api/v2/mycanal/page/<HODOR_TOKEN>/<digits>.json

with the playlist endpoint observed directly from the myCANAL homepage:

/api/v2/mycanal/me/<HODOR_TOKEN>/lists/playlist

This migration includes the `--getinfo` Copy-as-cURL parser, acquisition/pagination logic, tests, fixtures, README and SPEC.

The new endpoint has been manually validated against the real API.

## Important: `--getinfo` input must change too

Currently `--getinfo` expects/parses a Copy-as-cURL corresponding to the old `/page/<token>/<digits>.json` endpoint and rejects a cURL copied from the new `/lists/playlist` request.

Change this.

The intended workflow is now:

1. The user opens myCANAL.
2. The browser naturally requests:
   `/api/v2/mycanal/me/<HODOR_TOKEN>/lists/playlist?...`
3. The user uses Firefox "Copy as cURL" on THAT request.
4. `uv run python main.py --getinfo`
5. The user pastes that `/lists/playlist` cURL into the prompt_toolkit multiline input.
6. The program validates it as data, extracts the required authentication/context headers and Hodor token, and retrieves the complete playlist.

The user must no longer need to locate an old `/page/<token>/<digits>.json` request.

Do not execute the pasted cURL. Preserve all existing protections against shell syntax, substitutions, pipes, redirects, metacharacters, etc.

## Observed new endpoint

Representative shape:

https://hodor.canalplus.pro/api/v2/mycanal/me/<32-char-HODOR_TOKEN>/lists/playlist?dsp=detailPage&imageRatio=169&imageSize=normal&titleDisplayMode=all&displayLogo=true&maxContentRemaining=30&discoverMode=true&distmodes=catchup,live,svod,pretvod,tvod,posttvod&stickers=nbo

The real browser request already contains the required authentication/context headers, including:

- `tokenPass`
- `xx-profile-id`

Never persist or log these credentials.

Continue using the established Firefox User-Agent/compression behavior.

Strictly validate the expected HTTPS host and endpoint shape. Do not loosen URL validation merely to make tests pass.

## Pagination: manually validated behavior

For acquisition, request up to 100 items per page:

- `get=100`
- `maxContentRemaining=500`

The new endpoint DOES support `get`; this has been manually verified.

Observed with the current playlist:

page 1:
- 100 contents
- `paging.iterationType == "id"`
- `paging.hasNextPage == true`
- `paging.idStart == base64("arrayconnection:0")`
- `paging.idEnd == base64("arrayconnection:99")`

Then requesting the same `/lists/playlist` endpoint with:

`after=<paging.idEnd>`

returns the remaining 25 contents.

Page 2:
- 25 contents
- `paging.hasNextPage == false`

Use the server-provided opaque cursor. Do not derive/increment/decode it for production pagination.

Preserve the existing defensive behavior:
- first request has no `after`;
- subsequent requests use the previous response's `paging.idEnd`;
- abort on missing/invalid cursor when another page is advertised;
- detect cursor loops;
- maximum 5 pages / 500 items;
- do not attempt to bypass the known playlist limit.

Preserve the browser query parameters required by the new endpoint rather than unnecessarily stripping the request down. Normalize/override only acquisition parameters that the application owns, such as `get`, `maxContentRemaining`, and pagination cursor, where appropriate.

## Raw acquisition files

Preserve the existing transactional acquisition semantics.

Fetch and validate ALL pages before modifying active `input/*.json`.

Only after the entire acquisition succeeds:
- archive previous active JSON files as `.bak`;
- publish the newly acquired pages.

Any invalid cURL, auth failure, malformed response, later-page failure, cursor problem, etc. must leave the previous active inputs untouched.

Continue preserving each API response RAW. Do not merge, normalize or reserialize the responses before saving them.

Continue using portable filenames such as:

YYYY-MM-DD.HH-MM.json
YYYY-MM-DD.HH-MM.page2.json

Do not persist authentication headers.

API-returned Hodor URLs/tokens inside the raw JSON are expected and may remain because `input/` is gitignored.

## New playlist response format

The `/lists/playlist` response has a lighter top-level envelope than the old `/page/.../<digits>.json` response.

The old response could contain fields such as:
- currentPage
- tracking
- paging
- meta
- contents
- displayParameters
- context

The new response observed in production contains:
- currentPage
- contents
- displayParameters
- paging

Do not require removed top-level metadata if the application does not actually need it.

The important `contents` data remains available.

We compared common items between old and new playlist responses and the application-relevant content metadata remains available, including:
- contentID
- type
- title/subtitle and other presentation metadata used by the app
- onClick.path
- onClick.URLPage
- onClick parameters / feature toggle descriptors
- relevant playlist progress/completion data when supplied

## Important: detail URLs changed

The new playlist endpoint can return slightly different `onClick.URLPage` values from the old playlist endpoint.

In particular, observed new detail URLs may omit query parameters such as:

- `dsp=detailPage`
- `sdm=show`

while the corresponding `onClick` structure may expose `displayMode: "detailPage"`.

Do NOT reconstruct the old detail URLs.

Continue treating the playlist's current `onClick.URLPage` as the source URL and apply the existing feature-toggle logic to it.

If the `onClick.parameters` featureToggles descriptor allows `detailV5`, add only `detailV5` using the existing logic.

We manually tested representative current URLs from the new playlist using `featureToggles=detailV5` for:

- `detailPage`
- `detailShow`
- `detailSeason`

All returned usable detail responses.

The critical structures currently used by the tracker remain available:
- `detail.subgenre`
- `detail.availabilityEndDate` where applicable
- `actionLayout`
- `URLEpisodesList` for series
- season IDs
- resume season/episode coordinates

The detail responses still expose the expected major structures such as:
- currentPage
- detail
- meta
- actionLayout
- tabs
- tracking

Therefore adapt the application to the CURRENT URLs/schema rather than trying to preserve old URL query parameters.

## Fixtures

Once the new acquisition format and new detail URL path are proven to work through the application, migrate the relevant test fixtures to represent the CURRENT API structures.

Do not maintain obsolete playlist fixtures merely for historical compatibility unless a test genuinely needs them.

Replace all fixtures representing playlist responses from the old `/page/.../<digits>.json` format with sanitized synthetic fixtures structurally based on the new `/me/<token>/lists/playlist` responses.

Also review detail fixtures affected by the new playlist URL shape. Where existing fixtures represent responses reached through obsolete URL shapes, update them to sanitized/reduced fixtures based on the currently observed detailPage/detailShow/detailSeason structures.

Do NOT replace unrelated fixtures for other endpoints merely for consistency. For example, `/episodes` fixtures should remain based on `/episodes` responses.

As before:
- never put real account data or credentials in fixtures;
- do not store raw production responses unchanged;
- use synthetic fictional values while preserving real structure, field names, nesting, types and edge cases;
- geek/pop-culture fixture values are welcome;
- preserve the semantics being tested.

The objective is that after this migration the test suite documents the API contract the application ACTUALLY uses now, rather than carrying the old `<digits>.json` format indefinitely.

## Tests

Keep normal tests fully offline.

Add/update focused tests for at least:

- parsing a Firefox Copy-as-cURL whose URL is `/me/<token>/lists/playlist`;
- extraction of the 32-character Hodor token from that path;
- extraction of `tokenPass` and `xx-profile-id`;
- >2 KB multiline pasted cURL;
- synthetic tokenPass >1800 characters;
- data after the long header;
- backslash continuations;
- malicious shell syntax remains inert;
- wrong host rejected;
- wrong endpoint rejected;
- malformed Hodor token rejected;
- page 1 with 100 contents;
- pagination using server `paging.idEnd`;
- page 2 with 25 contents and `hasNextPage=false`;
- cursor loop detection;
- missing cursor while `hasNextPage=true`;
- 5-page / 500-item defensive limit;
- transactional failure on a later page leaves existing inputs untouched;
- raw responses are preserved;
- credentials are not persisted;
- new playlist fixture works through the existing playlist parser;
- representative detailPage/detailShow/detailSeason URLs from the new format work with the existing detailV5 URL-building logic;
- application-required fields continue to be extracted from the updated synthetic detail fixtures.

Inspect existing tests first and update/reuse them rather than duplicating coverage.

Do not make ordinary tests perform real network requests.

## Compatibility

This is a migration to the new observed endpoint.

Do not preserve support for the old `/page/<token>/<digits>.json` Copy-as-cURL/acquisition format solely for backward compatibility unless the existing architecture makes retaining it essentially free and harmless.

Prefer one clear current acquisition path over accumulating legacy behavior.

Existing historical `.bak` files do not need to become valid inputs for the new acquisition parser; they are forensic/user backups.

The normal playlist loader should remain robust for the active input files produced by the new acquisition flow.

## Documentation

Update README and SPEC so they describe the real current workflow:

`--getinfo` + Firefox Copy-as-cURL of the `/me/<token>/lists/playlist` request.

Remove obsolete instructions that tell the user to locate `<digits>.json` if they are no longer applicable.

Document pagination and the 500-item defensive limit accurately without claiming undocumented server internals.

Keep security/privacy warnings about Copy-as-cURL because it contains sensitive authentication headers.

## Validation order

Work incrementally.

1. Inspect current code/tests/fixtures and identify assumptions tied to the old endpoint.
2. Implement and run focused acquisition/parser tests.
3. Validate the new playlist fixture through playlist processing.
4. Update relevant fixtures and tests for the current structures.
5. Run focused tests for affected tracker/series/detail behavior.
6. Run the complete offline test suite ONCE at the end.

Do not run integration tests unless there is a specific reason to do so. We already manually validated the representative real detailPage/detailShow/detailSeason responses.

Do not chase unrelated coverage improvements.

Do not refactor unrelated code.

Do not commit.

At the end, report:
- files changed;
- important behavior changes;
- fixture migrations performed;
- focused test results;
- full offline suite result;
- any remaining assumptions or compatibility concerns.