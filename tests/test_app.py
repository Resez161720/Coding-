import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from tagbot.app import App
from tagbot.config import Config, Options
from tagbot.driver.fake import FakeGreenScreen, WorkOrder
from tagbot.store import Status

NOW = datetime(2026, 10, 27, 16, 3)
JOB = "\n".join(["MC-A2", "OCT26AA", "OP26ZZ000001", "OF26ZZ10000001", "DIE.4", "EMP-T0001"])


def write_master(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "machines.csv").write_text(
        "machine,name,color,multi_type,speed,action,route\n"
        "A2,Press 2,ชมพู,N,350,X04,1\n"
        "C4,Press 4,ชมพู,Y,280,,2\n"
        "W1,Weld 1,เขียว,N,120,,3\n", encoding="utf-8-sig")


@pytest.fixture
def app(tmp_path):
    write_master(tmp_path / "data")
    fakes = []

    def driver_factory():
        fakes.append(FakeGreenScreen([WorkOrder("OCT26AA", "DEMO-1", "DEMO ONE", 63, 1000, "0010", "STAMPING 1")],
                                     now=lambda: NOW))
        return fakes[-1]

    config = Config(data_dir=tmp_path / "data", options=Options(confirm_before_final_enter=False))
    application = App(config, driver_factory, now=lambda: NOW, dump_dir=tmp_path / "dumps")
    application.fakes = fakes
    yield application
    application.shutdown()


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("รอแล้วไม่เกิดขึ้น")


def test_import_creates_pending_requests_and_reports_problems(app):
    result = app.import_scans(JOB + "\nW26ZZ0000001\nCT-M04\nCMD-FULL")
    assert result["added"] == 1
    assert [(p["line"], p["kind"]) for p in result["problems"]] == [(7, "unknown")]
    [req] = app.state()["requests"]
    assert (req["machine"], req["cart"], req["status"]) == ("A2", "M04", Status.PENDING)


def test_importing_the_same_text_twice_is_reported_as_duplicate(app):
    app.import_scans(JOB + "\nCT-M04\nCMD-FULL")
    again = app.import_scans(JOB + "\nCT-M04\nCMD-FULL")
    assert again["duplicate"] is True
    assert again["added"] == 0
    assert len(app.state()["requests"]) == 1


def test_state_counts_ready_tags_per_color_and_shows_issues(app):
    app.import_scans(JOB + "\nCT-M04\nCMD-FULL\nMC-W1\nCT-M05\nCMD-FULL")
    state = app.state()
    assert state["groups"] == [{"color": "ชมพู", "ready": 1}, {"color": "เขียว", "ready": 0}]
    incomplete = [r for r in state["requests"] if r["machine"] == "W1"][0]
    assert {issue["field"] for issue in incomplete["issues"]} >= {"work_order", "mat_coil", "emp"}


def test_choosing_a_color_for_a_multi_type_machine_makes_its_tags_ready(app):
    app.import_scans(JOB.replace("MC-A2", "MC-C4") + "\nCT-M04\nCMD-FULL")
    assert app.state()["needs_color"] == [{"work_order": "OCT26AA", "count": 1}]
    app.set_wo_color("OCT26AA", "เขียว")
    state = app.state()
    assert state["needs_color"] == []
    assert state["groups"][1] == {"color": "เขียว", "ready": 1}


def test_edit_fixes_a_missing_cart_and_blank_quantity_means_full_basket(app):
    app.import_scans(JOB + "\nNUM-5\nCMD-END")
    [req] = app.state()["requests"]
    app.edit(req["id"], {"cart": "m04", "qty": ""})
    [req] = app.state()["requests"]
    assert (req["cart"], req["full"], req["qty"], req["issues"]) == ("M04", True, None, [])


def test_edit_rejects_quantity_that_is_not_a_number(app):
    app.import_scans(JOB + "\nCT-M04\nCMD-FULL")
    [req] = app.state()["requests"]
    with pytest.raises(ValueError):
        app.edit(req["id"], {"qty": "4O"})


def test_run_prints_after_the_clerk_confirms_the_paper(app):
    app.import_scans(JOB + "\nCT-M04\nCMD-FULL")
    assert app.start_run("ชมพู")[0] is True
    question = wait_for(lambda: app.state()["question"])
    assert question["kind"] == "paper"
    app.answer(question["id"], True)
    wait_for(lambda: app.state()["worker"]["state"] == "idle" and app.state()["requests"][0]["status"] == Status.DONE)
    assert app.state()["requests"][0]["mo_no"] == "OCT26AA27AA"
    assert len(app.fakes[0].printed) == 1


def test_stop_while_waiting_for_an_answer_cancels_the_run(app):
    app.import_scans(JOB + "\nCT-M04\nCMD-FULL")
    app.start_run("ชมพู")
    wait_for(lambda: app.state()["question"])
    app.stop()
    wait_for(lambda: app.state()["worker"]["state"] == "idle")
    assert app.state()["requests"][0]["status"] == Status.PENDING


def test_screen_dump_is_written_to_a_file(app):
    path = app.dump_screen()
    assert "DEP012G1" in path.read_text(encoding="utf-8")


def test_cards_page_has_a_barcode_for_each_machine(app):
    html = app.cards_html()
    assert html.count("<svg") >= 3 + 14
    for code in ("MC-A2", "MC-C4", "MC-W1", "CMD-FULL", "NUM-0"):
        assert code in html


def test_broken_master_data_blocks_printing_with_a_message(tmp_path):
    (tmp_path / "data").mkdir()
    config = Config(data_dir=tmp_path / "data")
    application = App(config, lambda: None, now=lambda: NOW)
    try:
        assert "machines.csv" in application.state()["master_error"]
        ok, message = application.start_run("ชมพู")
        assert ok is False and "machines.csv" in message
    finally:
        application.shutdown()


def test_http_server_serves_page_and_json_api(app):
    from tagbot.web import make_server

    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "ระบบช่วยพิมพ์ Tag" in page
        body = json.dumps({"text": JOB + "\nCT-M04\nCMD-FULL"}).encode("utf-8")
        request = urllib.request.Request(base + "/api/import", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Tagbot": "1"})
        assert json.loads(urllib.request.urlopen(request).read())["added"] == 1
        state = json.loads(urllib.request.urlopen(base + "/api/state").read())
        assert state["requests"][0]["work_order"] == "OCT26AA"
    finally:
        server.shutdown()


def test_post_without_the_app_header_is_refused(app):
    from tagbot.web import make_server

    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/run", method="POST",
                                         data=json.dumps({"color": "ชมพู"}).encode("utf-8"))
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
        assert app.state()["worker"]["state"] == "idle"
    finally:
        server.shutdown()
