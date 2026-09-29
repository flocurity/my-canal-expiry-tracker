"""Extract calendar dates from availability information in the Paris timezone."""

import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo('Europe/Paris')
_LABEL_DATE = re.compile(r"Dispo\.\s+jusqu['’]au\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)


def paris_today() -> date:
    return datetime.now(PARIS).date()


def days_remaining(end_date: date | None, today: date | None = None) -> int | None:
    return (end_date - (today or paris_today())).days if end_date else None


def _timestamp_datetime(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if math.isfinite(value):
            return datetime.fromtimestamp(value / 1000, PARIS)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _availability_text(value: datetime) -> str:
    weekdays = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
    months = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin',
              'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')
    return (f'{weekdays[value.weekday()]} {value.day} {months[value.month - 1]} '
            f'{value:%Hh%M}')


def extract_expiration(payload: object) -> date | None:
    return extract_availability(payload)[0]


def availability_from_raw(
    timestamp: int | float | None, label: str = '',
) -> tuple[date | None, str]:
    value = _timestamp_datetime(timestamp)
    if value is not None:
        return value.date(), _availability_text(value)
    match = _LABEL_DATE.search(label)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d/%m/%Y').date(), ''
        except ValueError:
            pass
    return None, ''


def extract_availability(payload: object) -> tuple[date | None, str]:
    return availability_from_raw(*extract_raw_availability(payload))


def extract_raw_availability(payload: object) -> tuple[int | float | None, str]:
    """Keep the selected timestamp, or a dated API label when no timestamp exists."""
    if not isinstance(payload, dict) or not isinstance(payload.get('detail'), dict):
        raise ValueError('Missing or invalid detail object')
    timestamp = payload['detail'].get('availabilityEndDate')
    if _timestamp_datetime(timestamp) is not None:
        return timestamp, ''
    info = payload['detail'].get('informations')
    if not isinstance(info, dict):
        return None, ''
    availability = info.get('contentAvailability')
    if not isinstance(availability, dict):
        return None, ''
    options = availability.get('availabilities')
    if not isinstance(options, dict):
        return None, ''

    ordered = [options.get('download'), options.get('stream')]
    ordered.extend(value for key, value in options.items() if key not in ('download', 'stream'))
    for option in ordered:
        if isinstance(option, dict):
            timestamp = option.get('availabilityEndDate')
            if _timestamp_datetime(timestamp) is not None:
                return timestamp, ''

    # Exact timestamps take precedence over the less precise display labels.
    for option in [options.get('stream'), *ordered]:
        if not isinstance(option, dict) or not isinstance(option.get('label'), str):
            continue
        match = _LABEL_DATE.search(option['label'])
        if match:
            try:
                datetime.strptime(match.group(1), '%d/%m/%Y')
                return None, match.group(0)
            except ValueError:
                continue
    return None, ''
