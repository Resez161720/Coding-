"""Orchestrates data fetching, verification and analysis for one ticker."""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import calendar_us as cal
from .chain import atm_iv, atm_straddle, build_chain, implied_prob_above
from .contracts import Context, ContractEval, evaluate, find_contract, pick_candidates, sanity_errors
from .data import EarningsInfo, Provider, Quote
from .pricing import expected_move
from .stats import (atr, beta, horizon_log_returns, hv_close_to_close, hv_parkinson, hv_percentile,
                    max_drawdown, rsi, sma)
from .validation import FAIL, PASS, WARN, ValidationReport, validate_chain, validate_history, validate_spot
from .weekly import WeeklyOutlook, weekly_outlook

DEFAULT_RATE = 0.04
MARKET = "SPY"


@dataclass
class StockSummary:
    name: str
    spot: float
    spot_time: dt.datetime | None
    last_date: dt.date
    change_1d: float
    change_5d: float
    change_21d: float
    high_52w: float
    low_52w: float
    sma20: float
    sma50: float
    sma200: float
    rsi14: float
    atr14_pct: float
    hv20: float
    hv60: float
    hv252: float
    hv20_percentile: float
    parkinson20: float
    max_drawdown_1y: float
    beta_1y: float
    dividend_yield: float


@dataclass
class ExpiryInfo:
    expiry: dt.date
    dte: int
    sessions: int
    T: float
    spot: float
    atm_iv: float
    straddle_strike: float | None
    straddle_price: float | None
    expected_move_iv: float
    implied_prob_up: float
    hist_prob_exceed_straddle: float
    hist_n: int
    put_call_oi: float
    put_call_volume: float
    skew_25d: float


@dataclass
class AnalysisResult:
    ticker: str
    generated_at: dt.datetime
    validation: ValidationReport = field(default_factory=ValidationReport)
    history: pd.DataFrame | None = None
    stock: StockSummary | None = None
    weekly: WeeklyOutlook | None = None
    market_note: str = ""
    vix: float | None = None
    spy_above_sma200: bool | None = None
    r: float = DEFAULT_RATE
    r_source: str = ""
    q: float = 0.0
    earnings: EarningsInfo | None = None
    earnings_moves: list[tuple[dt.date, float]] = field(default_factory=list)
    expirations: list[str] = field(default_factory=list)
    term: list[tuple[dt.date, int, float]] = field(default_factory=list)
    selected: ExpiryInfo | None = None
    chain: pd.DataFrame | None = None
    candidates: list[ContractEval] = field(default_factory=list)
    focus: ContractEval | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def options_ok(self) -> bool:
        return self.selected is not None and not self.validation.failed("ออปชั่น")


def _pct(a: float, b: float) -> float:
    return a / b - 1 if b else float("nan")


def _choose_expiry(expirations: list[str], today: dt.date, wanted: str | None, min_dte: int) -> tuple[str | None, str]:
    if wanted:
        if wanted in expirations:
            return wanted, ""
        return None, f"ไม่มีวันหมดอายุ {wanted} — วันที่มี: {', '.join(expirations[:12])}"
    for e in expirations:
        if (dt.date.fromisoformat(e) - today).days >= min_dte:
            return e, ""
    return None, "ไม่มีวันหมดอายุที่เหมาะสม"


def _skew(chain: pd.DataFrame) -> float:
    u = chain[chain["usable"]]
    puts = u[u["kind"] == "put"]
    calls = u[u["kind"] == "call"]
    if puts.empty or calls.empty:
        return float("nan")
    p = puts.iloc[(puts["delta"] + 0.25).abs().argsort().iloc[0]]
    c = calls.iloc[(calls["delta"] - 0.25).abs().argsort().iloc[0]]
    if abs(p["delta"] + 0.25) > 0.10 or abs(c["delta"] - 0.25) > 0.10:
        return float("nan")
    return float(p["iv"] - c["iv"])


