"""Risk evaluation of buying a single call or put, with transparent pass/warn/fail criteria."""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .pricing import prob_above, prob_itm, prob_touch
from .stats import EmpiricalProb, empirical_prob_horizon
from .validation import FAIL, PASS, WARN

POINTS = {PASS: 0, WARN: 1, FAIL: 2}


@dataclass
class Criterion:
    name: str
    status: str
    value: str
    rule: str
    weight: int


@dataclass
class Context:
    spot: float
    r: float
    q: float
    T: float
    expiry: dt.date
    today: dt.date
    sessions: int  # trading sessions until expiry
    close: pd.Series
    hv20: float
    hv60: float
    earnings_status: str
    earnings_dates: list[dt.date]
    above_sma50: bool | None
    above_sma200: bool | None
    lean: str


@dataclass
class ContractEval:
    kind: str
    strike: float
    expiry: dt.date
    contract: str
    dte: int
    sessions: int
    bid: float
    ask: float
    price: float
    price_source: str
    spread_pct: float
    volume: float
    oi: float
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    breakeven: float
    breakeven_move: float
    cost: float
    prob_itm: float
    prob_profit: float
    prob_profit_hist: EmpiricalProb
    prob_double: float
    prob_touch: float
    theta_pct: float
    iv_hv: float
    earnings_in_window: list[dt.date]
    criteria: list[Criterion] = field(default_factory=list)
    risk_score: float = float("nan")
    risk_level: str = ""


def _grade(value: float, good: float, ok: float, higher_is_better: bool) -> str:
    if value is None or not math.isfinite(value):
        return WARN
    if higher_is_better:
        return PASS if value >= good else WARN if value >= ok else FAIL
    return PASS if value <= good else WARN if value <= ok else FAIL


LEVELS = ("ต่ำ", "ปานกลาง", "สูง", "สูงมาก")


def risk_level(score: float, n_fail: int = 0) -> str:
    """Level from the weighted score, raised to at least "ปานกลาง" by any FAIL and "สูง" by 3+ FAILs."""
    i = 0 if score < 20 else 1 if score < 40 else 2 if score < 60 else 3
    if n_fail >= 3:
        i = max(i, 2)
    elif n_fail >= 1:
        i = max(i, 1)
    return LEVELS[i]


def earnings_between(dates: list[dt.date], start: dt.date, end: dt.date) -> list[dt.date]:
    """Earnings dates that can affect a contract alive from `start` to `end`.

    One day of slack after expiry: a provider date converted in a time zone ahead
    of New York (e.g. Thailand) can land one day later than the real report date.
    """
    return [d for d in dates if start <= d <= end + dt.timedelta(days=1)]


def evaluate(row: pd.Series, ctx: Context) -> ContractEval:
    kind = row["kind"]
    K = float(row["strike"])
    price = float(row["price"])
    iv = float(row["iv"])
    S, T, r, q = ctx.spot, ctx.T, ctx.r, ctx.q
    sign = 1 if kind == "call" else -1

    breakeven = K + price if kind == "call" else K - price
    be_move = breakeven / S - 1
    if breakeven > 0:
        p_be_above = prob_above(S, breakeven, T, r, iv, q)
        pop = p_be_above if kind == "call" else 1 - p_be_above
        hist = empirical_prob_horizon(ctx.close, max(ctx.sessions, 1), math.log(breakeven / S), above=kind == "call")
    else:
        pop = 0.0
        hist = EmpiricalProb(0.0, 0, float("nan"), float("nan"))
    double_level = K + 2 * price if kind == "call" else K - 2 * price
    if double_level > 0:
        p_dbl_above = prob_above(S, double_level, T, r, iv, q)
        p_double = p_dbl_above if kind == "call" else 1 - p_dbl_above
    else:
        p_double = 0.0

    hv = ctx.hv20 if math.isfinite(ctx.hv20) and ctx.hv20 > 0 else float("nan")
    ev = ContractEval(
        kind=kind, strike=K, expiry=ctx.expiry, contract=str(row.get("contract", "")),
        dte=(ctx.expiry - ctx.today).days, sessions=ctx.sessions,
        bid=float(row["bid"]), ask=float(row["ask"]), price=price, price_source=str(row["price_source"]),
        spread_pct=float(row["spread_pct"]) if pd.notna(row["spread_pct"]) else float("nan"),
        volume=float(row["volume"]), oi=float(row["oi"]), iv=iv,
        delta=float(row["delta"]), gamma=float(row["gamma"]), theta=float(row["theta"]), vega=float(row["vega"]),
        breakeven=breakeven, breakeven_move=be_move, cost=price * 100,
        prob_itm=prob_itm(S, K, T, r, iv, kind, q), prob_profit=pop, prob_profit_hist=hist,
        prob_double=p_double, prob_touch=prob_touch(S, K, T, r, iv, kind, q),
        theta_pct=abs(float(row["theta"])) / price if price > 0 else float("nan"),
        iv_hv=iv / hv if math.isfinite(hv) else float("nan"),
        earnings_in_window=earnings_between(ctx.earnings_dates, ctx.today, ctx.expiry),
    )
    ev.criteria = _criteria(ev, ctx, sign)
    total = sum(2 * c.weight for c in ev.criteria)
    ev.risk_score = 100.0 * sum(POINTS[c.status] * c.weight for c in ev.criteria) / total
    ev.risk_level = risk_level(ev.risk_score, sum(c.status == FAIL for c in ev.criteria))
    return ev


