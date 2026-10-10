"""Acquire playlist pages using transient browser-supplied request context."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo

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


def contains_authentication(value: object, context: RequestContext,
                            secrets: tuple[str, ...] = ()) -> bool:
    """Raw bodies cannot be redacted, so refuse an echoed authentication context."""
    if isinstance(value, dict):
        return any(
            key.casefold() in ('passid', 'passtoken', 'tokenpass', 'xx-profile-id')
            or contains_authentication(child, context, secrets)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(contains_authentication(child, context, secrets) for child in value)
    return isinstance(value, str) and (
        any(secret in value for secret in (*secrets, context.token_pass, context.profile_id) if secret)
    )


def _move_without_overwrite(source: Path, destination: Path) -> None:
    # Both paths are on the input filesystem. Unlike rename(), link() refuses
    # an existing destination even if it appeared after the preflight check.
    os.link(source, destination)
    try:
        source.unlink()
    except OSError:
        destination.unlink()
        raise


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
        try:
            secrets = tuple(authentication.secrets) if authentication is not None else ()
            sensitive = contains_authentication(payload, context, secrets)
        except RecursionError:
            raise AcquisitionError('Unexpected JSON nesting') from None
        if sensitive:
            raise AcquisitionError('Response contains authentication data; export refused')
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


def publish_pages(pages: list[bytes], directory: Path,
                  exported_at: datetime | None = None, *,
                  profile_id: str | None = None,
                  cache_directory: Path | None = None) -> list[Path]:
    """Stage fully acquired pages before archiving; roll back ordinary I/O failures."""
    stamp = (exported_at or datetime.now(ZoneInfo('Europe/Paris'))).astimezone(
        ZoneInfo('Europe/Paris')).strftime('%Y-%m-%d.%H-%M')
    destinations = [directory / (stamp + (f'.page{n}' if n > 1 else '') + '.json')
                    for n in range(1, len(pages) + 1)]
    old = sorted(directory.glob('*.json'))
    backups = [(path, path.with_name(path.name + '.bak')) for path in old]
    if any(backup.exists() or backup.is_symlink() for _, backup in backups):
        raise AcquisitionError('Backup already exists; move it before retrying')
    if any(path.is_symlink() or not path.is_file() for path in old):
        raise AcquisitionError('Active input must be a regular file')
    if any(path.exists() and path not in old for path in destinations):
        raise AcquisitionError('Export filename collision')
    profile_file = directory / '.acquisition-profile'
    if profile_file.is_symlink() or (profile_file.exists() and not profile_file.is_file()):
        raise AcquisitionError('Acquisition profile metadata must be a regular file')
    if cache_directory is not None and (cache_directory.is_symlink()
                                       or (cache_directory.exists() and not cache_directory.is_dir())):
        raise AcquisitionError('Cache must be a regular directory')
    archived, published = [], []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.playlist-', dir=directory) as temporary:
            staged = []
            for number, raw in enumerate(pages):
                path = Path(temporary) / str(number)
                path.touch(mode=0o600)
                path.write_bytes(raw)
                staged.append(path)
            previous_profile = Path(temporary) / 'previous-profile'
            previous_cache = Path(temporary) / 'previous-cache'
            staged_profile = Path(temporary) / 'profile'
            if profile_id is not None:
                staged_profile.write_text(json.dumps({'profileId': profile_id}))
            try:
                # Metadata and cache invalidation participate in the same rollback
                # as playlist publication; acquisition failures never reach here.
                if profile_id is not None and profile_file.exists():
                    _move_without_overwrite(profile_file, previous_profile)
                if cache_directory is not None and cache_directory.exists():
                    cache_directory.rename(previous_cache)
                for source, backup in backups:
                    _move_without_overwrite(source, backup)
                    archived.append((source, backup))
                for source, destination in zip(staged, destinations):
                    _move_without_overwrite(source, destination)
                    published.append(destination)
                if profile_id is not None:
                    _move_without_overwrite(staged_profile, profile_file)
                    published.append(profile_file)
            except (OSError, KeyboardInterrupt):
                for destination in published:
                    destination.unlink()
                for source, backup in reversed(archived):
                    _move_without_overwrite(backup, source)
                if previous_profile.exists():
                    _move_without_overwrite(previous_profile, profile_file)
                if previous_cache.exists():
                    previous_cache.rename(cache_directory)
                raise
    except OSError:
        raise AcquisitionError('Unable to publish playlist export; check input permissions') from None
    return destinations
