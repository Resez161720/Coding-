"""ฐานข้อมูล SQLite: รายการ tag, สถานะ, ประวัติทุกการเปลี่ยนแปลง และสีที่จำไว้ต่อใบสั่งงาน"""

import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .models import TagRequest
from .scan_parser import normalize


class StoreError(Exception):
    pass


class DuplicateUpload(StoreError):
    pass


class Status:
    PENDING = "pending"          # รอพิมพ์
    RUNNING = "running"          # กำลังกรอก ยังไม่กด F5
    SPLIT_SENT = "split_sent"    # กด F5 แล้ว ยังไม่เห็นหน้า L2
    SPLIT_DONE = "split_done"    # lot ใหม่ถูกสร้างแล้ว กำลังกรอกหน้า L2/L4
    DONE = "done"                # พิมพ์แล้ว
    FAILED = "failed"            # หยุดก่อน F5 ไม่มีอะไรถูกบันทึกใน AS/400
    ATTENTION = "attention"      # หยุดหลัง F5 ต้องตรวจบนจอเขียว
    CANCELLED = "cancelled"


SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    raw TEXT NOT NULL,
    problems TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    upload_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    machine TEXT NOT NULL, work_order TEXT NOT NULL, mat_do TEXT NOT NULL, mat_coil TEXT NOT NULL,
    die TEXT NOT NULL, emp TEXT NOT NULL, cart TEXT NOT NULL,
    full INTEGER NOT NULL, qty INTEGER, ng INTEGER NOT NULL,
    status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
    item_no TEXT NOT NULL DEFAULT '', item_name TEXT NOT NULL DEFAULT '',
    lot_size INTEGER, lot_qty INTEGER, mo_no TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS wo_colors (
    work_order TEXT PRIMARY KEY,
    color TEXT NOT NULL
);
"""

REQUEST_FIELDS = ("machine", "work_order", "mat_do", "mat_coil", "die", "emp", "cart", "full", "qty", "ng")
SCREEN_INFO = ("item_no", "item_name", "lot_size", "lot_qty", "mo_no")


@dataclass
class StoredRequest(TagRequest):
    id: int = 0
    upload_id: int = 0
    seq: int = 0
    status: str = Status.PENDING
    error: str = ""
    item_no: str = ""
    item_name: str = ""
    lot_size: int | None = None
    lot_qty: int | None = None
    mo_no: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Event:
    request_id: int
    at: str
    status: str
    detail: str


def content_hash(lines) -> str:
    normalized = "\n".join(text for text in (normalize(line) for line in lines) if text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path, now=datetime.now):
        self._clock = now
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.executescript(SCHEMA)

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _event(self, request_id, status, detail=""):
        self._db.execute(
            "INSERT INTO events (request_id, at, status, detail) VALUES (?, ?, ?, ?)",
            (request_id, self._now(), status, detail),
        )

    def add_upload(self, lines, requests, problems=(), force=False) -> int:
        digest = content_hash(lines)
        with self._lock, self._db:
            seen = self._db.execute("SELECT 1 FROM uploads WHERE content_hash = ?", (digest,)).fetchone()
            if seen and not force:
                raise DuplicateUpload("ข้อมูลชุดนี้เคยนำเข้าไปแล้ว")
            now = self._now()
            upload_id = self._db.execute(
                "INSERT INTO uploads (created_at, content_hash, raw, problems) VALUES (?, ?, ?, ?)",
                (now, digest, "\n".join(lines), json.dumps([asdict(p) for p in problems], ensure_ascii=False)),
            ).lastrowid
            for seq, req in enumerate(requests, start=1):
                values = [getattr(req, name) for name in REQUEST_FIELDS]
                request_id = self._db.execute(
                    f"INSERT INTO requests (upload_id, seq, {', '.join(REQUEST_FIELDS)}, status, created_at, updated_at)"
                    f" VALUES (?, ?, {', '.join('?' * len(REQUEST_FIELDS))}, ?, ?, ?)",
                    (upload_id, seq, *values, Status.PENDING, now, now),
                ).lastrowid
                self._event(request_id, Status.PENDING, "นำเข้าจากเครื่องยิง")
            return upload_id

    @staticmethod
    def _row(row) -> StoredRequest:
        data = dict(row)
        data["full"] = bool(data["full"])
        return StoredRequest(**data)

    def requests(self, statuses=None) -> list:
        with self._lock:
            if statuses:
                marks = ", ".join("?" * len(statuses))
                rows = self._db.execute(f"SELECT * FROM requests WHERE status IN ({marks}) ORDER BY id", tuple(statuses))
            else:
                rows = self._db.execute("SELECT * FROM requests ORDER BY id")
            return [self._row(row) for row in rows.fetchall()]

    def get(self, request_id) -> StoredRequest:
        with self._lock:
            row = self._db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise StoreError(f"ไม่พบรายการ {request_id}")
        return self._row(row)

    def update_fields(self, request_id, **changes):
        unknown = set(changes) - set(REQUEST_FIELDS)
        if unknown:
            raise StoreError(f"แก้ไขช่อง {', '.join(sorted(unknown))} ไม่ได้")
        with self._lock, self._db:
            current = self.get(request_id)
            if current.status not in (Status.PENDING, Status.FAILED):
                raise StoreError("แก้ไขได้เฉพาะรายการที่ยังไม่ได้เริ่มพิมพ์")
            assignments = ", ".join(f"{name} = ?" for name in changes)
            self._db.execute(
                f"UPDATE requests SET {assignments}, status = ?, error = '', updated_at = ? WHERE id = ?",
                (*changes.values(), Status.PENDING, self._now(), request_id),
            )
            self._event(request_id, Status.PENDING, "แก้ไข: " + ", ".join(f"{k}={v}" for k, v in changes.items()))

    def set_status(self, request_id, status, error="", **info):
        unknown = set(info) - set(SCREEN_INFO)
        if unknown:
            raise StoreError(f"บันทึกค่า {', '.join(sorted(unknown))} ไม่ได้")
        assignments = "".join(f", {name} = ?" for name in info)
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE requests SET status = ?, error = ?, updated_at = ?{assignments} WHERE id = ?",
                (status, error, self._now(), *info.values(), request_id),
            )
            self._event(request_id, status, error)

    def _move(self, request_id, allowed, status, detail):
        with self._lock, self._db:
            current = self.get(request_id)
            if current.status not in allowed:
                raise StoreError("ทำรายการนี้กับสถานะปัจจุบันไม่ได้")
            error = current.error if status == Status.CANCELLED else ""
            self._db.execute(
                "UPDATE requests SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, self._now(), request_id),
            )
            self._event(request_id, status, detail)

    def cancel(self, request_id):
        self._move(request_id, (Status.PENDING, Status.FAILED, Status.ATTENTION), Status.CANCELLED, "ยกเลิกโดยคนพิมพ์")

    def retry(self, request_id):
        self._move(request_id, (Status.FAILED,), Status.PENDING, "ลองใหม่")

    def resolve_manually(self, request_id):
        self._move(request_id, (Status.ATTENTION,), Status.DONE, "คนพิมพ์ทำต่อเองบนจอเขียวแล้ว")

    def recover_interrupted(self):
        """เรียกตอนเปิดโปรแกรม: รายการที่ค้างจากการปิดโปรแกรมกลางคัน"""
        for req in self.requests([Status.RUNNING]):
            self.set_status(req.id, Status.FAILED, "โปรแกรมหยุดกลางคันก่อนกด F5 ไม่มีอะไรถูกบันทึก ลองใหม่ได้")
        for req in self.requests([Status.SPLIT_SENT, Status.SPLIT_DONE]):
            self.set_status(req.id, Status.ATTENTION, "โปรแกรมหยุดกลางคันหลังกด F5 ตรวจรายการนี้บนจอเขียว")

    def events(self, request_id) -> list:
        with self._lock:
            rows = self._db.execute(
                "SELECT request_id, at, status, detail FROM events WHERE request_id = ? ORDER BY id", (request_id,)
            ).fetchall()
        return [Event(**dict(row)) for row in rows]

    def wo_color(self, work_order):
        with self._lock:
            row = self._db.execute("SELECT color FROM wo_colors WHERE work_order = ?", (work_order,)).fetchone()
        return row["color"] if row else None

    def set_wo_color(self, work_order, color):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO wo_colors (work_order, color) VALUES (?, ?)"
                " ON CONFLICT(work_order) DO UPDATE SET color = excluded.color",
                (work_order, color),
            )
