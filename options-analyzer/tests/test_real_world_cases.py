"""Cases found by running the tool on real Yahoo data (off-hours quirks, earnings timing, half days)."""
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest
from conftest import NOW, FakeProvider, amc, bmo, gbm_history

from options_analyzer import calendar_us as cal
from options_analyzer import earnings as em
from options_analyzer import report_text
from options_analyzer.analysis import analyze, iv_to_trading_basis
from options_analyzer.chain import build_chain
from options_analyzer.data import EarningsEvent, EarningsInfo, Quote
from options_analyzer.pricing import bs_price, implied_vol

NY = cal.NY
D = dt.date
FRI_CLOSE = dt.datetime(2026, 10, 9, 16, 0, tzinfo=NY)
MON_PRE = dt.datetime(2026, 10, 12, 1, 53, tzinfo=NY)


def statuses(rep, name):
    return [c.status for c in rep.checks if c.name == name]


# --- calendar: early closes and remaining sessions ------------------------------------------------

def test_nyse_early_closes_match_published_calendars():
    assert cal.nyse_early_closes(2024) == {D(2024, 7, 3), D(2024, 11, 29), D(2024, 12, 24)}
    assert cal.nyse_early_closes(2025) == {D(2025, 7, 3), D(2025, 11, 28), D(2025, 12, 24)}
    assert cal.nyse_early_closes(2026) == {D(2026, 11, 27), D(2026, 12, 24)}


def test_half_day_close_is_respected():
    after = dt.datetime(2026, 12, 24, 14, 0, tzinfo=NY)
    assert not cal.market_is_open(after)
    assert cal.valuation_time(after) == dt.datetime(2026, 12, 24, 13, 0, tzinfo=NY)
    assert cal.expiry_close(D(2026, 12, 24)) == dt.datetime(2026, 12, 24, 13, 0, tzinfo=NY)
    wed_close = dt.datetime(2026, 12, 23, 16, 0, tzinfo=NY)
    assert cal.years_to_expiry(wed_close, D(2026, 12, 24)) == pytest.approx(21 / (365 * 24))


def test_sessions_remaining_counts_the_unfinished_session():
    fri = D(2026, 10, 16)
    assert cal.sessions_remaining(FRI_CLOSE, fri) == 5
    assert cal.sessions_remaining(dt.datetime(2026, 10, 12, 9, 45, tzinfo=NY), fri) == pytest.approx(4 + 375 / 390)
    assert cal.sessions_remaining(dt.datetime(2026, 10, 15, 9, 45, tzinfo=NY), fri) == pytest.approx(1 + 375 / 390)
    assert cal.sessions_remaining(dt.datetime(2026, 10, 16, 16, 0, tzinfo=NY), fri) == 0


def test_iv_hv_ratio_does_not_depend_on_the_weekday():
    """An option priced at exactly HV per remaining trading session must grade ~1.0 any day."""
    hv, S, K, r, expiry = 0.164, 336.64, 337.5, 0.04, D(2026, 10, 16)
    for val in (FRI_CLOSE, dt.datetime(2026, 10, 12, 9, 45, tzinfo=NY), dt.datetime(2026, 10, 14, 10, 0, tzinfo=NY)):
        T = cal.years_to_expiry(val, expiry)
        n = cal.sessions_remaining(val, expiry)
        sigma_cal = hv * math.sqrt(n / 252 / T)  # same total variance, calendar-time convention
        price = bs_price(S, K, T, r, sigma_cal, "call")
        iv = implied_vol(price, S, K, T, r, "call")
        assert iv * iv_to_trading_basis(T, n) / hv == pytest.approx(1.0, abs=1e-6)


# --- earnings timing -------------------------------------------------------------------------------

def test_earnings_window_uses_report_time_of_day():
    expiry_close = cal.expiry_close(D(2026, 10, 16))
    assert not em.can_move_between(amc(D(2026, 10, 16)), FRI_CLOSE, expiry_close)  # after the options expire
    assert em.can_move_between(bmo(D(2026, 10, 16)), FRI_CLOSE, expiry_close)
    assert em.can_move_between(amc(D(2026, 10, 15)), FRI_CLOSE, expiry_close)
    assert em.can_move_between(amc(D(2026, 10, 9)), FRI_CLOSE, expiry_close)  # 16:05, after the snapshot
    assert not em.can_move_between(bmo(D(2026, 10, 9)), FRI_CLOSE, expiry_close)  # already in Friday's close
    # A date-only value from a local-time conversion may be one day late: 10-17 could really be 10-16.
    assert em.can_move_between(EarningsEvent(D(2026, 10, 17), None, exact_date=False), FRI_CLOSE, expiry_close)
    assert not em.can_move_between(EarningsEvent(D(2026, 10, 17), None, exact_date=True), FRI_CLOSE, expiry_close)


