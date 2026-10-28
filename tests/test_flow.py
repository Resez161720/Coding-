from datetime import datetime

import pytest
from helpers import Clerk

from tagbot.config import Options
from tagbot.driver.fake import FakeGreenScreen, WorkOrder
from tagbot.flow import FlowError, TagFlow, TagJob, screen_id

NOW = datetime(2026, 10, 27, 16, 3)


def green(**options):
    work_orders = [WorkOrder("OCT26AA", "DEMO-ITEM-1", "DEMO STACK", 63, 1000, "0010", "STAMPING 1")]
    return FakeGreenScreen(work_orders, now=lambda: NOW, **options)


def job(**changes):
    values = dict(work_order="OCT26AA", mat_do="OP26ZZ000001", mat_coil="OF26ZZ10000001", die="DIE.4",
                  emp="T0001", machine="A2", cart="M04", full=True, qty=None, ng=0,
                  shift="B", speed="350", action="X04", color="ชมพู")
    values.update(changes)
    return TagJob(**values)


def run(fake, tag_job, options=None, process_colors=None, clerk=None):
    checkpoints = []
    flow = TagFlow(fake, options or Options(confirm_before_final_enter=False), process_colors or {})
    result = flow.run(tag_job, checkpoint=lambda name, info: checkpoints.append((name, info)), ask=clerk or Clerk())
    return result, checkpoints


def test_full_basket_goes_through_five_screens_and_prints_one_tag():
    fake = green()
    result, checkpoints = run(fake, job())
    [tag] = fake.printed
    printed = {key: tag[key] for key in ("mo_no", "shift", "emp", "mc", "cart", "in_qty", "good", "ng",
                                          "die", "remark1", "remark3", "speed", "action", "tag_no", "press_mat")}
    assert printed == {
        "mo_no": "OCT26AA27AA", "shift": "B", "emp": "T0001", "mc": "A2", "cart": "M04", "in_qty": "63",
        "good": "63", "ng": "0", "die": "DIE.4", "remark1": "OP26ZZ000001", "remark3": "OF26ZZ10000001",
        "speed": "350", "action": "X04", "tag_no": "", "press_mat": "",
    }
    assert result.mo_no == "OCT26AA27AA"
    assert screen_id(fake.snapshot()) == "G1"


def test_values_read_from_the_screen_are_reported_at_each_checkpoint():
    _, checkpoints = run(green(), job())
    assert checkpoints == [
        ("split_sent", {"item_no": "DEMO-ITEM-1", "item_name": "DEMO STACK", "lot_size": 63, "lot_qty": 63}),
        ("split_done", {"mo_no": "OCT26AA27AA"}),
    ]


def test_partial_basket_with_ng_splits_good_plus_ng():
    fake = green()
    run(fake, job(full=False, qty=40, ng=2))
    tag = fake.printed[0]
    assert (tag["in_qty"], tag["good"], tag["ng"]) == ("42", "40", "2")


def test_split_quantity_leaves_out_ng_when_configured():
    fake = green()
    run(fake, job(full=False, qty=40, ng=2),
        options=Options(confirm_before_final_enter=False, lot_qty_includes_ng=False))
    assert fake.printed[0]["in_qty"] == "40"


def test_machine_without_action_code_leaves_action_empty():
    fake = green()
    run(fake, job(action=""))
    assert fake.printed[0]["action"] == ""


def test_unknown_work_order_fails_before_any_lot_is_created():
    fake = green()
    with pytest.raises(FlowError) as error:
        run(fake, job(work_order="OCT26ZZ"))
    assert error.value.after_split is False
    assert fake.splits == {}


def test_basket_bigger_than_lot_size_is_refused_before_split_and_can_return_home():
    fake = green()
    flow = TagFlow(fake, Options(confirm_before_final_enter=False), {})
    with pytest.raises(FlowError) as error:
        flow.run(job(full=False, qty=70), checkpoint=lambda *args: None, ask=Clerk())
    assert error.value.after_split is False
    assert fake.splits == {}
    assert flow.recover_to_home() is True
    assert screen_id(fake.snapshot()) == "G1"


def test_f5_that_does_not_reach_result_entry_needs_attention():
    fake = green()
    fake.frozen.add(("G4", "pf5"))
    with pytest.raises(FlowError) as error:
        run(fake, job())
    assert error.value.after_split is True


def test_confirm_screen_showing_a_different_value_stops_before_printing():
    fake = green()
    fake.confirm_overrides["good"] = "630000000"
    with pytest.raises(FlowError) as error:
        run(fake, job())
    assert error.value.after_split is True
    assert "Good" in str(error.value)
    assert fake.printed == []


def test_clerk_confirms_each_tag_when_option_is_on():
    fake, clerk = green(), Clerk()
    run(fake, job(), options=Options(confirm_before_final_enter=True), clerk=clerk)
    assert clerk.asked == ["final"]
    assert len(fake.printed) == 1


def test_clerk_declining_confirmation_leaves_tag_unprinted():
    fake, clerk = green(), Clerk({"final": False})
    with pytest.raises(FlowError) as error:
        run(fake, job(), options=Options(confirm_before_final_enter=True), clerk=clerk)
    assert error.value.after_split is True
    assert fake.printed == []


def test_field_that_locks_the_keyboard_is_reported_and_unlocked():
    fake = green()
    with pytest.raises(FlowError) as error:
        run(fake, job(speed="3X5"))
    assert error.value.after_split is True
    assert "M/C Speed" in str(error.value)
    assert fake.snapshot().input_inhibited is False


def test_flow_refuses_to_start_when_not_on_the_first_screen():
    fake = green(return_screen="MENU")
    run(fake, job())
    with pytest.raises(FlowError) as error:
        run(fake, job())
    assert error.value.after_split is False
    assert len(fake.printed) == 1


def test_process_needing_other_paper_asks_clerk_to_swap_paper():
    fake, clerk = green(), Clerk()
    result, _ = run(fake, job(color="ชมพู"), process_colors={"0010": "เขียว"}, clerk=clerk)
    assert clerk.asked == ["color"]
    assert result.paper_changed_to == "เขียว"
    assert len(fake.printed) == 1


def test_clerk_refusing_paper_swap_stops_without_printing():
    fake, clerk = green(), Clerk({"color": False})
    with pytest.raises(FlowError) as error:
        run(fake, job(color="ชมพู"), process_colors={"0010": "เขียว"}, clerk=clerk)
    assert error.value.after_split is True
    assert fake.printed == []


def test_value_longer_than_its_field_is_never_typed():
    fake = green()
    with pytest.raises(FlowError) as error:
        run(fake, job(cart="M0123456789"))
    assert "Cart" in str(error.value)
    assert fake.printed == []


def test_split_bigger_than_what_is_left_on_the_work_order_is_refused():
    work_orders = [WorkOrder("OCT26AA", "DEMO-ITEM-1", "DEMO STACK", 63, 50, "0010", "STAMPING 1")]
    fake = FakeGreenScreen(work_orders, now=lambda: NOW)
    with pytest.raises(FlowError) as error:
        run(fake, job())
    assert error.value.after_split is False
    assert fake.splits == {}
