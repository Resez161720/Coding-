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


@dataclass
class EarningsInfo:
    status: str  # "known", "none" (ETF/index), "unknown"
    upcoming: list[dt.date] = field(default_factory=list)
    past: list[dt.date] = field(default_factory=list)


class Provider(Protocol):
    def history(self, symbol: str, period: str = "10y") -> pd.DataFrame: ...
    def quotes(self, symbol: str) -> list[Quote]: ...
    def expirations(self, symbol: str) -> list[str]: ...
    def chain(self, symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame, Quote]: ...
    def profile(self, symbol: str) -> dict: ...
    def earnings(self, symbol: str) -> EarningsInfo: ...
    def dividends(self, symbol: str) -> pd.Series: ...
    def risk_free_rate(self) -> tuple[float | None, str]: ...


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
        key = (symbol, period)
        if key not in self._history_cache:
            df = self._retry(lambda: self._t(symbol).history(period=period, interval="1d",
                                                             auto_adjust=True, actions=False))
            self._history_cache[key] = normalise_history(df)
        return self._history_cache[key].copy()

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
        return list(self._retry(lambda: self._t(symbol).options))

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
        keys = ("shortName", "longName", "quoteType", "currency", "exchange", "sector", "industry")
        return {k: info.get(k) for k in keys if info.get(k) is not None}

    def earnings(self, symbol: str) -> EarningsInfo:
        prof = self.profile(symbol)
        if prof.get("quoteType") in ("ETF", "INDEX", "MUTUALFUND"):
            return EarningsInfo("none")
        upcoming: set[dt.date] = set()
        past: set[dt.date] = set()
        today = cal.now_ny().date()
        try:
            ed = self._t(symbol).get_earnings_dates(limit=16)
            if ed is not None and len(ed):
                for ts in pd.DatetimeIndex(ed.index):
                    d = (ts.tz_convert(cal.NY) if ts.tzinfo else ts).date()
                    (upcoming if d >= today else past).add(d)
        except Exception:
            pass
        try:
            calendar = self._t(symbol).calendar or {}
            for d in calendar.get("Earnings Date", []) or []:
                if isinstance(d, dt.datetime):
                    d = d.date()
                if isinstance(d, dt.date) and d >= today:
                    upcoming.add(d)
        except Exception:
            pass
        if not upcoming and not past:
            return EarningsInfo("unknown")
        return EarningsInfo("known" if upcoming else "unknown", sorted(upcoming), sorted(past))

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
