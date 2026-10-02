"""Acquire playlist pages using transient browser-supplied request context."""

import json
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo

import prompt_toolkit

from mycanal_hodor_core.logging import get_logger
from mycanal_expiry_tracker.canal_api import CanalClient, DetailError, validate_api_url

log = get_logger(__name__)


class AcquisitionError(ValueError):
    """A safe, non-sensitive acquisition failure."""


@dataclass(frozen=True, repr=False)
class RequestContext:
    hodor_token: str
    token_pass: str
    profile_id: str
    query_parameters: tuple[tuple[str, str], ...] = ()


def parse_curl(command: str) -> RequestContext:
    """Parse a restricted GET cURL grammar as data, never as shell code."""
    try:
        args = shlex.split(command.replace('\r\n', '\n').replace('\\\n', ''), posix=True)
    except ValueError:
        raise AcquisitionError('Invalid Copy-as-cURL quoting') from None
    if not args or args.pop(0) != 'curl':
        raise AcquisitionError('Expected a Firefox Copy-as-cURL request')
    url = None
    headers = {}
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in ('--compressed', '--globoff'):
            continue
        option, separator, inline = arg.partition('=')
        if option in ('-H', '--header', '-X', '--request', '--url',
                      '-A', '--user-agent', '-b', '--cookie'):
            if separator:
                value = inline
            else:
                if index == len(args):
                    raise AcquisitionError('Incomplete Copy-as-cURL option')
                value = args[index]
                index += 1
            if option in ('-H', '--header'):
                name, colon, value = value.partition(':')
                if not colon:
                    raise AcquisitionError('Invalid copied header')
                name, value = name.strip().lower(), value.strip()
                if name in ('tokenpass', 'xx-profile-id'):
                    if name in headers or not value or any(
                        ord(char) < 33 or ord(char) > 126 for char in value
                    ):
                        raise AcquisitionError('Invalid or duplicate required header')
                    headers[name] = value
            elif option in ('-X', '--request') and value != 'GET':
                raise AcquisitionError('Expected a GET playlist request')
            elif option == '--url':
                if url is not None:
                    raise AcquisitionError('Expected exactly one request URL')
                url = value
            continue
        if arg.startswith('https://') and url is None:
            url = arg
        else:
            raise AcquisitionError('Unrecognized Copy-as-cURL option or shell syntax')
    try:
        validate_api_url(url or '', 'me')
        match = re.fullmatch(r'/api/v2/mycanal/me/([a-fA-F0-9]{32})/lists/playlist',
                             urlsplit(url).path)
    except (DetailError, ValueError):
        match = None
    if match is None:
        raise AcquisitionError('Expected the Mes Vidéos Hodor playlist URL and a valid path token')
    if 'tokenpass' not in headers:
        raise AcquisitionError('Missing tokenPass header')
    if 'xx-profile-id' not in headers:
        raise AcquisitionError('Missing xx-profile-id header')
    query = tuple(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    if any(key.casefold() in ('tokenpass', 'xx-profile-id') for key, _ in query):
        raise AcquisitionError('Authentication context must use headers')
    return RequestContext(match[1], headers['tokenpass'], headers['xx-profile-id'], query)


def read_curl() -> str:
    print('Paste Firefox "Copy as cURL" from myCANAL > Mes Vidéos.')
    print('Sensitive request: do not share or save it. Press Esc, then Enter to submit.')
    return prompt_toolkit.prompt('> ', multiline=True)


def contains_authentication(value: object, context: RequestContext) -> bool:
    """Raw bodies cannot be redacted, so refuse an echoed authentication context."""
    if isinstance(value, dict):
        return any(
            key.casefold() in ('tokenpass', 'xx-profile-id')
            or contains_authentication(child, context)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(contains_authentication(child, context) for child in value)
    return isinstance(value, str) and (
        context.token_pass in value or context.profile_id in value
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


def acquire_pages(context: RequestContext, client: CanalClient) -> list[bytes]:
    def checked_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise AcquisitionError('Unexpected duplicate JSON field')
            result[key] = value
        return result

    pages = []
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
        raw = client.fetch_playlist_page(url, {
            'tokenPass': context.token_pass, 'xx-profile-id': context.profile_id,
        })
        try:
            payload = json.loads(raw, object_pairs_hook=checked_object)
        except (ValueError, UnicodeError, RecursionError):
            raise AcquisitionError('Response is not valid JSON') from None
        try:
            sensitive = contains_authentication(payload, context)
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
                  exported_at: datetime | None = None) -> list[Path]:
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
            try:
                for source, backup in backups:
                    _move_without_overwrite(source, backup)
                    archived.append((source, backup))
                for source, destination in zip(staged, destinations):
                    _move_without_overwrite(source, destination)
                    published.append(destination)
            except (OSError, KeyboardInterrupt):
                for destination in published:
                    destination.unlink()
                for source, backup in reversed(archived):
                    _move_without_overwrite(backup, source)
                raise
    except OSError:
        raise AcquisitionError('Unable to publish playlist export; check input permissions') from None
    return destinations
