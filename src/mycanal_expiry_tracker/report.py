"""Final business rows shared by snapshots and the Excel renderer."""
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tracker import ContentResult


@dataclass(frozen=True)
class ReportRow:
    content_id: str
    title: str
    subgenre: str
    service: str
    category: str
    in_offer: bool | None
    public_url: str
    expiration: date | None
    availability_end_date: int | float | None
    availability_text: str
    resume_episode: str
    episodes_remaining: int | None
    duration_minutes: int | None
    status: str


def season_category(numbers: tuple[int, ...]) -> str:
    if len(numbers) == 1:
        return f'Saison {numbers[0]}'
    if all(right == left + 1 for left, right in zip(numbers, numbers[1:])):
        return f'Saisons {numbers[0]} à {numbers[-1]}'
    return 'Saisons ' + ', '.join(str(number) for number in numbers)


def to_report_rows(results: list['ContentResult']) -> list[ReportRow]:
    rows = []
    for result in results:
        item = result.item
        if item.content_type == 'folder':
            minutes = result.duration_minutes if result.episodes_remaining is not None else None
        else:
            minutes = item.movie_duration_minutes
            if minutes is None:
                minutes = result.duration_minutes
                if (minutes is not None and item.content_type == 'VoD'
                        and item.duration_ms is not None and item.duration_ms >= 60_000):
                    minutes = item.duration_ms // 60_000
            if minutes is not None and minutes <= 0:
                minutes = None
        rows.append(ReportRow(
            item.content_id, item.title, result.subgenre, item.service,
            season_category(result.season_numbers) if result.season_numbers else item.subtitle,
            item.in_offer, item.web_url, result.expiration, result.availability_end_date,
            result.availability_text, result.resume_episode, result.episodes_remaining,
            minutes, result.status,
        ))
    return rows
