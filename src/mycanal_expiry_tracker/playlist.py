"""Extract useful playlist fields from acquired pages in memory."""

import json
from dataclasses import dataclass

from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.diagnostics import redact
from mycanal_hodor_core.timing import timeit

from mycanal_hodor_core.episodes import season_number, episode_number
from mycanal_hodor_core.detail import declares_detail_v5 as _declares_detail_v5
from .security import public_url

log = get_logger(__name__)


class PlaylistError(ValueError):
    """Acquired playlist pages cannot be processed."""


@dataclass(frozen=True)
class PlaylistItem:
    content_id: str
    title: str
    subtitle: str
    content_type: str
    service: str
    in_offer: bool | None
    path: str
    detail_url: str
    supports_detail_v5: bool = False
    duration_ms: int | None = None
    season_id: str = ''
    episode_id: str = ''
    season_number: int | None = None
    episode_number: int | None = None
    user_progress: int | None = None
    is_completed: bool = False

    @property
    def movie_duration_minutes(self) -> int | None:
        if (self.content_type == 'VoD' and self.subtitle.casefold().startswith('film ')
                and self.duration_ms is not None and self.duration_ms >= 60_000):
            return self.duration_ms // 60_000
        return None

    @property
    def web_url(self) -> str:
        return public_url(self.path)



def _text(value: object) -> str:
    return value if isinstance(value, str) else ''



@timeit()
def parse_playlist(pages: list[bytes], *, secrets: tuple[str, ...] = ()) -> list[PlaylistItem]:
    contents = []
    for raw in pages:
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise PlaylistError('Invalid playlist JSON') from None
        if not isinstance(data, dict) or not isinstance(data.get('contents'), list):
            raise PlaylistError('Expected an object containing a contents array')
        contents.append(data['contents'])
    items = []
    seen = set()
    for page in contents:
        for raw in page:
            if not isinstance(raw, dict):
                log.warning('playlist_item_skipped', reason='Item is not an object')
                continue
            click = raw.get('onClick')
            if not isinstance(click, dict) or not _text(click.get('URLPage')).strip():
                log.warning('playlist_item_skipped', content_id=redact(_text(raw.get('contentID')), secrets),
                            reason='Missing detail URL')
                continue
            content_id = _text(raw.get('contentID'))
            if content_id and content_id in seen:
                continue
            if content_id:
                seen.add(content_id)
            in_offer = raw.get('isInOffer')
            duration = raw.get('duration')
            items.append(PlaylistItem(
                content_id=content_id,
                title=_text(raw.get('title')),
                subtitle=_text(raw.get('subtitle')),
                content_type=_text(raw.get('type')),
                service=_text(raw.get('altLogoChannel')),
                in_offer=in_offer if isinstance(in_offer, bool) else None,
                path=_text(click.get('path')),
                detail_url=click['URLPage'],
                supports_detail_v5=_declares_detail_v5(click.get('parameters')),
                is_completed=raw.get('isCompleted') is True,
                season_id=_text(raw.get('seasonID')),
                episode_id=_text(raw.get('episodeID')),
                season_number=season_number(raw.get('seasonNumber')),
                episode_number=episode_number(raw.get('episodeNumber')),
                user_progress=(raw.get('userProgress')
                               if type(raw.get('userProgress')) is int else None),
                duration_ms=(duration if isinstance(duration, int)
                             and not isinstance(duration, bool) and duration > 0 else None),
            ))
    log.info('playlist_loaded', pages=len(pages), items=len(items))
    return items
