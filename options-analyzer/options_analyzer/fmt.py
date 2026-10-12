"""Number formatting shared by the text and HTML reports."""
from __future__ import annotations

import math

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
