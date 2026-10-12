import datetime as dt

import numpy as np
import pandas as pd
import pytest
from conftest import NOW, FakeProvider, gbm_history

from options_analyzer import calendar_us as cal
from options_analyzer.analysis import analyze
from options_analyzer.chain import build_chain
from options_analyzer.data import Quote
from options_analyzer.validation import FAIL, PASS, WARN, validate_chain, validate_history, validate_spot


def statuses(rep, name):
    return [c.status for c in rep.checks if c.name == name]


def test_clean_history_passes():
    rep, df = validate_history(gbm_history(), NOW)
    assert not rep.failed()
    assert rep.count(WARN) == 0
    assert len(df) == 2520


def test_stale_history_fails():
    h = gbm_history(end=NOW.date() - dt.timedelta(days=10))
    rep, _ = validate_history(h, NOW)
    assert statuses(rep, "ความสดใหม่") == [FAIL]


def test_one_session_lag_is_only_a_warning():
    h = gbm_history(end=dt.date(2026, 10, 9))  # previous Friday, run on Monday during market hours
    rep, _ = validate_history(h, NOW)
    assert statuses(rep, "ความสดใหม่") == [WARN]


def test_missing_recent_close_fails():
    h = gbm_history()
    h.iloc[-2, h.columns.get_loc("Close")] = np.nan
    rep, _ = validate_history(h, NOW)
    assert rep.failed()


def test_negative_recent_price_fails():
    h = gbm_history()
    h.iloc[-3, h.columns.get_loc("Close")] = -5
    rep, _ = validate_history(h, NOW)
    assert statuses(rep, "ราคาเป็นบวก") == [FAIL]


def test_inconsistent_ohlc_fails():
    h = gbm_history()
    h["High"] = h["Low"] * 0.9  # High below Low everywhere
    rep, _ = validate_history(h, NOW)
    assert statuses(rep, "OHLC สอดคล้อง") == [FAIL]


def test_duplicate_dates_are_removed():
    h = gbm_history()
    h = pd.concat([h, h.iloc[[-1]]])
    rep, df = validate_history(h, NOW)
    assert statuses(rep, "วันที่ซ้ำ") == [WARN]
    assert df.index.is_unique


def test_split_like_jump_is_flagged():
    h = gbm_history()
    h.iloc[-100:, :4] = h.iloc[-100:, :4] / 2  # an unadjusted 2-for-1 split
    rep, _ = validate_history(h, NOW)
    assert statuses(rep, "การเคลื่อนไหวผิดปกติ") == [WARN]


def test_spot_cross_check_thresholds():
    d = NOW.date()
    assert statuses(validate_spot(101, 100, d), "ตรวจไขว้กับราคาย้อนหลัง") == [PASS]
    assert statuses(validate_spot(115, 100, d), "ตรวจไขว้กับราคาย้อนหลัง") == [WARN]
    assert statuses(validate_spot(140, 100, d), "ตรวจไขว้กับราคาย้อนหลัง") == [FAIL]
    assert validate_spot(None, 100, d).failed()


def _chain(p: FakeProvider, spot=None):
    exp = p.expiries[1]
    calls, puts, _ = p.chain("X", exp)
    T = cal.years_to_expiry(NOW, dt.date.fromisoformat(exp))
    s = p.spot if spot is None else spot
    return build_chain(calls, puts, s, T, p.r, 0.0, NOW.date()), s, T


def test_clean_chain_passes_all_checks():
    p = FakeProvider()
    ch, s, T = _chain(p)
    rep = validate_chain(ch, s, T, p.r, 0.0, NOW.date())
    assert not rep.failed(), [c for c in rep.checks if c.status != PASS]


def test_parity_detects_chain_from_a_different_spot():
    p = FakeProvider()
    ch, s, T = _chain(p, spot=None)
    rep = validate_chain(ch, s * 1.08, T, p.r, 0.0, NOW.date())
    assert statuses(rep, "Put-Call Parity") == [FAIL]


