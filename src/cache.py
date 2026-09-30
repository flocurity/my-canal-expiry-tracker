"""A content-keyed JSON cache of raw detail enrichment."""

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from log import get_logger
from src.timing import timeit
from src.detail import DetailData, ResumeFallback
from src.expiration import availability_from_raw
from src.series import SeasonCatalog, identifier, positive_number

log = get_logger(__name__)
CACHE_LIFETIME = timedelta(hours=24)


class DetailCache:
    @timeit()
    def __init__(self, path: Path, lifetime: timedelta = CACHE_LIFETIME) -> None:
        self.path = path
        self.lifetime = lifetime
        self.entries: dict = {}
        self.dirty = False
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Cache must contain an object')
            # Legacy presentation-only entries cannot recover an exact timestamp.
            # Whitelist fields so obsolete URLs and metadata never survive a save.
            for content_id, entry in data.items():
                normalized = self._normalize_entry(entry)
                if normalized is not None:
                    self.entries[content_id] = normalized
            self.dirty = self.entries != data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning('cache_read_failed', path=str(path), reason=str(exc))

    @staticmethod
    def _normalize_entry(entry: object) -> dict | None:
        if isinstance(entry, dict) and entry.get('kind') == 'season':
            try:
                catalog = SeasonCatalog.from_cache(entry.get('catalog'))
                brand_id = identifier(entry.get('brand_id'))
                if not brand_id:
                    return None
                return {'kind': 'season', 'brand_id': brand_id,
                        'retrieved_at': entry.get('retrieved_at'),
                        'catalog': catalog.to_cache()}
            except (ValueError, TypeError):
                return None
        if not isinstance(entry, dict) or 'availability_end_date' not in entry:
            return None
        timestamp = entry['availability_end_date']
        if timestamp is not None and availability_from_raw(timestamp)[0] is None:
            return None
        label = entry.get('availability_label', '')
        if not isinstance(label, str):
            return None
        if label and availability_from_raw(None, label)[0] is None:
            return None
        subgenre = entry.get('subgenre', '')
        if not isinstance(subgenre, str) or not subgenre.strip():
            subgenre = ''
        minutes = entry.get('duration_minutes')
        if (isinstance(minutes, bool) or not isinstance(minutes, int)
                or minutes <= 0):
            minutes = None
        season_id = entry.get('season_content_id', '')
        if not isinstance(season_id, str):
            return None
        normalized = {
            'retrieved_at': entry.get('retrieved_at'),
            'availability_end_date': timestamp,
            'subgenre': subgenre,
        }
        if label and timestamp is None:
            normalized['availability_label'] = label
        if minutes is not None:
            normalized['duration_minutes'] = minutes
        if season_id:
            normalized['season_content_id'] = season_id
        fallback = entry.get('resume_fallback')
        if isinstance(fallback, dict):
            resume_season = identifier(fallback.get('season_id'))
            episode_id = identifier(fallback.get('episode_id'))
            episode_number = positive_number(fallback.get('episode_number'))
            if resume_season and (episode_id or episode_number):
                normalized['resume_fallback'] = asdict(ResumeFallback(
                    resume_season, episode_id,
                    positive_number(fallback.get('season_number')), episode_number,
                ))
        return normalized

    def get(self, content_id: str, season_content_id: str = '') -> DetailData | None:
        entry = self._normalize_entry(self.entries.get(content_id))
        if not content_id or entry is None:
            return None
        try:
            retrieved = datetime.fromisoformat(entry['retrieved_at'])
            age = datetime.now(timezone.utc) - retrieved
            if (not timedelta(0) <= age < self.lifetime
                    or entry.get('season_content_id', '') != season_content_id):
                return None
            return DetailData(
                availability_end_date=entry['availability_end_date'],
                availability_label=entry.get('availability_label', ''),
                subgenre=entry['subgenre'],
                duration_minutes=entry.get('duration_minutes'),
                resume_fallback=(ResumeFallback(**entry['resume_fallback'])
                                 if 'resume_fallback' in entry else None),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def put(self, content_id: str, detail: DetailData,
            season_content_id: str = '') -> None:
        if not content_id:
            return
        self.entries[content_id] = self._normalize_entry({
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'availability_end_date': detail.availability_end_date,
            'availability_label': detail.availability_label,
            'subgenre': detail.subgenre,
            'duration_minutes': detail.duration_minutes,
            'season_content_id': season_content_id,
            'resume_fallback': asdict(detail.resume_fallback) if detail.resume_fallback else None,
        })
        self.dirty = True

    def get_season(self, brand_id: str, season_id: str) -> SeasonCatalog | None:
        entry = self._normalize_entry(self.entries.get(f'season:{brand_id}:{season_id}'))
        if entry is None or entry.get('kind') != 'season' or entry['brand_id'] != brand_id:
            return None
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(entry['retrieved_at'])
            if not timedelta(0) <= age < self.lifetime:
                return None
            catalog = SeasonCatalog.from_cache(entry['catalog'])
            return catalog if catalog.season.content_id == season_id else None
        except (ValueError, TypeError):
            return None

    def put_season(self, brand_id: str, catalog: SeasonCatalog) -> None:
        if not identifier(brand_id):
            return
        self.entries[f'season:{brand_id}:{catalog.season.content_id}'] = {
            'kind': 'season', 'brand_id': brand_id,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'catalog': catalog.to_cache(),
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
