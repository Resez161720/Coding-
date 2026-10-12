"""Synthetic market data for offline tests. Never used for real analysis."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from options_analyzer import calendar_us as cal  # noqa: E402
from options_analyzer.data import EarningsEvent, EarningsInfo, Quote  # noqa: E402
from options_analyzer.pricing import bs_price  # noqa: E402

NOW = dt.datetime(2026, 10, 12, 11, 0, tzinfo=cal.NY)  # a Monday, market open


def amc(d: dt.date) -> EarningsEvent:
    """An after-the-close earnings report on day d."""
    return EarningsEvent(d, dt.datetime.combine(d, dt.time(16, 5), tzinfo=cal.NY))


def bmo(d: dt.date) -> EarningsEvent:
    return EarningsEvent(d, dt.datetime.combine(d, dt.time(7, 0), tzinfo=cal.NY))


def trading_dates(end: dt.date, n: int) -> list[dt.date]:
    out = []
    d = end
    while len(out) < n:
        if cal.is_trading_day(d):
            out.append(d)
        d -= dt.timedelta(days=1)
    return out[::-1]


def gbm_history(n: int = 2520, sigma: float = 0.30, mu: float = 0.08, seed: int = 7,
                end: dt.date = NOW.date(), start_price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = trading_dates(end, n)
    dtt = 1 / 252
    r = rng.normal((mu - 0.5 * sigma ** 2) * dtt, sigma * np.sqrt(dtt), n)
    close = start_price * np.exp(np.cumsum(r))
    open_ = np.concatenate([[start_price], close[:-1]]) * np.exp(rng.normal(0, 0.003, n))
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": hi, "Low": lo, "Close": close, "Volume": vol},
                        index=pd.DatetimeIndex(pd.to_datetime(dates), name="Date"))


def fridays_after(d: dt.date, n: int) -> list[dt.date]:
    out = []
    x = d + dt.timedelta(days=1)
    while len(out) < n:
        if x.weekday() == 4:
            out.append(x)
        x += dt.timedelta(days=1)
    return out


class FakeProvider:
    """Self-consistent synthetic data: chain priced with Black-Scholes at known vols."""

    def __init__(self, hist: pd.DataFrame | None = None, sigma_chain: float = 0.32, r: float = 0.045,
                 now: dt.datetime = NOW, earnings: EarningsInfo | None = None, spread: float = 0.03,
                 market: pd.DataFrame | None = None, off_hours: bool = False):
        self.hist = gbm_history() if hist is None else hist
        self.market = gbm_history(seed=11, sigma=0.18) if market is None else market
        self.sigma = sigma_chain
        self.r = r
        self.now = now
        self.spread = spread
        self.earn = earnings if earnings is not None else EarningsInfo("known", [
            amc(now.date() - dt.timedelta(days=60)), amc(now.date() + dt.timedelta(days=30))], True)
        self.expiries = [f"{d:%Y-%m-%d}" for d in fridays_after(now.date(), 6)]
        self.chain_overrides = {}
        # Off hours, Yahoo returns bid/ask/OI = 0 and the chain reflects the last session's close.
        self.off_hours = off_hours
        self.price_time = cal.valuation_time(now)

    @property
    def spot(self) -> float:
        return float(self.hist["Close"].iloc[-1])

    def history(self, symbol, period="10y"):
        if symbol == "SPY":
            return self.market
        if symbol == "^VIX":
            idx = self.hist.index[-21:]
            return pd.DataFrame({"Open": 18.0, "High": 19.0, "Low": 17.0, "Close": 18.0, "Volume": 0.0}, index=idx)
        return self.hist

    def quotes(self, symbol):
        return [Quote(self.spot, self.now, "Fake chart")]

    def expirations(self, symbol):
        return list(self.expiries)

    def iv_for(self, K: float) -> float:
        return self.sigma * (1 + 0.15 * max(0.0, 1 - K / self.spot))  # mild put skew

    def chain(self, symbol, expiry):
        if expiry in self.chain_overrides:
            return self.chain_overrides[expiry]
        S = self.spot
        T = cal.years_to_expiry(self.price_time, dt.date.fromisoformat(expiry))
        strikes = np.arange(round(S * 0.7), round(S * 1.3) + 1, 1.0)
        sides = {}
        for kind in ("call", "put"):
            rows = []
            for K in strikes:
                iv = self.iv_for(K)
                p = bs_price(S, K, T, self.r, iv, kind)
                bid = max(round(p * (1 - self.spread) - 0.01, 2), 0.0)
                ask = round(p * (1 + self.spread) + 0.01, 2)
                traded = self.price_time - dt.timedelta(minutes=2) if self.off_hours else self.now
                rows.append({
                    "contractSymbol": f"FAKE{expiry}{kind[0].upper()}{K:g}",
                    "strike": K, "bid": 0.0 if self.off_hours else bid, "ask": 0.0 if self.off_hours else ask,
                    "lastPrice": round(p, 2), "volume": 150.0, "openInterest": 0.0 if self.off_hours else 1200.0,
                    "impliedVolatility": 1e-5 if self.off_hours else iv,
                    "lastTradeDate": pd.Timestamp(traded).tz_convert("UTC"),
                })
            sides[kind] = pd.DataFrame(rows)
        return sides["call"], sides["put"], Quote(S, self.now, "Fake options")

    def profile(self, symbol):
        return {"longName": "Synthetic Test Corp", "quoteType": "EQUITY"}

    def earnings(self, symbol):
        return self.earn

    def dividends(self, symbol):
        return pd.Series(dtype=float)

    def risk_free_rate(self):
        return self.r, "fake"


@pytest.fixture
def provider():
    return FakeProvider()
