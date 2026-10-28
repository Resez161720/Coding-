"""แปลงข้อมูลจากเครื่องยิง barcode (บรรทัดละ 1 barcode) เป็นรายการ tag

กติกาการยิงที่หน้าเครื่องจักร:
  MC-<เครื่อง>   เริ่มเครื่องใหม่ และล้างเอกสารของเครื่องก่อนหน้าทั้งหมด
  ใบสั่งงาน / D/O / Coil / ดาย / EMP-<รหัส> / CT-<รถเข็น>   จำไว้ใช้กับตะกร้าถัดไป
  CMD-FULL       ตะกร้าเต็ม 1 ใบ (จำนวนมาตรฐาน = LOT SIZE บนจอเขียว)
  NUM-<0-9> ... CMD-END          ตะกร้าไม่เต็ม ตามจำนวนที่ยิง
  CMD-NG NUM-<0-9> ... CMD-END   จำนวน NG ของตะกร้าล่าสุด
  CMD-UNDO       ยกเลิกตัวเลขที่กำลังยิง หรือถ้าไม่ได้ยิงตัวเลขอยู่ ยกเลิกตะกร้าล่าสุด
"""

import re
from dataclasses import dataclass, field, replace

from .models import TagRequest
from .thai_keyboard import fix_thai_layout

MESSAGES = {
    "unknown": "ไม่รู้จัก barcode นี้",
    "unfinished_number": "ยิงตัวเลขแล้วไม่ได้ยิง 'จบ' ตัวเลขนี้ถูกทิ้ง",
    "ng_without_basket": "ยิง NG ก่อนมีตะกร้าของเครื่องนี้",
    "empty_number": "ยิง 'จบ' โดยไม่มีตัวเลข",
    "nothing_to_undo": "ไม่มีรายการให้ยกเลิก",
}


@dataclass
class ScanProblem:
    line: int
    raw: str
    kind: str
    message: str


@dataclass
class ParseResult:
    requests: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def normalize(raw: str) -> str:
    text = fix_thai_layout(raw.strip()).strip().upper()
    return text.strip("*").strip()


class _Parser:
    def __init__(self, patterns):
        self.document_patterns = [
            (name, re.compile(getattr(patterns, name)))
            for name in ("work_order", "mat_do", "mat_coil", "die")
        ]
        self.result = ParseResult()
        self.context = TagRequest()
        self.machine_requests = 0  # จำนวนตะกร้าที่สร้างตั้งแต่ยิงป้ายเครื่องล่าสุด
        self.digits = None  # None = ไม่ได้ยิงตัวเลขอยู่
        self.digits_line = 0
        self.digits_raw = ""
        self.ng_mode = False

    def problem(self, line, raw, kind):
        self.result.problems.append(ScanProblem(line, raw, kind, MESSAGES[kind]))

    def drop_pending_number(self):
        if self.digits:
            self.problem(self.digits_line, self.digits_raw, "unfinished_number")
        self.digits = None
        self.ng_mode = False

    def start_number(self, line, raw):
        if self.digits is None:
            self.digits = ""
            self.digits_line, self.digits_raw = line, raw

    def emit(self, full, qty):
        self.result.requests.append(replace(self.context, full=full, qty=qty, ng=0))
        self.machine_requests += 1

    def feed(self, line, raw):
        text = normalize(raw)
        if not text:
            return
        if text.startswith("MC-"):
            self.drop_pending_number()
            self.context = TagRequest(machine=text[3:])
            self.machine_requests = 0
        elif text.startswith("EMP-"):
            self.context.emp = text[4:]
        elif text.startswith("CT-"):
            self.context.cart = text[3:]
        elif re.fullmatch(r"NUM-\d", text):
            self.start_number(line, raw)
            self.digits += text[4:]
        elif text == "CMD-FULL":
            self.drop_pending_number()
            self.emit(full=True, qty=None)
        elif text == "CMD-NG":
            self.drop_pending_number()
            self.start_number(line, raw)
            self.ng_mode = True
        elif text == "CMD-END":
            self.finish_number(line, raw)
        elif text == "CMD-UNDO":
            self.undo(line, raw)
        else:
            for name, pattern in self.document_patterns:
                if pattern.match(text):
                    setattr(self.context, name, text)
                    return
            self.problem(line, raw, "unknown")

    def finish_number(self, line, raw):
        if not self.digits:
            self.problem(line, raw, "empty_number")
        elif self.ng_mode:
            if self.machine_requests:
                self.result.requests[-1].ng = int(self.digits)
            else:
                self.problem(self.digits_line, self.digits_raw, "ng_without_basket")
        else:
            self.emit(full=False, qty=int(self.digits))
        self.digits = None
        self.ng_mode = False

    def undo(self, line, raw):
        if self.digits is not None:
            self.digits = None
            self.ng_mode = False
        elif self.machine_requests:
            self.result.requests.pop()
            self.machine_requests -= 1
        else:
            self.problem(line, raw, "nothing_to_undo")

    def finish(self):
        self.drop_pending_number()
        return self.result


def parse_scans(lines, patterns) -> ParseResult:
    parser = _Parser(patterns)
    for number, raw in enumerate(lines, start=1):
        parser.feed(number, raw)
    return parser.finish()
