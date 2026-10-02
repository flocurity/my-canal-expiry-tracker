# Feature: automated raw myCANAL playlist acquisition with `--getinfo`

Implement a new acquisition mode for the existing myCANAL expiry tracker.

The goal is to replace the current manual workflow of exporting one or more playlist JSON responses from browser DevTools.

The user will still authenticate normally in myCANAL in their browser. The application must NOT implement login/authentication.

Instead, the user will copy one authenticated request from the myCANAL "Mes Vidéos" page using Firefox DevTools → "Copy as cURL", paste it into the CLI, and the application will extract the minimum information needed to retrieve the playlist itself.

Before implementing anything:
- Inspect the existing project architecture, `AGENTS.md`, CLI, HTTP client, playlist loader, logging, tests, README and SPEC.
- Reuse existing abstractions where appropriate.
- Make the smallest coherent change.
- Do not duplicate the existing Hodor HTTP/retry logic unnecessarily.
- Keep normal tests fully offline.

## CLI

Add:

    uv run python main.py --getinfo

`--getinfo` is intentionally generic. More information-acquisition features may later be added under this mode, so do not rename it to something playlist-specific.

For now, when invoked, it should interactively ask the user to paste a Firefox "Copy as cURL" request captured from the myCANAL "Mes Vidéos" page.

Example UX, wording can be adapted to the project's existing CLI style:

    Paste the "Copy as cURL" request from myCANAL > Mes Vidéos:
    > ...

Then fetch the complete playlist and save the raw Hodor response page(s) into `input/`.

Do not run the normal report generation as part of `--getinfo` unless the existing CLI architecture makes that explicitly appropriate. Treat this primarily as an acquisition command.

## Security: the pasted cURL is sensitive

The pasted cURL contains authentication/session information.

It MUST be treated as sensitive.

In particular:

- Parse the cURL as text.
- NEVER execute it as a shell command.
- NEVER invoke `curl` with the pasted command.
- NEVER persist the pasted cURL.
- NEVER log the pasted cURL.
- NEVER log or persist `tokenPass`.
- NEVER log or persist `xx-profile-id`.
- NEVER log or persist the Hodor path token extracted from the URL.
- This applies even in debug logging and error paths.
- Error messages must not accidentally include the original cURL or credentials.
- Tests and fixtures must use obviously fake synthetic credentials/tokens only.
- Do not add real captured requests to tests, docs or fixtures.

The repository is public.

## Information to extract

Parse the pasted "Copy as cURL" and extract at least:

1. `tokenPass`
2. `xx-profile-id`
3. the Hodor token present in the request URL path

The Hodor URL shape currently observed is similar to:

    https://hodor.canalplus.pro/api/v2/mycanal/page/<HODOR_TOKEN>/...

Do not hardcode a real token.

Header matching should not unnecessarily depend on header order or capitalization.

The input should be validated before making any API call.

If any required information cannot be extracted:

- fail with a clear non-sensitive error;
- make NO API request;
- make NO modification to `input/`;
- do NOT rename any existing JSON to `.bak`.

Also validate that the pasted request is sufficiently compatible with the expected myCANAL / Mes Vidéos Hodor request before using credentials extracted from arbitrary text.

Do not overfit parsing to one exact Firefox formatting if a small robust implementation can support normal Copy-as-cURL formatting.

## Playlist endpoint

Use the extracted Hodor token to request the playlist page endpoint.

The currently observed page identifier is:

    103412.json

Use these query parameters:

    maxContentRemaining=500
    get=100
    featureToggles=detailLight

The server has been experimentally observed to honor smaller `get` values but clamp values greater than 100 to 100, so use `get=100`.

Do not attempt to bypass the 500-content limit.

For the FIRST request, DO NOT send an `after` parameter.

Without `after`, Hodor starts naturally at playlist index 0.

## Required request context

The playlist request requires authenticated/profile context.

Send:

- `tokenPass`
- `xx-profile-id`

Also preserve/reuse the existing Hodor HTTP behavior already required elsewhere in the project, especially the Firefox-like User-Agent and compressed response handling.

