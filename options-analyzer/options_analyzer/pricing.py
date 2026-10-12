"""Black-Scholes-Merton pricing, Greeks, implied volatility and probabilities.

US equity options are American-style. For calls on stocks that pay no dividend
before expiry the American price equals the European (BSM) price. For puts the
early-exercise premium is small for short-dated, near-the-money contracts, which
is what this tool focuses on, so BSM is used as a documented approximation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)

CALL = "call"
PUT = "put"


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / SQRT2)


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def _check_kind(kind: str) -> str:
    k = kind.lower()
    if k not in (CALL, PUT):
        raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")
    return k


def _check_inputs(S: float, K: float, T: float, sigma: float) -> None:
    for name, v in (("S", S), ("K", K)):
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
            raise ValueError(f"{name} must be a positive finite number, got {v!r}")
    if not math.isfinite(T) or T < 0:
        raise ValueError(f"T must be >= 0, got {T!r}")
    if not math.isfinite(sigma) or sigma < 0:
        raise ValueError(f"sigma must be >= 0, got {sigma!r}")


def d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> tuple[float, float]:
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt
    return d1, d1 - vt


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    """European option price under Black-Scholes-Merton with continuous dividend yield q."""
    kind = _check_kind(kind)
    _check_inputs(S, K, T, sigma)
    if T == 0 or sigma == 0:
        fwd = S * math.exp((r - q) * T)
        disc = math.exp(-r * T)
        intrinsic = max(fwd - K, 0.0) if kind == CALL else max(K - fwd, 0.0)
        return disc * intrinsic
    d1, d2 = d1_d2(S, K, T, r, sigma, q)
    dq = math.exp(-q * T)
    dr = math.exp(-r * T)
    if kind == CALL:
        return S * dq * norm_cdf(d1) - K * dr * norm_cdf(d2)
    return K * dr * norm_cdf(-d2) - S * dq * norm_cdf(-d1)


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta_per_day: float  # change in option value per calendar day
    vega_per_point: float  # change in option value per 1 vol point (0.01)
    rho_per_point: float  # change in option value per 1% rate move


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> Greeks:
    kind = _check_kind(kind)
    _check_inputs(S, K, T, sigma)
    if T == 0 or sigma == 0:
        raise ValueError("Greeks are undefined at T == 0 or sigma == 0")
    d1, d2 = d1_d2(S, K, T, r, sigma, q)
    dq = math.exp(-q * T)
    dr = math.exp(-r * T)
    sqrt_t = math.sqrt(T)
    pdf = norm_pdf(d1)
    gamma = dq * pdf / (S * sigma * sqrt_t)
    vega = S * dq * pdf * sqrt_t
    common = -S * dq * pdf * sigma / (2.0 * sqrt_t)
    if kind == CALL:
        delta = dq * norm_cdf(d1)
        theta = common - r * K * dr * norm_cdf(d2) + q * S * dq * norm_cdf(d1)
        rho = K * T * dr * norm_cdf(d2)
    else:
        delta = -dq * norm_cdf(-d1)
        theta = common + r * K * dr * norm_cdf(-d2) - q * S * dq * norm_cdf(-d1)
        rho = -K * T * dr * norm_cdf(-d2)
    return Greeks(delta=delta, gamma=gamma, theta_per_day=theta / 365.0,
                  vega_per_point=vega / 100.0, rho_per_point=rho / 100.0)


def no_arbitrage_bounds(S: float, K: float, T: float, r: float, kind: str, q: float = 0.0) -> tuple[float, float]:
    """(lower, upper) bounds on a European option price."""
    kind = _check_kind(kind)
    s_disc = S * math.exp(-q * T)
    k_disc = K * math.exp(-r * T)
    if kind == CALL:
        return max(0.0, s_disc - k_disc), s_disc
    return max(0.0, k_disc - s_disc), k_disc


def implied_vol(price: float, S: float, K: float, T: float, r: float, kind: str, q: float = 0.0,
                lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-8) -> float | None:
    """Implied volatility by bisection (the BSM price is strictly increasing in sigma).

    Returns None when the price is outside the no-arbitrage range or the solution
    lies outside [lo, hi]; callers must treat None as "no reliable IV".
    """
    kind = _check_kind(kind)
    if not (math.isfinite(price) and price > 0) or T <= 0:
        return None
    _check_inputs(S, K, T, 0.0)
    lower, upper = no_arbitrage_bounds(S, K, T, r, kind, q)
    if price <= lower or price >= upper:
        return None
    if price < bs_price(S, K, T, r, lo, kind, q) or price > bs_price(S, K, T, r, hi, kind, q):
        return None
    a, b = lo, hi
    while b - a > tol:
        mid = 0.5 * (a + b)
        if bs_price(S, K, T, r, mid, kind, q) < price:
            a = mid
        else:
            b = mid
    return 0.5 * (a + b)


def prob_above(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Risk-neutral probability that S_T > K under a lognormal model (N(d2))."""
    _check_inputs(S, K, T, sigma)
    if T == 0 or sigma == 0:
        fwd = S * math.exp((r - q) * T)
        return 1.0 if fwd > K else 0.0
    _, d2 = d1_d2(S, K, T, r, sigma, q)
    return norm_cdf(d2)


def prob_itm(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    kind = _check_kind(kind)
    p = prob_above(S, K, T, r, sigma, q)
    return p if kind == CALL else 1.0 - p


def prob_touch(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    """Approximate probability the price touches K before expiry.

    Uses the reflection-principle rule of thumb P(touch) ~= 2 * P(ITM at expiry),
    exact for driftless Brownian motion; capped at 1. If K is already in the
    money the strike has been "touched" and 1.0 is returned.
    """
    kind = _check_kind(kind)
    if (kind == CALL and S >= K) or (kind == PUT and S <= K):
        return 1.0
    return min(1.0, 2.0 * prob_itm(S, K, T, r, sigma, kind, q))


def expected_move(S: float, sigma: float, T: float) -> float:
    """One standard deviation price move implied by annualised vol sigma over T years."""
    return S * sigma * math.sqrt(T)