def _criteria(ev: ContractEval, ctx: Context, sign: int) -> list[Criterion]:
    c: list[Criterion] = []
    if ev.price_source == "mid":
        c.append(Criterion("สภาพคล่อง (Bid-Ask spread)", _grade(ev.spread_pct, 0.05, 0.10, False),
                           f"{ev.spread_pct:.1%} ของราคากลาง", "≤5% ดี, ≤10% พอใช้, >10% เสียเปรียบตอนซื้อ/ขาย", 2))
    else:
        c.append(Criterion("สภาพคล่อง (Bid-Ask spread)", WARN, "ไม่มี bid/ask ขณะนี้",
                           "ใช้ราคาซื้อขายล่าสุดแทน — ตรวจ spread จริงก่อนส่งคำสั่ง", 2))
    c.append(Criterion("Open Interest", _grade(ev.oi, 500, 100, True), f"{ev.oi:,.0f} สัญญา",
                       "≥500 ดี, ≥100 พอใช้, <100 สภาพคล่องต่ำ", 1))
    c.append(Criterion("โอกาสกำไร ณ วันหมดอายุ (ตาม IV)", _grade(ev.prob_profit, 0.40, 0.25, True),
                       f"{ev.prob_profit:.1%}", "≥40% ดี, ≥25% พอรับได้, <25% ต่ำ", 3))
    hp = ev.prob_profit_hist
    c.append(Criterion("โอกาสกำไร ณ วันหมดอายุ (สถิติจริงย้อนหลัง 5 ปี)", _grade(hp.prob, 0.40, 0.25, True),
                       f"{hp.prob:.1%} (จาก {hp.n:,} ช่วงเวลา)" if hp.n else "ไม่มีข้อมูล",
                       "≥40% ดี, ≥25% พอรับได้, <25% ต่ำ", 2))
    c.append(Criterion("ค่าเสื่อมเวลา (Theta) ต่อวัน", _grade(ev.theta_pct, 0.03, 0.07, False),
                       f"{ev.theta_pct:.1%} ของราคาออปชั่นต่อวัน (${abs(ev.theta) * 100:,.2f}/สัญญา)",
                       "≤3% ดี, ≤7% พอใช้, >7% มูลค่าหายเร็ว", 2))
    c.append(Criterion("ระยะเวลาถึงวันหมดอายุ", _grade(ev.dte, 21, 7, True), f"{ev.dte} วัน ({ev.sessions} วันทำการ)",
                       "≥21 วัน ดี, 7–20 วัน ระวัง, <7 วัน เสี่ยงสูง (theta/gamma)", 2))
    c.append(Criterion("ราคาออปชั่นแพง/ถูก (IV ÷ HV20)", _grade(ev.iv_hv, 1.10, 1.40, False),
                       f"{ev.iv_hv:.2f} เท่า" if math.isfinite(ev.iv_hv) else "คำนวณไม่ได้",
                       "≤1.10 ราคาสมเหตุสมผล, ≤1.40 ค่อนข้างแพง, >1.40 แพงมากสำหรับผู้ซื้อ", 2))
    if ctx.earnings_status == "none":
        c.append(Criterion("ประกาศงบก่อนหมดอายุ", PASS, "ไม่มี (ETF/ดัชนี)", "มีงบ = เสี่ยง IV crush และ gap", 2))
    elif ev.earnings_in_window:
        days = ", ".join(f"{d:%Y-%m-%d}" for d in ev.earnings_in_window)
        c.append(Criterion("ประกาศงบก่อนหมดอายุ", FAIL, f"มี ({days})",
                           "ราคาออปชั่นมักร่วงหลังงบ (IV crush) แม้หุ้นวิ่งถูกทาง", 2))
    elif ctx.earnings_status == "known":
        c.append(Criterion("ประกาศงบก่อนหมดอายุ", PASS,
                           f"ไม่มี (งบถัดไป {ctx.earnings_dates[0]:%Y-%m-%d})" if ctx.earnings_dates else "ไม่มี",
                           "มีงบ = เสี่ยง IV crush และ gap", 2))
    else:
        c.append(Criterion("ประกาศงบก่อนหมดอายุ", WARN, "ยืนยันวันประกาศงบไม่ได้",
                           "ตรวจวันประกาศงบเองก่อนซื้อ", 2))
    c.append(Criterion("Delta (โอกาสแบบลอตเตอรี่)", _grade(abs(ev.delta), 0.30, 0.15, True), f"{ev.delta:+.2f}",
                       "|Δ| ≥0.30 ดี, 0.15–0.30 ระวัง, <0.15 ต้องวิ่งแรงมากถึงจะกำไร", 1))
    c.append(_trend_criterion(ev, ctx, sign))
    c.append(Criterion("คุณภาพราคาที่ใช้คำนวณ", PASS if ev.price_source == "mid" else WARN,
                       "ราคากลาง bid/ask" if ev.price_source == "mid" else "ราคาซื้อขายล่าสุด (อาจไม่ใช่ราคาปัจจุบัน)",
                       "ควรมี bid/ask สด", 1))
    return c


