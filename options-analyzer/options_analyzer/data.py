"""Market data access. YahooProvider uses yfinance; tests use an in-memory provider.

Every value fetched here is checked in validation.py before it is used.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from . import calendar_us as cal


@dataclass
class Quote:
    price: float | None
    time: dt.datetime | None
    source: str


@dataclass(frozen=True)
class EarningsEvent:
    date: dt.date  # report date in New York
    when: dt.datetime | None = None  # exact New York time when the provider gives one
    exact_date: bool = True  # False when a local time-zone conversion may have shifted the date by +1 day

    @property
    def timing(self) -> str:
        """'AMC' (after the close), 'BMO' (before the open) or 'unknown'."""
        if self.when is None or not self.exact_date:
            return "unknown"
        t = self.when.time()
        if t == dt.time(0, 0):  # date-only placeholder
            return "unknown"
        if t >= dt.time(15, 0):  # Yahoo stamps after-close reports 15:00-16:00 depending on DST
            return "AMC"
        if t < cal.MARKET_OPEN:
            return "BMO"
        return "unknown"


@dataclass
class EarningsInfo:
    status: str  # "known" (provider returned dates), "none" (ETF/index), "unknown"
    events: list[EarningsEvent] = field(default_factory=list)
    confirmed: bool | None = None  # Yahoo's flag for its next scheduled date (False = estimate)


class Provider(Protocol):
    def history(self, symbol: str, period: str = "10y") -> pd.DataFrame: ...
    def quotes(self, symbol: str) -> list[Quote]: ...
    def expirations(self, symbol: str) -> list[str]: ...
    def chain(self, symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame, Quote]: ...
    def profile(self, symbol: str) -> dict: ...
    def earnings(self, symbol: str) -> EarningsInfo: ...
    def dividends(self, symbol: str) -> pd.Series: ...
    def risk_free_rate(self) -> tuple[float | None, str]: ...
    # Optional: def intraday(self, symbol: str) -> pd.Series | None  (1-minute closes, America/New_York)


def normalise_history(df: pd.DataFrame) -> pd.DataFrame:
    """Daily bars indexed by naive session date (America/New_York)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(cal.NY).tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "Date"
    return df


def _ts_to_ny(ts) -> dt.datetime | None:
    """Epoch seconds or a datetime/Timestamp (naive = UTC) -> aware America/New_York datetime."""
    if ts is None:
        return None
    if isinstance(ts, (pd.Timestamp, dt.datetime)):
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return t.tz_convert(cal.NY).to_pydatetime()
    try:
        return dt.datetime.fromtimestamp(int(ts), tz=cal.NY)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _get(mapping, key):
    try:
        return mapping[key]
    except (KeyError, TypeError, IndexError):
        return None


