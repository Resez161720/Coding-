"""กรอกจอเขียว 5 หน้าสำหรับ tag 1 ใบ

DEP012G1 -> DEP012G3 -> DEP012G4 -[F5: lot ถูกสร้างจริง]-> DTNOG1L2 -> DTNOG1L4 (CONFIRM) -[Enter: พิมพ์]

กติกาความปลอดภัย:
- ก่อนกด F5 ถ้ามีอะไรผิดปกติ ถอยกลับหน้าแรกได้ (ไม่มีอะไรถูกบันทึก)
- หลังกด F5 ห้ามทิ้งงานค้าง ถ้าผิดปกติให้หยุดอยู่ที่หน้านั้นให้คนตรวจ (FlowError.after_split = True)
- ก่อนกด Enter สุดท้าย อ่านทุกค่าบนหน้า CONFIRM มาเทียบกับที่ตั้งใจกรอก
"""

import re
from dataclasses import dataclass

SCREEN_IDS = {"G1": "DEP012G1", "G3": "DEP012G3", "G4": "DEP012G4", "L2": "DTNOG1L2", "L4": "DTNOG1L4"}


@dataclass
class Label:
    name: str
    pattern: str
    until: str | None = None


MFG_ORDER = Label("MFG ORDER NO.", r"MFG ORDER NO\.")
LOT_QTY = Label("LOT M/O QTY.", r"LOT M/O QTY\.")
ITEM_NO = Label("ITEM NO.", r"ITEM NO\.")
ITEM_NAME = Label("ITEM NAME", r"ITEM NAME")
LOT_SIZE = Label("LOT SIZE", r"LOT SIZE")
MO_NO = Label("M/O No.", r"M/O\s*No\.?")
PROCESS = Label("Process", r"Process")
IN_QTY = Label("In Qty", r"In\s*Qty\.?")
SHIFT = Label("Shift", r"Shift")
EMP = Label("Emp No.", r"Emp\s*No\.?")
MACHINE = Label("M/C No.", r"M/C\s*No\.?", until=r"Cart\s*No")
CART = Label("Cart No.", r"Cart\s*No\.?")
GOOD = Label("Good Qty", r"Good\s*Qty\.?")
NG = Label("Ng Qty", r"Ng\s*Qty\.?")
DIE = Label("Die No.", r"Die\s*No\.?")
REMARK1 = Label("Remark 1 (Mat.D/O)", r"Remark\s*1")
REMARK3 = Label("Remark 3 (Mat.Coil)", r"Remark\s*3")
SPEED = Label("M/C Speed", r"M/C\s*Speed")
ACTION = Label("Action", r"Action\s*:?")


class FlowError(Exception):
    def __init__(self, message, after_split, screen=None):
        super().__init__(message)
        self.after_split = after_split
        self.screen = screen


@dataclass
class TagJob:
    work_order: str
    mat_do: str
    mat_coil: str
    die: str
    emp: str
    machine: str
    cart: str
    full: bool
    qty: int | None
    ng: int
    shift: str
    speed: str
    action: str
    color: str  # สีกระดาษที่ใส่อยู่ในเครื่องพิมพ์ตอนนี้


@dataclass
class FlowResult:
    mo_no: str
    lot_qty: int
    good: int
    paper_changed_to: str | None = None


def screen_id(screen):
    for key, ident in SCREEN_IDS.items():
        if screen.contains(ident):
            return key
    return None


def _number(text):
    text = (text or "").replace(",", "")
    return int(text) if text.isdigit() else None


