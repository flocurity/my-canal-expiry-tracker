"""Scalar enrichment retained only during the current execution."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DetailData:
    availability_end_date: int | float | None = None
    availability_label: str = ''
    subgenre: str = ''
    duration_minutes: int | None = None
