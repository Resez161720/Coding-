"""พิมพ์ tag ทีละสี: ถามใส่กระดาษ แล้วกรอกจอเขียวทีละรายการตามลำดับเส้นทางเดิน"""

import logging
from dataclasses import dataclass
from datetime import datetime

from .dumps import write_dump
from .flow import FlowError, TagFlow, TagJob, screen_id
from .shifts import shift_for
from .store import Status
from .validation import resolve_color, validate

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    color: str
    done: int = 0
    failed: int = 0
    attention: int = 0
    stopped_reason: str = ""


class Runner:
    def __init__(self, store, driver, master, config, ask, now=datetime.now, dump_dir=None):
        self.store = store
        self.driver = driver
        self.master = master
        self.config = config
        self.ask = ask
        self.now = now
        self.dump_dir = dump_dir

    def color_of(self, req):
        return resolve_color(req, self.master, self.store.wo_color(req.work_order))

    def issues_of(self, req):
        return validate(req, self.master, self.config.barcodes, self.config.colors, self.store.wo_color(req.work_order))

    def ready_for_color(self, color) -> list:
        ready = [req for req in self.store.requests([Status.PENDING])
                 if not self.issues_of(req) and self.color_of(req) == color]
        return sorted(ready, key=lambda req: (self.master.machines[req.machine].route, req.id))

    def _job(self, req, color) -> TagJob:
        machine = self.master.machines[req.machine]
        return TagJob(
            work_order=req.work_order, mat_do=req.mat_do, mat_coil=req.mat_coil, die=req.die, emp=req.emp,
            machine=req.machine, cart=req.cart, full=req.full, qty=req.qty, ng=req.ng,
            shift=shift_for(self.now(), self.config.shifts), speed=machine.speed, action=machine.action,
            color=color,
        )

    def _at_home(self, flow, after_print) -> bool:
        """ให้จอเขียวอยู่หน้า DEP012G1 ก่อนเริ่มใบถัดไป"""
        if screen_id(self.driver.snapshot()) == "G1":
            return True
        if after_print:
            for key in self.config.options.home_keys:
                self.driver.press(key)
                self.driver.wait_ready(self.config.options.step_timeout_seconds)
            if screen_id(self.driver.snapshot()) == "G1":
                return True
        message = "เปิดจอเขียวไปหน้า DEP012G1 (MFG ORDER SPLIT LOT)"
        return self.ask("home", message, self.driver.snapshot()) and screen_id(self.driver.snapshot()) == "G1"

    def run_color(self, color, should_stop=lambda: False) -> RunSummary:
        summary = RunSummary(color)
        queue = self.ready_for_color(color)
        if not queue:
            summary.stopped_reason = f"ไม่มีรายการสี{color}ที่พร้อมพิมพ์"
            return summary
        if not self.ask("paper", f"ใส่กระดาษสี{color}ในเครื่องพิมพ์ (ต้องใช้ {len(queue)} ใบ)", None):
            summary.stopped_reason = "ยกเลิกก่อนเริ่ม"
            return summary
        flow = TagFlow(self.driver, self.config.options, self.config.process_colors)
        if not self._at_home(flow, after_print=False):
            summary.stopped_reason = "จอเขียวไม่ได้อยู่หน้า DEP012G1"
            return summary

        for req in queue:
            if should_stop():
                summary.stopped_reason = "หยุดตามที่สั่ง"
                break
            req = self.store.get(req.id)
            if req.status != Status.PENDING:
                continue
            self.store.set_status(req.id, Status.RUNNING)

            def checkpoint(name, info, request_id=req.id):
                status = Status.SPLIT_SENT if name == "split_sent" else Status.SPLIT_DONE
                self.store.set_status(request_id, status, **info)

            try:
                result = flow.run(self._job(req, color), checkpoint=checkpoint, ask=self.ask)
            except FlowError as error:
                if error.screen is not None and self.dump_dir:
                    write_dump(error.screen, self.dump_dir, f"รายการ {req.id}: {error}")
                if error.after_split:
                    self.store.set_status(req.id, Status.ATTENTION, str(error))
                    summary.attention += 1
                    summary.stopped_reason = f"รายการ {req.id} ต้องตรวจบนจอเขียว: {error}"
                    break
                self.store.set_status(req.id, Status.FAILED, str(error))
                summary.failed += 1
                if not flow.recover_to_home():
                    summary.stopped_reason = "กลับหน้า DEP012G1 ไม่ได้"
                    break
                continue
            except Exception as error:  # การเชื่อมต่อขาด หรือเหตุไม่คาดคิด: ตัดสินจากว่ากด F5 ไปแล้วหรือยัง
                log.exception("request %s stopped unexpectedly", req.id)
                if self.store.get(req.id).status in (Status.SPLIT_SENT, Status.SPLIT_DONE):
                    self.store.set_status(req.id, Status.ATTENTION, f"หยุดกะทันหันหลังกด F5 ตรวจบนจอเขียว: {error}")
                    summary.attention += 1
                else:
                    self.store.set_status(req.id, Status.FAILED, f"หยุดกะทันหันก่อนกด F5 ลองใหม่ได้: {error}")
                    summary.failed += 1
                summary.stopped_reason = f"รายการ {req.id} หยุดเพราะ: {error}"
                break

            self.store.set_status(req.id, Status.DONE, mo_no=result.mo_no, lot_qty=result.lot_qty)
            summary.done += 1
            if result.paper_changed_to:
                self.store.set_wo_color(req.work_order, result.paper_changed_to)
                if not self.ask("paper", f"เปลี่ยนกระดาษกลับเป็นสี{color}", None):
                    summary.stopped_reason = "หยุดหลังเปลี่ยนสีกระดาษ"
                    break
            if not self._at_home(flow, after_print=True):
                summary.stopped_reason = "จอเขียวไม่ได้กลับมาหน้า DEP012G1"
                break
        return summary