def _earnings_moves(close: pd.Series, dates: list[dt.date], n: int = 8) -> list[tuple[dt.date, float]]:
    """Close before the report date -> close after it (covers before-open and after-close reports)."""
    out = []
    idx = close.index
    for d in sorted(dates)[-n:]:
        ts = pd.Timestamp(d)
        before = idx[idx < ts]
        after = idx[idx > ts]
        if len(before) == 0 or len(after) == 0 or (after[0] - ts).days > 5:
            continue
        out.append((d, float(close.loc[after[0]] / close.loc[before[-1]] - 1)))
    return out


def _check_quote_time(t: dt.datetime | None, now: dt.datetime, rep: ValidationReport) -> None:
    if t is None:
        rep.add("ราคาปัจจุบัน", "เวลาของราคา", WARN, "แหล่งข้อมูลไม่ระบุเวลาของราคา")
        return
    if cal.market_is_open(now):
        age = (now - t).total_seconds() / 60
        if age > 30:
            rep.add("ราคาปัจจุบัน", "เวลาของราคา", WARN,
                    f"ราคาล่าสุดเมื่อ {t:%Y-%m-%d %H:%M} ET ({age:,.0f} นาทีที่แล้ว) ขณะตลาดเปิด — อาจถูกพักการซื้อขายหรือข้อมูลค้าง")
            return
    elif t.date() < cal.last_session_with_data(now):
        rep.add("ราคาปัจจุบัน", "เวลาของราคา", WARN,
                f"ราคาล่าสุดเมื่อ {t:%Y-%m-%d %H:%M} ET เก่ากว่าวันทำการล่าสุด")
        return
    rep.add("ราคาปัจจุบัน", "เวลาของราคา", PASS, f"ราคา ณ {t:%Y-%m-%d %H:%M} ET")


def _cross_check_quotes(quotes: list[Quote], rep: ValidationReport) -> None:
    good = [q for q in quotes if q.price is not None and q.price > 0]
    if len(good) < 2:
        return
    a, b = good[0], good[1]
    diff = b.price / a.price - 1
    detail = f"{a.source} = {a.price:,.2f} เทียบ {b.source} = {b.price:,.2f} ({diff:+.2%})"
    if abs(diff) <= 0.01:
        rep.add("ราคาปัจจุบัน", "ตรวจไขว้ 2 แหล่ง", PASS, detail)
    elif abs(diff) <= 0.05:
        rep.add("ราคาปัจจุบัน", "ตรวจไขว้ 2 แหล่ง", WARN, detail + " — อาจเป็นเพราะเวลาอัปเดตต่างกัน")
    else:
        rep.add("ราคาปัจจุบัน", "ตรวจไขว้ 2 แหล่ง", FAIL, detail + " — ราคาไม่ตรงกัน")


