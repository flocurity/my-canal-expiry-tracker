Implement the next series-reporting improvement: split a series into multiple Excel rows when its remaining episodes have different expiration timestamps.

Inspect the current implementation, SPEC.md and tests first. Preserve the existing V1.2 series backlog behavior, cache model, fallback-resume caching, timing instrumentation, movie behavior and Excel formatting unless explicitly changed below.

## Goal

Currently a series produces one Excel row.

Its remaining episode count and duration cover the entire remaining backlog, while its expiration is the earliest known `availabilityEndDate` among those episodes.

This can be misleading.

For example, a series may have:

- resume point: S3E3
- 29 remaining episodes across seasons 3, 4 and 5
- total remaining duration: 10h35
- only the 9 remaining episodes of season 3 expire tomorrow
- seasons 4 and 5 expire later

The current single row looks as though all 29 episodes / 10h35 expire tomorrow.

Instead, partition the remaining backlog by expiration and emit one Excel row per distinct expiration group.

This is a partition, not duplication: every remaining episode must belong to exactly one output group.

## Required semantics

For a series with remaining episodes, group those episodes by their raw canonical `availabilityEndDate`.

Episodes with the same exact valid timestamp belong to the same group even when they are in different seasons.

Different timestamps must remain different groups, even if they convert to the same Europe/Paris calendar date.

Episodes without a valid `availabilityEndDate` belong to one separate unknown-expiration group.

Do not invent an expiration for that group.

Do not group by season.

Do not group by display label.

Do not group by local calendar date.

Use the canonical raw timestamp already stored in the season catalogs.

## Resume point

`Épisode à reprendre` remains the resume point of the series as a whole.

Determine it exactly as V1.2 does today:
- explicit usable playlist resume state remains authoritative;
- otherwise use the cached/fetched detail fallback according to the existing behavior.

Then copy the same resume label to every expiration-group row for that series.

Do NOT replace it with the first episode of each expiration group.

Example:

If the actual resume point is S3E3 and the remaining backlog produces two expiration groups, both rows must display:

`Épisode à reprendre = S3E3`

Even if the second row contains only episodes from seasons 4 and 5.

This may look slightly unusual, but it is intentional: the column answers "where do I resume this show?", not "what is the first episode represented by this row?".

## Episodes remaining

`Épisodes restants` becomes the number of remaining episodes in that expiration group, not the total series backlog.

Across all rows generated for one series:

sum(`Épisodes restants`) == total remaining episode count

No episode may be duplicated between groups.

## Duration

`Durée` becomes the total duration of the episodes in that expiration group.

Keep the existing Excel numeric-duration representation and formatting.

Across all groups, when all relevant episode durations are known:

sum(`Durée`) == total remaining duration

Preserve the existing conservative missing-duration rule at group level:

- if every episode in a group has a usable duration, sum them;
- if at least one episode in that group has an unknown/unusable duration, that group's duration is blank.

An unknown duration in one expiration group must not blank the duration of another complete group.

## Expiration

For a group with a valid timestamp:

- `Fin de disponibilité` uses that group's raw timestamp;
- `Disponible jusqu'au` uses the existing Europe/Paris absolute-date formatting;
- `Jours restants` continues to use the existing dynamic Excel formula and conditional formatting.

For the unknown-expiration group:

- `Fin de disponibilité` is blank;
- `Disponible jusqu'au` follows the existing unknown-expiration behavior;
- `Jours restants` is blank.

There must no longer be a `min(all remaining timestamps)` collapse for the series output.

Each known timestamp becomes its own output row.

## Example

Conceptually, if a show has:

- resume S3E3
- S3E3 through S3E11: 9 episodes, 3h31, expiration A
- all remaining S4/S5 episodes: 20 episodes, 7h04, expiration B

the report should contain two rows equivalent to:

Show | S3E3 | 9  | 3h31 | Saison 3      | expiration A
Show | S3E3 | 20 | 7h04 | Saisons 4 à 5 | expiration B

The `Titre` value remains unchanged across all rows generated for the same series.

For series expiration groups, `Catégorie` must describe the season or season
range actually represented by that row rather than blindly reusing the original
playlist category.

Examples:
- episodes only from season 3 -> `Saison 3`
- episodes spanning seasons 4 and 5 -> `Saisons 4 à 5`
- episodes only from season 5 -> `Saison 5`

Derive this from the structured season numbers of the episodes belonging to the
expiration group, not from the expiration timestamp or the original playlist label.

If a group spans non-contiguous season numbers, do not falsely represent it as a
continuous range; use a truthful representation based on the actual seasons.

