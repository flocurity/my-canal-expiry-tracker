"""Tracker-only serialization of shared season models; preserves existing cache JSON."""
from dataclasses import asdict
from mycanal_hodor_core.episodes import Season, Episode, SeasonCatalog, identifier, positive_number, season_number, episode_number, validate_catalog
from mycanal_hodor_core.timing import timeit
from .expiration import availability_from_raw


def catalog_to_cache(catalog: SeasonCatalog) -> dict:
    return {'season': asdict(catalog.season),
            'seasons': [asdict(season) for season in catalog.seasons],
            'episodes': [asdict(episode) for episode in catalog.episodes]}


@timeit()
def catalog_from_cache(raw: object) -> SeasonCatalog:
    if not isinstance(raw, dict):
        raise ValueError('Invalid season catalog')
    season = _cached_season(raw.get('season'))
    seasons_raw, episodes_raw = raw.get('seasons'), raw.get('episodes')
    if not isinstance(seasons_raw, list) or not isinstance(episodes_raw, list):
        raise ValueError('Invalid cached catalog lists')
    seasons = tuple(_cached_season(value) for value in seasons_raw)
    episodes = []
    for value in episodes_raw:
        if not isinstance(value, dict) or episode_number(value.get('number')) is None:
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
        title = value.get('title')
        episodes.append(Episode(episode_id, value['number'], minutes, timestamp,
                                title if isinstance(title, str) else None))
    validate_catalog(season, seasons, episodes)
    return SeasonCatalog(season, seasons, tuple(episodes))

def _cached_season(raw: object) -> Season:
    if (not isinstance(raw, dict) or not identifier(raw.get('content_id'))
            or season_number(raw.get('number')) is None):
        raise ValueError('Invalid cached season')
    return Season(raw['content_id'], raw['number'])