def analyze(ticker: str, provider: Provider, now: dt.datetime | None = None, expiry: str | None = None,
            focus: tuple[str, float] | None = None, min_dte: int = 4, term_n: int = 4,
            per_side: int = 6) -> AnalysisResult:
    ticker = ticker.upper().strip()
    now = now or cal.now_ny()
    today = now.date()
    res = AnalysisResult(ticker=ticker, generated_at=now)
    rep = res.validation

    # 1. Price history ---------------------------------------------------------------
    try:
        raw = provider.history(ticker, "10y")
    except Exception as e:
        res.errors.append(f"ดึงข้อมูลราคา {ticker} ไม่สำเร็จ: {e}")
        return res
    hrep, hist = validate_history(raw, now)
    rep.extend(hrep)
    if hrep.failed():
        res.errors.append("ข้อมูลราคาย้อนหลังไม่ผ่านการตรวจสอบ — หยุดการวิเคราะห์เพื่อป้องกันผลลัพธ์ผิดพลาด")
        return res
    res.history = hist
    close = hist["Close"]
    last_close = float(close.iloc[-1])
    last_date = hist.index[-1].date()

    # 2. Live quote, cross-checked ------------------------------------------------------
    quotes = []
    try:
        quotes = provider.quotes(ticker)
    except Exception:
        pass
    q0 = next((q for q in quotes if q.price), None)
    spot = q0.price if q0 else last_close
    spot_time = q0.time if q0 else None
    if q0 is None:
        rep.add("ราคาปัจจุบัน", "ราคาปัจจุบัน", WARN, "ไม่ได้รับราคาปัจจุบันแยก — ใช้ราคาปิดล่าสุดจากข้อมูลย้อนหลัง")
    else:
        srep = validate_spot(spot, last_close, last_date)
        _check_quote_time(spot_time, now, srep)
        rep.extend(srep)
        if srep.failed():
            res.errors.append("ราคาปัจจุบันไม่สอดคล้องกับข้อมูลย้อนหลัง — หยุดการวิเคราะห์")
            return res

    profile = {}
    try:
        profile = provider.profile(ticker) or {}
    except Exception:
        pass
    name = profile.get("longName") or profile.get("shortName") or ticker

    # 3. Rates and dividends -------------------------------------------------------------
    r, r_src = None, ""
    try:
        r, r_src = provider.risk_free_rate()
    except Exception as e:
        r_src = str(e)
    if r is None or not (0.0 <= r <= 0.15):
        rep.add("อัตราดอกเบี้ย", "อัตราดอกเบี้ยปลอดความเสี่ยง", WARN,
                f"ใช้ค่าเริ่มต้น {DEFAULT_RATE:.2%} เพราะ: {r_src or 'ค่าไม่อยู่ในช่วงที่สมเหตุสมผล'}")
        r, r_src = DEFAULT_RATE, "ค่าเริ่มต้น"
    else:
        rep.add("อัตราดอกเบี้ย", "อัตราดอกเบี้ยปลอดความเสี่ยง", PASS, f"{r:.2%} จาก {r_src}")
    res.r, res.r_source = r, r_src

    q = 0.0
    try:
        div = provider.dividends(ticker)
        if div is not None and len(div):
            ttm = float(div[div.index > pd.Timestamp(today - dt.timedelta(days=365))].sum())
            q = ttm / spot
    except Exception:
        pass
    if not (0.0 <= q <= 0.15):
        rep.add("ปันผล", "อัตราปันผล", WARN, f"อัตราปันผลคำนวณได้ {q:.2%} ผิดปกติ — ใช้ 0%")
        q = 0.0
    res.q = q

    # 4. Market context ------------------------------------------------------------------
    market_close = None
    if ticker == MARKET:
        market_close = close
    else:
        try:
            mrep, mhist = validate_history(provider.history(MARKET, "10y"), now, area="ตลาด (SPY)")
            if mrep.failed():
                res.notes.append("ข้อมูล SPY ไม่ผ่านการตรวจสอบ — ไม่ใช้ปัจจัยตลาดในการวิเคราะห์")
            else:
                market_close = mhist["Close"]
        except Exception as e:
            res.notes.append(f"ดึงข้อมูล SPY ไม่ได้ ({e}) — ไม่ใช้ปัจจัยตลาด")
    if market_close is not None and len(market_close) > 200:
        res.spy_above_sma200 = bool(market_close.iloc[-1] > sma(market_close, 200).iloc[-1])
    try:
        vix = provider.history("^VIX", "1mo")["Close"].dropna()
        if len(vix) and 5 <= float(vix.iloc[-1]) <= 150:
            res.vix = float(vix.iloc[-1])
    except Exception:
        pass

    # 5. Stock statistics ----------------------------------------------------------------
    hi, lo = hist["High"], hist["Low"]
    last_year = close.iloc[-252:]
    s20, s50, s200 = (sma(close, n).iloc[-1] for n in (20, 50, 200))
    res.stock = StockSummary(
        name=name, spot=spot, spot_time=spot_time, last_date=last_date,
        change_1d=_pct(close.iloc[-1], close.iloc[-2]) if len(close) > 1 else float("nan"),
        change_5d=_pct(close.iloc[-1], close.iloc[-6]) if len(close) > 5 else float("nan"),
        change_21d=_pct(close.iloc[-1], close.iloc[-22]) if len(close) > 21 else float("nan"),
        high_52w=float(hi.iloc[-252:].max()), low_52w=float(lo.iloc[-252:].min()),
        sma20=float(s20), sma50=float(s50), sma200=float(s200),
        rsi14=float(rsi(close).iloc[-1]),
        atr14_pct=float(atr(hi, lo, close).iloc[-1] / close.iloc[-1]),
        hv20=hv_close_to_close(close, 20), hv60=hv_close_to_close(close, 60), hv252=hv_close_to_close(close, 252),
        hv20_percentile=hv_percentile(close, 20, 252),
        parkinson20=hv_parkinson(hi, lo, 20),
        max_drawdown_1y=max_drawdown(last_year),
        beta_1y=beta(close, market_close) if market_close is not None and ticker != MARKET else (
            1.0 if ticker == MARKET else float("nan")),
        dividend_yield=q,
    )

    # 6. Weekly outlook ------------------------------------------------------------------
    try:
        res.weekly = weekly_outlook(close, market_close)
    except Exception as e:
        res.notes.append(f"คำนวณสถิติรายสัปดาห์ไม่ได้: {e}")

    # 7. Earnings ---------------------------------------------------------------------------
    try:
        res.earnings = provider.earnings(ticker)
    except Exception:
        res.earnings = EarningsInfo("unknown")
    if res.earnings.past:
        res.earnings_moves = _earnings_moves(close, res.earnings.past)

    # 8. Options ---------------------------------------------------------------------------
    try:
        res.expirations = provider.expirations(ticker)
    except Exception as e:
        res.notes.append(f"ดึงรายการวันหมดอายุออปชั่นไม่ได้: {e}")
        return res
    if not res.expirations:
        res.notes.append("หุ้นตัวนี้ไม่มีออปชั่นซื้อขาย (หรือแหล่งข้อมูลไม่ส่งมา)")
        return res
    chosen, msg = _choose_expiry(res.expirations, today, expiry, min_dte)
    if chosen is None:
        res.errors.append(msg)
        return res

    last_session = cal.last_session_with_data(now)
    to_fetch = [chosen] + [e for e in res.expirations if e != chosen and dt.date.fromisoformat(e) > today][:term_n]
    for e in to_fetch:
        e_date = dt.date.fromisoformat(e)
        T = cal.years_to_expiry(now, e_date)
        try:
            calls, puts, uq = provider.chain(ticker, e)
        except Exception as ex:
            if e == chosen:
                rep.add("ออปชั่น", "ดึงข้อมูล option chain", FAIL, str(ex))
                return res
            continue
        if e == chosen:
            _cross_check_quotes(quotes + [uq], rep)
            if rep.failed("ราคาปัจจุบัน"):
                res.errors.append("ราคาหุ้นจากแต่ละแหล่งไม่ตรงกัน — ไม่แสดงการประเมินออปชั่นเพื่อป้องกันข้อมูลผิดพลาด")
                return res
        chain_spot = uq.price if uq.price and abs(uq.price / spot - 1) <= 0.05 else spot
        ch = build_chain(calls, puts, chain_spot, T, r, q, last_session)
        crep = validate_chain(ch, chain_spot, T, r, q, last_session)
        if e == chosen:
            rep.extend(crep)
            res.chain = ch
            if crep.failed():
                res.errors.append("ข้อมูลออปชั่นไม่ผ่านการตรวจสอบ — ไม่แสดงการประเมินสัญญาเพื่อป้องกันข้อมูลผิดพลาด")
                return res
            _fill_expiry(res, ch, chain_spot, e_date, T, today, close, r)
            _evaluate_contracts(res, ch, chain_spot, e_date, T, today, close, r, q, focus, per_side)
        elif crep.failed():
            res.notes.append(f"ไม่แสดง IV ของวันหมดอายุ {e} ใน term structure เพราะข้อมูลไม่ผ่านการตรวจสอบ")
            continue
        iv_atm = atm_iv(ch, chain_spot)
        if math.isfinite(iv_atm):
            res.term.append((e_date, (e_date - today).days, iv_atm))
    res.term.sort()
    return res


