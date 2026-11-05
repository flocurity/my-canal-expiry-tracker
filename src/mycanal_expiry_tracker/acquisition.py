"""Acquire complete playlist pages in memory using Core authentication."""

import re
from urllib.parse import urlsplit

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
    from mycanal_hodor_core.playlist import acquire_playlist_pages, PlaylistError

    recovered = False

    def fetch_page(url):
        nonlocal recovered
        headers = dict(authentication.headers) if authentication is not None else context.headers
        try:
            return client.fetch_playlist_page(url, headers)
        except DetailError as error:
            if recovered or not recover_authentication(
                    HodorError('Authentication failure', status_code=error.status_code),
                    authentication, headers):
                raise
            recovered = True
            return client.fetch_playlist_page(url, headers)

    try:
        return acquire_playlist_pages(fetch_page, context.hodor_token,
                                      query_parameters=context.query_parameters,
                                      max_pages=5, max_contents=500)
    except PlaylistError as error:
        raise AcquisitionError(str(error)) from None
