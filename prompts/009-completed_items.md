Implement one final correction to series backlog calculation: respect the playlist's explicit completion state for the current/resume episode.

Context
-------
The playlist JSON can explicitly mark the current episode as completed:

    "episodeID": "...",
    "seasonID": "...",
    "isCompleted": true,
    "userProgress": 98

This has been observed on real playlist entries whose UI also indicates that the content has already been watched.

`isCompleted` is the authoritative signal here.

Do NOT infer completion from `userProgress`.
For example, `userProgress == 98` alone must NOT be interpreted as completed.

Current behavior
----------------
The series backlog currently includes the matched resume episode in full.

This was intentional in V1.2 because partially watched episodes should count with their full duration.

However, this produces an incorrect result when the playlist explicitly says that the resume episode is completed.

For example, a completed final episode can currently produce:

    Resume: S3E10
    Episodes remaining: 1
    Duration: 50 min

even though Canal explicitly marks that episode as completed.

Required behavior
-----------------
Preserve the existing behavior for normal and partially watched episodes:

    isCompleted missing / false
        -> include the resume episode in full
        -> ignore userProgress for duration calculation

But when:

    isCompleted == true

exclude the matched resume episode itself from the remaining backlog.

Then continue normally with:

- later episodes in the same season;
- all episodes in later seasons.

Examples:

1. Partially watched episode

    Resume: S3E4
    isCompleted: false
    userProgress: 65

    -> S3E4 remains included in full.

2. Completed episode with later episodes

    Resume: S3E4
    isCompleted: true

    -> backlog starts at S3E5.

3. Completed final episode of a season with a later season

    Resume: S2E10
    isCompleted: true

    -> S2E10 is excluded.
    -> backlog continues with S3E1 and later episodes.

4. Completed final episode with nothing after it

    Resume: S3E10
    isCompleted: true

    -> Episodes remaining: 0
    -> Remaining duration: 0
    -> No resume episode should be displayed because there is nothing left to resume.

Keep the playlist row
---------------------
A fully completed series must NOT disappear from the Excel report.

It is still part of the user's playlist and should therefore remain represented.

When no episodes remain:

    Épisode à reprendre: blank
    Épisodes restants: 0
    Durée: 0

Use the existing numeric Excel duration representation/formatting for zero if possible without special-casing the cell as text.

Expiration grouping
-------------------
The current expiration-group behavior must remain unchanged for non-empty backlogs.

Only remaining, non-completed episodes participate in expiration groups.

A completed resume episode must therefore contribute:

- no episode count;
- no duration;
- no expiration timestamp.

If excluding the completed resume episode leaves zero remaining episodes, do not invent an expiration group from that episode.

Preserve the playlist row as described above rather than dropping the content entirely.

Playlist parsing
----------------
Add `isCompleted` to the playlist model/state needed by series enrichment.

Preserve the value as an explicit boolean.

Do not derive it from:

- userProgress;
- subtitle;
- altText;
- episode position;
- being the last episode;
- any other heuristic.

Only literal boolean `true` means completed.

Missing, null, false or malformed values must behave as not completed unless the existing validation conventions suggest rejecting malformed booleans is safer.

Cache behavior
--------------
Do NOT add completion state to the detail or season catalog cache.

`isCompleted` is current playlist/user state, just like the resume coordinates.

The playlist export remains the source of truth.

Therefore a newly exported playlist with a changed `isCompleted` value must immediately affect backlog calculation without requiring `--refresh` or rebuilding cached season catalogs.

Do not change:

- detail cache identity;
- season catalog cache identity;
- TTL behavior;
- request behavior;
- network traversal;
- expiration-group cache behavior.

A fully cached run should remain zero-network when all required catalogs/detail fallback information are already cached.

Tests
-----
Add focused synthetic tests covering at least:

- incomplete/false resume episode remains included;
- partially watched resume episode remains included regardless of userProgress;
- completed resume episode is excluded;
- completed episode followed by episodes in the same season;
- completed final episode followed by a later season;
- completed final episode with no later content produces zero remaining episodes;
- zero-backlog series remains present in the report;
- completed episode's duration is not included;
- completed episode's expiration timestamp is not included in expiration grouping;
- changing only playlist `isCompleted` with fresh caches changes the result with zero network requests;
- movie behavior remains unchanged.

Use synthetic/private-safe fixtures only. Do not copy real viewing titles, content IDs, URLs or tokens into tests or documentation.

Documentation
-------------
Update README/SPEC where appropriate.

In particular, replace the previous V1.2 statement saying that `isCompleted` is not a progression source.

Document the precise distinction:

- `userProgress` does not prorate or determine completion;
- `isCompleted == true` explicitly marks the playlist resume episode as completed and excludes that episode from the remaining backlog;
- partially watched episodes continue to count in full.

Constraints
-----------
Make the smallest coherent change.

Do not redesign series traversal.
Do not change expiration grouping beyond excluding completed episodes.
Do not add new API calls.
Do not use authenticated `/me` endpoints.
Do not optimize unrelated code.
Do not commit.

Preserve the existing timing instrumentation and any unrelated working-tree changes.

Run the focused tests first, then the full offline suite once after implementation.



-----

One clarification before you finish:

When `isCompleted == true` and episodes remain after excluding the matched
completed episode, `Épisode à reprendre` should become the first actual
remaining episode, not stay on the completed episode.

Examples:
- completed S3E4, remaining starts at S3E5 -> display S3E5
- completed S2E10, next remaining episode is S3E1 -> display S3E1
- completed final episode with no remaining episodes -> blank

As before, that resulting resume label is repeated on every expiration-group
row for the series.