def _fill_expiry(res: AnalysisResult, ch: pd.DataFrame, spot: float, e_date: dt.date, T: float,
                 today: dt.date, close: pd.Series, r: float) -> None:
    sessions = max(cal.trading_days_between(today, e_date), 1)
    iv = atm_iv(ch, spot)
    st = atm_straddle(ch, spot)
    hist_p, hist_n = float("nan"), 0
    if st is not None:
        rets = horizon_log_returns(close, sessions, 5 * 252)
        hist_n = len(rets)
        if hist_n:
            hist_p = float((np.abs(np.expm1(rets)) > st[1] / spot).mean())
    oi = ch.groupby("kind")["oi"].sum()
    vol = ch.groupby("kind")["volume"].sum()
    res.selected = ExpiryInfo(
        expiry=e_date, dte=(e_date - today).days, sessions=sessions, T=T, spot=spot, atm_iv=iv,
        straddle_strike=st[0] if st else None, straddle_price=st[1] if st else None,
        expected_move_iv=expected_move(spot, iv, T) if math.isfinite(iv) else float("nan"),
        implied_prob_up=implied_prob_above(ch, spot, T, r),
        hist_prob_exceed_straddle=hist_p, hist_n=hist_n,
        put_call_oi=float(oi.get("put", 0) / oi.get("call", 0)) if oi.get("call", 0) else float("nan"),
        put_call_volume=float(vol.get("put", 0) / vol.get("call", 0)) if vol.get("call", 0) else float("nan"),
        skew_25d=_skew(ch),
    )


