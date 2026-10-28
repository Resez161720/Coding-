from datetime import datetime

from helpers import Clerk

from tagbot.config import Config, Options
from tagbot.driver.fake import FakeGreenScreen, WorkOrder
from tagbot.masterdata import Machine, MasterData
from tagbot.models import TagRequest
from tagbot.runner import Runner
from tagbot.store import Status, Store

NOW = datetime(2026, 10, 27, 16, 3)
MASTER = MasterData(
    machines={
        "A2": Machine("A2", "", "ชมพู", False, "350", "X04", 2),
        "A6": Machine("A6", "", "ชมพู", False, "300", "", 1),
        "W1": Machine("W1", "", "เขียว", False, "120", "", 3),
    },
    operators={},
    carts=set(),
)
WORK_ORDERS = [
    WorkOrder("OCT26AA", "DEMO-1", "DEMO ONE", 63, 1000, "0010", "STAMPING 1"),
    WorkOrder("OCT26BB", "DEMO-2", "DEMO TWO", 203, 5000, "0187", "STAMPING+L 100%"),
]


def request(machine, work_order="OCT26AA", **changes):
    values = dict(machine=machine, work_order=work_order, mat_do="OP26ZZ000001", mat_coil="OF26ZZ10000001",
                  die="DIE.4", emp="T0001", cart="M04", full=True)
    values.update(changes)
    return TagRequest(**values)


def setup(tmp_path, requests, options=None, process_colors=None, clerk=None, return_screen="G1"):
    store = Store(tmp_path / "tagbot.db")
    store.add_upload([f"line {i}" for i in range(len(requests))], requests)
    config = Config(options=options or Options(confirm_before_final_enter=False),
                    process_colors=process_colors or {})
    fake = FakeGreenScreen(WORK_ORDERS, now=lambda: NOW, return_screen=return_screen)
    clerk = clerk or Clerk()
    runner = Runner(store, fake, MASTER, config, ask=clerk, now=lambda: NOW, dump_dir=tmp_path / "dumps")
    return store, fake, clerk, runner


def statuses(store):
    return [r.status for r in store.requests()]


def test_runs_valid_pending_requests_of_one_color_in_route_order(tmp_path):
    store, fake, _, runner = setup(tmp_path, [
        request("A2"), request("W1"), request("A6"), request("A2", mat_coil=""),
    ])
    summary = runner.run_color("ชมพู")
    assert [tag["mc"] for tag in fake.printed] == ["A6", "A2"]
    assert statuses(store) == [Status.DONE, Status.PENDING, Status.DONE, Status.PENDING]
    assert summary.done == 2


def test_paper_question_comes_first_and_declining_prints_nothing(tmp_path):
    clerk = Clerk({"paper": False})
    store, fake, _, runner = setup(tmp_path, [request("A2")], clerk=clerk)
    runner.run_color("ชมพู")
    assert clerk.asked == ["paper"]
    assert fake.printed == []
    assert statuses(store) == [Status.PENDING]


def test_failure_before_split_is_marked_failed_and_batch_continues(tmp_path):
    store, fake, _, runner = setup(tmp_path, [request("A6", work_order="OCT26ZZ"), request("A2")])
    summary = runner.run_color("ชมพู")
    assert statuses(store) == [Status.FAILED, Status.DONE]
    assert store.requests()[0].error
    assert (summary.done, summary.failed) == (1, 1)


def test_failure_after_split_stops_the_whole_batch(tmp_path):
    store, fake, _, runner = setup(tmp_path, [request("A6"), request("A2")])
    fake.frozen.add(("G4", "pf5"))
    summary = runner.run_color("ชมพู")
    assert statuses(store) == [Status.ATTENTION, Status.PENDING]
    assert summary.stopped_reason


def test_attention_keeps_a_dump_of_the_green_screen(tmp_path):
    _, fake, _, runner = setup(tmp_path, [request("A6")])
    fake.frozen.add(("G4", "pf5"))
    runner.run_color("ชมพู")
    [dump] = (tmp_path / "dumps").iterdir()
    assert "DEP012G4" in dump.read_text(encoding="utf-8")


def test_stop_request_finishes_the_current_tag_then_stops(tmp_path):
    store, fake, _, runner = setup(tmp_path, [request("A6"), request("A2")])
    runner.run_color("ชมพู", should_stop=lambda: len(fake.printed) >= 1)
    assert statuses(store) == [Status.DONE, Status.PENDING]


