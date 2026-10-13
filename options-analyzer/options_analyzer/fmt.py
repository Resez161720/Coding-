"""Number formatting shared by the text and HTML reports."""
from __future__ import annotations

import math

from .earnings import TIMING_TH
from .validation import FAIL, PASS, WARN

STATUS_TH = {PASS: "ผ่าน", WARN: "เตือน", FAIL: "ไม่ผ่าน"}

DISCLAIMER = (
    "ข้อมูลนี้เป็นการวิเคราะห์ทางสถิติเพื่อประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน "
    "ความน่าจะเป็นทุกตัวคำนวณจากแบบจำลองและข้อมูลในอดีต ซึ่งไม่รับประกันผลในอนาคต "
    "ผู้ซื้อออปชั่นอาจเสียเงินค่าพรีเมียมทั้งหมด ข้อมูลจาก Yahoo Finance อาจล่าช้าประมาณ 15 นาที "
    "ตรวจสอบราคา bid/ask กับโบรกเกอร์ของคุณทุกครั้งก่อนส่งคำสั่ง"
)


def ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def pct(x, digits: int = 1, sign: bool = False) -> str:
    if not ok(x):
        return "n/a"
    return f"{x:+.{digits}%}" if sign else f"{x:.{digits}%}"


def num(x, digits: int = 2) -> str:
    return f"{x:,.{digits}f}" if ok(x) else "n/a"


def money(x, digits: int = 2) -> str:
    if not ok(x):
        return "n/a"
    return f"-${-x:,.{digits}f}" if x < 0 else f"${x:,.{digits}f}"


def vol_points(x) -> str:
    return f"{x * 100:+.1f} จุด" if ok(x) else "n/a"


def earnings_note(confirmed) -> str:
    if confirmed is True:
        return "Yahoo ระบุว่ายืนยันแล้ว"
    if confirmed is False:
        return "เป็นวันประมาณการ อาจเปลี่ยน"
    return "ไม่ทราบว่ายืนยันแล้วหรือยัง"


def sessions_text(n) -> str:
    """5 -> '5', 4.96 -> '5.0', 4.5 -> '4.5'."""
    if not ok(n):
        return "n/a"
    return f"{n:.0f}" if abs(n - round(n)) < 1e-9 else f"{n:.1f}"


def quote_text(x) -> str:
    """Yahoo sends 0 for 'no quote'."""
    return num(x) if ok(x) and x > 0 else "n/a"


def next_earnings_text(res) -> str:
    earn = res.earnings
    if earn is None:
        return "ไม่ทราบ"
    if earn.status == "none":
        return "ไม่มี (ETF/ดัชนี)"
    e = res.next_earnings
    if e is None:
        return "ยืนยันไม่ได้ — โปรดตรวจสอบเองก่อนซื้อ"
    return f"{e.date} ({TIMING_TH[e.timing]}; {earnings_note(earn.confirmed)})"


def earnings_moves_text(moves) -> tuple[str, str, str]:
    """(average, per-report list, footnote) for [(date, move, '1d'|'2d'), ...]."""
    if not moves:
        return "", "", ""
    avg = sum(abs(m) for _, m, _ in moves) / len(moves)
    items = ", ".join(f"{d:%Y-%m-%d}: {m:+.1%}{'*' if k == '2d' else ''}" for d, m, k in moves)
    note = "ราคาปิดก่อนงบ → ราคาปิดแรกหลังงบ"
    if any(k == "2d" for _, _, k in moves):
        note += "; * ไม่ทราบเวลาประกาศ จึงวัดช่วง 2 วันทำการ"
    return f"±{avg:.1%}", items, note


def iv_basis_text(basis: str) -> str:
    return {"mid": "คำนวณเองจากราคากลาง bid/ask", "last": "คำนวณเองจากราคาซื้อขายล่าสุดช่วงท้ายตลาด",
            "mixed": "คำนวณเองจากราคากลางและราคาซื้อขายล่าสุด"}.get(basis, "คำนวณเองจากราคาตลาด")