This is display metadata only. It must not affect series identity, resume state,
episode grouping, cache identity or API behavior.

The exact existing Excel column order and formatting should otherwise remain unchanged.

If seasons 4 and 5 share expiration B, they belong to the same row.

If they have different expiration timestamps, they become separate rows.

## Ordering

Preserve the report's existing expiration-based sorting.

Series expiration-group rows should therefore naturally sort according to their own expiration timestamps rather than being forced to remain adjacent.

Unknown-expiration groups should follow the existing unknown-date sorting behavior.

Do not add special grouping/merging in Excel just to keep rows for the same show together.

## Movies

Movie behavior must remain unchanged.

A movie still produces exactly one row.

Do not apply series expiration partitioning to movies or other existing non-series behavior.

## Cache and network behavior

This feature must operate entirely from the remaining episode catalogs already used by V1.2.

Do not introduce new API requests merely to build expiration groups.

Preserve the fallback-resume caching behavior that was just added:

- playlist resume state wins;
- cached fallback resume can be reused on normal runs;
- `--refresh` bypasses/refetches it;
- fully cached runs with all required catalogs must remain zero-network.

Do not store derived expiration groups in the cache.

The cache should continue to contain canonical raw episode/catalog data, not Excel/report presentation state.

Do not persist URLs, Hodor tokens, raw detail payloads, progress percentages, credentials, derived durations, derived group counts, or display strings.

## Incomplete catalogs and failures

Preserve the existing conservative V1.2 behavior for incomplete catalogs, pagination uncertainty, conflicting metadata and failed later-season fetches.

Do not manufacture partial expiration groups when the implementation currently considers the overall remaining backlog unsafe/incomplete.

A safely known resume label may continue to survive an incomplete result according to the existing behavior.

Do not weaken existing validation merely to produce grouped rows.

## Data model

Refactor the series result model only as much as necessary.

The implementation should represent zero/one/multiple expiration groups cleanly rather than encoding multiple groups inside display strings.

Keep raw numeric values canonical until report generation.

Prefer a small explicit model for an expiration group if that fits the existing architecture.

Do not duplicate the entire PlaylistItem or report row inside the series layer unless there is a good architectural reason.

## Tests

Add focused regression tests covering at least:

1. One expiration timestamp:
   - series still produces one row;
   - existing count, duration and expiration behavior is preserved.

2. Multiple expiration timestamps:
   - produces multiple rows;
   - each row contains only the episodes belonging to that timestamp;
   - counts and durations are partitioned correctly;
   - total count/duration across rows equals the original backlog.

3. Same expiration across multiple seasons:
   - episodes from those seasons are combined into one row.

4. Different expiration timestamps within the same season:
   - produces separate rows.

5. Resume label:
   - the exact same series resume label appears on every generated row;
   - it is NOT replaced by the first episode of a later expiration group.

6. Unknown expiration:
   - all remaining episodes without a timestamp form one separate unknown group;
   - they are not mixed into a known expiration group;
   - unknown fields remain blank according to existing report behavior.

7. Mixed known and unknown expiration:
   - known groups remain fully usable;
   - unknown episodes form their own row.

8. Missing duration in one group:
   - only that group's duration is blank;
   - other groups retain their valid summed duration.

9. Movies:
   - existing movie regression tests remain unchanged;
   - one movie still produces exactly one row.

10. Network/cache regression:
   - a fully cached second run performs zero detail and zero episodes requests;
   - grouping itself causes no network request;
   - `--refresh` semantics remain unchanged.

11. Excel:
   - multiple rows are actually emitted for a multi-expiration series;
   - `Jours restants` formulas and conditional formatting reference each row's own expiration;
   - duration cells remain numeric/summable;
   - existing column layout is preserved.

Use synthetic fixtures/titles/IDs only. Do not copy private real viewing titles into public tests or documentation.

A synthetic fixture modeled after the already existing multi-season regression is fine.

## Documentation

Update SPEC.md and README.md to explain that series are now partitioned into one report row per distinct remaining-episode expiration timestamp.

Make clear that:
- `Épisode à reprendre` is the same series-level resume point on every row;
- `Épisodes restants` and `Durée` describe only the episodes represented by that row;
- rows with the same title may therefore represent different expiration subsets.

Keep the documentation concise.

## Validation

Run the complete non-integration test suite.

Also verify request-count regressions after the recent fallback-resume cache change.

Report:
- files changed;
- final test count;
- whether fully cached runs remain zero-network;
- the synthetic multi-expiration example and its resulting groups;
- any edge case where the existing conservative incomplete-series behavior prevents grouping.

Do not commit anything.