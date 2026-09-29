# Fixture provenance

`playlist.json` is a reduced, fictionalized version of the actual `input/page1.json`
and `input/page2.json` item structures. In particular, a season can use a different
endpoint content ID from the playlist's brand content ID.

Public endpoint inspection on 2026-09-28 returned HTTP 200 for `detailShow` and
`detailSeason`. Both contained `detail.informations` without `contentAvailability`.
`detail_show.json` and `detail_season.json` preserve the relevant observed nesting,
with fictional IDs/titles and unrelated metadata omitted. Neither fixture asserts
an expiration for an episode or an entire series.

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