Previous project investigation established that Hodor requests can depend on the Firefox-like User-Agent plus compressed-response behavior, so do not "simplify" those away merely because this particular endpoint may appear more permissive.

Do not blindly forward every header from the copied cURL.

Use only the required extracted authentication/profile data plus the project's established Hodor request behavior.

## Pagination

Pagination must be driven entirely by the server response.

For each response inspect:

    paging.hasNextPage
    paging.idEnd

First request:

    no `after`

If:

    paging.hasNextPage == false

the acquisition is complete.

If:

    paging.hasNextPage == true

then the next request must use the EXACT `paging.idEnd` returned by Hodor as the value of `after`.

Conceptually:

    page 1: no after
    page 2: after=<page 1 paging.idEnd>
    page 3: after=<page 2 paging.idEnd>
    ...

Treat `idEnd` as an opaque server-issued cursor.

Do NOT calculate cursors such as 99, 199, 299 in application code, even though reverse engineering has shown values resembling Base64-encoded `arrayconnection:N`.

Stop immediately when `hasNextPage` is false.

Add defensive pagination checks:

- if `hasNextPage` is true but `idEnd` is missing/invalid, abort;
- if the same cursor is returned again and would create a loop, abort;
- prevent infinite pagination;
- given the known maximum of 500 contents and page size 100, more than 5 pages should be treated as unexpected rather than followed indefinitely.

Do not invent pagination beyond the observed API behavior.

## Preserve RAW Hodor responses

This is important.

Do NOT merge pages into a synthetic JSON document.

Do NOT normalize the response.

Do NOT reconstruct `paging`.

Do NOT modify `contents`.

Do NOT pretty-print/re-serialize a parsed representation if doing so would prevent preserving the original response body.

The files in `input/` are intentionally useful as raw evidence for API debugging, including investigation of "ghost favorite" behavior.

Each saved page must therefore contain the original JSON response from Hodor for that request.

If there is only one page, save one file.

If there are multiple pages, save every raw page separately.

Use one common export timestamp for the complete acquisition.

Preferred portable naming:

    YYYY-MM-DD.HH-MM.json

For additional pages:

    YYYY-MM-DD.HH-MM.page2.json
    YYYY-MM-DD.HH-MM.page3.json
    ...

Use Europe/Paris for the export timestamp.

If the existing project has a clearly preferable filename convention, preserve the intent above while staying consistent.

## Existing input files: archive, never delete

Existing active `*.json` files in `input/` must NOT be deleted.

After a new COMPLETE export has been successfully acquired and validated, rename existing active JSON files:

    filename.json
    -> filename.json.bak

This intentionally makes the existing playlist loader ignore them while preserving them for later debugging/history.

Do not rename existing `.bak` files again.

Never silently overwrite an existing backup. Handle collisions safely and predictably.

## IMPORTANT: transactional behavior

Archiving the old inputs must happen ONLY after the entire new export has been successfully acquired.

The required order is:

1. Read pasted cURL.
2. Parse it.
3. Validate ALL required information:
   - Hodor URL/token
   - `tokenPass`
   - `xx-profile-id`
   - expected request context
4. If validation fails:
   - no API calls;
   - no filesystem changes.
5. Fetch page 1.
6. Validate HTTP success and expected JSON/paging structure.
7. Continue pagination until `hasNextPage == false`.
8. Validate that ALL pages required for this export were acquired successfully.
9. Only now archive previous `input/*.json` files to `.json.bak`.
10. Write/publish the newly acquired raw page files as the active `.json` files.

The old active export must remain untouched if ANY part of acquisition fails.

Examples:

    invalid pasted cURL
    -> old input remains untouched

    401 on page 1
    -> old input remains untouched

    page 1 succeeds, page 2 fails
    -> old input remains untouched

    malformed JSON/paging response
    -> old input remains untouched

    cursor loop
    -> old input remains untouched

Only a complete successful acquisition may replace/archive the previous active input set.

