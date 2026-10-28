from dataclasses import dataclass


@dataclass
class TagRequest:
    """ข้อมูลของ tag 1 ใบ ตามที่ยิงมาจากหน้าเครื่องจักร"""

    machine: str = ""
    work_order: str = ""
    mat_do: str = ""
    mat_coil: str = ""
    die: str = ""
    emp: str = ""
    cart: str = ""
    full: bool = False
    qty: int | None = None
    ng: int = 0
