# Fixture provenance

On 2026-10-02, four temporary real captures from the new playlist flow were
inspected before updating the fixtures: playlist, detailPage, detailShow and
detailSeason. They are structural references only, never runtime test inputs.

`playlist.json` now models the observed top-level `currentPage` (contentGrid /
playlist), `contents` and cursor `paging`, including its API-provided
`/me/<token>/lists/playlist` URL. Both movie and folder onClick descriptors
advertise detailV5. Movie duration remains integer milliseconds; folders can
provide string season/episode IDs, boolean completion and integer progress.
The folder's brand ID can differ from its detailSeason endpoint ID. This reduced
two-item synthetic export is deliberately complete; the captured page had 100
items. Counts, cursors, resume state, identities and tokens here are synthetic.
Missing optional fields are constructed explicitly in tests.

`detail_show.json` and `detail_season.json` now use the observed flattened
`detail` object rather than the older `detail.informations` shape. Neither current
capture exposes a series availability timestamp, duration, `detail.seasons` or
`parentShow.seasons`. Both expose primary-action `onClick.URLEpisodesList`,
nested `onClick.episodesList`, action-level `tracking.dataLayer` season/episode
numbers and an episodesList tab. Episode descriptors advertise tvodFunnelV5 and
registerProspect, not detailV5. Resume scenarios and URL IDs are fictional;
unrelated player/media/personal endpoints and tracking query values are omitted.
`detail_series_v5.json` uses this same current navigation structure while keeping
its existing synthetic regression scenario. `detail_movie_v5.json` preserves
flat integer-minute duration and availabilityEndDate plus tracking subgenre.
Its synthetic values are intentionally independent of the captured movie.

Legacy availability fixtures below remain to cover supported historical fallbacks.
The current captures do not prove legacy season selectors or episodes pagination;
`episodes_series.json` remains based on the earlier episodes observations.
Acquisition separately validates the current `/me/<token>/lists/playlist` endpoint;
these fixtures contain no authentication header values.
No tests read `prompts/`; deleting the temporary captures does not affect tests.

`detail_documentary.json` is based on an inspected HTTP 200 `detailPage` response.
It preserves the actual availability keys, nesting, timestamp, booleans and generic
stream label, with fictional identity/title and media URLs/irrelevant data removed.
The timestamp must take precedence over the non-date "plus de 3 mois" label.

Movie requests were inconsistent: the full application retrieved 59 known dates,
but targeted movie fixture-inspection requests returned HTTP 403. Therefore
`detail_movie.json` combines the verified `detailPage` availability structure with
the timestamp/dated label observed and documented in SPEC.md; it is not a direct
capture of a successfully inspected movie response. `detail_stream_label.json`
is a deliberate label-only variant for the specified fallback behavior, with the
download availability omitted. Dates and availability semantics remain explicit;
no raw API responses, real titles, content IDs or media URLs are stored here.

Fixtures are local and static. Normal tests never fetch or regenerate them.


`detail_movie_v5.json` is reduced from a successful public detailV5 movie response
inspected on 2026-09-29. The title is fictional. The observed `detail.genre` was
`Cinéma`, `detail.duration` was the integer `98`, and `detail.editorialTitle`
contained `1h38`, confirming minutes. The timestamp and relevant metadata retain
the observed values. No legacy duration field or series duration was inferred.


The movie in `playlist.json` now includes the observed playlist `duration` shape:
integer milliseconds, with 5880000 representing 98 minutes. Local exports on
2026-09-29 contained this field for all observed `Film` items and no duration on
folders. The field also occurs on some non-movie VoD items, so duration alone does
not classify a movie. The detailV5 fixture remains the verified fallback when
playlist movie duration is absent. Cache token regression tests use fictional
same-shape tokens; they never call the network or persist request URLs in cache.


`detail_series_v5.json` and `episodes_series.json` retain the series structures
inspected on 2026-09-29: primary-action `onClick.URLEpisodesList`, action
`tracking.dataLayer` coordinates, `episodes.contents`, `episodes.paging`, and a
top-level selector with structured season numbers and `onClick.URLPage`. Every
title, identity, token and resume scenario is synthetic. Episode counts, durations
and dates form deliberately constructed regressions, not personal viewing exports.
The inspected paging flags were both false and `nbContents` matched the returned
array length; no safe continuation URL was observed. Multi-page/corrupt variants
are synthetic failure cases. Legacy `detail.seasons` was also observed with
structured numbers and IDs; legacy detail URLs are not mistaken for episodes URLs.
