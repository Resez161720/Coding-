"""Data verification. Every analysis runs these checks before any number is reported.

A FAIL means the data cannot be trusted for that part of the analysis and the
tool withholds the affected conclusions. A WARN is shown to the user next to the
result it affects.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import calendar_us as cal

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    area: str
    name: str
    status: str
    detail: str


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, area: str, name: str, status: str, detail: str) -> None:
        self.checks.append(Check(area, name, status, detail))

    def extend(self, other: "ValidationReport") -> None:
        self.checks.extend(other.checks)

    def failed(self, area: str | None = None) -> bool:
        return any(c.status == FAIL and (area is None or c.area == area) for c in self.checks)

    def count(self, status: str) -> int:
        return sum(c.status == status for c in self.checks)

    def for_area(self, area: str) -> list[Check]:
        return [c for c in self.checks if c.area == area]


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def validate_history(df: pd.DataFrame, now_ny: dt.datetime, area: str = "ราคาหุ้นย้อนหลัง",
                     min_rows: int = 260) -> tuple[ValidationReport, pd.DataFrame]:
    """Validate and clean daily OHLCV history. Returns the report and the cleaned frame."""
    rep = ValidationReport()
    if df is None or df.empty:
        rep.add(area, "มีข้อมูล", FAIL, "ไม่ได้รับข้อมูลราคาย้อนหลัง — ตรวจชื่อหุ้นและการเชื่อมต่ออินเทอร์เน็ต")
        return rep, pd.DataFrame(columns=list(REQUIRED_COLUMNS))
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        rep.add(area, "คอลัมน์ครบ", FAIL, f"ขาดคอลัมน์ {missing}")
        return rep, df
    adj = df["AdjClose"] if "AdjClose" in df.columns else None
    df = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    df["AdjClose"] = df["Close"] if adj is None else adj

    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
        rep.add(area, "ลำดับวันที่", WARN, "ข้อมูลไม่เรียงตามวันที่ — จัดเรียงใหม่แล้ว")
    dup = int(df.index.duplicated(keep="last").sum())
    if dup:
        df = df[~df.index.duplicated(keep="last")]
        rep.add(area, "วันที่ซ้ำ", WARN, f"พบวันที่ซ้ำ {dup} แถว — เก็บแถวล่าสุดไว้")
    else:
        rep.add(area, "วันที่ซ้ำ", PASS, "ไม่มีวันที่ซ้ำ")

    nan_close = df["Close"].isna()
    if nan_close.iloc[-5:].any():
        rep.add(area, "ราคาปิดหาย", FAIL, "ราคาปิดช่วง 5 วันล่าสุดหายไป — ข้อมูลล่าสุดใช้ไม่ได้")
    elif nan_close.any():
        rep.add(area, "ราคาปิดหาย", WARN, f"ราคาปิดหาย {int(nan_close.sum())} วันในอดีต — ตัดทิ้งแล้ว")
    else:
        rep.add(area, "ราคาปิดหาย", PASS, "ไม่มีราคาปิดที่หายไป")
    df = df[~nan_close]

    price_cols = ["Open", "High", "Low", "Close"]
    nonpos = (df[price_cols] <= 0).any(axis=1)
    if nonpos.any():
        rep.add(area, "ราคาเป็นบวก", FAIL if nonpos.iloc[-20:].any() else WARN,
                f"พบราคา <= 0 จำนวน {int(nonpos.sum())} วัน — ตัดทิ้งแล้ว")
        df = df[~nonpos]
    else:
        rep.add(area, "ราคาเป็นบวก", PASS, "ราคาทุกวันมากกว่า 0")

    complete = df[price_cols].notna().all(axis=1)
    tol = 1e-4
    hi_bad = complete & (df["High"] < df[["Open", "Close"]].max(axis=1) * (1 - tol))
    lo_bad = complete & (df["Low"] > df[["Open", "Close"]].min(axis=1) * (1 + tol))
    n_bad = int((hi_bad | lo_bad).sum())
    share = n_bad / max(len(df), 1)
    if n_bad == 0:
        rep.add(area, "OHLC สอดคล้อง", PASS, "High/Low ครอบคลุม Open/Close ทุกวัน")
    elif share <= 0.01:
        rep.add(area, "OHLC สอดคล้อง", WARN, f"High/Low ไม่สอดคล้อง {n_bad} วัน ({share:.2%}) — ผลกระทบน้อย")
    else:
        rep.add(area, "OHLC สอดคล้อง", FAIL, f"High/Low ไม่สอดคล้อง {n_bad} วัน ({share:.2%})")

    if len(df) < 60:
        rep.add(area, "จำนวนข้อมูล", FAIL, f"มีข้อมูลเพียง {len(df)} วันทำการ (ต้องการอย่างน้อย 60)")
    elif len(df) < min_rows:
        rep.add(area, "จำนวนข้อมูล", WARN, f"มีข้อมูล {len(df)} วันทำการ (น้อยกว่า {min_rows}) — สถิติบางตัวอาจคลาดเคลื่อน")
    else:
        rep.add(area, "จำนวนข้อมูล", PASS, f"{len(df)} วันทำการ ({df.index[0]:%Y-%m-%d} ถึง {df.index[-1]:%Y-%m-%d})")

    if len(df) > 1:
        rets = df["Close"].pct_change().dropna()
        big = rets[(rets <= -0.40) | (rets >= 0.60)]
        if big.empty:
            rep.add(area, "การเคลื่อนไหวผิดปกติ", PASS, "ไม่พบการเปลี่ยนแปลงรายวันที่รุนแรงผิดปกติ (−40%/+60%)")
        else:
            dates = ", ".join(f"{d:%Y-%m-%d} ({v:+.0%})" for d, v in big.iloc[-5:].items())
            rep.add(area, "การเคลื่อนไหวผิดปกติ", WARN,
                    f"พบราคาเปลี่ยนแรงใน 1 วัน: {dates} — อาจเป็นข่าวจริงหรือการแตกพาร์ที่ปรับไม่ถูก "
                    "สถิติความผันผวนอาจคลาดเคลื่อน โปรดตรวจสอบ")

    if adj is not None and not df.empty:
        # Dividend adjustment factor must be in (0, 1] and reach 1 at the latest bar.
        ratio = df["AdjClose"] / df["Close"]
        bad = ~ratio.between(0.01, 1.0005) | ratio.isna()
        if bad.any() or abs(float(ratio.iloc[-1]) - 1) > 0.0005:
            df["AdjClose"] = df["Close"]
            rep.add(area, "ราคาปรับปันผล", WARN, "ราคาปรับปันผลผิดปกติ — ใช้ราคาปิดจริงแทนในการคำนวณผลตอบแทน")
        else:
            rep.add(area, "ราคาปรับปันผล", PASS, "ราคาปรับปันผลสอดคล้องกับราคาปิดจริง")

    if not df.empty:
        rep.add(*_staleness_check(area, df.index[-1].date(), now_ny))
        zero_vol = int((df["Volume"].iloc[-20:] <= 0).sum())
        if zero_vol:
            rep.add(area, "ปริมาณซื้อขาย", WARN, f"มีวันที่ volume = 0 จำนวน {zero_vol} วันใน 20 วันล่าสุด")
        else:
            rep.add(area, "ปริมาณซื้อขาย", PASS, "มีการซื้อขายทุกวันใน 20 วันล่าสุด")
    return rep, df


def _staleness_check(area: str, last_bar: dt.date, now_ny: dt.datetime) -> tuple[str, str, str, str]:
    expected = cal.last_session_with_data(now_ny)
    if last_bar >= expected:
        return area, "ความสดใหม่", PASS, f"ข้อมูลล่าสุดวันที่ {last_bar:%Y-%m-%d} (ตรงกับวันทำการล่าสุด)"
    if last_bar >= cal.previous_trading_day(expected):
        return (area, "ความสดใหม่", WARN,
                f"ข้อมูลล่าสุดวันที่ {last_bar:%Y-%m-%d} แต่วันทำการล่าสุดคือ {expected:%Y-%m-%d} — "
                "อาจยังไม่อัปเดต หรือวันนั้นตลาดปิดพิเศษ")
    return (area, "ความสดใหม่", FAIL,
            f"ข้อมูลล่าสุดวันที่ {last_bar:%Y-%m-%d} เก่ากว่าวันทำการล่าสุด ({expected:%Y-%m-%d}) เกิน 1 วัน")


def validate_spot(spot: float | None, last_close: float, last_close_date: dt.date,
                  area: str = "ราคาปัจจุบัน") -> ValidationReport:
    """Cross-check the live quote against the last close from the separate history endpoint."""
    rep = ValidationReport()
    if spot is None or not math.isfinite(spot) or spot <= 0:
        rep.add(area, "ราคาปัจจุบัน", FAIL, f"ราคาปัจจุบันไม่ถูกต้อง: {spot!r}")
        return rep
    diff = spot / last_close - 1.0
    detail = (f"ราคาปัจจุบัน {spot:,.2f} เทียบราคาปิดในข้อมูลย้อนหลัง {last_close:,.2f} "
              f"({last_close_date:%Y-%m-%d}) ต่างกัน {diff:+.2%}")
    if abs(diff) <= 0.10:
        rep.add(area, "ตรวจไขว้กับราคาย้อนหลัง", PASS, detail)
    elif abs(diff) <= 0.25:
        rep.add(area, "ตรวจไขว้กับราคาย้อนหลัง", WARN, detail + " — ต่างกันมาก โปรดยืนยันว่ามีข่าวจริง")
    else:
        rep.add(area, "ตรวจไขว้กับราคาย้อนหลัง", FAIL, detail + " — ต่างกันผิดปกติ ข้อมูลอาจผิด")
    return rep


def validate_chain(chain: pd.DataFrame, spot: float, T: float, r: float, q: float,
                   last_session: dt.date, area: str = "ออปชั่น") -> ValidationReport:
    """Validate a normalised option chain (see chain.build_chain)."""
    rep = ValidationReport()
    if chain is None or chain.empty:
        rep.add(area, "มีข้อมูล", FAIL, "ไม่ได้รับข้อมูล option chain")
        return rep
    if T <= 0:
        rep.add(area, "วันหมดอายุ", FAIL, "สัญญาหมดอายุแล้ว")
        return rep
    calls = chain[chain["kind"] == "call"]
    puts = chain[chain["kind"] == "put"]
    if calls.empty or puts.empty:
        rep.add(area, "มีทั้ง Call และ Put", FAIL, f"Call {len(calls)} สัญญา, Put {len(puts)} สัญญา")
        return rep
    rep.add(area, "มีทั้ง Call และ Put", PASS, f"Call {len(calls)} สัญญา, Put {len(puts)} สัญญา")

    crossed = int(chain["crossed"].sum())
    if crossed:
        rep.add(area, "Bid ≤ Ask", WARN, f"พบ bid > ask {crossed} สัญญา — ตัดออกจากการวิเคราะห์")
    else:
        rep.add(area, "Bid ≤ Ask", PASS, "ทุกสัญญามี bid ≤ ask")

    n_quote = int((chain["price_source"] == "mid").sum())
    n_last = int((chain["price_source"] == "last").sum())
    if n_quote + n_last == 0:
        rep.add(area, "ราคาเสนอซื้อ/ขาย", FAIL, "ไม่มีราคาที่ใช้ได้เลย")
    elif n_quote < n_last:
        rep.add(area, "ราคาเสนอซื้อ/ขาย", WARN,
                (f"มี bid/ask เพียง {n_quote} สัญญา" if n_quote else "ไม่มี bid/ask")
                + " (ตลาดปิดหรือแหล่งข้อมูลไม่ส่งมา) — ใช้ราคาซื้อขายล่าสุดช่วงท้ายตลาด "
                f"{n_last} สัญญาแทน ไม่ทราบ spread จริง ควรรันใหม่ในเวลาตลาดเปิดก่อนตัดสินใจ")
    else:
        rep.add(area, "ราคาเสนอซื้อ/ขาย", PASS, f"มี bid/ask ที่ใช้ได้ {n_quote} สัญญา")

    if float((chain["oi"] > 0).mean()) < 0.05:
        rep.add(area, "Open Interest", WARN,
                "แหล่งข้อมูลส่ง Open Interest เป็น 0 เกือบทุกสัญญา (Yahoo มักเป็นแบบนี้นอกเวลาตลาด) "
                "— ไม่ใช้ OI ในการประเมิน")
    else:
        rep.add(area, "Open Interest", PASS, f"มี Open Interest {int((chain['oi'] > 0).sum())} สัญญา")

    below = int(chain["below_intrinsic"].sum())
    # Escalate only on live two-sided quotes near the money; stale last trades and wide deep-ITM
    # markets violate intrinsic value routinely and are simply excluded.
    near_mid = ((chain["strike"] / spot - 1).abs() <= 0.15) & (chain["price_source"] == "mid")
    bad_near = int((chain["below_intrinsic"] & near_mid).sum())
    if bad_near >= 3 and bad_near > 0.10 * int(near_mid.sum()):
        rep.add(area, "ราคาไม่ต่ำกว่ามูลค่าที่แท้จริง", FAIL,
                f"{bad_near} จาก {int(near_mid.sum())} สัญญาใกล้ ATM มีราคาต่ำกว่า intrinsic value "
                "— ราคาออปชั่นไม่สอดคล้องกับราคาหุ้น")
    elif below:
        rep.add(area, "ราคาไม่ต่ำกว่ามูลค่าที่แท้จริง", WARN,
                f"{below} สัญญามีราคาต่ำกว่า intrinsic value (ราคาค้าง/ผิด) — ตัดออกแล้ว")
    else:
        rep.add(area, "ราคาไม่ต่ำกว่ามูลค่าที่แท้จริง", PASS, "ทุกสัญญามีราคา ≥ intrinsic value")

    rep.add(*_monotonic_check(area, chain, spot))
    rep.add(*_parity_check(area, chain, spot, T, r, q))

    usable = chain[chain["usable"]]
    if usable.empty:
        rep.add(area, "สัญญาที่ใช้ได้", FAIL, "ไม่มีสัญญาที่ผ่านการตรวจสอบเลย")
    else:
        dropped = []
        n_stale_q = int(chain.get("stale_quote", pd.Series(dtype=bool)).sum())
        n_stale_l = int(chain.get("stale_last", pd.Series(dtype=bool)).sum())
        if n_stale_q:
            dropped.append(f"bid/ask ค้างจากวันก่อน {n_stale_q} สัญญา")
        if n_stale_l:
            dropped.append(f"ราคาซื้อขายล่าสุดที่หุ้นเปลี่ยนราคาไปมากหลังจากนั้น {n_stale_l} สัญญา")
        rep.add(area, "สัญญาที่ใช้ได้", PASS, f"ผ่านการตรวจสอบ {len(usable)} จาก {len(chain)} สัญญา"
                + (f" (ตัดออก: {', '.join(dropped)})" if dropped else ""))

    rep.add(*_iv_roundtrip_check(area, usable, spot, T, r, q))

    traded = chain["last_trade"].dropna()
    if not traded.empty:
        latest = max(traded).date()
        if latest < cal.previous_trading_day(last_session):
            rep.add(area, "ความสดใหม่ของราคาออปชั่น", FAIL,
                    f"การซื้อขายล่าสุดใน chain คือ {latest:%Y-%m-%d} — ข้อมูลเก่าเกินไป")
        else:
            rep.add(area, "ความสดใหม่ของราคาออปชั่น", PASS, f"มีการซื้อขายล่าสุดวันที่ {latest:%Y-%m-%d}")

    near = usable[(usable["strike"] / spot - 1).abs() <= 0.05].dropna(subset=["iv", "iv_source"])
    if not near.empty:
        diff = (near["iv"] - near["iv_source"]).abs().median() * 100
        status = PASS if diff <= 5 else WARN
        rep.add(area, "IV เทียบกับแหล่งข้อมูล", status,
                f"IV ที่คำนวณเองต่างจาก IV ของ Yahoo เฉลี่ย {diff:.1f} จุด (สัญญาใกล้ ATM) — "
                "เครื่องมือนี้ใช้ IV ที่คำนวณเองจากราคาจริงเสมอ")
    return rep


def _monotonic_check(area: str, chain: pd.DataFrame, spot: float) -> tuple[str, str, str, str]:
    """Calls must not get dearer, puts not cheaper, as the strike rises.

    Runs on the prices the analysis actually uses, within ±20% of the spot. A violation between two
    live bid/ask quotes can fail the chain; one involving a last trade (taken at a different moment)
    can only warn.
    """
    bad_mid = bad_last = total = 0
    for kind, sign in (("call", -1), ("put", 1)):
        side = chain[(chain["kind"] == kind) & chain["usable"]
                     & ((chain["strike"] / spot - 1).abs() <= 0.20)].sort_values("strike")
        p = side["price"].to_numpy()
        src = side["price_source"].to_numpy()
        if len(p) < 2:
            continue
        step = np.diff(p) * sign  # calls should fall and puts rise with strike
        tol = 0.02 + 0.02 * np.maximum(p[:-1], p[1:])
        viol = step < -tol
        both_mid = (src[:-1] == "mid") & (src[1:] == "mid")
        bad_mid += int((viol & both_mid).sum())
        bad_last += int((viol & ~both_mid).sum())
        total += len(step)
    name = "ราคาสอดคล้องตาม strike"
    if total == 0:
        return area, name, WARN, "มีข้อมูลไม่พอสำหรับตรวจ"
    if bad_mid + bad_last == 0:
        return area, name, PASS, f"Call ถูกลงและ Put แพงขึ้นตาม strike ตามทฤษฎี (ตรวจ {total} คู่ในช่วง ±20%)"
    detail = f"ราคาไม่เรียงตามทฤษฎี {bad_mid + bad_last} จุดจาก {total} คู่ในช่วง ±20%"
    if bad_mid / total > 0.05:
        return area, name, FAIL, detail
    return area, name, WARN, detail + " — ตัดสินจากราคาต่างเวลากันหรือจำนวนน้อย จึงเป็นเพียงคำเตือน"


def _parity_check(area: str, chain: pd.DataFrame, spot: float, T: float, r: float,
                  q: float) -> tuple[str, str, str, str]:
    """Put-call parity: spot implied by C - P near the money must agree with the quote."""
    # All two-sided quotes, not just "usable" ones: a chain struck off the wrong spot fails the other
    # checks first, and filtering on them would hide exactly the evidence this check needs.
    both = _parity_pairs(chain[chain["price_source"] == "mid"], spot)
    source = "bid/ask"
    if both.empty:
        # Market closed: fall back to last trades (already restricted to the end of the session).
        both = _parity_pairs(chain[chain["price_source"] == "last"], spot)
        source = "ราคาซื้อขายล่าสุดช่วงท้ายตลาด"
    if both.empty:
        return area, "Put-Call Parity", WARN, "ไม่มีคู่ Call/Put ที่มีราคาในช่วง ±20% ของราคาหุ้นสำหรับตรวจ"
    implied = (both["c"] - both["p"] + both.index.to_numpy() * math.exp(-r * T)) * math.exp(q * T)
    s_impl = float(implied.median())
    diff = s_impl / spot - 1
    detail = (f"ราคาหุ้นที่คำนวณจาก Call−Put ({source}, {len(both)} strike) = {s_impl:,.2f} "
              f"เทียบราคาจริง {spot:,.2f} ({diff:+.2%})")
    if abs(diff) <= 0.015:
        return area, "Put-Call Parity", PASS, detail
    if abs(diff) <= 0.05 or source != "bid/ask":
        # Last trades happen at different moments, so they can only warn, never prove a bad chain.
        return area, "Put-Call Parity", WARN, detail + " — ราคาออปชั่นกับหุ้นอาจไม่ได้มาจากเวลาเดียวกัน"
    return area, "Put-Call Parity", FAIL, detail + " — ราคาออปชั่นไม่สอดคล้องกับราคาหุ้น"


def _parity_pairs(priced: pd.DataFrame, spot: float) -> pd.DataFrame:
    """Call/put prices at the (up to) 5 strikes nearest the spot that have both legs, within ±20%."""
    c = priced[priced["kind"] == "call"].set_index("strike")["price"]
    p = priced[priced["kind"] == "put"].set_index("strike")["price"]
    both = pd.concat([c, p], axis=1, join="inner", keys=["c", "p"])
    dist = (both.index.to_series() / spot - 1).abs()
    near = dist[dist <= 0.20].sort_values()
    return both.loc[near.index[:5]]


def _iv_roundtrip_check(area: str, usable: pd.DataFrame, spot: float, T: float, r: float,
                        q: float) -> tuple[str, str, str, str]:
    """Re-price every contract from its solved IV; the result must reproduce the market price."""
    from .pricing import bs_price

    if usable.empty:
        return area, "ตรวจ IV ย้อนกลับ", WARN, "ไม่มีสัญญาให้ตรวจ"
    errs = [abs(bs_price(spot, float(k), T, r, float(v), kind, q) - float(p))
            for k, v, kind, p in zip(usable["strike"], usable["iv"], usable["kind"], usable["price"])]
    worst = max(errs)
    if worst <= 0.001:
        return area, "ตรวจ IV ย้อนกลับ", PASS, f"คำนวณราคาจาก IV กลับได้ตรงราคาตลาดทุกสัญญา (คลาดเคลื่อนสูงสุด ${worst:.5f})"
    return area, "ตรวจ IV ย้อนกลับ", FAIL, f"คำนวณราคาจาก IV กลับไม่ตรง (คลาดเคลื่อนสูงสุด ${worst:.4f})"
