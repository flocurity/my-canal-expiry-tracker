"""Tracker URL policy and report error mapping; transport lives exclusively in Core."""
import re
from urllib.parse import urlsplit
from mycanal_hodor_core import http
from mycanal_hodor_core.http import DEFAULT_DELAY, TIMEOUT_SECONDS, MAX_ATTEMPTS, USER_AGENT


class DetailError(Exception):
    def __init__(self, message: str, status: str = 'Erreur HTTP') -> None:
        super().__init__(message)
        self.status = status


def _report_error(error: http.HodorError) -> DetailError:
    return DetailError(str(error), 'Erreur parsing' if error.kind == 'parsing' else 'Erreur HTTP')


def validate_api_url(url: str, resource: str) -> None:
    try:
        http.validate_api_url(url, resource)
        if resource == 'me' and re.fullmatch(
            r'/api/v2/mycanal/me/[a-fA-F0-9]{32}/lists/playlist', urlsplit(url).path,
        ) is None:
            raise http.HodorError('Expected the Hodor playlist resource')
    except http.HodorError as exc:
        raise _report_error(exc) from None


def validate_detail_url(url: str) -> None:
    validate_api_url(url, 'detail')


def build_detail_url(source_url: str, supports_detail_v5: bool = False) -> str:
    try:
        return http.build_detail_url(source_url, supports_detail_v5)
    except http.HodorError as exc:
        raise _report_error(exc) from None


class CanalClient(http.CanalClient):
    """Compatibility facade: map technical errors, never duplicate HTTP behavior."""
    def fetch(self, url: str, content_id: str = '') -> dict:
        try:
            return super().fetch(url, content_id)
        except http.HodorError as exc:
            raise _report_error(exc) from None

    def fetch_episodes(self, url: str, content_id: str = '') -> dict:
        try:
            return super().fetch_episodes(url, content_id)
        except http.HodorError as exc:
            raise _report_error(exc) from None

    def fetch_playlist_page(self, url: str, headers: dict[str, str]) -> bytes:
        validate_api_url(url, 'me')
        try:
            return super().get_bytes(url, headers)
        except http.HodorError as exc:
            raise _report_error(exc) from None
