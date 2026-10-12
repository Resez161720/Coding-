import datetime as dt
import math
from collections import namedtuple

import pandas as pd
import pytest
from conftest import NOW, FakeProvider

from options_analyzer import calendar_us as cal
from options_analyzer import report_html, report_text
from options_analyzer.analysis import analyze
from options_analyzer.cli import main
from options_analyzer.contracts import sanity_errors
from options_analyzer.data import EarningsInfo, YahooProvider
from options_analyzer.pricing import norm_cdf, prob_above
from options_analyzer.stats import empirical_prob_horizon
from options_analyzer.validation import FAIL


def test_full_analysis_on_consistent_data():
    p = FakeProvider()
    res = analyze("TEST", p, now=NOW, focus=("call", round(p.spot)))
    assert res.errors == []
    assert res.validation.count(FAIL) == 0
    assert res.stock.spot == pytest.approx(p.spot)
    assert res.selected.expiry == dt.date(2026, 10, 16)  # first expiry at least 4 days out
    assert res.selected.atm_iv == pytest.approx(p.sigma, abs=0.01)
    assert res.candidates and res.focus is not None
    for ev in res.candidates + [res.focus]:
        assert sanity_errors(ev) == []
    text = report_text.render(res)
    assert "TEST" in text and "ระดับความเสี่ยง" in text
    html = report_html.render(res)
    assert html.startswith("<!doctype html>") and "TEST" in html


def test_contract_probabilities_match_independent_formulas():
    p = FakeProvider()
    res = analyze("TEST", p, now=NOW, focus=("put", round(p.spot)))
    ev, e = res.focus, res.selected
    S, T, r = e.spot, e.T, res.r
    # Long put profits below K - premium.
    be = ev.strike - ev.price
    d2 = (math.log(S / be) + (r - 0.5 * ev.iv ** 2) * T) / (ev.iv * math.sqrt(T))
    assert ev.breakeven == pytest.approx(be)
    assert ev.prob_profit == pytest.approx(norm_cdf(-d2), abs=1e-12)
    assert ev.prob_profit == pytest.approx(1 - prob_above(S, be, T, r, ev.iv), abs=1e-12)
    hist = empirical_prob_horizon(p.hist["Close"], ev.sessions, math.log(be / S), above=False)
    assert ev.prob_profit_hist.prob == pytest.approx(hist.prob)
    assert ev.cost == pytest.approx(ev.price * 100)


def test_model_free_probability_is_close_to_lognormal():
    p = FakeProvider(spread=0.0)
    res = analyze("TEST", p, now=NOW)
    e = res.selected
    lognormal = prob_above(e.spot, e.spot, e.T, res.r, p.iv_for(e.spot))
    assert e.implied_prob_up == pytest.approx(lognormal, abs=0.06)


def test_earnings_before_expiry_fails_the_criterion():
    p = FakeProvider(earnings=EarningsInfo("known", [dt.date(2026, 10, 14)], []))
    res = analyze("TEST", p, now=NOW, focus=("call", round(p.spot)))
    crit = {c.name: c for c in res.focus.criteria}
    assert crit["ประกาศงบก่อนหมดอายุ"].status == FAIL
    assert res.focus.risk_level in ("ปานกลาง", "สูง", "สูงมาก")


def test_unknown_contract_lists_nearby_strikes():
    p = FakeProvider()
    res = analyze("TEST", p, now=NOW, focus=("call", 9999))
    assert res.focus is None
    assert any("strike ใกล้เคียง" in e for e in res.errors)


def test_unknown_expiry_is_reported():
    res = analyze("TEST", FakeProvider(), now=NOW, expiry="2030-01-01")
    assert res.selected is None
    assert any("ไม่มีวันหมดอายุ" in e for e in res.errors)


# --- YahooProvider parsing, with a stand-in for the yfinance module (same shapes yfinance 1.x returns) ---