Prefer staging the raw responses in memory or temporary files until acquisition is complete. With at most 5 pages / 500 playlist entries, memory usage is negligible.

If temporary files are used, they must not be mistaken for active tracker inputs and must be cleaned up appropriately.

## Failure behavior

Provide concise useful errors without exposing credentials.

Differentiate where practical between cases such as:

- invalid/unrecognized Copy-as-cURL input;
- missing `tokenPass`;
- missing `xx-profile-id`;
- unable to extract Hodor token;
- authentication failure such as HTTP 401;
- HTTP/API failure;
- invalid JSON;
- unexpected playlist response;
- pagination inconsistency;
- cursor loop;
- incomplete acquisition.

Do not print sensitive request headers or URLs containing the Hodor token in error messages.

## Existing HTTP behavior

Inspect and reuse the existing Canal/Hodor client where sensible.

The project already has:

- Firefox-like User-Agent behavior;
- compressed response support;
- timeout handling;
- retry/backoff behavior;
- 429 handling;
- transient HTTP retry handling;
- structured logging.

Do not regress those behaviors.

However, be careful that authenticated playlist headers such as `tokenPass` and `xx-profile-id` never leak into existing logging.

Do not store these credentials in the existing detail/season cache.

## Tests

Add focused offline tests.

Do NOT make real myCANAL/Hodor requests in the normal test suite.

At minimum cover:

- parsing a synthetic Firefox Copy-as-cURL request;
- header order/case tolerance where appropriate;
- missing `tokenPass`;
- missing `xx-profile-id`;
- missing/invalid Hodor URL/token;
- validation failure causes zero HTTP calls;
- validation failure causes zero filesystem changes;
- first request contains NO `after`;
- request uses `get=100`;
- request uses `maxContentRemaining=500`;
- request uses `featureToggles=detailLight`;
- second request uses exactly the first response's `paging.idEnd`;
- `hasNextPage=false` stops pagination;
- successful one-page acquisition;
- successful multi-page acquisition;
- raw response bodies are preserved in output files;
- page filenames are correct and share one timestamp;
- cursor loop protection;
- `hasNextPage=true` with missing `idEnd`;
- unexpected >5 page behavior;
- page 1 success + later page failure leaves old inputs untouched;
- malformed later response leaves old inputs untouched;
- successful complete acquisition archives previous `*.json` to `.json.bak`;
- existing `.bak` files are not treated as active JSON;
- backup collision cannot silently overwrite data;
- secrets are not present in logs/errors/output/cache.
- Security regression: verify that the pasted user-controlled cURL is treated strictly as data and can never execute commands, shell substitutions, redirects, pipes, or other shell syntax. Include a malicious synthetic input containing command-substitution/shell metacharacters and assert that no command or side effect is executed or created. The implementation must never pass the pasted input through a shell, `eval`, `exec`, `os.system`, or equivalent.

Use synthetic data and fake credentials only.

Follow the project's existing testing conventions and AGENTS.md guidance: focused tests while implementing, then run the full offline suite once at the end.

## Existing playlist loader compatibility

Inspect how the current loader discovers and merges JSON files.

The intended behavior after a successful acquisition is:

    old export.json.bak
    new timestamp.json
    new timestamp.page2.json

The existing normal tracker run should therefore naturally process only the new active `.json` files.

Do not unnecessarily redesign the playlist loader if the existing `*.json` behavior already gives us this.

## Documentation

Update README and SPEC appropriately.

Document the new optional workflow:

    uv run python main.py --getinfo

Explain that the user:

1. logs into myCANAL normally;
2. opens "Mes Vidéos";
3. opens browser DevTools / Network;
4. copies an authenticated Hodor request using "Copy as cURL";
5. runs `--getinfo`;
6. pastes the cURL when prompted.

Clearly warn that the copied request contains sensitive authentication information and must not be shared, committed or stored.

Do not put real credentials, real Hodor tokens, real profile IDs, or the user's real playlist titles in documentation/examples.

Use synthetic examples if needed.

