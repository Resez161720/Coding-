"""จอเขียวจำลอง 5 หน้า ตามที่เห็นจากหน้าจอจริง ใช้ในโหมดทดลอง (demo) และชุดทดสอบ

เลียนแบบพฤติกรรมของระบบจริงที่รู้แล้ว:
- กรอกผิดแล้วไม่มีข้อความ error หน้าจอแค่ไม่เปลี่ยน
- พิมพ์ตัวอักษรในช่องตัวเลขแล้วแป้นพิมพ์ล็อก จนกว่าจะกด Reset
- กด F5 ที่หน้า DEP012G4 แล้ว lot ใหม่ถูกสร้างทันที
- กด Enter ที่หน้า CONFIRM แล้วพิมพ์ tag
"""

from dataclasses import dataclass
from datetime import datetime

from ..screen import Field, Screen

TITLE = "PRODUCTION CONTROL BUSINESS ACTIVITIES SUPPORT SYSTEM"


@dataclass
class WorkOrder:
    number: str
    item_no: str
    item_name: str
    lot_size: int
    schedule_qty: int
    process_code: str
    process_name: str


@dataclass
class _Input:
    name: str
    row: int
    col: int
    length: int
    numeric: bool = False


INPUTS = {
    "G1": [
        _Input("section", 5, 45, 4),
        _Input("mfg_order", 7, 45, 12),
        _Input("schd_start", 9, 45, 6, numeric=True),
        _Input("item_no", 11, 45, 15),
        _Input("rev", 11, 66, 3),
        _Input("first_proc", 13, 45, 7),
    ],
    "G3": [_Input("lot_qty", 6, 17, 9, numeric=True)],
    "L2": [
        _Input("shift", 5, 50, 1),
        _Input("tag_no", 9, 13, 8),
        _Input("emp", 10, 13, 6),
        _Input("mc", 11, 13, 6),
        _Input("cart", 11, 31, 10),
        _Input("good", 14, 13, 9, numeric=True),
        _Input("ng", 15, 13, 9, numeric=True),
        _Input("box", 15, 72, 3, numeric=True),
        _Input("start_time", 17, 67, 6, numeric=True),
        _Input("die", 18, 13, 15),
        _Input("speed", 18, 46, 6, numeric=True),
        _Input("proc_time", 18, 72, 5),
        _Input("remark1", 19, 13, 20),
        _Input("remark3", 19, 46, 20),
        _Input("press_mat", 21, 13, 15),
        _Input("action", 21, 46, 8),
    ],
}


