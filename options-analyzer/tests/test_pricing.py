import math

import numpy as np
import pytest

from options_analyzer.pricing import (bs_greeks, bs_price, expected_move, implied_vol, no_arbitrage_bounds,
                                      norm_cdf, prob_above, prob_itm, prob_touch)


def test_norm_cdf_reference_values():
    assert norm_cdf(0) == pytest.approx(0.5)
    assert norm_cdf(1.96) == pytest.approx(0.9750021, abs=1e-7)
    assert norm_cdf(-1) == pytest.approx(0.1586553, abs=1e-7)


def test_hull_textbook_example():
    # Hull, Options Futures and Other Derivatives, Example 15.6: c = 4.76, p = 0.81
    assert bs_price(42, 40, 0.5, 0.10, 0.20, "call") == pytest.approx(4.7594, abs=1e-4)
    assert bs_price(42, 40, 0.5, 0.10, 0.20, "put") == pytest.approx(0.8086, abs=1e-4)


@pytest.mark.parametrize("S,K,T,r,q,sigma", [
    (100, 100, 0.25, 0.05, 0.0, 0.2), (50, 60, 1.0, 0.03, 0.02, 0.45), (250, 200, 7 / 365, 0.045, 0.005, 0.8),
])
def test_put_call_parity(S, K, T, r, q, sigma):
    c = bs_price(S, K, T, r, sigma, "call", q)
    p = bs_price(S, K, T, r, sigma, "put", q)
    assert c - p == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-10)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("K", [80, 95, 100, 105, 120])
@pytest.mark.parametrize("sigma", [0.08, 0.25, 0.6, 1.5])
@pytest.mark.parametrize("T", [3 / 365, 30 / 365, 1.0])
def test_implied_vol_round_trip(kind, K, sigma, T):
    price = bs_price(100, K, T, 0.04, sigma, kind, 0.01)
    lower, _ = no_arbitrage_bounds(100, K, T, 0.04, kind, 0.01)
    if price - lower < 1e-6:  # no time value left to identify a volatility
        return
    iv = implied_vol(price, 100, K, T, 0.04, kind, 0.01)
    assert iv is not None
    assert bs_price(100, K, T, 0.04, iv, kind, 0.01) == pytest.approx(price, abs=1e-6)
    assert iv == pytest.approx(sigma, rel=1e-3)


def test_implied_vol_rejects_arbitrage_prices():
    assert implied_vol(4.0, 100, 95, 0.1, 0.0, "call") is None  # below intrinsic 5
    assert implied_vol(101.0, 100, 95, 0.1, 0.0, "call") is None  # above the stock price
    assert implied_vol(0.0, 100, 95, 0.1, 0.0, "call") is None
    assert implied_vol(float("nan"), 100, 95, 0.1, 0.0, "put") is None


@pytest.mark.parametrize("kind", ["call", "put"])
def test_greeks_match_finite_differences(kind):
    S, K, T, r, q, s = 100.0, 103.0, 45 / 365, 0.04, 0.01, 0.3
    g = bs_greeks(S, K, T, r, s, kind, q)
    h = 1e-3
    f = lambda **kw: bs_price(kw.get("S", S), K, kw.get("T", T), r, kw.get("s", s), kind, q)
    assert g.delta == pytest.approx((f(S=S + h) - f(S=S - h)) / (2 * h), rel=1e-5)
    assert g.gamma == pytest.approx((f(S=S + h) - 2 * f() + f(S=S - h)) / h ** 2, rel=1e-3)
    assert g.vega_per_point == pytest.approx((f(s=s + 1e-4) - f(s=s - 1e-4)) / 2e-4 / 100, rel=1e-5)
    day = 1 / 365
    assert g.theta_per_day == pytest.approx(f(T=T - day) - f(), rel=2e-2)


def test_probabilities_match_monte_carlo():
    rng = np.random.default_rng(0)
    S, T, r, q, s = 100.0, 30 / 365, 0.04, 0.0, 0.35
    z = rng.standard_normal(2_000_000)
    ST = S * np.exp((r - q - 0.5 * s * s) * T + s * math.sqrt(T) * z)
    for K in (90, 100, 110):
        assert prob_above(S, K, T, r, s, q) == pytest.approx((ST > K).mean(), abs=2e-3)
        assert prob_itm(S, K, T, r, s, "put", q) == pytest.approx((ST < K).mean(), abs=2e-3)
        # Discounted mean payoff must equal the closed-form price.
        mc_call = math.exp(-r * T) * np.maximum(ST - K, 0).mean()
        assert bs_price(S, K, T, r, s, "call", q) == pytest.approx(mc_call, rel=1e-2)


def test_prob_touch_bounds():
    assert prob_touch(100, 95, 0.1, 0.0, 0.3, "call") == 1.0  # already in the money
    p_itm = prob_itm(100, 110, 0.1, 0.0, 0.3, "call")
    assert prob_touch(100, 110, 0.1, 0.0, 0.3, "call") == pytest.approx(min(1, 2 * p_itm))


def test_expected_move():
    assert expected_move(100, 0.32, 1.0) == pytest.approx(32.0)
    assert expected_move(100, 0.32, 0.25) == pytest.approx(16.0)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        bs_price(-1, 100, 0.1, 0.0, 0.2, "call")
    with pytest.raises(ValueError):
        bs_price(100, 100, 0.1, 0.0, 0.2, "straddle")
