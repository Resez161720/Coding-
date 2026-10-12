"""Normalise a raw option chain and attach our own implied volatility and Greeks."""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from . import calendar_us as cal
from .pricing import bs_greeks, implied_vol

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
                last_session: dt.date) -> pd.DataFrame:
    frames = [_side(df, kind) for df, kind in ((calls, "call"), (puts, "put")) if df is not None and len(df)]
    if not frames:
        return pd.DataFrame()
    ch = pd.concat(frames, ignore_index=True)
    ch = ch.drop_duplicates(subset=["kind", "strike"], keep="first").reset_index(drop=True)

    has_quote = (ch["bid"] > 0) & (ch["ask"] > 0)
    ch["crossed"] = has_quote & (ch["bid"] > ch["ask"])
    ch["mid"] = np.where(has_quote & ~ch["crossed"], (ch["bid"] + ch["ask"]) / 2.0, np.nan)
    ch["spread_pct"] = np.where(ch["mid"] > 0, (ch["ask"] - ch["bid"]) / ch["mid"], np.nan)

    traded_recently = ch["last_trade"].apply(
        lambda t: t is not None and not pd.isna(t) and t.date() >= last_session)
    use_last = ~(has_quote) & (ch["last"] > 0) & traded_recently
    ch["price_source"] = np.where(ch["mid"].notna(), "mid", np.where(use_last, "last", "none"))
    ch["price"] = np.where(ch["mid"].notna(), ch["mid"], np.where(use_last, ch["last"], np.nan))

    intrinsic = np.where(ch["kind"] == "call", np.maximum(spot - ch["strike"], 0.0),
                         np.maximum(ch["strike"] - spot, 0.0))
    ch["intrinsic"] = intrinsic
    tol = np.maximum(0.05, 0.02 * intrinsic)
    ch["below_intrinsic"] = ch["price"].notna() & (ch["price"] < intrinsic - tol)

    ivs, deltas, gammas, thetas, vegas = [], [], [], [], []
    for row in ch.itertuples(index=False):
        iv = None
        if row.price_source != "none" and not row.crossed and not row.below_intrinsic and T > 0:
            iv = implied_vol(float(row.price), spot, float(row.strike), T, r, row.kind, q)
        ivs.append(np.nan if iv is None else iv)
        if iv is not None:
            g = bs_greeks(spot, float(row.strike), T, r, iv, row.kind, q)
            deltas.append(g.delta)
            gammas.append(g.gamma)
            thetas.append(g.theta_per_day)
            vegas.append(g.vega_per_point)
        else:
            deltas.append(np.nan)
            gammas.append(np.nan)
            thetas.append(np.nan)
            vegas.append(np.nan)
    ch["iv"] = ivs
    ch["delta"] = deltas
    ch["gamma"] = gammas
    ch["theta"] = thetas
    ch["vega"] = vegas
    ch["usable"] = ch["iv"].notna()
    return ch.sort_values(["kind", "strike"]).reset_index(drop=True)


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
