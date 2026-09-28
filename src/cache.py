"""A URL-bound JSON cache of successful extracted availability information."""

import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from log import get_logger

log = get_logger(__name__)
CACHE_LIFETIME = timedelta(hours=24)


class DetailCache:
    def __init__(self, path: Path, lifetime: timedelta = CACHE_LIFETIME) -> None:
        self.path = path
        self.lifetime = lifetime
        self.entries: dict = {}
        self.dirty = False
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Cache must contain an object')
            self.entries = data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning('cache_read_failed', path=str(path), reason=str(exc))

    def get(self, content_id: str, url: str) -> tuple[bool, date | None, str]:
        entry = self.entries.get(content_id)
        if not content_id or not isinstance(entry, dict):
            return False, None, ''
        try:
            retrieved = datetime.fromisoformat(entry['retrieved_at'])
            age = datetime.now(timezone.utc) - retrieved
            if not timedelta(0) <= age < self.lifetime or entry['url'] != url:
                return False, None, ''
            raw_date = entry['expiration']
            expiration = date.fromisoformat(raw_date) if raw_date is not None else None
            if entry['status'] != ('OK' if expiration else 'Date inconnue'):
                return False, None, ''
            # Older cache entries remain usable without an additional API call.
            subgenre = entry.get('subgenre')
            if not isinstance(subgenre, str) or not subgenre.strip():
                subgenre = ''
            return True, expiration, subgenre
        except (KeyError, ValueError, TypeError):
            return False, None, ''

    def put(self, content_id: str, url: str, expiration: date | None,
            subgenre: str = '') -> None:
        if not content_id:
            return
        self.entries[content_id] = {
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'url': url,
            'expiration': expiration.isoformat() if expiration else None,
            'subgenre': subgenre,
            'status': 'OK' if expiration else 'Date inconnue',
        }
        self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self.path.parent,
                prefix='.details-', suffix='.tmp', delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(self.entries, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
            self.dirty = False
        except OSError as exc:
            log.warning('cache_write_failed', path=str(self.path), reason=str(exc))
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    log.warning('cache_cleanup_failed', reason=str(exc))
