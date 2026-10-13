"""Earnings events relative to the moment prices were taken (the valuation time)."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from . import calendar_us as cal
from .data import EarningsEvent


def _window(e: EarningsEvent) -> tuple[dt.datetime, dt.datetime]:
    """Earliest and latest moment the report can be released."""
    if e.timing in ("AMC", "BMO"):
        return e.when, e.when
    first_day = e.date - dt.timedelta(days=0 if e.exact_date else 1)
    return (dt.datetime.combine(first_day, dt.time(0, 0), tzinfo=cal.NY),
            dt.datetime.combine(e.date, dt.time(23, 59, 59), tzinfo=cal.NY))


def can_move_between(e: EarningsEvent, start: dt.datetime, end: dt.datetime) -> bool:
    """True if the report may come out after `start` and before `end` (e.g. valuation -> expiry close).

    A known after-close report on the expiry day itself comes after the options stop trading.
    """
    first, last = _window(e)
    return last > start and first < end


def released_between(e: EarningsEvent, start: dt.datetime, end: dt.datetime) -> str | None:
    """'yes' if the report was surely released in (start, end], 'maybe' if possibly, else None."""
    first, last = _window(e)
    if first > start and last <= end:
        return "yes"
    if last > start and first <= end:
        return "maybe"
    return None


def upcoming(events: list[EarningsEvent], after: dt.datetime) -> list[EarningsEvent]:
    far = after + dt.timedelta(days=3650)
    return [e for e in events if can_move_between(e, after, far)]


def past(events: list[EarningsEvent], before: dt.datetime) -> list[EarningsEvent]:
    return [e for e in events if _window(e)[1] < before]


TIMING_TH = {"AMC": "หลังตลาดปิด", "BMO": "ก่อนตลาดเปิด", "unknown": "ไม่ทราบช่วงเวลา"}


def reactions(close: pd.Series, events: list[EarningsEvent], n: int = 8) -> list[tuple[dt.date, float, str]]:
    """Price reaction to each report: (date, move, window).

    After-close reports: close on the report day -> next close. Before-open reports: previous
    close -> close on the report day. Unknown timing: previous close -> close after the report
    day (2-session window, marked "2d").
    """
    out = []
    idx = close.index
    for e in sorted(events, key=lambda x: x.date)[-n:]:
        d = pd.Timestamp(e.date)
        if e.timing == "AMC":
            before, after, kind = idx[idx <= d], idx[idx > d], "1d"
        elif e.timing == "BMO":
            before, after, kind = idx[idx < d], idx[idx >= d], "1d"
        else:
            first = d - pd.Timedelta(days=0 if e.exact_date else 1)
            before, after, kind = idx[idx < first], idx[idx > d], "2d"
        if len(before) == 0 or len(after) == 0:
            continue
        if (after[0] - d).days > 5 or (d - before[-1]).days > 5:
            continue
        out.append((e.date, float(close.loc[after[0]] / close.loc[before[-1]] - 1), kind))
    return out
