"""ภาพหน้าจอ 5250 ณ ขณะหนึ่ง และการหาช่องจากชื่อช่อง (ไม่ผูกกับตำแหน่งตายตัว)

แถวและคอลัมน์นับจาก 1 เหมือนในจอเขียว (มุมขวาล่างของ PCOMM แสดงเป็น แถว/คอลัมน์)
"""

import re
from dataclasses import dataclass, field


@dataclass
class Field:
    row: int
    col: int
    length: int
    protected: bool
    numeric: bool
    text: str = ""


@dataclass
class Screen:
    rows: list
    fields: list = field(default_factory=list)
    cursor: tuple = (1, 1)
    input_inhibited: bool = False

    def text(self) -> str:
        return "\n".join(self.rows)

    def contains(self, text: str) -> bool:
        return any(text in row for row in self.rows)

    def find(self, label: str):
        """(แถว, คอลัมน์ถัดจากชื่อช่อง) ของชื่อช่องแรกที่เจอ หรือ None"""
        pattern = re.compile(label)
        for number, row in enumerate(self.rows, start=1):
            match = pattern.search(row)
            if match:
                return number, match.end() + 1
        return None

    def input_after(self, label: str):
        """ช่องกรอกที่อยู่ใกล้ที่สุดทางขวาของชื่อช่อง ในแถวเดียวกัน"""
        found = self.find(label)
        if found is None:
            return None
        row, after = found
        candidates = [f for f in self.fields if f.row == row and f.col >= after and not f.protected]
        return min(candidates, key=lambda f: f.col, default=None)

    def text_after(self, label: str, until: str | None = None) -> str:
        """ข้อความทั้งหมดหลังชื่อช่องในแถวเดียวกัน (ตัดก่อนชื่อช่องถัดไปถ้าระบุ until)"""
        found = self.find(label)
        if found is None:
            return ""
        row, after = found
        segment = self.rows[row - 1][after - 1:]
        if until:
            stop = re.search(until, segment)
            if stop:
                segment = segment[:stop.start()]
        return segment.lstrip(" .:_").rstrip()

    def value_after(self, label: str, until: str | None = None) -> str:
        """คำแรกที่อยู่หลังชื่อช่อง"""
        words = self.text_after(label, until).split()
        return words[0] if words else ""