def _finite(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class YahooProvider:
    """Yahoo Finance via yfinance (free, delayed ~15 min during market hours)."""

    def __init__(self, retries: int = 3, pause: float = 2.0):
        import yfinance as yf  # imported lazily so tests do not need network libs

        self._yf = yf
        self._retries = retries
        self._pause = pause
        self._tickers: dict[str, object] = {}
        self._history_cache: dict[tuple[str, str], pd.DataFrame] = {}  # SPY/^VIX are reused across a scan

    def _t(self, symbol: str):
        if symbol not in self._tickers:
            self._tickers[symbol] = self._yf.Ticker(symbol)
        return self._tickers[symbol]

    def _retry(self, fn):
        last = None
        for i in range(self._retries):
            try:
                return fn()
            except Exception as e:  # network errors, rate limits, parse errors
                last = e
                time.sleep(self._pause * (i + 1))
        raise RuntimeError(f"ดึงข้อมูลไม่สำเร็จหลังลอง {self._retries} ครั้ง: {last}") from last

    def history(self, symbol: str, period: str = "10y") -> pd.DataFrame:
        """Daily bars as traded (split-adjusted, like a broker chart) plus a dividend-adjusted AdjClose."""
        key = (symbol, period)
        if key not in self._history_cache:
            df = self._retry(lambda: self._t(symbol).history(period=period, interval="1d",
                                                             auto_adjust=False, actions=False))
            df = normalise_history(df).rename(columns={"Adj Close": "AdjClose"})
            self._history_cache[key] = df
        return self._history_cache[key].copy()

    def intraday(self, symbol: str) -> pd.Series | None:
        """1-minute closes for the last few sessions, used to date-check option last trades."""
        try:
            # prepost: ETF options (SPY, QQQ, ...) keep trading until 16:15, after the stock's close.
            df = self._retry(lambda: self._t(symbol).history(period="5d", interval="1m", auto_adjust=False,
                                                             actions=False, prepost=True))
        except Exception:
            return None
        if df is None or df.empty or "Close" not in df:
            return None
        s = df["Close"].dropna()
        idx = pd.DatetimeIndex(s.index)
        s.index = idx.tz_convert(cal.NY) if idx.tz is not None else idx.tz_localize(cal.NY)
        return s.sort_index()

    def quotes(self, symbol: str) -> list[Quote]:
        """Live quote from the chart endpoint metadata (fetched together with history)."""
        out = []
        try:
            meta = self._t(symbol).history_metadata
            out.append(Quote(_finite(_get(meta, "regularMarketPrice")),
                             _ts_to_ny(_get(meta, "regularMarketTime")), "Yahoo chart"))
        except Exception:
            pass
        return out

    def expirations(self, symbol: str) -> list[str]:
        """Yahoo answers a rate-limited request with an empty list, so retry before believing it."""
        for i in range(self._retries):
            exp = list(self._retry(lambda: self._t(symbol).options))
            if exp:
                return exp
            if i < self._retries - 1:
                self._tickers.pop(symbol, None)  # fresh session and crumb
                time.sleep(self._pause * (i + 1))
        return []

    def chain(self, symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame, Quote]:
        oc = self._retry(lambda: self._t(symbol).option_chain(expiry))
        u = oc.underlying or {}
        q = Quote(_finite(_get(u, "regularMarketPrice")), _ts_to_ny(_get(u, "regularMarketTime")), "Yahoo options")
        return oc.calls, oc.puts, q

    def profile(self, symbol: str) -> dict:
        try:
            info = self._t(symbol).info or {}
        except Exception:
            return {}
        keys = ("shortName", "longName", "quoteType", "currency", "exchange", "sector", "industry",
                "preMarketPrice", "preMarketTime", "postMarketPrice", "postMarketTime")
        return {k: info.get(k) for k in keys if info.get(k) is not None}

    def extended_quote(self, symbol: str) -> Quote | None:
        """Most recent pre- or post-market price, if Yahoo has one."""
        prof = self.profile(symbol)
        best = None
        for p_key, t_key, label in (("preMarketPrice", "preMarketTime", "pre-market"),
                                    ("postMarketPrice", "postMarketTime", "post-market")):
            price, t = _finite(prof.get(p_key)), _ts_to_ny(prof.get(t_key))
            if price and t and (best is None or t > best.time):
                best = Quote(price, t, f"Yahoo {label}")
        return best

    def earnings(self, symbol: str) -> EarningsInfo:
        prof = self.profile(symbol)
        if prof.get("quoteType") in ("ETF", "INDEX", "MUTUALFUND"):
            return EarningsInfo("none")
        events: dict[dt.date, EarningsEvent] = {}
        confirmed = None

        def add(t: dt.datetime | None, d: dt.date, exact: bool = True) -> None:
            if d not in events or (events[d].when is None and t is not None):
                events[d] = EarningsEvent(d, t, exact)

        try:
            # Raw calendarEvents: exact timestamps and Yahoo's "is estimate" flag, both dropped by
            # yfinance's .calendar (which also converts in the local time zone and can shift the date).
            raw = self._t(symbol)._quote._fetch(modules=["calendarEvents"])
            earn = raw["quoteSummary"]["result"][0]["calendarEvents"].get("earnings") or {}
            for ts in earn.get("earningsDate") or []:
                t = _ts_to_ny(ts)
                if t is not None:
                    add(t, t.date())
            if "isEarningsDateEstimate" in earn:
                confirmed = not bool(earn["isEarningsDateEstimate"])
        except Exception:
            pass
        try:
            ed = self._t(symbol).get_earnings_dates(limit=16)
            if ed is not None and len(ed):
                for ts in pd.DatetimeIndex(ed.index):
                    t = _ts_to_ny(ts)
                    if t is not None:
                        add(t, t.date())
        except Exception:
            pass
        today = cal.now_ny().date()
        if not any(d >= today - dt.timedelta(days=1) for d in events):
            try:
                calendar = self._t(symbol).calendar or {}
                for d in calendar.get("Earnings Date", []) or []:
                    if isinstance(d, dt.datetime):
                        d = d.date()
                    if isinstance(d, dt.date):
                        add(None, d, exact=False)
            except Exception:
                pass
        if not events:
            return EarningsInfo("unknown")
        return EarningsInfo("known", sorted(events.values(), key=lambda e: e.date), confirmed)

    def dividends(self, symbol: str) -> pd.Series:
        try:
            s = self._t(symbol).dividends
        except Exception:
            return pd.Series(dtype=float)
        if s is None or s.empty:
            return pd.Series(dtype=float)
        return normalise_history(s.to_frame("d"))["d"]

    def risk_free_rate(self) -> tuple[float | None, str]:
        """13-week US T-bill yield (^IRX, quoted in percent)."""
        try:
            h = self.history("^IRX", period="1mo")
            v = float(h["Close"].dropna().iloc[-1]) / 100.0
            return v, f"^IRX (13-week T-bill) ณ {h.index[-1]:%Y-%m-%d}"
        except Exception as e:
            return None, f"ดึง ^IRX ไม่ได้: {e}"
