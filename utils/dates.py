from __future__ import annotations

from datetime import date, datetime, timedelta


def today() -> date:
    return date.today()


def to_date(value: str | date | datetime) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()


def iso(value: str | date | datetime) -> str:
    return to_date(value).isoformat()


def last_6_months_range(reference: date | None = None) -> tuple[date, date]:
    end = reference or today()
    start = end - timedelta(days=183)
    return start, end


def current_week_range(reference: date | None = None) -> tuple[date, date]:
    ref = reference or today()
    start = ref - timedelta(days=ref.weekday())
    end = start + timedelta(days=6)
    return start, end


def current_month_range(reference: date | None = None) -> tuple[date, date]:
    ref = reference or today()
    start = ref.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    end = next_month - timedelta(days=1)
    return start, end


def display_ddmm(value: str | date | datetime) -> str:
    return to_date(value).strftime("%d/%m")


def display_yyyymm(value: str | date | datetime) -> str:
    d = to_date(value)
    return f"{d.year:04d}-{d.month:02d}"
