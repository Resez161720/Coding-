"""เชื่อมต่อจอเขียว IBM Personal Communications / iSeries Access for Windows (PC5250)

ใช้ Host Access Class Library: PCOMM.autECLPS (อ่านจอ/กรอก/กดปุ่ม) และ PCOMM.autECLOIA (สถานะแป้นพิมพ์)
ต้องใช้ Python แบบ 32-bit และ pywin32 บน Windows เครื่องเดียวกับที่เปิดจอเขียวไว้
"""

import time

from ..screen import Field, Screen

KEYS = {
    "enter": "[enter]",
    "pf1": "[pf1]",
    "pf3": "[pf3]",
    "pf5": "[pf5]",
    "reset": "[reset]",
}


class PcommError(Exception):
    pass


def _escape(text: str) -> str:
    # "[" เปิดคำสั่งปุ่มของ SendKeys ต้องเขียนซ้ำเพื่อพิมพ์ตัวอักษรจริง
    return text.replace("[", "[[")


class PcommDriver:
    def __init__(self, session="A", ps=None, oia=None, sleep=time.sleep, clock=time.monotonic):
        if ps is None or oia is None:
            ps, oia = self._connect(session)
        self.ps, self.oia = ps, oia
        self._sleep, self._clock = sleep, clock

    @staticmethod
    def _connect(session):
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            raise PcommError("ไม่พบ pywin32 ติดตั้งด้วยคำสั่ง: py -3-32 -m pip install pywin32") from None
        pythoncom.CoInitialize()
        try:
            ps = win32com.client.Dispatch("PCOMM.autECLPS")
            ps.SetConnectionByName(session)
            oia = win32com.client.Dispatch("PCOMM.autECLOIA")
            oia.SetConnectionByName(session)
        except Exception as error:  # COM แจ้ง error หลายแบบ เช่น ยังไม่ได้เปิด session หรือใช้ Python 64-bit
            raise PcommError(
                f"เชื่อมต่อจอเขียว session '{session}' ไม่ได้: {error}"
                " (เปิดจอเขียวไว้หรือยัง และใช้ Python 32-bit หรือเปล่า)"
            ) from None
        return ps, oia

    def _all_text(self) -> str:
        return self.ps.GetText(1, 1, self.ps.NumRows * self.ps.NumCols).replace("\x00", " ")

    def snapshot(self) -> Screen:
        cols = self.ps.NumCols
        text = self._all_text()
        rows = [text[i * cols:(i + 1) * cols].ljust(cols) for i in range(self.ps.NumRows)]
        field_list = self.ps.autECLFieldList
        field_list.Refresh()
        fields = []
        for index in range(1, field_list.Count + 1):
            item = field_list.Item(index)
            fields.append(Field(
                row=item.StartRow,
                col=item.StartCol,
                length=item.Length,
                protected=bool(item.Protected),
                numeric=bool(item.Numeric),
                text=(item.GetText() or "").replace("\x00", " "),
            ))
        return Screen(
            rows=rows,
            fields=fields,
            cursor=(self.ps.CursorPosRow, self.ps.CursorPosCol),
            input_inhibited=self.oia.InputInhibited != 0,
        )

    def fill(self, field: Field, text: str):
        self.ps.SetCursorPos(field.row, field.col)
        self.ps.SendKeys("[eraseeof]")
        if text:
            self.ps.SendKeys(_escape(text))
        # ช่องตัวเลขที่พิมพ์ไม่เต็มช่อง ต้องกด Field Exit ให้ชิดขวา
        # ถ้าพิมพ์เต็มช่อง เคอร์เซอร์จะข้ามไปช่องถัดไปเอง ห้ามกด Field Exit (จะไปลบช่องถัดไป)
        if field.numeric and len(text) < field.length:
            self.ps.SendKeys("[fldext]")

    def press(self, key: str):
        if key not in KEYS:
            raise ValueError(f"ไม่รู้จักปุ่ม {key}")
        self.ps.SendKeys(KEYS[key])

    def wait_ready(self, timeout: float) -> bool:
        """รอจนแป้นพิมพ์ปลดล็อกและหน้าจอนิ่ง"""
        deadline = self._clock() + timeout
        if not self.oia.WaitForInputReady(int(timeout * 1000)):
            return False
        previous = None
        while self._clock() < deadline:
            current = self._all_text()
            if current == previous and self.oia.InputInhibited == 0:
                return True
            previous = current
            self._sleep(0.15)
        return False