def test_report_after_the_price_snapshot_blocks_options():
    # Thursday after-close report; run on Friday 02:00 New York (13:00 in Thailand): prices are pre-report.
    thu = D(2026, 10, 8)
    now = dt.datetime(2026, 10, 9, 2, 0, tzinfo=NY)
    p = FakeProvider(hist=gbm_history(end=thu), now=now, off_hours=True,
                     earnings=EarningsInfo("known", [amc(thu), amc(D(2027, 1, 28))], True))
    res = analyze("TEST", p, now=now, focus=("call", round(p.spot)))
    assert statuses(res.validation, "งบออกหลังราคาที่ใช้") == ["FAIL"]
    assert res.candidates == [] and res.focus is None
    assert any("ประกาศงบหลังราคา" in e for e in res.errors)


def test_report_before_the_snapshot_is_history_not_upcoming():
    p = FakeProvider(earnings=EarningsInfo("known", [amc(D(2026, 7, 30)), amc(D(2026, 11, 2))], True))
    res = analyze("TEST", p, now=NOW)
    assert res.next_earnings.date == D(2026, 11, 2)
    assert [d for d, _, _ in res.earnings_moves] == [D(2026, 7, 30)]


def test_earnings_reaction_windows_follow_timing():
    idx = pd.to_datetime(["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03"])
    close = pd.Series([100.0, 101.0, 102.0, 90.0, 91.0], index=idx)
    (_, m_amc, k1), = em.reactions(close, [amc(D(2026, 7, 30))])
    assert k1 == "1d" and m_amc == pytest.approx(90 / 102 - 1)  # close on report day -> next close
    (_, m_bmo, _), = em.reactions(close, [bmo(D(2026, 7, 31))])
    assert m_bmo == pytest.approx(90 / 102 - 1)  # previous close -> close on report day
    (_, m_unk, k3), = em.reactions(close, [EarningsEvent(D(2026, 7, 30))])
    assert k3 == "2d" and m_unk == pytest.approx(90 / 101 - 1)


# --- off-hours option prices ------------------------------------------------------------------------

def _chain_for(p, expiry):
    calls, puts, _ = p.chain("X", expiry)
    T = cal.years_to_expiry(p.price_time, D.fromisoformat(expiry))
    return calls, puts, T


def test_months_old_quotes_are_not_used_off_hours():
    p = FakeProvider(hist=gbm_history(end=D(2026, 10, 9)), now=MON_PRE, off_hours=True)
    exp = p.expiries[0]
    calls, puts, T = _chain_for(p, exp)
    deep = puts.index[-3:]  # deep ITM puts with a stale two-sided quote, untraded since July
    puts.loc[deep, ["bid", "ask"]] = [[50.0, 51.0]] * 3
    puts.loc[deep, "lastTradeDate"] = pd.Timestamp("2026-07-30", tz="UTC")
    closed = build_chain(calls, puts, p.spot, T, p.r, 0.0, D(2026, 10, 9), val_time=p.price_time, market_open=False)
    k = puts.loc[deep, "strike"]
    rows = closed[(closed["kind"] == "put") & closed["strike"].isin(k)]
    assert rows["stale_quote"].all() and not rows["usable"].any()
    live = build_chain(calls, puts, p.spot, T, p.r, 0.0, D(2026, 10, 9), val_time=p.price_time, market_open=True)
    rows = live[(live["kind"] == "put") & live["strike"].isin(k)]
    assert (rows["price_source"] == "mid").all()


def test_last_trade_taken_when_the_stock_was_elsewhere_is_dropped():
    p = FakeProvider(hist=gbm_history(end=D(2026, 10, 9)), now=MON_PRE, off_hours=True)
    exp = p.expiries[0]
    calls, puts, T = _chain_for(p, exp)
    S = p.spot
    itm = calls.index[(calls["strike"] - (S - 2)).abs().argsort()[:1]]
    calls.loc[itm, "lastTradeDate"] = pd.Timestamp("2026-10-09 19:11", tz="UTC")  # 15:11 ET
    minutes = pd.date_range("2026-10-09 09:30", "2026-10-09 15:59", freq="min", tz=NY)
    moved = pd.Series(S, index=minutes)
    moved[moved.index < pd.Timestamp("2026-10-09 15:30", tz=NY)] = S * 1.005  # stock 0.5% higher earlier
    ch = build_chain(calls, puts, S, T, p.r, 0.0, D(2026, 10, 9), val_time=p.price_time, market_open=False,
                     spot_path=moved)
    k = float(calls.loc[itm, "strike"].iloc[0])
    row = ch[(ch["kind"] == "call") & (ch["strike"] == k)].iloc[0]
    assert row["stale_last"] and not row["usable"]
    flat = pd.Series(S, index=minutes)
    ch2 = build_chain(calls, puts, S, T, p.r, 0.0, D(2026, 10, 9), val_time=p.price_time, market_open=False,
                      spot_path=flat)
    row2 = ch2[(ch2["kind"] == "call") & (ch2["strike"] == k)].iloc[0]
    assert row2["usable"] and not row2["stale_last"]


