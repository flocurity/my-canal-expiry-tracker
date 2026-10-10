"""Personal backlog selection using the shared Hodor episode catalog."""
import re
from collections.abc import Callable
from dataclasses import dataclass
from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.timing import timeit
from mycanal_hodor_core.episodes import (
    Episode, SeasonCatalog, parse_catalog, parse_duration_label,
    identifier, extract_navigation as _navigation,
    url_season as _url_season, for_season as _for_season,
    legacy_selector as _legacy_selector,
)
from mycanal_hodor_core.http import HodorError
from .canal_api import CanalClient, DetailError, _report_error
from .playlist import PlaylistItem
log = get_logger(__name__)


def is_synthetic_episode_number(episode: Episode) -> bool:
    # The absent-number fallback is strictly positive; explicit zero is editorial.
    if episode.number == 0:
        return False
    content_id = identifier(episode.content_id)
    digits = content_id.replace('_', '')
    if not digits or not re.fullmatch(r'[0-9]+', digits):
        return False
    try:
        return episode.number == int(digits)
    except ValueError:
        return False


def _episode_label(season_number: int, episode: Episode) -> str:
    if not is_synthetic_episode_number(episode):
        return f'S{season_number}E{episode.number}'
    if episode.title and episode.title.strip():
        return episode.title
    log.warning('series_episode_title_unknown', content_id=episode.content_id,
                season_number=season_number)
    return 'Unité non numérotée'


@dataclass(frozen=True)
class ExpirationGroup:
    season_numbers: tuple[int, ...]
    episodes_remaining: int
    duration_minutes: int | None
    availability_end_date: int | float | None


@dataclass(frozen=True)
class SeriesBacklog:
    resume_episode: str
    groups: tuple[ExpirationGroup, ...]


class SeriesIncomplete(DetailError):
    """Keep a safely matched resume episode when a later catalog fails."""

    def __init__(self, error: DetailError | ValueError, resume_episode: str) -> None:
        status = error.status if isinstance(error, DetailError) else 'Série incomplète'
        super().__init__(str(error), status)
        self.resume_episode = resume_episode


@timeit()
def enrich_series(item: PlaylistItem, client: CanalClient,
                  load_detail: Callable[[], dict], *,
                  secrets: tuple[str, ...] = ()) -> SeriesBacklog:
    payload = None
    base_url = ''
    urls: dict[str, str] = {}

    def navigation() -> tuple[str, str, int | None, int | None]:
        nonlocal payload, base_url
        if payload is None:
            payload = load_detail()
        result = _navigation(payload)
        base_url, episode_id, season_number, episode_number = result
        return result

    # Do not let a conflicting detail action replace even an unmatchable explicit
    # playlist point: uncertainty is safer than counting from the wrong episode.
    season_id = identifier(item.season_id)
    episode_id = identifier(item.episode_id)
    season_number, episode_number = item.season_number, item.episode_number
    if not season_id or not (episode_id or episode_number is not None):
        url, fallback_id, fallback_season, fallback_episode = navigation()
        fallback_season_id = _url_season(url)
        if season_id and season_id != fallback_season_id:
            raise ValueError('Incomplete playlist resume point conflicts with detail')
        if episode_id and fallback_id and episode_id != fallback_id:
            raise ValueError('Incomplete playlist resume point conflicts with detail')
        season_id = season_id or fallback_season_id
        episode_id = episode_id or fallback_id
        if season_number is None:
            season_number = fallback_season
        if episode_number is None:
            episode_number = fallback_episode
    if not season_id or not (episode_id or episode_number is not None):
        raise ValueError('Missing usable resume season/episode')

    def catalog_for(requested_id: str) -> SeasonCatalog:
        if requested_id in urls:
            url = urls[requested_id]
            if _url_season(url) != requested_id:
                raise ValueError('Selector URL disagrees with season ID')
        else:
            if not base_url:
                navigation()
            url = _for_season(base_url, requested_id)
        response = client.fetch_episodes(url, item.content_id)
        catalog, discovered = parse_catalog(response, requested_id, _legacy_selector(payload),
                                             diagnostic_secrets=secrets)
        urls.update(discovered)
        return catalog

    current = catalog_for(season_id)
    if season_number is not None and current.season.number != season_number:
        raise ValueError('Resume season coordinates disagree')
    matches = [episode for episode in current.episodes
               if episode_id and episode.content_id == episode_id]
    if not matches and episode_number is not None:
        matches = [episode for episode in current.episodes if not is_synthetic_episode_number(episode) and episode.number == episode_number]
    if len(matches) != 1:
        raise ValueError('Resume episode not found safely')
    resume = matches[0]
    # Editorial numbers describe units; only Hodor list position defines progression.
    resume_index = current.episodes.index(resume)
    start = resume_index + (item.is_completed is True)
    remaining = [(current.season.number, episode) for episode in current.episodes[start:]]
    resume_label = _episode_label(current.season.number, resume)
    try:
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
            remaining.extend((later.season.number, episode) for episode in later.episodes)
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
        episode_ids = [e.content_id for _, e in remaining if e.content_id]
        if len(set(episode_ids)) != len(episode_ids):
            raise ValueError('Episode repeated across remaining seasons')
        partitions: dict[int | float | None, list[tuple[int, Episode]]] = {}
        for number, episode in remaining:
            partitions.setdefault(episode.availability_end_date, []).append((number, episode))
        groups = []
        for timestamp, members in partitions.items():
            minutes = (None if any(e.duration_minutes is None for _, e in members)
                       else sum(e.duration_minutes for _, e in members))
            groups.append(ExpirationGroup(
                tuple(sorted({number for number, _ in members})),
                len(members), minutes, timestamp,
            ))
    except HodorError as exc:
        raise SeriesIncomplete(_report_error(exc), resume_label) from exc
    except (DetailError, ValueError) as exc:
        raise SeriesIncomplete(exc, resume_label) from exc
    if remaining and item.is_completed is True:
        season_number = min(number for number, _ in remaining)
        candidates = [episode for number, episode in remaining if number == season_number]
        episode = candidates[0]
        resume_label = _episode_label(season_number, episode)
    return SeriesBacklog(resume_label if remaining else '', tuple(groups))
