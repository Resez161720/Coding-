"""แกนของโปรแกรม: นำเข้า, แก้ไข, สถานะสำหรับหน้าเว็บ และ worker ที่ถือการเชื่อมต่อจอเขียว

การเชื่อมต่อจอเขียว (COM) ต้องใช้จาก thread เดียวตลอด จึงให้ worker thread เป็นผู้ใช้ driver คนเดียว
หน้าเว็บสั่งงานผ่านคิว และตอบคำถาม (ใส่กระดาษ / ยืนยันพิมพ์) ผ่าน answer()
"""

import logging
import queue
import threading
from concurrent.futures import Future
from dataclasses import asdict
from datetime import datetime

from .cards import build_cards_html
from .demo import DEMO_SCANS
from .dumps import write_dump
from .masterdata import MasterDataError, load_masterdata
from .runner import Runner
from .scan_parser import parse_scans
from .store import DuplicateUpload, Status, Store
from .validation import resolve_color, validate

log = logging.getLogger(__name__)

STATUS_TH = {
    Status.PENDING: "รอพิมพ์",
    Status.RUNNING: "กำลังกรอก",
    Status.SPLIT_SENT: "กด F5 แล้ว",
    Status.SPLIT_DONE: "กำลังกรอกผลผลิต",
    Status.DONE: "พิมพ์แล้ว",
    Status.FAILED: "ไม่สำเร็จ (แก้แล้วลองใหม่ได้)",
    Status.ATTENTION: "ต้องตรวจบนจอเขียว",
    Status.CANCELLED: "ยกเลิก",
}

QUESTION_LABELS = {
    "paper": ("ใส่กระดาษแล้ว ทำต่อ", "ยกเลิก"),
    "final": ("พิมพ์", "ไม่พิมพ์ (หยุด)"),
    "color": ("เปลี่ยนกระดาษแล้ว ทำต่อ", "หยุด"),
    "home": ("อยู่หน้า DEP012G1 แล้ว ทำต่อ", "หยุด"),
}

TEXT_FIELDS = ("machine", "work_order", "mat_do", "mat_coil", "die", "emp", "cart")


class Worker:
    def __init__(self, app, driver_factory):
        self.app = app
        self.driver_factory = driver_factory
        self.driver = None
        self._commands = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._answered = threading.Event()
        self._answer = False
        self._question_id = 0
        self.state, self.message, self.color, self.summary, self.question = "idle", "", None, None, None
        self._thread = threading.Thread(target=self._loop, name="green-screen-worker", daemon=True)
        self._thread.start()

    # ---- คิวคำสั่ง ----

    def submit(self, name, *args) -> Future:
        future = Future()
        self._commands.put((name, args, future))
        return future

    def _loop(self):
        while True:
            item = self._commands.get()
            if item is None:
                return
            name, args, future = item
            try:
                future.set_result(getattr(self, "_do_" + name)(*args))
            except Exception as error:  # แสดงบนหน้าเว็บแทนการให้ thread ตาย
                log.exception("worker command %s failed", name)
                with self._lock:
                    self.state, self.message = "idle", f"ผิดพลาด: {error}"
                future.set_exception(error)

    def _driver(self):
        if self.driver is None:
            self.driver = self.driver_factory()
        return self.driver

    def _do_run(self, color):
        try:
            runner = Runner(self.app.store, self._driver(), self.app.master, self.app.config,
                            ask=self.ask, now=self.app.now, dump_dir=self.app.dump_dir)
            summary = runner.run_color(color, should_stop=self._stop.is_set)
            with self._lock:
                self.summary = asdict(summary)
                self.message = summary.stopped_reason or f"พิมพ์สี{color}เสร็จ {summary.done} ใบ"
            log.info("run %s: %s", color, self.summary)
        finally:
            with self._lock:
                self.state, self.color, self.question = "idle", None, None

    def _do_dump(self):
        return write_dump(self._driver().snapshot(), self.app.dump_dir, "บันทึกหน้าจอโดยคนพิมพ์")

    # ---- งานพิมพ์และคำถาม ----

    def start(self, color) -> bool:
        with self._lock:
            if self.state != "idle":
                return False
            self.state, self.color, self.message, self.summary = "running", color, f"กำลังพิมพ์สี{color}", None
        self._stop.clear()
        self.submit("run", color)
        return True

    def ask(self, kind, message, screen) -> bool:
        if self._stop.is_set():
            return False
        self._answered.clear()
        with self._lock:
            self._question_id += 1
            yes, no = QUESTION_LABELS.get(kind, ("ทำต่อ", "หยุด"))
            self.question = {"id": self._question_id, "kind": kind, "message": message,
                             "screen": screen.text() if screen is not None else "", "yes": yes, "no": no}
            self.state = "asking"
        while not self._answered.wait(0.1):
            if self._stop.is_set():
                break
        with self._lock:
            answer = self._answer if self._answered.is_set() else False
            self.question, self.state = None, "running"
        return answer

    def answer(self, question_id, yes) -> bool:
        with self._lock:
            if not self.question or self.question["id"] != question_id:
                return False
            self._answer = bool(yes)
        self._answered.set()
        return True

    def stop(self):
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "message": self.message, "color": self.color,
                    "summary": self.summary, "question": self.question}

    def shutdown(self):
        self._stop.set()
        self._commands.put(None)


