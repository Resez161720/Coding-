import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from options_analyzer import calendar_us as cal
from options_analyzer.stats import (empirical_prob_horizon, hv_close_to_close, hv_parkinson, max_drawdown, rsi,
                                    wilson_interval)

D = dt.date


def test_nyse_holidays_2026():
    # NYSE published schedule for 2026.
    expected = {D(2026, 1, 1), D(2026, 1, 19), D(2026, 2, 16), D(2026, 4, 3), D(2026, 5, 25), D(2026, 6, 19),
                D(2026, 7, 3), D(2026, 9, 7), D(2026, 11, 26), D(2026, 12, 25)}
    assert cal.nyse_holidays(2026) == expected


def test_nyse_holidays_2027_observed_rules():
    expected = {D(2027, 1, 1), D(2027, 1, 18), D(2027, 2, 15), D(2027, 3, 26), D(2027, 5, 31), D(2027, 6, 18),
                D(2027, 7, 5), D(2027, 9, 6), D(2027, 11, 25), D(2027, 12, 24)}
    assert cal.nyse_holidays(2027) == expected


def test_saturday_new_year_has_no_friday_closure():
    assert cal.is_trading_day(D(2021, 12, 31))
    assert D(2022, 1, 1) not in cal.nyse_holidays(2022)


def test_last_session_with_data():
    ny = cal.NY
    assert cal.last_session_with_data(dt.datetime(2026, 10, 12, 8, 0, tzinfo=ny)) == D(2026, 10, 9)
    assert cal.last_session_with_data(dt.datetime(2026, 10, 12, 9, 45, tzinfo=ny)) == D(2026, 10, 12)
    assert cal.last_session_with_data(dt.datetime(2026, 10, 17, 12, 0, tzinfo=ny)) == D(2026, 10, 16)
    # Thanksgiving Thursday -> the Wednesday before
    assert cal.last_session_with_data(dt.datetime(2026, 11, 26, 12, 0, tzinfo=ny)) == D(2026, 11, 25)


def test_trading_days_between_skips_weekends_and_holidays():
    assert cal.trading_days_between(D(2026, 10, 12), D(2026, 10, 16)) == 4
    assert cal.trading_days_between(D(2026, 11, 23), D(2026, 11, 27)) == 3  # Thanksgiving
    assert cal.trading_days_between(D(2026, 10, 16), D(2026, 10, 16)) == 0


def test_years_to_expiry_uses_4pm_close():
    now = dt.datetime(2026, 10, 16, 15, 0, tzinfo=cal.NY)
    assert cal.years_to_expiry(now, D(2026, 10, 16)) == pytest.approx(1 / (365 * 24))
    assert cal.years_to_expiry(now, D(2026, 10, 15)) == 0.0


def _gbm(sigma, n=5000, seed=3):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, sigma / math.sqrt(252), n)
    return pd.Series(100 * np.exp(np.cumsum(r)), index=pd.bdate_range("2000-01-03", periods=n))


def test_historical_volatility_recovers_known_sigma():
    c = _gbm(0.30)
    assert hv_close_to_close(c, 4000) == pytest.approx(0.30, rel=0.03)


def test_parkinson_volatility_on_constant_range():
    hi = pd.Series(np.full(30, 101.0))
    lo = pd.Series(np.full(30, 99.0))
    expected = math.sqrt(math.log(101 / 99) ** 2 / (4 * math.log(2))) * math.sqrt(252)
    assert hv_parkinson(hi, lo, 20) == pytest.approx(expected)


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert rsi(down).iloc[-1] == pytest.approx(0.0)


def test_max_drawdown():
    assert max_drawdown(pd.Series([100, 120, 60, 90, 130.0])) == pytest.approx(-0.5)


def test_wilson_interval_reference():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-4)
    assert hi == pytest.approx(0.5962, abs=1e-4)


def test_empirical_prob_matches_manual_count():
    c = _gbm(0.25, n=1500)
    h, thr = 5, math.log(1.02)
    res = empirical_prob_horizon(c, h, thr, above=True, lookback_days=1000)
    window = c.iloc[-(1000 + h):]
    manual = np.log(window / window.shift(h)).dropna()
    assert res.n == len(manual) == 1000
    assert res.prob == pytest.approx((manual > thr).mean())
    assert res.ci_low <= res.prob <= res.ci_high


def test_valuation_time_uses_last_close_when_market_is_closed():
    ny = cal.NY
    open_now = dt.datetime(2026, 10, 12, 11, 0, tzinfo=ny)
    assert cal.valuation_time(open_now) == open_now
    friday_close = dt.datetime(2026, 10, 9, 16, 0, tzinfo=ny)
    assert cal.valuation_time(dt.datetime(2026, 10, 12, 1, 53, tzinfo=ny)) == friday_close  # Monday pre-open
    assert cal.valuation_time(dt.datetime(2026, 10, 10, 12, 0, tzinfo=ny)) == friday_close  # Saturday
    assert cal.valuation_time(dt.datetime(2026, 10, 12, 18, 0, tzinfo=ny)) == dt.datetime(2026, 10, 12, 16, 0, tzinfo=ny)
