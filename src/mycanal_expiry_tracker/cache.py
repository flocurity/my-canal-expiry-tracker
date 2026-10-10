"""Autonomous timestamped report snapshots; no incremental enrichment cache."""
import json
import math
import os
import re
from dataclasses import asdict, fields
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from .report import ReportRow
from .security import validate_persistent_data, validate_public_url

NAME = re.compile(r'\d{4}-\d{2}-\d{2}\.\d{2}-\d{2}\.cache\.json')


def active_snapshots(directory: Path) -> list[Path]:
    if directory.is_symlink():
        raise ValueError('Snapshot directory must not be a symlink')
    paths = sorted(directory.glob('*.cache.json'))
    for path in paths:
        if not NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            raise ValueError('Invalid active snapshot file')
        try:
            datetime.strptime(path.name, '%Y-%m-%d.%H-%M.cache.json')
        except ValueError:
            raise ValueError('Invalid snapshot timestamp') from None
    return paths


def _decode_row(raw: object) -> ReportRow:
    names = {field.name for field in fields(ReportRow)}
    if not isinstance(raw, dict) or set(raw) != names:
        raise ValueError('Invalid snapshot row fields')
    row = dict(raw)
    for key in names - {'in_offer', 'expiration', 'availability_end_date',
                         'episodes_remaining', 'duration_minutes'}:
        if not isinstance(row[key], str):
            raise ValueError('Invalid snapshot text field')
    if row['in_offer'] is not None and type(row['in_offer']) is not bool:
        raise ValueError('Invalid snapshot offer flag')
    for key in ('episodes_remaining', 'duration_minutes'):
        if row[key] is not None and (type(row[key]) is not int or row[key] < 0):
            raise ValueError('Invalid snapshot count or duration')
    timestamp = row['availability_end_date']
    if timestamp is not None and (type(timestamp) not in (int, float)
                                   or not math.isfinite(timestamp)):
        raise ValueError('Invalid snapshot availability timestamp')
    if row['expiration'] is not None:
        if not isinstance(row['expiration'], str):
            raise ValueError('Invalid snapshot expiration')
        row['expiration'] = date.fromisoformat(row['expiration'])
    validate_public_url(row['public_url'])
    return ReportRow(**row)


def snapshot_data(rows: list[ReportRow], secrets: tuple[str, ...] = ()) -> dict:
    records = []
    for row in rows:
        record = asdict(row)
        record['expiration'] = row.expiration.isoformat() if row.expiration else None
        _decode_row(record)
        records.append(record)
    data = {'schema_version': 1, 'rows': records}
    validate_persistent_data(data, secrets)
    return data


def load_snapshot(directory: Path) -> list[ReportRow]:
    paths = active_snapshots(directory)
    if not paths:
        raise ValueError('No active snapshot; run a fresh acquisition first')
    try:
        data = json.loads(paths[-1].read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or set(data) != {'schema_version', 'rows'}
                or type(data['schema_version']) is not int or data['schema_version'] != 1
                or not isinstance(data['rows'], list)):
            raise ValueError('Unsupported snapshot format')
        validate_persistent_data(data)
        return [_decode_row(row) for row in data['rows']]
    except (ValueError, UnicodeError, RecursionError):
        # Never echo file content or fall back to an older active file or backup.
        raise ValueError('Invalid latest snapshot; run a fresh acquisition first') from None


def _move_without_overwrite(source: Path, destination: Path) -> None:
    os.link(source, destination)
    try:
        source.unlink()
    except BaseException:
        destination.unlink()
        raise


def save_snapshot(rows: list[ReportRow], directory: Path, *,
                  secrets: tuple[str, ...] = (), created_at: datetime | None = None) -> Path:
    data = snapshot_data(rows, secrets)
    stamp = (created_at or datetime.now(ZoneInfo('Europe/Paris'))).astimezone(
        ZoneInfo('Europe/Paris')).strftime('%Y-%m-%d.%H-%M')
    if directory.is_symlink():
        raise ValueError('Snapshot directory must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f'{stamp}.cache.json'
    active = active_snapshots(directory)
    backups = [(path, path.with_name(path.name + '.bak')) for path in active]
    if destination.exists() or destination.is_symlink():
        raise ValueError('Snapshot filename collision')
    if any(backup.exists() or backup.is_symlink() for _, backup in backups):
        raise ValueError('Snapshot backup collision')
    archived = []
    with TemporaryDirectory(prefix='.snapshot-', dir=directory) as temporary:
        staged = Path(temporary) / 'snapshot'
        staged.touch(mode=0o600)
        staged.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
                          encoding='utf-8')
        try:
            for source, backup in backups:
                _move_without_overwrite(source, backup)
                archived.append((source, backup))
            _move_without_overwrite(staged, destination)
        except (OSError, KeyboardInterrupt):
            for source, backup in reversed(archived):
                _move_without_overwrite(backup, source)
            raise
    return destination
