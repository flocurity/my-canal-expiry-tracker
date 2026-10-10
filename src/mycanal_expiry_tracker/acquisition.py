"""Acquire complete playlist pages in memory using Core authentication."""

import json
import re
from urllib.parse import urlencode, urlsplit

from mycanal_hodor_core.bootstrap import (
    BootstrapError, HodorRuntimeContext, parse_curl as parse_browser_curl, read_curl,
)
from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.authentication import PassIdAuth, recover_authentication
from mycanal_hodor_core.http import HodorError
from .canal_api import DetailError
from mycanal_expiry_tracker.canal_api import CanalClient

log = get_logger(__name__)


class AcquisitionError(ValueError):
    """A safe, non-sensitive acquisition failure."""


# Keep the existing acquisition API; parsing and interactive input live in Core.
RequestContext = HodorRuntimeContext


def parse_curl(command: str) -> RequestContext:
    try:
        context = parse_browser_curl(command)
    except BootstrapError as exc:
        if 'Hodor API URL' in str(exc):
            raise AcquisitionError('Expected the Mes Vidéos Hodor playlist URL and a valid path token') from None
        raise AcquisitionError(str(exc)) from None
    if not re.fullmatch(r'/api/v2/mycanal/me/[a-fA-F0-9]{32}/lists/playlist',
                        urlsplit(context.request_url).path):
        raise AcquisitionError('Expected the Mes Vidéos Hodor playlist URL and a valid path token')
    return context


def acquire_pages(context: RequestContext, client: CanalClient,
                  authentication: PassIdAuth | None = None) -> list[bytes]:
    def checked_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise AcquisitionError('Unexpected duplicate JSON field')
            result[key] = value
        return result

    pages = []
    recovered = False
    cursors = set()
    cursor = None
    total = 0
    for page_number in range(1, 6):
        query = [(key, value) for key, value in context.query_parameters
                 if key.casefold() not in ('get', 'maxcontentremaining', 'after')]
        query.extend([('get', '100'), ('maxContentRemaining', '500')])
        if cursor is not None:
            query.append(('after', cursor))
        url = (f'https://hodor.canalplus.pro/api/v2/mycanal/me/'
               f'{context.hodor_token}/lists/playlist?{urlencode(query)}')
        headers = dict(authentication.headers) if authentication is not None else context.headers
        try:
            raw = client.fetch_playlist_page(url, headers)
        except DetailError as error:
            if recovered or not recover_authentication(
                    HodorError('Authentication failure', status_code=error.status_code),
                    authentication, headers):
                raise
            recovered = True
            raw = client.fetch_playlist_page(url, headers)
        try:
            payload = json.loads(raw, object_pairs_hook=checked_object)
        except (ValueError, UnicodeError, RecursionError):
            raise AcquisitionError('Response is not valid JSON') from None
        if not isinstance(payload, dict) or not isinstance(payload.get('contents'), list):
            raise AcquisitionError('Unexpected playlist response')
        paging = payload.get('paging')
        if not isinstance(paging, dict) or type(paging.get('hasNextPage')) is not bool:
            raise AcquisitionError('Unexpected playlist paging')
        count = len(payload['contents'])
        total += count
        if count > 100 or total > 500:
            raise AcquisitionError('Unexpected playlist size')
        pages.append(raw)
        log.info('playlist_page_acquired', page=page_number, contents=count)
        if not paging['hasNextPage']:
            log.info('playlist_acquisition_complete', pages=page_number, contents=total)
            return pages
        cursor = paging.get('idEnd')
        if not isinstance(cursor, str) or not cursor.strip() or any(
            ord(char) < 32 for char in cursor
        ):
            raise AcquisitionError('Missing or invalid pagination cursor')
        if cursor in cursors:
            raise AcquisitionError('Pagination cursor loop')
        cursors.add(cursor)
    raise AcquisitionError('Incomplete acquisition: more than five pages indicated')