class App:
    def __init__(self, config, driver_factory, now=datetime.now, dump_dir=None):
        self.config = config
        self.now = now
        self.dump_dir = dump_dir or (config.data_dir.parent / "dumps")
        self.store = Store(config.data_dir / "tagbot.db", now=now)
        self.store.recover_interrupted()
        self.master, self.master_error = None, None
        self.reload_master()
        self.worker = Worker(self, driver_factory)

    def shutdown(self):
        self.worker.shutdown()

    def reload_master(self):
        try:
            self.master, self.master_error = load_masterdata(self.config.data_dir), None
        except MasterDataError as error:
            self.master, self.master_error = None, f"ตารางข้อมูลมีปัญหา: {error}"
        return self.master_error

    # ---- นำเข้าและแก้ไข ----

    def import_scans(self, text, force=False) -> dict:
        lines = text.splitlines()
        result = parse_scans(lines, self.config.barcodes)
        problems = [asdict(problem) for problem in result.problems]
        if not result.requests:
            return {"added": 0, "problems": problems, "duplicate": False, "message": "ไม่พบตะกร้าในข้อมูลที่นำเข้า"}
        try:
            self.store.add_upload(lines, result.requests, result.problems, force=force)
        except DuplicateUpload as error:
            return {"added": 0, "problems": problems, "duplicate": True, "message": str(error)}
        return {"added": len(result.requests), "problems": problems, "duplicate": False,
                "message": f"นำเข้า {len(result.requests)} ตะกร้า"}

    def edit(self, request_id, changes):
        values = {}
        for name, value in changes.items():
            if name in TEXT_FIELDS:
                values[name] = str(value).strip().upper()
            elif name == "qty":
                text = str(value if value is not None else "").strip()
                if not text:
                    values.update(full=True, qty=None)
                elif text.isdigit():
                    values.update(full=False, qty=int(text))
                else:
                    raise ValueError("จำนวนต้องเป็นตัวเลข (เว้นว่าง = เต็มตะกร้า)")
            elif name == "ng":
                text = str(value if value is not None else "").strip() or "0"
                if not text.isdigit():
                    raise ValueError("NG ต้องเป็นตัวเลข")
                values["ng"] = int(text)
            else:
                raise ValueError(f"แก้ไขช่อง {name} ไม่ได้")
        self.store.update_fields(request_id, **values)

    def set_wo_color(self, work_order, color):
        if color not in self.config.colors:
            raise ValueError(f"ไม่มีสี {color} ในรายการสี")
        self.store.set_wo_color(work_order.strip().upper(), color)

    def cancel(self, request_id):
        self.store.cancel(request_id)

    def retry(self, request_id):
        self.store.retry(request_id)

    def resolve(self, request_id):
        self.store.resolve_manually(request_id)

    # ---- สั่งพิมพ์ ----

    def start_run(self, color):
        if self.master is None:
            return False, self.master_error
        if color not in self.config.colors:
            return False, f"ไม่มีสี {color} ในรายการสี"
        if not self.worker.start(color):
            return False, "กำลังพิมพ์อยู่ รอให้เสร็จก่อน"
        return True, ""

    def stop(self):
        self.worker.stop()

    def answer(self, question_id, yes):
        return self.worker.answer(question_id, yes)

    def dump_screen(self):
        if self.worker.snapshot()["state"] != "idle":
            raise ValueError("กำลังพิมพ์อยู่ บันทึกหน้าจอได้หลังพิมพ์เสร็จ")
        return self.worker.submit("dump").result(timeout=30)

    def cards_html(self):
        return build_cards_html(self.master)

    # ---- สถานะสำหรับหน้าเว็บ ----

    def state(self) -> dict:
        today = self.now().date().isoformat()
        ready = {color: 0 for color in self.config.colors}
        needs_color = {}
        rows = []
        for req in self.store.requests():
            if req.status in (Status.DONE, Status.CANCELLED) and not req.updated_at.startswith(today):
                continue
            issues, color = [], None
            if self.master is not None:
                wo_color = self.store.wo_color(req.work_order)
                issues = validate(req, self.master, self.config.barcodes, self.config.colors, wo_color)
                color = resolve_color(req, self.master, wo_color)
                if req.status == Status.PENDING:
                    if not issues and color in ready:
                        ready[color] += 1
                    if any(issue.field == "color" for issue in issues) and req.work_order and color is None:
                        needs_color[req.work_order] = needs_color.get(req.work_order, 0) + 1
            row = asdict(req)
            row.update(status_th=STATUS_TH.get(req.status, req.status), color=color,
                       issues=[asdict(issue) for issue in issues])
            rows.append(row)
        worker = self.worker.snapshot()
        return {
            "mode": self.config.mode,
            "worker": {key: worker[key] for key in ("state", "message", "color", "summary")},
            "question": worker["question"],
            "colors": list(self.config.colors),
            "groups": [{"color": color, "ready": count} for color, count in ready.items()],
            "needs_color": [{"work_order": wo, "count": count} for wo, count in needs_color.items()],
            "requests": rows,
            "master_error": self.master_error,
            "demo_scans": DEMO_SCANS if self.config.mode == "demo" else "",
        }