def _evaluate_contracts(res: AnalysisResult, ch: pd.DataFrame, spot: float, e_date: dt.date, T: float,
                        today: dt.date, close: pd.Series, r: float, q: float,
                        focus: tuple[str, float] | None, per_side: int) -> None:
    st = res.stock
    sma50 = st.sma50 if math.isfinite(st.sma50) else None
    sma200 = st.sma200 if math.isfinite(st.sma200) else None
    earn = res.earnings or EarningsInfo("unknown")
    ctx = Context(
        spot=spot, r=r, q=q, T=T, expiry=e_date, today=today,
        sessions=max(cal.trading_days_between(today, e_date), 1), close=close,
        hv20=st.hv20, hv60=st.hv60, earnings_status=earn.status, earnings_dates=earn.upcoming,
        above_sma50=None if sma50 is None else spot > sma50,
        above_sma200=None if sma200 is None else spot > sma200,
        lean=res.weekly.lean if res.weekly else "NEUTRAL",
    )
    bad = 0
    for _, row in pick_candidates(ch, spot, per_side).iterrows():
        ev = evaluate(row, ctx)
        errs = sanity_errors(ev)
        if errs:
            bad += 1
            res.notes.append(f"ตัด {ev.kind.upper()} {ev.strike:g} ออก เพราะผลคำนวณไม่สอดคล้องกันเอง: {'; '.join(errs)}")
        else:
            res.candidates.append(ev)
    if res.candidates or bad:
        res.validation.add("การคำนวณ", "ความสอดคล้องของผลคำนวณ", PASS if bad == 0 else WARN,
                           f"ตรวจ {len(res.candidates) + bad} สัญญา: ความน่าจะเป็นอยู่ในช่วง 0–1, "
                           "โอกาสกำไร ≤ โอกาส ITM, จุดคุ้มทุน/ต้นทุน/เครื่องหมาย delta ถูกต้อง"
                           + (f" — ตัดออก {bad} สัญญา" if bad else ""))
    if focus:
        kind, strike = focus
        row = find_contract(ch, kind, strike)
        if row is None:
            strikes = ch[ch["kind"] == kind]["strike"]
            near = strikes.iloc[(strikes - strike).abs().argsort().iloc[:5]].sort_values()
            res.errors.append(f"ไม่พบ {kind.upper()} strike {strike:g} ใน {e_date} — strike ใกล้เคียง: "
                              + ", ".join(f"{k:g}" for k in near))
        elif not bool(row["usable"]):
            res.errors.append(f"{kind.upper()} {strike:g} ไม่มีราคาที่ผ่านการตรวจสอบ (ไม่มี bid/ask หรือราคาผิดปกติ) "
                              "— ไม่สามารถประเมินได้อย่างถูกต้อง")
        else:
            ev = evaluate(row, ctx)
            errs = sanity_errors(ev)
            if errs:
                res.errors.append(f"ผลคำนวณของ {kind.upper()} {strike:g} ไม่สอดคล้องกันเอง จึงไม่แสดงผล: {'; '.join(errs)}")
            else:
                res.focus = ev
