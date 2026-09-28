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


def _timestamp_date(value: object) -> date | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if math.isfinite(value):
            return datetime.fromtimestamp(value / 1000, PARIS).date()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def extract_expiration(payload: object) -> date | None:
    if not isinstance(payload, dict) or not isinstance(payload.get('detail'), dict):
        raise ValueError('Missing or invalid detail object')
    result = _timestamp_date(payload['detail'].get('availabilityEndDate'))
    if result is not None:
        return result
    info = payload['detail'].get('informations')
    if not isinstance(info, dict):
        return None
    availability = info.get('contentAvailability')
    if not isinstance(availability, dict):
        return None
    options = availability.get('availabilities')
    if not isinstance(options, dict):
        return None

    ordered = [options.get('download'), options.get('stream')]
    ordered.extend(value for key, value in options.items() if key not in ('download', 'stream'))
    for option in ordered:
        if isinstance(option, dict):
            result = _timestamp_date(option.get('availabilityEndDate'))
            if result is not None:
                return result

    # Exact timestamps take precedence over the less precise display labels.
    for option in [options.get('stream'), *ordered]:
        if not isinstance(option, dict) or not isinstance(option.get('label'), str):
            continue
        match = _LABEL_DATE.search(option['label'])
        if match:
            try:
                return datetime.strptime(match.group(1), '%d/%m/%Y').date()
            except ValueError:
                continue
    return None
