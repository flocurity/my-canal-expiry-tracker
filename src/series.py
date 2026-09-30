"""Fetch season catalogs and calculate a backlog from fresh playlist resume state."""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from log import get_logger
from src.timing import timeit
from src.canal_api import CanalClient, DetailError, validate_api_url
from src.expiration import availability_from_raw
from src.detail import ResumeFallback
from src.playlist import PlaylistItem

if TYPE_CHECKING:
    from src.cache import DetailCache

log = get_logger(__name__)


def positive_number(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def identifier(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r'[\w-]+', value, re.ASCII) else ''


def parse_duration_label(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d+)\s*min\s*', value)
    if match:
        return positive_number(int(match[1]))
    match = re.fullmatch(r'\s*(\d+)\s*h\s*([0-5]\d)\s*(?:min)?\s*', value)
    return positive_number(int(match[1]) * 60 + int(match[2])) if match else None


@dataclass(frozen=True)
class Season:
    content_id: str
    number: int


@dataclass(frozen=True)
class Episode:
    content_id: str
    number: int
    duration_minutes: int | None
    availability_end_date: int | float | None


@dataclass(frozen=True)
class SeasonCatalog:
    season: Season
    seasons: tuple[Season, ...]
    episodes: tuple[Episode, ...]

    def to_cache(self) -> dict:
        return {'season': asdict(self.season),
                'seasons': [asdict(season) for season in self.seasons],
                'episodes': [asdict(episode) for episode in self.episodes]}

    @classmethod
    @timeit()
    def from_cache(cls, raw: object) -> 'SeasonCatalog':
        if not isinstance(raw, dict):
            raise ValueError('Invalid season catalog')
        season = _cached_season(raw.get('season'))
        seasons_raw, episodes_raw = raw.get('seasons'), raw.get('episodes')
        if not isinstance(seasons_raw, list) or not isinstance(episodes_raw, list):
            raise ValueError('Invalid cached catalog lists')
        seasons = tuple(_cached_season(value) for value in seasons_raw)
        episodes = []
        for value in episodes_raw:
            if not isinstance(value, dict) or not positive_number(value.get('number')):
                raise ValueError('Invalid cached episode')
            episode_id = value.get('content_id')
            if not isinstance(episode_id, str) or (episode_id and not identifier(episode_id)):
                raise ValueError('Invalid cached episode ID')
            timestamp = value.get('availability_end_date')
            if timestamp is not None and availability_from_raw(timestamp)[0] is None:
                raise ValueError('Invalid cached episode timestamp')
            minutes = value.get('duration_minutes')
            if minutes is not None and positive_number(minutes) is None:
                raise ValueError('Invalid cached episode duration')
            episodes.append(Episode(episode_id, value['number'], minutes, timestamp))
        _validate_catalog(season, seasons, episodes)
        return cls(season, seasons, tuple(episodes))


def _cached_season(raw: object) -> Season:
    if (not isinstance(raw, dict) or not identifier(raw.get('content_id'))
            or not positive_number(raw.get('number'))):
        raise ValueError('Invalid cached season')
    return Season(raw['content_id'], raw['number'])


def _validate_catalog(season: Season, seasons: tuple[Season, ...], episodes: list[Episode]) -> None:
    if (not seasons or season not in seasons
            or len({s.content_id for s in seasons}) != len(seasons)
            or len({s.number for s in seasons}) != len(seasons)):
        raise ValueError('Missing or ambiguous season selector')
    ids = [e.content_id for e in episodes if e.content_id]
    if len(set(ids)) != len(ids) or len({e.number for e in episodes}) != len(episodes):
        raise ValueError('Duplicate episode identities or numbers')


def parse_catalog(payload: dict, season_id: str,
                  fallback_selector: list | None = None) -> tuple[SeasonCatalog, dict[str, str]]:
    block = payload.get('episodes')
    if not isinstance(block, dict) or not isinstance(block.get('contents'), list):
        raise ValueError('Missing episodes contents')
    paging = block.get('paging')
    # Observed paging exposes cursors but no verified continuation URL. Never
    # turn a partial catalog into complete totals by guessing cursor semantics.
    if not isinstance(paging, dict) or paging.get('hasNextPage') is not False:
        raise ValueError('Incomplete pagination: no verified continuation URL')
    if paging.get('hasPreviousPage') is not False:
        raise ValueError('Catalog start page is incomplete or unknown')
    count = paging.get('nbContents')
    if type(count) is int and count != len(block['contents']):
        raise ValueError('Paging count disagrees with returned episode count')
    selector = payload.get('selector', fallback_selector)
    if not isinstance(selector, list):
        raise ValueError('Missing season selector')
    seasons, urls = [], {}
    for value in selector:
        if (not isinstance(value, dict) or not identifier(value.get('contentID'))
                or not positive_number(value.get('seasonNumber'))):
            raise ValueError('Invalid season selector entry')
        seasons.append(Season(value['contentID'], value['seasonNumber']))
        click = value.get('onClick')
        if isinstance(click, dict) and isinstance(click.get('URLPage'), str):
            urls[value['contentID']] = click['URLPage']
    current = [season for season in seasons if season.content_id == season_id]
    if len(current) != 1:
        raise ValueError('Requested season absent from selector')
    season = current[0]
    episodes = []
    for value in block['contents']:
        if (not isinstance(value, dict) or not positive_number(value.get('episodeNumber'))
                or positive_number(value.get('seasonNumber')) != season.number):
            raise ValueError('Missing or inconsistent episode coordinates')
        minutes = parse_duration_label(value.get('durationLabel'))
        if minutes is None:
            log.warning('series_duration_unknown', season_id=season_id,
                        episode_number=value['episodeNumber'])
        timestamp = value.get('availabilityEndDate')
        if availability_from_raw(timestamp)[0] is None:
            timestamp = None
        episodes.append(Episode(identifier(value.get('contentID')), value['episodeNumber'],
                                minutes, timestamp))
    _validate_catalog(season, tuple(seasons), episodes)
    return SeasonCatalog(season, tuple(seasons), tuple(episodes)), urls


@dataclass(frozen=True)
class SeriesBacklog:
    resume_episode: str
    episodes_remaining: int
    duration_minutes: int | None
    availability_end_date: int | float | None


class SeriesIncomplete(DetailError):
    """Keep a safely matched resume episode when a later catalog fails."""

    def __init__(self, error: DetailError | ValueError, resume_episode: str) -> None:
        status = error.status if isinstance(error, DetailError) else 'Série incomplète'
        super().__init__(str(error), status)
        self.resume_episode = resume_episode


def _tracking_number(value: object, name: str) -> int | None:
    """Tracking may be nested under an action or its onClick object."""
    found = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            number = positive_number(node.get(name))
            if number is not None:
                found.add(number)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return next(iter(found)) if len(found) == 1 else None


def _navigation(payload: dict) -> tuple[str, str, int | None, int | None]:
    layout = payload.get('actionLayout')
    actions = layout.get('primaryActions') if isinstance(layout, dict) else None
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            click = action.get('onClick')
            if not isinstance(click, dict):
                continue
            url = click.get('URLEpisodesList')
            if isinstance(url, str):
                return (url, identifier(click.get('contentID')),
                        _tracking_number(action, 'seasonNumber'),
                        _tracking_number(action, 'episodeNumber'))
    # Tabs can provide catalog navigation, but cannot invent a resume episode.
    tabs = payload.get('tabs')
    if isinstance(tabs, list):
        for tab in tabs:
            url = tab.get('URLPage') if isinstance(tab, dict) else None
            if isinstance(url, str) and urlsplit(url).path.startswith('/api/v2/mycanal/episodes/'):
                return url, '', None, None
    raise ValueError('Missing episodes navigation')


def _url_season(url: str) -> str:
    validate_api_url(url, 'episodes')
    values = [value for key, value in parse_qsl(urlsplit(url).query) if key == 'seasonID']
    return identifier(values[0]) if len(values) == 1 else ''


def _for_season(url: str, season_id: str) -> str:
    # Reuse the API endpoint and its observed seasonID parameter. This is needed
    # when detail suggests an earlier episode/season than the current playlist.
    current_season = _url_season(url)
    if current_season == season_id:
        return url
    if not current_season or not identifier(season_id):
        raise ValueError('Missing usable seasonID in episodes navigation')
    parsed = urlsplit(url)
    query = [(key, season_id if key == 'seasonID' else value)
             for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _legacy_selector(payload: dict | None) -> list | None:
    if payload is None:
        return None
    detail = payload.get('detail')
    parent = payload.get('parentShow')
    for source in (detail, parent):
        values = source.get('seasons') if isinstance(source, dict) else None
        if isinstance(values, list) and values:
            # Legacy URLs target detail pages, not catalogs. Keep only structured
            # season identities; reuse the existing episodes endpoint if needed.
            return [{'contentID': value.get('contentID'),
                     'seasonNumber': value.get('seasonNumber')}
                    if isinstance(value, dict) else {} for value in values]
    return None


@timeit()
def enrich_series(item: PlaylistItem, client: CanalClient, cache: 'DetailCache',
                  load_detail: Callable[[], dict], refresh: bool = False) -> SeriesBacklog:
    payload = None
    base_url = ''
    urls: dict[str, str] = {}
    
    def navigation() -> tuple[str, str, int | None, int | None]:
        nonlocal payload, base_url
        if payload is None:
            payload = load_detail()
        result = _navigation(payload)
        base_url, episode_id, season_number, episode_number = result
        season_id = _url_season(base_url)
        if season_id and (episode_id or episode_number):
            detail = cache.get(item.content_id)
            if detail is not None:
                cache.put(item.content_id, replace(detail, resume_fallback=ResumeFallback(
                    season_id, episode_id, season_number, episode_number,
                )))
        return result

    # Do not let a conflicting detail action replace even an unmatchable explicit
    # playlist point: uncertainty is safer than counting from the wrong episode.
    season_id = identifier(item.season_id)
    episode_id = identifier(item.episode_id)
    season_number, episode_number = item.season_number, item.episode_number
    if not season_id or not (episode_id or episode_number):
        detail = None if refresh else cache.get(item.content_id)
        fallback = detail.resume_fallback if detail is not None else None
        if fallback is None:
            url, fallback_id, fallback_season, fallback_episode = navigation()
            fallback = ResumeFallback(_url_season(url), fallback_id,
                                      fallback_season, fallback_episode)
        if season_id and season_id != fallback.season_id:
            raise ValueError('Incomplete playlist resume point conflicts with detail')
        if episode_id and fallback.episode_id and episode_id != fallback.episode_id:
            raise ValueError('Incomplete playlist resume point conflicts with detail')
        season_id = season_id or fallback.season_id
        episode_id = episode_id or fallback.episode_id
        season_number = season_number or fallback.season_number
        episode_number = episode_number or fallback.episode_number
    if not season_id or not (episode_id or episode_number):
        raise ValueError('Missing usable resume season/episode')

    def catalog_for(requested_id: str) -> SeasonCatalog:
        catalog = None if refresh else cache.get_season(item.content_id, requested_id)
        if catalog is not None:
            return catalog
        if requested_id in urls:
            url = urls[requested_id]
            if _url_season(url) != requested_id:
                raise ValueError('Selector URL disagrees with season ID')
        else:
            if not base_url:
                navigation()
            url = _for_season(base_url, requested_id)
        response = client.fetch_episodes(url, item.content_id)
        catalog, discovered = parse_catalog(response, requested_id, _legacy_selector(payload))
        urls.update(discovered)
        cache.put_season(item.content_id, catalog)
        return catalog

    current = catalog_for(season_id)
    if season_number is not None and current.season.number != season_number:
        raise ValueError('Resume season coordinates disagree')
    matches = [episode for episode in current.episodes
               if episode_id and episode.content_id == episode_id]
    if not matches and episode_number is not None:
        matches = [episode for episode in current.episodes if episode.number == episode_number]
    if len(matches) != 1:
        raise ValueError('Resume episode not found safely')
    resume = matches[0]
    remaining = [episode for episode in current.episodes if episode.number >= resume.number]
    resume_label = f'S{current.season.number}E{resume.number}'
    try:
        # The selector is catalog data, not user state. Cached selectors can therefore
        # discover later seasons without fetching detail again on a fully cached run.
        pending = {season.content_id: season for season in current.seasons
                   if season.number > current.season.number}
        known = {season.content_id: season for season in current.seasons}
        visited = {season_id}
        while pending:
            if len(visited) >= 100:
                raise ValueError('Season traversal exceeds safety limit')
            season = min(pending.values(), key=lambda value: value.number)
            del pending[season.content_id]
            if season.content_id in visited:
                continue
            later = catalog_for(season.content_id)
            if later.season != season:
                raise ValueError('Conflicting season metadata')
            remaining.extend(later.episodes)
            visited.add(season.content_id)
            for discovered in later.seasons:
                previous = known.get(discovered.content_id)
                if ((previous is not None and previous != discovered)
                        or any(s.number == discovered.number and s.content_id != discovered.content_id
                               for s in known.values())):
                    raise ValueError('Conflicting later season metadata')
                known[discovered.content_id] = discovered
                if (discovered.number > current.season.number
                        and discovered.content_id not in visited):
                    existing = pending.get(discovered.content_id)
                    if existing is not None and existing != discovered:
                        raise ValueError('Conflicting later season metadata')
                    pending[discovered.content_id] = discovered
        episode_ids = [e.content_id for e in remaining if e.content_id]
        if len(set(episode_ids)) != len(episode_ids):
            raise ValueError('Episode repeated across remaining seasons')
        minutes = None if any(e.duration_minutes is None for e in remaining) else sum(
            e.duration_minutes for e in remaining
        )
        timestamps = [e.availability_end_date for e in remaining
                      if e.availability_end_date is not None]
    except (DetailError, ValueError) as exc:
        raise SeriesIncomplete(exc, resume_label) from exc
    return SeriesBacklog(resume_label, len(remaining),
                         minutes, min(timestamps) if timestamps else None)