def test_monotonic_violation_between_last_trades_only_warns():
    p = FakeProvider(hist=gbm_history(end=D(2026, 10, 9)), now=MON_PRE, off_hours=True)
    exp = p.expiries[0]
    calls, puts, _ = p.chain("X", exp)
    i = (calls["strike"] - p.spot).abs().idxmin()
    calls.loc[i + 1, "lastPrice"] = calls.loc[i, "lastPrice"] + 0.30  # higher strike priced above lower one
    p.chain_overrides[exp] = (calls, puts, Quote(p.spot, FRI_CLOSE, "Fake options"))
    res = analyze("TEST", p, now=MON_PRE)
    assert statuses(res.validation, "ราคาสอดคล้องตาม strike") == ["WARN"]
    assert res.selected is not None


# --- prices as traded vs adjusted, small reporting fixes -----------------------------------------------

def test_ranges_use_traded_prices_and_volatility_uses_adjusted():
    h = gbm_history()
    h["AdjClose"] = h["Close"] * np.linspace(0.9, 1.0, len(h))
    res = analyze("TEST", FakeProvider(hist=h), now=NOW)
    assert res.stock.low_52w == pytest.approx(h["Low"].iloc[-252:].min())
    assert res.stock.sma50 == pytest.approx(h["Close"].iloc[-50:].mean())
    from options_analyzer.stats import hv_close_to_close
    assert res.stock.hv60 == pytest.approx(hv_close_to_close(h["AdjClose"], 60))


def test_contract_request_without_options_is_an_error():
    p = FakeProvider()
    p.expiries = []
    res = analyze("TEST", p, now=NOW, focus=("call", 700000))
    assert any("ไม่ได้รับข้อมูลออปชั่น" in e for e in res.errors)


def test_header_does_not_show_an_unfetched_rate():
    p = FakeProvider(hist=gbm_history(end=NOW.date() - dt.timedelta(days=30)))
    res = analyze("TEST", p, now=NOW)
    assert res.stock is None
    assert "อัตราดอกเบี้ย n/a" in report_text.render(res)


def test_big_after_hours_move_is_flagged():
    p = FakeProvider(hist=gbm_history(end=D(2026, 10, 9)), now=MON_PRE, off_hours=True)
    p.extended_quote = lambda symbol: Quote(p.spot * 0.94, dt.datetime(2026, 10, 9, 19, 0, tzinfo=NY),
                                            "Yahoo post-market")
    res = analyze("TEST", p, now=MON_PRE)
    assert statuses(res.validation, "ราคานอกเวลาทำการ") == ["WARN"]


def test_off_hours_report_shows_no_fake_zero_quotes():
    p = FakeProvider(hist=gbm_history(end=D(2026, 10, 9)), now=MON_PRE, off_hours=True)
    res = analyze("TEST", p, now=MON_PRE, focus=("call", round(p.spot)))
    text = report_text.render(res)
    assert "bid n/a / ask n/a" in text and "bid 0.00" not in text


def test_etf_options_trading_until_1615_are_priced_after_the_close():
    p = FakeProvider(hist=gbm_history(end=D(2026, 10, 9)), now=MON_PRE, off_hours=True)
    exp = p.expiries[0]
    calls, puts, T = _chain_for(p, exp)
    S = p.spot
    calls["lastTradeDate"] = pd.Timestamp("2026-10-09 20:14", tz="UTC")  # 16:14 ET, late ETF options session
    minutes = pd.date_range("2026-10-09 09:30", "2026-10-09 16:20", freq="min", tz=NY)
    path = pd.Series(S, index=minutes)
    ch = build_chain(calls, puts, S, T, p.r, 0.0, D(2026, 10, 9), val_time=p.price_time, market_open=False,
                     spot_path=path)
    assert (ch.loc[ch["kind"] == "call", "price_source"] == "last").any()
    late = pd.Timestamp("2026-10-09 20:40", tz="UTC")  # 16:40 ET: after the late session, not trusted
    calls["lastTradeDate"] = late
    ch2 = build_chain(calls, puts, S, T, p.r, 0.0, D(2026, 10, 9), val_time=p.price_time, market_open=False,
                      spot_path=path)
    assert (ch2.loc[ch2["kind"] == "call", "price_source"] == "none").all()