def _fake_yf(provider: FakeProvider):
    Options = namedtuple("Options", ["calls", "puts", "underlying"])
    hist = provider.hist.copy()
    hist.index = hist.index.tz_localize(cal.NY)

    class T:
        def __init__(self, symbol):
            self.symbol = symbol
            self.history_metadata = {
                "regularMarketPrice": provider.spot,
                "regularMarketTime": pd.Timestamp(NOW).tz_convert("America/New_York"),
            }
            self.options = tuple(provider.expiries)
            self.info = {"longName": "Yahoo Shape Corp", "quoteType": "EQUITY"}
            self.calendar = {"Earnings Date": [dt.date(2026, 11, 11)]}
            self.dividends = pd.Series([0.25, 0.25], index=pd.DatetimeIndex(
                ["2026-03-10", "2026-09-10"]).tz_localize(cal.NY))

        def history(self, period, interval, auto_adjust, actions):
            assert interval == "1d" and auto_adjust is True
            if self.symbol == "^IRX":
                return pd.DataFrame({"Open": 4.4, "High": 4.4, "Low": 4.4, "Close": 4.4, "Volume": 0.0},
                                    index=hist.index[-20:])
            if self.symbol == "^VIX":
                return pd.DataFrame({"Open": 17, "High": 18, "Low": 16, "Close": 17.5, "Volume": 0.0},
                                    index=hist.index[-20:])
            if self.symbol == "SPY":
                m = provider.market.copy()
                m.index = m.index.tz_localize(cal.NY)
                return m
            return hist

        def option_chain(self, expiry):
            calls, puts, _ = provider.chain(self.symbol, expiry)
            return Options(calls, puts, {"regularMarketPrice": provider.spot,
                                         "regularMarketTime": int(NOW.timestamp())})

        def get_earnings_dates(self, limit):
            idx = pd.DatetimeIndex(["2026-11-11 16:00", "2026-07-30 16:00"]).tz_localize(cal.NY)
            return pd.DataFrame({"EPS Estimate": [1.0, 1.0]}, index=idx)

    class YF:
        Ticker = T

    return YF


def test_yahoo_provider_parsing(monkeypatch):
    fp = FakeProvider()
    yp = YahooProvider.__new__(YahooProvider)
    yp._yf, yp._retries, yp._pause, yp._tickers, yp._history_cache = _fake_yf(fp), 1, 0, {}, {}
    monkeypatch.setattr(cal, "now_ny", lambda: NOW)

    h = yp.history("TEST")
    assert h.index.tz is None and h.index[-1] == pd.Timestamp(NOW.date())
    q = yp.quotes("TEST")[0]
    assert q.price == pytest.approx(fp.spot) and q.time == NOW
    calls, puts, uq = yp.chain("TEST", fp.expiries[0])
    assert uq.price == pytest.approx(fp.spot) and uq.time == NOW
    r, src = yp.risk_free_rate()
    assert r == pytest.approx(0.044) and "^IRX" in src
    e = yp.earnings("TEST")
    assert e.status == "known" and e.upcoming == [dt.date(2026, 11, 11)] and e.past == [dt.date(2026, 7, 30)]
    d = yp.dividends("TEST")
    assert d.sum() == pytest.approx(0.5)

    res = analyze("TEST", yp, now=NOW, focus=("call", round(fp.spot)))
    assert res.errors == [], res.errors
    assert res.stock.name == "Yahoo Shape Corp"
    assert res.q == pytest.approx(0.5 / fp.spot)
    assert res.vix == pytest.approx(17.5)
    assert res.focus is not None


def test_cli_writes_reports(tmp_path, monkeypatch, capsys):
    fp = FakeProvider()
    monkeypatch.setattr("options_analyzer.cli._provider", lambda: fp)
    monkeypatch.setattr(cal, "now_ny", lambda: NOW)
    out = tmp_path / "r.html"
    code = main(["TEST", "--put", str(round(fp.spot)), "--html", str(out)])
    assert code == 0
    assert out.exists() and "<html" in out.read_text(encoding="utf-8")
    assert "สัญญาที่คุณเลือก" in capsys.readouterr().out

    out2 = tmp_path / "s.html"
    assert main(["scan", "AAA", "BBB", "--html", str(out2)]) == 0
    assert out2.exists()
    assert "AAA" in capsys.readouterr().out


def test_cli_rejects_both_call_and_put(monkeypatch):
    monkeypatch.setattr("options_analyzer.cli._provider", lambda: FakeProvider())
    assert main(["TEST", "--call", "30", "--put", "30", "--no-html"]) == 2