def test_shift_comes_from_the_clock_and_speed_and_action_from_machine_table(tmp_path):
    _, fake, _, runner = setup(tmp_path, [request("A2")])
    runner.run_color("ชมพู")
    tag = fake.printed[0]
    assert (tag["shift"], tag["speed"], tag["action"]) == ("B", "350", "X04")


def test_clerk_brings_screen_back_when_print_lands_elsewhere(tmp_path):
    clerk = Clerk()
    store, fake, _, runner = setup(tmp_path, [request("A6"), request("A2")], clerk=clerk, return_screen="MENU")
    clerk.actions["home"] = lambda: fake.press("pf1")
    runner.run_color("ชมพู")
    assert statuses(store) == [Status.DONE, Status.DONE]
    assert "home" in clerk.asked


def test_configured_home_keys_return_to_first_screen_without_asking(tmp_path):
    options = Options(confirm_before_final_enter=False, home_keys=["pf1"])
    store, fake, clerk, runner = setup(tmp_path, [request("A6"), request("A2")], options=options,
                                       return_screen="MENU")
    runner.run_color("ชมพู")
    assert statuses(store) == [Status.DONE, Status.DONE]
    assert "home" not in clerk.asked


def test_paper_swapped_for_a_process_is_swapped_back_and_remembered(tmp_path):
    store, fake, clerk, runner = setup(tmp_path, [request("A2", work_order="OCT26BB"), request("A6")],
                                       process_colors={"0187": "เขียว"})
    runner.run_color("ชมพู")
    assert clerk.asked == ["paper", "color", "paper"]
    assert store.wo_color("OCT26BB") == "เขียว"
    assert len(fake.printed) == 2


def test_remembered_work_order_color_moves_request_to_that_color(tmp_path):
    store, fake, _, runner = setup(tmp_path, [request("A6")])
    store.set_wo_color("OCT26AA", "เขียว")
    runner.run_color("ชมพู")
    assert fake.printed == []
    runner.run_color("เขียว")
    assert len(fake.printed) == 1


def test_lot_creation_is_saved_before_f5_is_pressed(tmp_path):
    # ถ้าโปรแกรมดับหลังกด F5 สถานะที่บันทึกไว้ต้องบอกว่า "อาจสร้าง lot แล้ว" ไม่ใช่ "ลองใหม่ได้"
    store, fake, _, runner = setup(tmp_path, [request("A6")])
    seen = []
    press = fake.press

    def watching_press(key):
        if key == "pf5":
            seen.append(store.requests()[0].status)
        press(key)

    fake.press = watching_press
    runner.run_color("ชมพู")
    assert seen == [Status.SPLIT_SENT]


class BrokenGreenScreen(FakeGreenScreen):
    """จอเขียวที่การเชื่อมต่อขาดตอนกดปุ่มที่หน้าที่กำหนด (เช่น ปิดหน้าต่างจอเขียวระหว่างทำงาน)"""

    def __init__(self, *args, break_on, **kwargs):
        super().__init__(*args, **kwargs)
        self.break_on = break_on

    def press(self, key):
        if (self.screen, key) == self.break_on:
            raise OSError("connection to session A lost")
        super().press(key)


def broken_setup(tmp_path, break_on):
    store, _, clerk, _ = setup(tmp_path, [request("A6"), request("A2")])
    fake = BrokenGreenScreen(WORK_ORDERS, now=lambda: NOW, break_on=break_on)
    config = Config(options=Options(confirm_before_final_enter=False))
    return store, Runner(store, fake, MASTER, config, ask=clerk, now=lambda: NOW)


def test_connection_lost_before_f5_marks_failed_and_stops(tmp_path):
    store, runner = broken_setup(tmp_path, ("G1", "enter"))
    summary = runner.run_color("ชมพู")
    assert statuses(store) == [Status.FAILED, Status.PENDING]
    assert "connection" in store.requests()[0].error
    assert summary.stopped_reason


def test_connection_lost_after_f5_marks_attention_and_stops(tmp_path):
    store, runner = broken_setup(tmp_path, ("L2", "enter"))
    summary = runner.run_color("ชมพู")
    assert statuses(store) == [Status.ATTENTION, Status.PENDING]
    assert summary.stopped_reason
