"""Process every playlist item, retaining individual failures in the report."""

from dataclasses import dataclass
from datetime import date

from log import get_logger
from src.cache import DetailCache
from src.canal_api import CanalClient, DetailError, build_detail_url
from src.expiration import extract_availability
from src.playlist import PlaylistItem

log = get_logger(__name__)


@dataclass(frozen=True)
class ContentResult:
    item: PlaylistItem
    expiration: date | None
    status: str
    subgenre: str = ''
    duration: str = ''
    availability_text: str = ''


def extract_subgenre(payload: dict) -> str:
    detail = payload.get('detail')
    if isinstance(detail, dict):
        value = detail.get('subgenre')
        if isinstance(value, str) and value.strip():
            return value
    tracking = payload.get('tracking')
    if not isinstance(tracking, dict):
        return ''
    data_layer = tracking.get('dataLayer')
    if not isinstance(data_layer, dict):
        return ''
    value = data_layer.get('subgenre')
    return value if isinstance(value, str) and value.strip() else ''


def extract_duration(payload: dict) -> str:
    detail = payload.get('detail')
    # Only the observed movie schema is supported; never aggregate series/episodes.
    if not isinstance(detail, dict) or detail.get('genre') != 'Cinéma':
        return ''
    minutes = detail.get('duration')
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        return ''
    hours, minutes = divmod(minutes, 60)
    return f'{hours} h {minutes:02d} min' if hours else f'{minutes} min'


def process_items(items: list[PlaylistItem], client: CanalClient, cache: DetailCache,
                  refresh: bool = False) -> list[ContentResult]:
    results = []
    for index, item in enumerate(items, start=1):
        expiration = None
        subgenre = ''
        duration = ''
        availability_text = ''
        try:
            request_url = build_detail_url(item.detail_url, item.supports_detail_v5)
            hit = False
            if not refresh:
                hit, expiration, subgenre, duration, availability_text = cache.get(item.content_id, request_url)
            if hit:
                log.debug('cache_hit', content_id=item.content_id)
            else:
                payload = client.fetch(request_url, item.content_id)
                expiration, availability_text = extract_availability(payload)
                duration = extract_duration(payload)
                subgenre = extract_subgenre(payload)
                cache.put(item.content_id, request_url, expiration, subgenre,
                          duration, availability_text)
            status = 'OK' if expiration else 'Date inconnue'
        except DetailError as exc:
            status = exc.status
            log.error('content_failed', content_id=item.content_id, status=status, reason=str(exc))
        except ValueError as exc:
            status = 'Erreur parsing'
            log.error('content_failed', content_id=item.content_id, status=status, reason=str(exc))
        results.append(ContentResult(item, expiration, status, subgenre,
                                     duration, availability_text))
        log.info('content_processed', index=index, total=len(items), title=item.title,
                 expiration=expiration, status=status)
    cache.save()
    return results