class TagFlow:
    def __init__(self, driver, options, process_colors):
        self.driver = driver
        self.options = options
        self.process_colors = process_colors

    # ---- ตัวช่วย ----

    def _snapshot(self):
        return self.driver.snapshot()

    def _press(self, key, after_split):
        self.driver.press(key)
        timeout = self.options.step_timeout_seconds
        if not self.driver.wait_ready(timeout):
            raise FlowError(f"รอจอเขียวตอบนานเกิน {timeout:g} วินาที หลังกด {key.upper()}", after_split,
                            self._snapshot())
        return self._snapshot()

    def _fill(self, screen, label, value, after_split):
        field = screen.input_after(label.pattern)
        if field is None:
            raise FlowError(f"หาช่อง {label.name} บนจอไม่เจอ", after_split, screen)
        if len(value) > field.length:
            raise FlowError(f"ค่า '{value}' ยาวเกินช่อง {label.name} ({field.length} ตัว)", after_split, screen)
        self.driver.fill(field, value)
        screen = self._snapshot()
        if screen.input_inhibited:
            self.driver.press("reset")
            raise FlowError(f"ช่อง {label.name} กรอก '{value}' ไม่ได้ (แป้นพิมพ์ล็อก / แถบแดง)", after_split, screen)
        return screen

    def _expect(self, screen, key, message, after_split):
        if screen_id(screen) != key:
            raise FlowError(message, after_split, screen)

    def recover_to_home(self) -> bool:
        """ใช้หลังผิดพลาดก่อน F5 เท่านั้น: กด CMD1-RETURN (F1) จนกลับหน้า DEP012G1"""
        for _ in range(3):
            screen = self._snapshot()
            if screen.input_inhibited:
                self.driver.press("reset")
                screen = self._snapshot()
            current = screen_id(screen)
            if current == "G1":
                return True
            if current not in ("G3", "G4"):
                return False
            self.driver.press("pf1")
            self.driver.wait_ready(self.options.step_timeout_seconds)
        return screen_id(self._snapshot()) == "G1"

    # ---- ขั้นตอนหลัก ----

    def run(self, job, checkpoint, ask) -> FlowResult:
        screen = self._snapshot()
        self._expect(screen, "G1", "จอเขียวไม่ได้อยู่หน้า DEP012G1 (MFG ORDER SPLIT LOT)", after_split=False)

        # หน้า 1: ใบสั่งงาน
        self._fill(screen, MFG_ORDER, job.work_order, after_split=False)
        screen = self._press("enter", after_split=False)
        self._expect(screen, "G3", f"ไม่พบใบสั่งงาน {job.work_order} (กด Enter แล้วหน้าจอไม่เปลี่ยน)", after_split=False)

        # หน้า 2: จำนวนของ lot ที่จะแยก
        item_no = screen.value_after(ITEM_NO.pattern)
        item_name = screen.text_after(ITEM_NAME.pattern)
        lot_size = _number(screen.value_after(LOT_SIZE.pattern))
        if lot_size is None:
            raise FlowError("อ่าน LOT SIZE บนจอไม่ได้", False, screen)
        good = lot_size if job.full else job.qty
        lot_qty = good + job.ng if self.options.lot_qty_includes_ng else good
        if good > lot_size:
            raise FlowError(f"จำนวนดี {good} มากกว่า LOT SIZE {lot_size}", False, screen)
        parent = re.search(rf"^\s*{re.escape(job.work_order)}\s+([\d,]+)", screen.text(), re.MULTILINE)
        remaining = _number(parent.group(1)) if parent else None
        if remaining is not None and lot_qty > remaining:
            raise FlowError(f"จำนวน {lot_qty} มากกว่ายอดคงเหลือของใบสั่งงาน {remaining}", False, screen)
        self._fill(screen, LOT_QTY, str(lot_qty), after_split=False)
        screen = self._press("enter", after_split=False)
        self._expect(screen, "G4", f"ใส่จำนวน {lot_qty} แล้วหน้าจอไม่ไปหน้า DEP012G4", after_split=False)

        # หน้า 3: ตรวจแถว lot ใหม่ แล้วกด F5 (จุดที่ lot ถูกสร้างใน AS/400)
        new_row = re.search(rf"^\s*{re.escape(job.work_order)}\S+\s+([\d,]+)", screen.text(), re.MULTILINE)
        if new_row is None or _number(new_row.group(1)) != lot_qty:
            raise FlowError(f"หน้า DEP012G4 ไม่แสดง lot ใหม่จำนวน {lot_qty}", False, screen)
        checkpoint("split_sent", {"item_no": item_no, "item_name": item_name, "lot_size": lot_size, "lot_qty": lot_qty})
        screen = self._press("pf5", after_split=True)
        self._expect(screen, "L2", "กด F5 แล้วไม่ไปหน้า DTNOG1L2 ตรวจบนจอเขียวว่า lot ถูกสร้างหรือยัง", after_split=True)

        # หน้า 4: ผลการผลิต
        mo_no = screen.value_after(MO_NO.pattern)
        checkpoint("split_done", {"mo_no": mo_no})
        in_qty = _number(screen.value_after(IN_QTY.pattern))
        if in_qty != lot_qty:
            raise FlowError(f"In Qty บนจอ ({in_qty}) ไม่ตรงกับจำนวนที่แยก ({lot_qty})", True, screen)

        paper_changed_to = None
        process = screen.value_after(PROCESS.pattern)
        needed = self.process_colors.get(process)
        if needed and needed != job.color:
            message = (f"งานนี้เป็น process {process} ต้องใช้กระดาษสี{needed} แต่ตอนนี้ใส่สี{job.color} อยู่"
                       f" ให้เปลี่ยนเป็นกระดาษสี{needed}")
            if not ask("color", message, screen):
                raise FlowError(f"หยุดเพราะต้องใช้กระดาษสี{needed} (ค้างที่หน้า DTNOG1L2)", True, screen)
            paper_changed_to = needed

        values = [(SHIFT, job.shift), (EMP, job.emp), (MACHINE, job.machine), (CART, job.cart),
                  (GOOD, str(good)), (NG, str(job.ng)), (DIE, job.die), (REMARK1, job.mat_do),
                  (REMARK3, job.mat_coil), (SPEED, job.speed)]
        if job.action:
            values.append((ACTION, job.action))
        for label, value in values:
            screen = self._fill(screen, label, value, after_split=True)
        screen = self._press("enter", after_split=True)
        self._expect(screen, "L4", "กด Enter แล้วไม่ไปหน้า CONFIRM (DTNOG1L4)", after_split=True)

        # หน้า 5: เทียบทุกค่าก่อนพิมพ์
        expected = values + [(MO_NO, mo_no), (IN_QTY, str(lot_qty))]
        wrong = []
        for label, value in expected:
            shown = screen.value_after(label.pattern, until=label.until)
            same = _number(shown) == _number(value) if _number(value) is not None else shown == value
            if not same:
                wrong.append(f"{label.name}: ต้องเป็น '{value}' แต่จอแสดง '{shown}'")
        if wrong:
            raise FlowError("หน้า CONFIRM แสดงค่าไม่ตรง: " + "; ".join(wrong), True, screen)
        if self.options.confirm_before_final_enter and not ask("final", "ตรวจค่าบนหน้า CONFIRM ให้ถูกต้องก่อนพิมพ์", screen):
            raise FlowError("ยังไม่ได้ยืนยันการพิมพ์ (ค้างที่หน้า CONFIRM)", True, screen)
        screen = self._press("enter", after_split=True)
        if screen_id(screen) == "L4":
            raise FlowError("กด Enter แล้วยังอยู่หน้า CONFIRM ตรวจบนจอเขียวว่าพิมพ์แล้วหรือยัง", True, screen)
        return FlowResult(mo_no=mo_no, lot_qty=lot_qty, good=good, paper_changed_to=paper_changed_to)
