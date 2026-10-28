"""หน้าการ์ด barcode สำหรับพิมพ์: คำสั่ง, ตัวเลข, เครื่องจักร, รถเข็น, พนักงาน"""

from html import escape

from .code128 import svg

COMMANDS = [
    ("CMD-FULL", "เต็มตะกร้า"),
    ("CMD-END", "จบ (ยืนยันตัวเลข)"),
    ("CMD-NG", "NG (ตามด้วยตัวเลข แล้ว จบ)"),
    ("CMD-UNDO", "ยกเลิกรายการล่าสุด"),
]

STYLE = """
body { font-family: Tahoma, 'Leelawadee UI', sans-serif; margin: 16px; color: #111; background: #fff; }
h1 { font-size: 20px; }
h2 { font-size: 16px; margin: 24px 0 8px; border-bottom: 2px solid #333; }
.hint { color: #555; }
.grid { display: flex; flex-wrap: wrap; gap: 8px; }
.card { border: 1px dashed #999; padding: 8px 10px; width: 300px; text-align: center; page-break-inside: avoid; }
.card .title { font-size: 18px; font-weight: bold; margin-bottom: 4px; }
.card .code { font-family: monospace; font-size: 12px; color: #444; }
.card svg { max-width: 100%; height: 60px; }
@media print { .hint { display: none; } h2 { page-break-after: avoid; } }
"""


def _card(code, title):
    return (f'<div class="card"><div class="title">{escape(title)}</div>{svg(code)}'
            f'<div class="code">{escape(code)}</div></div>')


def _section(title, cards):
    if not cards:
        return ""
    return f'<h2>{escape(title)}</h2><div class="grid">{"".join(cards)}</div>'


def build_cards_html(master) -> str:
    commands = [_card(code, title) for code, title in COMMANDS]
    digits = [_card(f"NUM-{digit}", f"เลข {digit}") for digit in range(10)]
    machines = carts = operators = []
    if master is not None:
        machines = [_card(f"MC-{m.code}", f"เครื่อง {m.code} {m.name}".strip())
                    for m in sorted(master.machines.values(), key=lambda m: (m.route, m.code))]
        carts = [_card(f"CT-{cart}", f"รถเข็น {cart}") for cart in sorted(master.carts)]
        operators = [_card(f"EMP-{emp}", f"{emp} {name}".strip()) for emp, name in sorted(master.operators.items())]
    body = "".join([
        "<h1>การ์ด barcode สำหรับเครื่องยิง</h1>",
        '<p class="hint">กด Ctrl+P เพื่อพิมพ์ แนะนำให้เคลือบพลาสติก ทดลองยิงทุกใบก่อนใช้งานจริง</p>',
        _section("คำสั่ง", commands),
        _section("ตัวเลข (ยิงทีละหลัก แล้วยิง 'จบ')", digits),
        _section("เครื่องจักร (ติดที่เครื่อง)", machines),
        _section("รถเข็น (ติดที่รถเข็น)", carts),
        _section("พนักงาน (เสียบไว้ที่เครื่องตอนต้นกะ)", operators),
    ])
    return (f'<!doctype html><html lang="th"><head><meta charset="utf-8"><title>การ์ด barcode</title>'
            f"<style>{STYLE}</style></head><body>{body}</body></html>")
