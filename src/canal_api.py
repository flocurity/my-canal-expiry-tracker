"""Conservative, sequential Hodor transport shared by reports and acquisition."""

import math
import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import requests

from log import get_logger

log = get_logger(__name__)
DEFAULT_DELAY = 0.18
TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 4
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:156.0) Gecko/20100101 Firefox/156.0'
RETRY_STATUSES = {429, 502, 503, 504}


class DetailError(Exception):
    def __init__(self, message: str, status: str = 'Erreur HTTP') -> None:
        super().__init__(message)
        self.status = status


def validate_api_url(url: str, resource: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == 'https'
            and parsed.hostname == 'hodor.canalplus.pro'
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password
            and parsed.path.startswith(f'/api/v2/mycanal/{resource}/')
            and (resource != 'me' or re.fullmatch(
                r'/api/v2/mycanal/me/[a-fA-F0-9]{32}/lists/playlist', parsed.path
            ) is not None)
            and not any(part in ('.', '..') for part in unquote(parsed.path).split('/'))
            and not any(key.casefold() in ('tokenpass', 'xx-profile-id')
                        for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
            and not parsed.fragment
            and not any(char.isspace() or char == '\\' for char in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise DetailError(f'Expected a public HTTPS hodor.canalplus.pro /{resource}/ URL')


def validate_detail_url(url: str) -> None:
    validate_api_url(url, 'detail')


def build_detail_url(source_url: str, supports_detail_v5: bool = False) -> str:
    if not supports_detail_v5:
        return source_url
    # Validate before rebuilding so parsing cannot hide an invalid source URL.
    validate_detail_url(source_url)
    parsed = urlsplit(source_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    existing = [value for key, value in query if key == 'featureToggles']
    toggles = [toggle for value in existing for toggle in value.split(',') if toggle]
    if len(existing) == 1 and 'detailV5' in toggles:
        return source_url
    if 'detailV5' not in toggles:
        toggles.append('detailV5')
    # Preserve toggles explicitly supplied in the source, not the descriptor enum.
    query = [(key, value) for key, value in query if key != 'featureToggles']
    query.append(('featureToggles', ','.join(dict.fromkeys(toggles))))
    return urlunsplit(parsed._replace(query=urlencode(query)))


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
        return None
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            return max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class CanalClient:
    def __init__(self, delay: float = DEFAULT_DELAY) -> None:
        if not math.isfinite(delay) or delay < 0:
            raise ValueError('Delay must be finite and non-negative')
        self.delay = delay
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        self.session.headers['Accept-Encoding'] = 'deflate, gzip'
        self._has_requested = False
        self._cooldown = 0.0

    def __enter__(self) -> 'CanalClient':
        return self

    def __exit__(self, *args: object) -> None:
        self.session.close()

    def fetch(self, url: str, content_id: str = '') -> dict:
        return self._fetch(url, content_id, 'detail')

    def fetch_episodes(self, url: str, content_id: str = '') -> dict:
        return self._fetch(url, content_id, 'episodes')

    def _fetch(self, url: str, content_id: str, resource: str) -> dict:
        response = self._request(url, content_id, resource)
        try:
            try:
                payload = response.json()
            except ValueError:
                raise DetailError('Response is not valid JSON', 'Erreur parsing') from None
            if not isinstance(payload, dict) or not isinstance(payload.get(resource), dict):
                raise DetailError(f'Missing or invalid {resource} object', 'Erreur parsing')
            return payload
        finally:
            response.close()

    def fetch_playlist_page(self, url: str, headers: dict[str, str]) -> bytes:
        """Return the decompressed response bytes without reserializing JSON."""
        response = self._request(url, '', 'me', headers)
        try:
            return response.content
        finally:
            response.close()

    def _request(self, url: str, content_id: str, resource: str,
                 headers: dict[str, str] | None = None) -> requests.Response:
        validate_api_url(url, resource)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._has_requested:
                time.sleep(max(random.uniform(self.delay, self.delay + 0.15), self._cooldown))
            self._cooldown = 0.0
            self._has_requested = True
            try:
                # Redirects must not turn a validated public URL into another target.
                options = {'headers': headers} if headers is not None else {}
                response = self.session.get(
                    url, timeout=TIMEOUT_SECONDS, allow_redirects=False, **options,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                reason = type(exc).__name__
                status_code = None
                retry_after = None
            except requests.RequestException as exc:
                raise DetailError(type(exc).__name__) from None
            else:
                status_code = response.status_code
                if status_code == 200:
                    return response
                try:
                    if status_code not in RETRY_STATUSES:
                        raise DetailError(f'HTTP {status_code}')
                    reason = f'HTTP {status_code}'
                    retry_after = retry_after_seconds(response.headers.get('Retry-After'))
                finally:
                    response.close()

            if retry_after is not None:
                self._cooldown = retry_after
            else:
                self._cooldown = 2 ** (attempt - 1) + random.uniform(0, 0.25)
            if attempt == MAX_ATTEMPTS:
                # Preserve cooldown across items, including the final 429 attempt.
                raise DetailError(f'{reason}; exhausted {MAX_ATTEMPTS} attempts')
            log.warning('api_retry', content_id=content_id, status_code=status_code,
                        attempt=attempt, delay=max(self.delay, self._cooldown), reason=reason)
        raise AssertionError('Unreachable retry state')
