"""Validate manually exported playlists before merging their usable entries."""

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from log import get_logger

log = get_logger(__name__)


class PlaylistError(ValueError):
    """One or more playlist files cannot be processed."""


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

    @property
    def movie_duration_minutes(self) -> int | None:
        if (self.content_type == 'VoD' and self.subtitle.casefold().startswith('film ')
                and self.duration_ms is not None and self.duration_ms >= 60_000):
            return self.duration_ms // 60_000
        return None

    @property
    def season_content_id(self) -> str:
        # A playlist brand ID can point to different seasons across exports.
        try:
            parsed = urlsplit(self.detail_url)
            if parse_qs(parsed.query).get('detailType') == ['detailSeason']:
                return Path(parsed.path).stem
        except ValueError:
            pass
        return ''

    @property
    def web_url(self) -> str:
        # Do not let protocol-relative or malformed paths change the link host.
        if self.path.startswith('/') and not self.path.startswith('//'):
            if not any(char.isspace() or char == '\\' for char in self.path):
                return 'https://www.canalplus.com' + self.path
        try:
            parsed = urlsplit(self.detail_url)
            if parsed.scheme == 'https' and parsed.hostname:
                return self.detail_url
        except ValueError:
            pass
        return ''


def _text(value: object) -> str:
    return value if isinstance(value, str) else ''


def _declares_detail_v5(parameters: object) -> bool:
    if not isinstance(parameters, list):
        return False
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        values = parameter.get('enum')
        if (parameter.get('in') == 'parameters'
                and parameter.get('id') == 'featureToggles'
                and isinstance(values, list)
                and all(isinstance(value, str) for value in values)
                and 'detailV5' in values):
            return True
    return False


def load_playlist(directory: Path) -> list[PlaylistItem]:
    paths = sorted(directory.glob('*.json'))
    if not paths:
        raise PlaylistError(f'No .json playlist files found in {directory}')

    pages = []
    errors = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('contents'), list):
                raise ValueError('Expected an object containing a contents array')
            pages.append(data['contents'])
        except (OSError, ValueError) as exc:
            errors.append(f'{path}: {exc}')
    if errors:
        raise PlaylistError('\n'.join(errors))

    items = []
    seen = set()
    for page in pages:
        for raw in page:
            if not isinstance(raw, dict):
                log.warning('playlist_item_skipped', reason='Item is not an object')
                continue
            click = raw.get('onClick')
            if not isinstance(click, dict) or not _text(click.get('URLPage')).strip():
                log.warning('playlist_item_skipped', content_id=raw.get('contentID'),
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
                duration_ms=(duration if isinstance(duration, int)
                             and not isinstance(duration, bool) and duration > 0 else None),
            ))
    log.info('playlist_loaded', files=len(paths), items=len(items))
    return items
