"""ตรวจข้อมูล tag ก่อนส่งไปกรอกจอเขียว (ระบบเดิมไม่ตรวจให้)"""

import re
from dataclasses import dataclass

DOCUMENTS = (("work_order", "ใบสั่งงาน"), ("mat_do", "D/O"), ("mat_coil", "Coil"), ("die", "ดาย"))


@dataclass
class Issue:
    field: str
    message: str


def resolve_color(req, master, wo_color):
    """สีกระดาษ: ใช้สีที่จำไว้ของใบสั่งงานก่อน (สีขึ้นกับประเภทงาน)
    ถ้ายังไม่รู้ ใช้สีประจำเครื่อง ยกเว้นเครื่องที่ทำได้หลายประเภทงานต้องให้คนเลือก"""
    machine = master.machines.get(req.machine)
    if machine is None:
        return None
    if wo_color:
        return wo_color
    if machine.multi_type:
        return None
    return machine.color


def validate(req, master, patterns, colors, wo_color) -> list:
    issues = []

    def add(field, message):
        issues.append(Issue(field, message))

    machine = master.machines.get(req.machine)
    if not req.machine:
        add("machine", "ไม่มีป้ายเครื่อง")
    elif machine is None:
        add("machine", f"ไม่พบเครื่อง {req.machine} ใน machines.csv")
    elif not machine.speed.isdigit():
        add("machine", f"M/C Speed ของเครื่อง {req.machine} ใน machines.csv ต้องเป็นตัวเลข")

    for name, label in DOCUMENTS:
        value = getattr(req, name)
        if not value:
            add(name, f"ไม่มี{label}")
        elif not re.match(getattr(patterns, name), value):
            add(name, f"{label} รูปแบบไม่ถูกต้อง: {value}")

    if not req.emp:
        add("emp", "ไม่มีการ์ดพนักงาน")
    elif master.operators and req.emp not in master.operators:
        add("emp", f"ไม่พบรหัสพนักงาน {req.emp} ใน operators.csv")

    if not req.cart:
        add("cart", "ไม่มีป้ายรถเข็น")
    elif master.carts and req.cart not in master.carts:
        add("cart", f"ไม่พบรถเข็น {req.cart} ใน carts.csv")

    if not req.full and (req.qty is None or req.qty <= 0):
        add("qty", "จำนวนต้องมากกว่า 0")
    if req.ng < 0:
        add("ng", "NG ติดลบไม่ได้")

    if machine is not None:
        color = resolve_color(req, master, wo_color)
        if color is None:
            add("color", "เครื่องนี้ทำได้หลายประเภทงาน ต้องเลือกสีกระดาษของใบสั่งงานนี้")
        elif color not in colors:
            add("color", f"สี '{color}' ไม่อยู่ในรายการสีใน config.toml")
    return issues
