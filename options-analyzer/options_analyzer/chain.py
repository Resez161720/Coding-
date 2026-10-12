"""Normalise a raw option chain and attach our own implied volatility and Greeks."""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from . import calendar_us as cal
from .pricing import bs_greeks, implied_vol

# Without a minute-by-minute stock price, only trades this close to the valuation time are trusted.
LAST_TRADE_WINDOW = pd.Timedelta(minutes=15)
# With it, older trades are allowed when the stock had not moved enough to matter (DRIFT_TOLERANCE
# of the option's time value), still within this window so the time-to-expiry error stays small.
LAST_TRADE_WINDOW_PATH = pd.Timedelta(minutes=120)
DRIFT_TOLERANCE = 0.10
# Options on broad ETFs (SPY, QQQ, IWM, ...) trade until 16:15 ET, after the stock's 16:00 close.
LATE_OPTIONS_SESSION = pd.Timedelta(minutes=15)
RAW_COLUMNS = ("contractSymbol", "strike", "bid", "ask", "lastPrice", "volume",
               "openInterest", "impliedVolatility", "lastTradeDate")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _side(raw: pd.DataFrame, kind: str) -> pd.DataFrame:
    raw = raw.reindex(columns=list(RAW_COLUMNS))
    out = pd.DataFrame({
        "kind": kind,
        "contract": raw["contractSymbol"].astype(str),
        "strike": _num(raw["strike"]),
        "bid": _num(raw["bid"]).fillna(0.0),
        "ask": _num(raw["ask"]).fillna(0.0),
        "last": _num(raw["lastPrice"]).fillna(0.0),
        "volume": _num(raw["volume"]).fillna(0.0),
        "oi": _num(raw["openInterest"]).fillna(0.0),
        "iv_source": _num(raw["impliedVolatility"]),
    })
    lt = pd.to_datetime(raw["lastTradeDate"], errors="coerce", utc=True)
    out["last_trade"] = lt.dt.tz_convert(cal.NY)
    return out[out["strike"] > 0]


def build_chain(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, T: float, r: float, q: float,
                last_session: dt.date, val_time: dt.datetime | None = None, market_open: bool = True,
                spot_path: pd.Series | None = None) -> pd.DataFrame:
    """Normalised chain with our own IV/Greeks valued at `spot` and time-to-expiry `T`.

    Prices are only used when they belong to the moment `spot` refers to:
    - bid/ask: always while the market is open; off-hours only for contracts that traded in the
      latest session (Yahoo keeps months-old quotes on strikes nobody trades);
    - last trade (no quote): only from the latest session, near `val_time`, and only if the stock
      had not moved enough since the trade to change the option's time value materially.
    """
    frames = [_side(df, kind) for df, kind in ((calls, "call"), (puts, "put")) if df is not None and len(df)]
    if not frames:
        return pd.DataFrame()
    ch = pd.concat(frames, ignore_index=True)
    ch = ch.drop_duplicates(subset=["kind", "strike"], keep="first").reset_index(drop=True)

    lt = ch["last_trade"]
    traded_latest = lt.notna() & lt.apply(lambda t: not pd.isna(t) and t.date() >= last_session)
    has_quote = (ch["bid"] > 0) & (ch["ask"] > 0)
    live_quote = has_quote & (market_open | traded_latest)
    ch["stale_quote"] = has_quote & ~live_quote
    ch["crossed"] = live_quote & (ch["bid"] > ch["ask"])
    ch["mid"] = np.where(live_quote & ~ch["crossed"], (ch["bid"] + ch["ask"]) / 2.0, np.nan)
    ch["spread_pct"] = np.where(ch["mid"] > 0, (ch["ask"] - ch["bid"]) / ch["mid"], np.nan)

    recent = traded_latest
    if val_time is not None:
        window = LAST_TRADE_WINDOW_PATH if spot_path is not None else LAST_TRADE_WINDOW
        late = pd.Timedelta(minutes=1) if market_open else LATE_OPTIONS_SESSION
        recent = recent & lt.apply(lambda t: not pd.isna(t) and val_time - window <= t <= val_time + late)
    use_last = ch["mid"].isna() & ~ch["crossed"] & (ch["last"] > 0) & recent
    ch["price_source"] = np.where(ch["mid"].notna(), "mid", np.where(use_last, "last", "none"))
    ch["price"] = np.where(ch["mid"].notna(), ch["mid"], np.where(use_last, ch["last"], np.nan))

    intrinsic = np.where(ch["kind"] == "call", np.maximum(spot - ch["strike"], 0.0),
                         np.maximum(ch["strike"] - spot, 0.0))
    ch["intrinsic"] = intrinsic
    tol = np.maximum(0.05, 0.02 * intrinsic)
    ch["below_intrinsic"] = ch["price"].notna() & (ch["price"] < intrinsic - tol)

    cols = {k: [] for k in ("iv", "delta", "gamma", "theta", "vega", "stale_last", "spot_at_trade")}
    for row in ch.itertuples(index=False):
        iv, g, stale, s_trade = None, None, False, np.nan
        if row.price_source != "none" and not row.crossed and not row.below_intrinsic and T > 0:
            iv = implied_vol(float(row.price), spot, float(row.strike), T, r, row.kind, q)
        if iv is not None:
            g = bs_greeks(spot, float(row.strike), T, r, iv, row.kind, q)
            if row.price_source == "last" and spot_path is not None:
                s_trade = _spot_at(spot_path, row.last_trade)
                if np.isnan(s_trade):
                    stale = True
                else:
                    # Price error from the stock having moved since the trade, vs. the time value
                    # that the IV is solved from.
                    drift = abs(g.delta) * abs(s_trade - spot)
                    extrinsic = float(row.price) - float(row.intrinsic)
                    stale = drift > max(DRIFT_TOLERANCE * extrinsic, 0.02)
            if stale:
                iv, g = None, None
        cols["iv"].append(np.nan if iv is None else iv)
        cols["delta"].append(g.delta if g else np.nan)
        cols["gamma"].append(g.gamma if g else np.nan)
        cols["theta"].append(g.theta_per_day if g else np.nan)
        cols["vega"].append(g.vega_per_point if g else np.nan)
        cols["stale_last"].append(stale)
        cols["spot_at_trade"].append(s_trade)
    for k, v in cols.items():
        ch[k] = v
    ch["usable"] = ch["iv"].notna()
    return ch.sort_values(["kind", "strike"]).reset_index(drop=True)