def test_crossed_and_below_intrinsic_quotes_are_excluded():
    p = FakeProvider()
    exp = p.expiries[1]
    calls, puts, _ = p.chain("X", exp)
    S = p.spot
    i_atm = int((calls["strike"] - S).abs().idxmin())
    calls.loc[i_atm, ["bid", "ask"]] = [2.0, 1.0]  # crossed
    deep = int((calls["strike"] - (S - 5)).abs().idxmin())
    calls.loc[deep, ["bid", "ask"]] = [0.10, 0.20]  # far below intrinsic of ~5
    T = cal.years_to_expiry(NOW, dt.date.fromisoformat(exp))
    ch = build_chain(calls, puts, S, T, p.r, 0.0, NOW.date())
    rep = validate_chain(ch, S, T, p.r, 0.0, NOW.date())
    assert statuses(rep, "Bid ≤ Ask") == [WARN]
    assert statuses(rep, "ราคาไม่ต่ำกว่ามูลค่าที่แท้จริง") == [WARN]
    k_atm, k_deep = calls.loc[i_atm, "strike"], calls.loc[deep, "strike"]
    c = ch[ch["kind"] == "call"].set_index("strike")
    assert not c.loc[k_atm, "usable"] and not c.loc[k_deep, "usable"]


def test_no_quotes_falls_back_to_last_trade_with_warning():
    p = FakeProvider()
    exp = p.expiries[1]
    calls, puts, _ = p.chain("X", exp)
    for df in (calls, puts):
        df["bid"] = 0.0
        df["ask"] = 0.0
    T = cal.years_to_expiry(NOW, dt.date.fromisoformat(exp))
    ch = build_chain(calls, puts, p.spot, T, p.r, 0.0, NOW.date())
    rep = validate_chain(ch, p.spot, T, p.r, 0.0, NOW.date())
    assert statuses(rep, "ราคาเสนอซื้อ/ขาย") == [WARN]
    assert (ch.loc[ch["usable"], "price_source"] == "last").all()


def test_old_last_trades_are_not_used():
    p = FakeProvider()
    exp = p.expiries[1]
    calls, puts, _ = p.chain("X", exp)
    for df in (calls, puts):
        df["bid"] = 0.0
        df["ask"] = 0.0
        df["lastTradeDate"] = pd.Timestamp("2026-09-01", tz="UTC")
    T = cal.years_to_expiry(NOW, dt.date.fromisoformat(exp))
    ch = build_chain(calls, puts, p.spot, T, p.r, 0.0, NOW.date())
    assert not ch["usable"].any()
    rep = validate_chain(ch, p.spot, T, p.r, 0.0, NOW.date())
    assert rep.failed()


def test_analysis_stops_on_bad_history():
    p = FakeProvider(hist=gbm_history(end=NOW.date() - dt.timedelta(days=20)))
    res = analyze("X", p, now=NOW)
    assert res.errors and res.stock is None and res.candidates == []


def test_analysis_withholds_contracts_when_chain_is_inconsistent():
    p = FakeProvider()
    exp = p.expiries[0]
    calls, puts, _ = p.chain("X", exp)
    # Chain quoted against a stock price 10% higher than the real one: parity check must catch it.
    shifted = FakeProvider(hist=p.hist.assign(Close=p.hist["Close"] * 1.10, High=p.hist["High"] * 1.10,
                                              Open=p.hist["Open"] * 1.10, Low=p.hist["Low"] * 1.10))
    calls, puts, _ = shifted.chain("X", exp)
    p.chain_overrides[exp] = (calls, puts, Quote(p.spot, NOW, "Fake options"))
    res = analyze("X", p, now=NOW)
    assert res.validation.failed("ออปชั่น")
    assert res.candidates == [] and res.focus is None
    assert any("ออปชั่น" in e for e in res.errors)


def test_mismatched_quote_sources_fail():
    p = FakeProvider()
    exp = p.expiries[0]
    calls, puts, _ = p.chain("X", exp)
    p.chain_overrides[exp] = (calls, puts, Quote(p.spot * 1.2, NOW, "Fake options"))
    res = analyze("X", p, now=NOW, focus=("call", round(p.spot)))
    assert statuses(res.validation, "ตรวจไขว้ 2 แหล่ง") == [FAIL]
    assert res.candidates == [] and res.focus is None
    assert res.stock is not None  # stock statistics do not depend on the option quote


def test_stale_quote_during_market_hours_warns():
    p = FakeProvider()
    p.quotes = lambda symbol: [Quote(p.spot, NOW - dt.timedelta(hours=2), "Fake chart")]
    res = analyze("X", p, now=NOW)
    assert statuses(res.validation, "เวลาของราคา") == [WARN]


def test_rate_out_of_range_falls_back_with_warning():
    p = FakeProvider(r=0.9)
    res = analyze("X", p, now=NOW)
    assert res.r == pytest.approx(0.04)
    assert statuses(res.validation, "อัตราดอกเบี้ยปลอดความเสี่ยง") == [WARN]
