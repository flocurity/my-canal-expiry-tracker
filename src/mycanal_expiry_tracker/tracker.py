"""Process every playlist item, retaining individual failures in the report."""

from dataclasses import dataclass
from datetime import date

from mycanal_hodor_core.diagnostics import debug_failure
from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.timing import timeit
from mycanal_expiry_tracker.cache import DetailCache
from mycanal_expiry_tracker.canal_api import CanalClient, DetailError, build_detail_url
from mycanal_expiry_tracker.detail import DetailData
from mycanal_expiry_tracker.expiration import availability_from_raw, extract_raw_availability
from mycanal_expiry_tracker.playlist import PlaylistItem
from mycanal_expiry_tracker.series import SeriesIncomplete, enrich_series

from mycanal_hodor_core.detail import extract_subgenre, extract_duration

log = get_logger(__name__)


@dataclass(frozen=True)
class ContentResult:
    item: PlaylistItem
    expiration: date | None
    status: str
    subgenre: str = ''
    duration_minutes: int | None = None
    availability_text: str = ''
    resume_episode: str = ''
    episodes_remaining: int | None = None
    season_numbers: tuple[int, ...] = ()
    availability_end_date: int | float | None = None


@timeit()
def process_items(items: list[PlaylistItem], client: CanalClient | None, cache: DetailCache,
                  refresh: bool = False, *, offline: bool = False) -> list[ContentResult]:
    results = []
    for index, item in enumerate(items, start=1):
        expiration = None
        subgenre = ''
        duration_minutes = None
        availability_text = ''
        resume_episode = ''
        episodes_remaining = None
        payload = None
        backlog = None
        # Series-specific dates now live in season catalogs. Scalar series detail
        # enrichment (subgenre) is brand-level, independent of the resume season.
        resource_id = '' if item.content_type == 'folder' else item.season_content_id
        detail = None if refresh else cache.get(item.content_id, resource_id)
        local_incomplete = offline and detail is None
        if detail is not None:
            subgenre = detail.subgenre
            log.debug('cache_hit', content_id=item.content_id)

        def load_detail() -> dict:
            nonlocal payload, detail, subgenre
            if payload is None:
                if offline:
                    raise DetailError('Détail absent des données locales',
                                      'Données locales incomplètes')
                request_url = build_detail_url(item.detail_url, item.supports_detail_v5)
                payload = client.fetch(request_url, item.content_id)
                timestamp, label = extract_raw_availability(payload)
                fallback_minutes = None
                if item.content_type == 'folder':
                    timestamp, label = None, ''
                elif item.movie_duration_minutes is None:
                    fallback_minutes = extract_duration(payload)
                subgenre = extract_subgenre(payload)
                detail = DetailData(timestamp, label, subgenre, fallback_minutes)
                cache.put(item.content_id, detail, resource_id)
            return payload

        try:
            if item.content_type == 'folder':
                backlog = enrich_series(item, client, cache, load_detail, refresh, offline=offline)
                resume_episode = backlog.resume_episode
            else:
                if detail is None:
                    load_detail()
                expiration, availability_text = availability_from_raw(
                    detail.availability_end_date, detail.availability_label,
                )
                duration_minutes = detail.duration_minutes
            status = 'OK' if expiration else 'Date inconnue'
            if local_incomplete:
                status = 'Données locales incomplètes'
        except DetailError as exc:
            if isinstance(exc, SeriesIncomplete):
                resume_episode = exc.resume_episode
            status = exc.status
            log.error('content_failed', content_id=item.content_id, status=status, reason=str(exc))
            debug_failure(log, 'content_failure_debug', exc, content_id=item.content_id)
        except ValueError as exc:
            status = 'Série incomplète' if item.content_type == 'folder' else 'Erreur parsing'
            log.error('content_failed', content_id=item.content_id, status=status, reason=str(exc))
            debug_failure(log, 'content_failure_debug', exc, content_id=item.content_id)
        if backlog is not None:
            if not backlog.groups:
                # A validated empty backlog still represents a playlist item,
                # but has no expiration group to report.
                results.append(ContentResult(
                    item, None, status, subgenre,
                    duration_minutes=0, episodes_remaining=0,
                ))
            for group in backlog.groups:
                expiration, availability_text = availability_from_raw(group.availability_end_date)
                status = 'OK' if expiration else 'Date inconnue'
                if local_incomplete:
                    status = 'Données locales incomplètes'
                results.append(ContentResult(
                    item, expiration, status, subgenre, group.duration_minutes,
                    availability_text, resume_episode, group.episodes_remaining,
                    group.season_numbers, group.availability_end_date,
                ))
        else:
            results.append(ContentResult(item, expiration, status, subgenre,
                                         duration_minutes, availability_text,
                                         resume_episode, episodes_remaining))
        log.info('content_processed', index=index, total=len(items), title=item.title,
                 expiration=expiration, status=status)
    if not offline:
        cache.save()
    return results