def _spot_at(path: pd.Series, t) -> float:
    """Stock price on the 1-minute bar covering time t (NaN if t is outside the path)."""
    if t is None or pd.isna(t) or path.empty:
        return float("nan")
    t = pd.Timestamp(t)
    if t < path.index[0] or t > path.index[-1] + pd.Timedelta(minutes=2):
        return float("nan")
    v = path.asof(t.floor("min"))
    return float(v) if pd.notna(v) else float("nan")


def atm_iv(chain: pd.DataFrame, spot: float) -> float:
    """ATM implied vol: average of call and put IV interpolated in strike at the spot."""
    vals = []
    for kind in ("call", "put"):
        side = chain[(chain["kind"] == kind) & chain["usable"]].sort_values("strike")
        if len(side) < 2:
            continue
        k = side["strike"].to_numpy()
        v = side["iv"].to_numpy()
        if k[0] <= spot <= k[-1]:
            vals.append(float(np.interp(spot, k, v)))
    return float(np.mean(vals)) if vals else float("nan")


def atm_straddle(chain: pd.DataFrame, spot: float) -> tuple[float, float] | None:
    """(strike, call+put price) at the strike closest to spot that has both legs usable."""
    usable = chain[chain["usable"]]
    c = usable[usable["kind"] == "call"].set_index("strike")["price"]
    p = usable[usable["kind"] == "put"].set_index("strike")["price"]
    both = pd.concat([c, p], axis=1, join="inner", keys=["c", "p"])
    if both.empty:
        return None
    k = both.index[np.argmin(np.abs(both.index.to_numpy() - spot))]
    if abs(k / spot - 1) > 0.05:
        return None
    return float(k), float(both.loc[k, "c"] + both.loc[k, "p"])


def implied_prob_above(chain: pd.DataFrame, level: float, T: float, r: float) -> float:
    """Risk-neutral P(S_T > level) from the call-price slope: -e^{rT} dC/dK.

    Model-free (does not assume lognormal), uses quoted call prices around `level`.
    """
    c = chain[(chain["kind"] == "call") & chain["usable"] & (chain["price_source"] == "mid")]
    c = c.sort_values("strike")
    k = c["strike"].to_numpy()
    p = c["price"].to_numpy()
    if len(k) < 3 or not (k[0] < level < k[-1]):
        return float("nan")
    i = int(np.searchsorted(k, level))
    lo, hi = i - 1, i
    if k[hi] - k[lo] <= 0:
        return float("nan")
    slope = (p[hi] - p[lo]) / (k[hi] - k[lo])
    prob = -math.exp(r * T) * slope
    if not (0.0 <= prob <= 1.0):
        return float("nan")
    return float(prob)


def oi_available(chain: pd.DataFrame) -> bool:
    """Yahoo reports open interest as 0 for every contract outside market hours."""
    return bool(len(chain)) and float((chain["oi"] > 0).mean()) >= 0.05
