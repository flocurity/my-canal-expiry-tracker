"""Extract calendar dates from availability information in the Paris timezone."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from mycanal_hodor_core.availability import (
    extract_raw_availability, timestamp_datetime, parse_availability_label,
)

PARIS = ZoneInfo('Europe/Paris')


def paris_today() -> date:
    return datetime.now(PARIS).date()


def days_remaining(end_date: date | None, today: date | None = None) -> int | None:
    return (end_date - (today or paris_today())).days if end_date else None


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
    value = timestamp_datetime(timestamp, PARIS)
    if value is not None:
        return value.date(), _availability_text(value)
    value = parse_availability_label(label)
    return (value, '') if value is not None else (None, '')


def extract_availability(payload: object) -> tuple[date | None, str]:
    return availability_from_raw(*extract_raw_availability(payload))