class FakeGreenScreen:
    def __init__(self, work_orders, now=datetime.now, user_name="DEMO USER", user_emp="T0000",
                 return_screen="G1"):
        self.work_orders = {wo.number: wo for wo in work_orders}
        self.remaining = {wo.number: wo.schedule_qty for wo in work_orders}
        self.now = now
        self.user_name, self.user_emp = user_name, user_emp
        self.return_screen = return_screen
        self.printed = []
        self.frozen = set()            # {(หน้า, ปุ่ม)} กดแล้วหน้าจอไม่เปลี่ยน ใช้จำลองปัญหา
        self.confirm_overrides = {}    # ค่าที่หน้า CONFIRM แสดงไม่ตรงกับที่กรอก ใช้จำลองปัญหา
        self.splits = {}
        self.inhibited = False
        self.context = {}
        self._show("G1", {"section": "9999"})

    # ---- ส่วนที่ driver ใช้ ----

    def snapshot(self) -> Screen:
        grid = [[" "] * 80 for _ in range(24)]

        def put(row, col, text):
            for offset, char in enumerate(str(text)):
                if col - 1 + offset < 80:
                    grid[row - 1][col - 1 + offset] = char

        for row, col, text in self._texts():
            put(row, col, text)
        fields = []
        for spec in INPUTS.get(self.screen, []):
            shown = self.values.get(spec.name, "").ljust(spec.length)[:spec.length]
            put(spec.row, spec.col, shown)
            fields.append(Field(spec.row, spec.col, spec.length, protected=False, numeric=spec.numeric, text=shown))
        cursor = (fields[0].row, fields[0].col) if fields else (1, 1)
        return Screen(["".join(row) for row in grid], fields, cursor, self.inhibited)

    def fill(self, field: Field, text: str):
        if self.inhibited:
            return
        spec = next((s for s in INPUTS.get(self.screen, []) if (s.row, s.col) == (field.row, field.col)), None)
        if spec is None:
            self.inhibited = True  # พิมพ์ลงพื้นที่ที่กรอกไม่ได้
            return
        if len(text) > spec.length:
            raise ValueError(f"ข้อความ '{text}' ยาวเกินช่อง {spec.name} ({spec.length} ตัว)")
        if spec.numeric and text and not text.isdigit():
            self.inhibited = True
            return
        self.values[spec.name] = text

    def press(self, key: str):
        if key == "reset":
            self.inhibited = False
            return
        if self.inhibited or (self.screen, key) in self.frozen:
            return
        action = {
            ("G1", "enter"): self._find_work_order,
            ("G3", "enter"): self._preview_split,
            ("G3", "pf1"): self._home,
            ("G4", "pf1"): self._home,
            ("G4", "pf5"): self._split,
            ("L2", "enter"): lambda: self._show("L4", self.values),
            ("L4", "pf3"): lambda: self._show("L2", self.values),
            ("L4", "enter"): self._print,
            ("MENU", "pf1"): self._home,
        }.get((self.screen, key))
        if action:
            action()

    def wait_ready(self, timeout: float) -> bool:
        return True

    # ---- การทำงานของแต่ละหน้า ----

    def _show(self, screen, values):
        self.screen = screen
        self.values = dict(values)

    def _home(self):
        self.context = {}
        self._show("G1", {"section": "9999"})

    def _find_work_order(self):
        wo = self.work_orders.get(self.values.get("mfg_order", "").strip().upper())
        if wo is None:
            return
        self.context = {"wo": wo}
        self._show("G3", {"lot_qty": str(wo.lot_size)})

    def _preview_split(self):
        text = self.values.get("lot_qty", "").strip()
        if not text.isdigit() or int(text) <= 0:
            return
        self.context["qty"] = int(text)
        self._show("G4", {})

    def _split(self):
        wo, qty, now = self.context["wo"], self.context["qty"], self.now()
        day = f"{now.day:02d}"
        count = self.splits.get((wo.number, day), 0)
        self.splits[(wo.number, day)] = count + 1
        mo_no = f"{wo.number}{day}{chr(65 + count // 26)}{chr(65 + count % 26)}"
        self.remaining[wo.number] -= qty
        self.context["mo_no"] = mo_no
        self._show("L2", {
            "shift": "", "tag_no": "", "emp": self.user_emp, "mc": "", "cart": "",
            "good": str(qty), "ng": "0", "box": "002", "start_time": now.strftime("%H%M%S"),
            "die": "", "speed": "", "proc_time": "", "remark1": "", "remark3": "",
            "press_mat": "", "action": "",
        })

    def _print(self):
        wo = self.context["wo"]
        record = {"mo_no": self.context["mo_no"], "work_order": wo.number, "item_no": wo.item_no,
                  "in_qty": str(self.context["qty"])}
        record.update(self.values)
        self.printed.append(record)
        self.context = {}
        if self.return_screen == "G1":
            self._home()
        else:
            self._show(self.return_screen, {})

    # ---- ข้อความบนหน้าจอ ----

    def _texts(self):
        now = self.now()
        date, clock = now.strftime("%d/%m/%y"), now.strftime("%H:%M:%S")
        ymd = f"{now.year} / {now.month:02d} / {now.day:02d}"
        wo = self.context.get("wo")
        if self.screen == "MENU":
            return [(1, 2, "MAIN MENU"), (5, 5, "1. MFG ORDER SPLIT LOT"), (22, 5, "F1=MFG ORDER SPLIT LOT")]
        if self.screen == "G1":
            return [
                (1, 2, "DEP012G1"), (1, 14, TITLE), (1, 71, date),
                (2, 2, "PBASPR"), (2, 24, "* MFG ORDER SPLIT LOT(PARTIAL PROCESS) *"), (2, 71, clock),
                (3, 2, self.user_name),
                (5, 22, "SECTION CODE ...... :"), (7, 22, "MFG ORDER NO. ..... :"),
                (9, 22, "SCHD START(DMY) ... :"), (11, 22, "ITEM NO. .......... :"), (11, 62, "REV"),
                (13, 22, "FIRST IN PORCESS... :"),
                (22, 6, "CMD1 - RETURN,  ENTER - NEXT"),
            ]
        if self.screen in ("G3", "G4"):
            remaining = self.remaining[wo.number]
            texts = [
                (1, 2, "DEP012" + self.screen), (1, 14, TITLE), (1, 71, date),
                (2, 2, "PBASPR"), (2, 24, "* MFG ORDER SPLIT LOT(PARTIAL PROCESSS) *"), (2, 71, clock),
                (3, 2, self.user_name),
                (4, 3, "SECT.... 9999"), (4, 30, "ITEM NO."), (4, 40, wo.item_no), (4, 58, "RV"),
                (5, 30, "ITEM NAME"), (5, 40, wo.item_name[:39]),
                (6, 3, "LOT M/O QTY."), (6, 30, "LOT SIZE"), (6, 40, f"{wo.lot_size:>9}"),
                (8, 18, "SCHEDULE"), (8, 58, "ISSUE"), (8, 68, "FIRST CUSTOMER"),
                (9, 3, "MFG NO."), (9, 22, "QTY"), (9, 27, "START(DMY)"), (9, 39, "END(DMY)"),
                (9, 50, "INST.(DMY)"), (9, 62, "PRCS"), (9, 68, "DUE(DMY)"),
            ]
            if self.screen == "G3":
                return texts + [
                    (11, 3, wo.number), (11, 13, f"{remaining:>12,}"), (11, 27, "1/10/2026"),
                    (22, 6, "CMD.1-RETURN   ENTER-NEXT"),
                ]
            qty = self.context["qty"]
            return texts + [
                (6, 17, f"{qty:>9}"),
                (11, 3, wo.number), (11, 13, f"{remaining - qty:>12,}"), (11, 27, "1/10/2026"),
                (12, 3, f"{wo.number}{now.day:02d}"), (12, 13, f"{qty:>12,}"), (12, 27, now.strftime("%d/%m/%Y")),
                (22, 6, "CMD.1-RETURN   CMD.5-UPDATE"),
            ]
        # L2 และ L4
        qty, mo_no = self.context["qty"], self.context["mo_no"]
        texts = [
            (1, 1, "DTNOG1" + self.screen), (1, 14, TITLE), (1, 71, clock),
            (2, 10, "9999"), (2, 25, "** PRODUCTION RESULT ENTRY **"), (2, 57, "For Press"), (2, 71, date),
            (3, 57, "1ST PROCESS"),
            (5, 2, "Start YMD"), (5, 13, ymd), (5, 40, "Shift"), (5, 60, "Last Lot"),
            (6, 2, "Process"), (6, 13, wo.process_code), (6, 20, wo.process_name[:19]),
            (6, 60, "Lot Size"), (6, 72, f"{wo.lot_size:>8}"),
            (7, 2, "M/O No."), (7, 13, mo_no), (7, 40, "Schd Qty"), (7, 50, f"{qty:>8}"),
            (7, 60, "Instruc"), (7, 79, "0"),
            (8, 2, "Item No."), (8, 13, wo.item_no[:26]), (8, 40, "Item Name"), (8, 50, wo.item_name[:30]),
            (9, 2, "Tag No."), (9, 40, "1st in Proc"), (9, 60, "Lot No."), (9, 68, mo_no[:12]),
            (10, 2, "Emp No."), (10, 60, "Ttl Prod"), (10, 79, "0"),
            (11, 2, "M/C No."), (11, 22, "Cart No."),
            (13, 3, "In Qty."), (13, 13, f"{qty:>9}"),
            (14, 3, "Good Qty."),
            (15, 3, "Ng Qty."), (15, 40, "End YMD."), (15, 50, ymd),
            (17, 3, "Only Proc =0010 Stamping"), (17, 55, "START TIME"),
            (18, 3, "Die No."), (18, 35, "M/C Speed"), (18, 53, "PCS/MIN"), (18, 62, "PROC.TIME"),
            (19, 3, "Remark 1"), (19, 35, "Remark 3"),
            (20, 3, "(Mat.D/O)"), (20, 35, "(Mat.Coil)"),
            (21, 3, "Press Mat"), (21, 35, "Action :"),
            (23, 5, "F3=PREV-SCRN  ,ENTER=PROCESS"),
        ]
        if self.values.get("emp") == self.user_emp:
            texts.append((10, 21, self.user_name[:38]))
        if self.screen == "L2":
            return texts
        texts.append((3, 25, "((C O N F I R M))"))
        for spec in INPUTS["L2"]:
            value = self.confirm_overrides.get(spec.name, self.values.get(spec.name, ""))
            texts.append((spec.row, spec.col, value.rjust(spec.length) if spec.numeric else value))
        return texts
