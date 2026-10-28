import pytest

from tagbot.models import TagRequest
from tagbot.store import DuplicateUpload, Status, Store, StoreError

LINES = ["MC-A2", "OCT26XY", "CT-M04", "CMD-FULL", "CT-M05", "NUM-4", "NUM-0", "CMD-END"]


def two_requests():
    return [
        TagRequest(machine="A2", work_order="OCT26XY", cart="M04", full=True),
        TagRequest(machine="A2", work_order="OCT26XY", cart="M05", full=False, qty=40, ng=2),
    ]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "tagbot.db")


def test_imported_requests_are_pending_in_scan_order(store):
    store.add_upload(LINES, two_requests())
    first, second = store.requests()
    assert (first.seq, first.cart, first.full, first.status) == (1, "M04", True, Status.PENDING)
    assert (second.seq, second.cart, second.full, second.qty, second.ng) == (2, "M05", False, 40, 2)


def test_importing_the_same_scan_data_twice_is_refused_unless_forced(store):
    store.add_upload(LINES, two_requests())
    with pytest.raises(DuplicateUpload):
        store.add_upload(["  MC-A2"] + LINES[1:] + [""], two_requests())
    store.add_upload(LINES, two_requests(), force=True)
    assert len(store.requests()) == 4


def test_editing_a_failed_request_puts_it_back_in_the_queue(store):
    store.add_upload(LINES, two_requests())
    req = store.requests()[0]
    store.set_status(req.id, Status.FAILED, error="ไม่พบใบสั่งงาน")
    store.update_fields(req.id, cart="M09")
    edited = store.get(req.id)
    assert (edited.cart, edited.status, edited.error) == ("M09", Status.PENDING, "")


def test_printed_request_cannot_be_edited(store):
    store.add_upload(LINES, two_requests())
    req = store.requests()[0]
    store.set_status(req.id, Status.DONE)
    with pytest.raises(StoreError):
        store.update_fields(req.id, cart="M09")


def test_unknown_field_cannot_be_edited(store):
    store.add_upload(LINES, two_requests())
    with pytest.raises(StoreError):
        store.update_fields(store.requests()[0].id, status="done")


def test_every_status_change_is_kept_as_history(store):
    store.add_upload(LINES, two_requests())
    req = store.requests()[0]
    for status in (Status.RUNNING, Status.SPLIT_SENT, Status.DONE):
        store.set_status(req.id, status)
    assert [event.status for event in store.events(req.id)] == [
        Status.PENDING, Status.RUNNING, Status.SPLIT_SENT, Status.DONE]


def test_values_read_from_the_green_screen_are_saved(store):
    store.add_upload(LINES, two_requests())
    req = store.requests()[0]
    store.set_status(req.id, Status.SPLIT_DONE, mo_no="OCT26XY27AF", item_no="ITEM-1", lot_size=63, lot_qty=63)
    saved = store.get(req.id)
    assert (saved.mo_no, saved.item_no, saved.lot_size, saved.lot_qty) == ("OCT26XY27AF", "ITEM-1", 63, 63)


def test_interrupted_run_is_recovered_by_whether_f5_was_pressed(store):
    store.add_upload(LINES + ["CT-M06", "CMD-FULL"], two_requests() + [TagRequest(machine="A2", cart="M06", full=True)])
    running, split_sent, split_done = store.requests()
    store.set_status(running.id, Status.RUNNING)
    store.set_status(split_sent.id, Status.SPLIT_SENT)
    store.set_status(split_done.id, Status.SPLIT_DONE)
    store.recover_interrupted()
    assert [store.get(r.id).status for r in (running, split_sent, split_done)] == [
        Status.FAILED, Status.ATTENTION, Status.ATTENTION]


def test_cancel_and_resolve_follow_the_allowed_moves(store):
    store.add_upload(LINES, two_requests())
    first, second = store.requests()
    store.set_status(first.id, Status.DONE)
    with pytest.raises(StoreError):
        store.cancel(first.id)
    store.set_status(second.id, Status.ATTENTION, error="ค้างที่หน้า L2")
    store.resolve_manually(second.id)
    assert store.get(second.id).status == Status.DONE


def test_color_chosen_for_a_work_order_is_remembered(store):
    assert store.wo_color("OCT26XY") is None
    store.set_wo_color("OCT26XY", "ชมพู")
    store.set_wo_color("OCT26XY", "เขียว")
    assert store.wo_color("OCT26XY") == "เขียว"


def test_queue_survives_closing_the_program(tmp_path):
    Store(tmp_path / "tagbot.db").add_upload(LINES, two_requests())
    assert len(Store(tmp_path / "tagbot.db").requests()) == 2


def test_retry_only_moves_failed_requests_back_to_pending(store):
    store.add_upload(LINES, two_requests())
    first, second = store.requests()
    store.set_status(first.id, Status.FAILED, error="หน้าจอไม่เปลี่ยน")
    store.retry(first.id)
    assert (store.get(first.id).status, store.get(first.id).error) == (Status.PENDING, "")
    store.set_status(second.id, Status.ATTENTION, error="ค้างที่หน้า L2")
    with pytest.raises(StoreError):
        store.retry(second.id)
