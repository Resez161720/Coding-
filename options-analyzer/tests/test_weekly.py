import numpy as np
import pandas as pd
import pytest

from options_analyzer.weekly import HORIZON, decide_lean, fit_logistic, walk_forward, weekly_blocks, weekly_outlook


def _series(daily_returns):
    idx = pd.bdate_range("2014-01-06", periods=len(daily_returns))
    return pd.Series(100 * np.exp(np.cumsum(daily_returns)), index=idx)


def test_blocks_are_anchored_at_latest_bar_and_non_overlapping():
    df = pd.DataFrame({"x": np.arange(23)})
    b = weekly_blocks(df)
    assert b["x"].iloc[-1] == 22
    assert np.all(np.diff(b["x"].to_numpy()) == HORIZON)


def test_random_walk_is_not_validated():
    rng = np.random.default_rng(42)
    out = weekly_outlook(_series(rng.normal(0, 0.015, 2600)))
    assert out.model is not None
    assert not out.model.validated
    assert out.lean in ("NEUTRAL", "LEAN_CALL", "LEAN_PUT")


def test_predictable_series_is_validated_and_direction_is_right():
    # Weekly returns with strong positive autocorrelation: last week's direction predicts next week's.
    rng = np.random.default_rng(1)
    n_weeks = 520
    w = np.zeros(n_weeks)
    for i in range(1, n_weeks):
        w[i] = 0.6 * w[i - 1] + rng.normal(0, 0.02)
    w[-1] = 0.05  # strong up week just ended
    daily = np.repeat(w / HORIZON, HORIZON)
    out = weekly_outlook(_series(daily))
    m = out.model
    assert m.validated, out.model_note
    assert m.accuracy > m.naive_accuracy
    assert m.prob_up > 0.55
    assert out.lean == "CALL"


def test_walk_forward_has_no_lookahead():
    rng = np.random.default_rng(5)
    X = rng.normal(size=(300, 3))
    y = (rng.random(300) > 0.5).astype(float)
    p1, n1, a1 = walk_forward(X, y, min_train=100)
    y2 = y.copy()
    y2[-1] = 1 - y2[-1]  # change the final outcome: no forecast may depend on it
    p2, n2, _ = walk_forward(X, y2, min_train=100)
    np.testing.assert_array_equal(p1, p2)
    np.testing.assert_array_equal(n1, n2)
    assert len(p1) == 200


def test_logistic_recovers_coefficients():
    rng = np.random.default_rng(9)
    X = rng.normal(size=(20000, 2))
    true = np.array([0.3, 1.5, -0.8])
    p = 1 / (1 + np.exp(-(true[0] + X @ true[1:])))
    y = (rng.random(20000) < p).astype(float)
    w = fit_logistic(X, y, l2=0.0)
    np.testing.assert_allclose(w, true, atol=0.08)


def test_short_history_has_no_model():
    rng = np.random.default_rng(2)
    out = weekly_outlook(_series(rng.normal(0, 0.01, 600)))
    assert out.model is None
    assert "ทดสอบโมเดลย้อนหลังไม่ได้" in out.model_note
    assert out.lean in ("NEUTRAL", "LEAN_CALL", "LEAN_PUT")


def test_base_rate_matches_manual_count():
    rng = np.random.default_rng(3)
    c = _series(rng.normal(0.0005, 0.012, 1500))
    out = weekly_outlook(c)
    idx = np.arange(len(c) - 1, -1, -HORIZON)[::-1]
    sampled = c.iloc[idx].to_numpy()
    fwd = sampled[1:] / sampled[:-1] - 1
    assert out.n_weeks == len(fwd)
    assert out.base_up_rate == pytest.approx((fwd > 0).mean())
    assert out.abs_move_pct["median"] == pytest.approx(np.median(np.abs(fwd)))


def test_lean_uses_confidence_interval_without_validated_model():
    rng = np.random.default_rng(4)
    out = weekly_outlook(_series(rng.normal(0, 0.01, 1000)))
    out.model = None
    out.base_up_rate, out.base_ci = 0.60, (0.55, 0.65)
    assert decide_lean(out)[0] == "LEAN_CALL"
    out.base_up_rate, out.base_ci = 0.52, (0.47, 0.57)
    assert decide_lean(out)[0] == "NEUTRAL"
    out.base_up_rate, out.base_ci = 0.40, (0.35, 0.45)
    assert decide_lean(out)[0] == "LEAN_PUT"
