"""NYSE trading calendar (full-day closures) and US/Eastern time helpers."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
BANGKOK = ZoneInfo("Asia/Bangkok")
MARKET_OPEN = dt.time(9, 30)
MARKET_CLOSE = dt.time(16, 0)


def _observed(d: dt.date) -> dt.date:
    """Saturday holidays are observed Friday, Sunday holidays Monday."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> dt.date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset[dt.date]:
    days = set()
    new_year = dt.date(year, 1, 1)
    # NYSE does not close on Friday Dec 31 when Jan 1 falls on a Saturday.
    if new_year.weekday() != 5:
        days.add(_observed(new_year))
    days.add(_nth_weekday(year, 1, 0, 3))  # Martin Luther King Jr. Day
    days.add(_nth_weekday(year, 2, 0, 3))  # Washington's Birthday
    days.add(_easter(year) - dt.timedelta(days=2))  # Good Friday
    days.add(_last_weekday(year, 5, 0))  # Memorial Day
    if year >= 2022:
        days.add(_observed(dt.date(year, 6, 19)))  # Juneteenth
    days.add(_observed(dt.date(year, 7, 4)))
    days.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    days.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    days.add(_observed(dt.date(year, 12, 25)))
    return frozenset(d for d in days if d.year == year)


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def previous_trading_day(d: dt.date) -> dt.date:
    d -= dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def last_session_with_data(now_ny: dt.datetime) -> dt.date:
    """The most recent session whose daily bar should exist at `now_ny`.

    During or after a trading session the current day's (possibly partial) bar is
    expected; before the open the previous session is the latest one.
    """
    d = now_ny.date()
    if is_trading_day(d) and now_ny.time() >= MARKET_OPEN:
        return d
    return previous_trading_day(d)


def trading_days_between(start: dt.date, end: dt.date) -> int:
    """Number of trading sessions in (start, end]."""
    if end <= start:
        return 0
    n = 0
    d = start + dt.timedelta(days=1)
    while d <= end:
        if is_trading_day(d):
            n += 1
        d += dt.timedelta(days=1)
    return n


def market_is_open(now_ny: dt.datetime) -> bool:
    return is_trading_day(now_ny.date()) and MARKET_OPEN <= now_ny.time() < MARKET_CLOSE


def now_ny() -> dt.datetime:
    return dt.datetime.now(NY)


def expiry_close(expiry: dt.date) -> dt.datetime:
    """Options stop trading at the 16:00 ET close on the expiration date."""
    return dt.datetime.combine(expiry, MARKET_CLOSE, tzinfo=NY)


def years_to_expiry(now: dt.datetime, expiry: dt.date) -> float:
    seconds = (expiry_close(expiry) - now).total_seconds()
    return max(seconds, 0.0) / (365.0 * 24 * 3600)


def stamp(t: dt.datetime) -> str:
    """'2026-10-12 11:00 (นิวยอร์ก) / 22:00 (ไทย)'."""
    th = t.astimezone(BANGKOK)
    return f"{t:%Y-%m-%d %H:%M} (นิวยอร์ก) / {th:%Y-%m-%d %H:%M} (ไทย)"