## Non-goals

Do NOT:

- implement myCANAL login;
- persist credentials;
- add browser automation;
- bypass the 500-item playlist limit;
- use `/me`;
- change existing detailV5 logic;
- change series enrichment behavior;
- change cache identity/schema unless genuinely required;
- merge/normalize raw playlist pages;
- add viewing-history functionality;
- add unrelated refactors;
- commit or push anything unless explicitly requested.

## Acceptance criteria

The intended end-user flow is approximately:

    $ uv run python main.py --getinfo
    Paste the "Copy as cURL" request from myCANAL > Mes Vidéos:
    > ...

    Fetching playlist...
    Page 1: 100 contents
    Page 2: 25 contents
    Saved 125 contents:
      input/2026-10-01.18-42.json
      input/2026-10-01.18-42.page2.json

After this:

- the two files contain the untouched raw Hodor responses;
- previous active `.json` exports are now preserved as `.json.bak`;
- normal tracker execution sees only the new active export;
- no authentication material has been persisted;
- a failure at any point before complete acquisition leaves the previous active input completely untouched.

At the end, report:
- files changed;
- architecture/implementation choices;
- tests added;
- focused test result;
- full offline test result;
- any assumptions or API behaviors that remain inferred rather than demonstrated.

Do not commit.


--- Question: 
```
Raw playlist responses may themselves contain tokenized Hodor URLs. If a response contains the extracted request token or credentials, should acquisition abort (preserving raw bodies and avoiding secret persistence), or may API-returned URL tokens remain in the raw export?
```
--- Answer
Preserve API response bodies exactly as returned, including API-returned tokenized Hodor URLs. The purpose of input/ is to retain the original raw Hodor responses for later debugging.

Never persist or log the user-supplied authentication headers/credentials (especially tokenPass and xx-profile-id), and never inject them into the saved response.

Do not reject an otherwise valid raw response merely because it contains Hodor URL tokens returned by the API.


--updates
Please make a small, focused change to the interactive `--getinfo` input.

## Goal

Replace the current line-by-line `input()` implementation used to paste Firefox "Copy as cURL" with `prompt_toolkit`, using its native multiline input support.

The current `read_curl()` loops over `input()` calls until an empty line. Replace that mechanism with a single multiline prompt.

## Requirements

- Add `prompt-toolkit` as a project dependency using the existing `uv` workflow.
- Use `prompt_toolkit.prompt(..., multiline=True)` for the interactive cURL paste.
- The user flow should be:
  1. Run `uv run python main.py --getinfo`
  2. Paste the complete Firefox "Copy as cURL" request.
  3. Press `Esc`, then `Enter` to submit the multiline input.
  4. Continue with the existing parsing/acquisition flow.
- Update the displayed instructions accordingly. Do not tell the user to finish with an empty line anymore.
- Preserve the pasted text as provided by `prompt_toolkit`; do not normalize/reconstruct the cURL unnecessarily.
- Keep the existing cURL parser and security model:
  - pasted content is data only;
  - never execute it;
  - no `shell=True`, `eval`, `exec`, `os.system`, or equivalent;
  - credentials must not be logged or persisted;
  - API-returned Hodor URL tokens may still be preserved in raw playlist responses as already specified.
- Do not change playlist acquisition, pagination, transactional publication, cache behavior, or report generation.
- Do not introduce clipboard-specific/platform-specific handling.

## Tests

Update/add focused offline tests for the new interactive input path.

Include a realistic synthetic multiline Firefox cURL large enough to exercise this use case:
- total input comfortably above 2 KB;
- a synthetic `tokenPass` header longer than 1800 characters;
- required data occurring after the long section as well, so the test verifies that the entire multiline input reaches the existing parser;
- multiline `\` continuations as produced by Firefox;
- no real credentials/tokens.

Keep the existing security regression coverage ensuring malicious shell syntax in pasted input is never executed.

Run focused tests while implementing, then run the full offline test suite once at the end.

Update README/SPEC only where the interactive instructions need to change.

Do not commit.