def _trend_criterion(ev: ContractEval, ctx: Context, sign: int) -> Criterion:
    name = "ทิศทางสอดคล้องกับแนวโน้ม"
    rule = "ซื้อสวนแนวโน้ม = โอกาสต่ำกว่า; สัญญาณจากโมเดลที่ผ่านการทดสอบมีน้ำหนักมากที่สุด"
    against_model = (sign > 0 and ctx.lean == "PUT") or (sign < 0 and ctx.lean == "CALL")
    if against_model:
        return Criterion(name, FAIL, "สวนทางกับโมเดลรายสัปดาห์ที่ผ่านการทดสอบ", rule, 1)
    if ctx.above_sma50 is None or ctx.above_sma200 is None:
        return Criterion(name, WARN, "ข้อมูลไม่พอคำนวณ SMA", rule, 1)
    trend_up = ctx.above_sma50 and ctx.above_sma200
    trend_down = not ctx.above_sma50 and not ctx.above_sma200
    if (sign > 0 and trend_down) or (sign < 0 and trend_up):
        side = "ขาลง (ใต้ SMA50 และ SMA200)" if trend_down else "ขาขึ้น (เหนือ SMA50 และ SMA200)"
        return Criterion(name, WARN, f"สวนแนวโน้ม{side}", rule, 1)
    if (sign > 0 and trend_up) or (sign < 0 and trend_down):
        return Criterion(name, PASS, "ไปทางเดียวกับแนวโน้ม", rule, 1)
    return Criterion(name, PASS, "แนวโน้มไม่ชัดเจน (SMA50/SMA200 ให้สัญญาณต่างกัน)", rule, 1)


def pick_candidates(chain: pd.DataFrame, spot: float, per_side: int = 6) -> pd.DataFrame:
    """Usable contracts with 0.10 ≤ |delta| ≤ 0.85, nearest to the money first."""
    ok = chain[chain["usable"] & chain["delta"].abs().between(0.10, 0.85)].copy()
    ok["dist"] = (ok["strike"] - spot).abs()
    picks = [ok[ok["kind"] == k].nsmallest(per_side, "dist") for k in ("call", "put")]
    out = pd.concat(picks)
    return out.sort_values(["kind", "strike"]).drop(columns="dist")


def find_contract(chain: pd.DataFrame, kind: str, strike: float) -> pd.Series | None:
    side = chain[(chain["kind"] == kind)]
    hit = side[np.isclose(side["strike"], strike)]
    if hit.empty:
        return None
    return hit.iloc[0]


def sanity_errors(ev: ContractEval) -> list[str]:
    """Internal consistency of the computed numbers; any message means the evaluation is withheld."""
    errs = []
    probs = {"prob_itm": ev.prob_itm, "prob_profit": ev.prob_profit, "prob_double": ev.prob_double,
             "prob_touch": ev.prob_touch}
    for name, p in probs.items():
        if not (math.isfinite(p) and -1e-9 <= p <= 1 + 1e-9):
            errs.append(f"{name} = {p} อยู่นอกช่วง 0–1")
    if ev.prob_profit > ev.prob_itm + 1e-9:
        errs.append("โอกาสกำไรมากกว่าโอกาส ITM (เป็นไปไม่ได้สำหรับผู้ซื้อ)")
    if ev.prob_double > ev.prob_profit + 1e-9:
        errs.append("โอกาสกำไร 100% มากกว่าโอกาสกำไร (เป็นไปไม่ได้)")
    if ev.prob_touch + 1e-9 < ev.prob_itm:
        errs.append("โอกาสแตะ strike น้อยกว่าโอกาส ITM (เป็นไปไม่ได้)")
    if not abs(ev.delta) <= 1:
        errs.append(f"delta = {ev.delta} เกิน ±1")
    if (ev.kind == "call" and not ev.delta > 0) or (ev.kind == "put" and not ev.delta < 0):
        errs.append("เครื่องหมาย delta ไม่ถูกต้อง")
    if not abs(ev.cost - ev.price * 100) < 1e-6:
        errs.append("ต้นทุนต่อสัญญาไม่เท่ากับราคา × 100")
    expected_be = ev.strike + ev.price if ev.kind == "call" else ev.strike - ev.price
    if not abs(ev.breakeven - expected_be) < 1e-9:
        errs.append("จุดคุ้มทุนคำนวณผิด")
    if hasattr(ev, "theta") and ev.theta > 1e-9 and ev.kind == "call":
        errs.append("theta ของ long call เป็นบวก (ผิดปกติ)")
    return errs
