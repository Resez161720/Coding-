"""Historical statistics on daily price data."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close).diff().dropna()


def hv_close_to_close(close: pd.Series, window: int) -> float:
    """Annualised close-to-close volatility of the last `window` daily log returns."""
    r = log_returns(close).iloc[-window:]
    if len(r) < max(5, window // 2):
        return float("nan")
    return float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))


def hv_parkinson(high: pd.Series, low: pd.Series, window: int) -> float:
    """Annualised Parkinson (high-low range) volatility."""
    hl = np.log(high / low).iloc[-window:]
    if len(hl) < max(5, window // 2):
        return float("nan")
    return float(math.sqrt((hl ** 2).mean() / (4.0 * math.log(2.0))) * math.sqrt(TRADING_DAYS))


def rolling_hv(close: pd.Series, window: int) -> pd.Series:
    return log_returns(close).rolling(window).std(ddof=1) * math.sqrt(TRADING_DAYS)


def hv_percentile(close: pd.Series, window: int = 20, lookback: int = 252) -> float:
    """Percentile (0-100) of the current rolling HV within the last `lookback` values."""
    s = rolling_hv(close, window).dropna().iloc[-lookback:]
    if len(s) < 20:
        return float("nan")
    return float((s <= s.iloc[-1]).mean() * 100.0)


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    out[(avg_loss == 0) & (avg_gain > 0)] = 100.0
    return out


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def max_drawdown(close: pd.Series) -> float:
    peak = close.cummax()
    return float((close / peak - 1.0).min())


def beta(stock_close: pd.Series, market_close: pd.Series, window: int = 252) -> float:
    joined = pd.concat([log_returns(stock_close), log_returns(market_close)], axis=1, join="inner").dropna()
    joined = joined.iloc[-window:]
    if len(joined) < 60:
        return float("nan")
    cov = np.cov(joined.iloc[:, 0], joined.iloc[:, 1], ddof=1)
    return float(cov[0, 1] / cov[1, 1])


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


@dataclass(frozen=True)
class EmpiricalProb:
    prob: float
    n: int
    ci_low: float
    ci_high: float


def horizon_log_returns(close: pd.Series, horizon: int, lookback_days: int | None = None) -> pd.Series:
    """Overlapping `horizon`-session log returns over the last `lookback_days` sessions."""
    c = close if lookback_days is None else close.iloc[-(lookback_days + horizon):]
    return np.log(c / c.shift(horizon)).dropna()


def empirical_prob(returns: pd.Series, threshold: float, above: bool) -> EmpiricalProb:
    """Share of historical log returns above (or below) `threshold`.

    Overlapping windows are not independent, so the interval uses the number of
    non-overlapping windows as the effective sample size.
    """
    n = len(returns)
    if n == 0:
        return EmpiricalProb(float("nan"), 0, float("nan"), float("nan"))
    hits = int((returns > threshold).sum() if above else (returns < threshold).sum())
    p = hits / n
    return EmpiricalProb(p, n, *_effective_ci(p, n))


def _effective_ci(p: float, n: int, overlap: int = 1) -> tuple[float, float]:
    n_eff = max(1, n // max(1, overlap))
    return wilson_interval(round(p * n_eff), n_eff)


def empirical_prob_horizon(close: pd.Series, horizon: int, threshold: float, above: bool,
                           lookback_days: int = 5 * TRADING_DAYS) -> EmpiricalProb:
    rets = horizon_log_returns(close, horizon, lookback_days)
    res = empirical_prob(rets, threshold, above)
    if res.n == 0:
        return res
    return EmpiricalProb(res.prob, res.n, *_effective_ci(res.prob, res.n, horizon))
