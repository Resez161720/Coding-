from tagbot.config import BarcodePatterns
from tagbot.masterdata import Machine, MasterData
from tagbot.models import TagRequest
from tagbot.validation import resolve_color, validate

COLORS = ["ชมพู", "เขียว"]
MASTER = MasterData(
    machines={
        "A2": Machine("A2", "", "ชมพู", False, "350", "X04", 1),
        "C4": Machine("C4", "", "ชมพู", True, "280", "", 2),
        "Z9": Machine("Z9", "", "ม่วง", False, "100", "", 3),
    },
    operators={"T0001": "สมชาย"},
    carts={"M04"},
)


def good_request(**changes):
    values = dict(machine="A2", work_order="OCT26XY", mat_do="OP26ZZ000001", mat_coil="OF26ZZ10000001",
                  die="DIE.4", emp="T0001", cart="M04", full=True, qty=None, ng=0)
    values.update(changes)
    return TagRequest(**values)


def fields_with_issues(req, master=MASTER, wo_color=None):
    return [issue.field for issue in validate(req, master, BarcodePatterns(), COLORS, wo_color)]


def test_complete_request_has_no_issues():
    assert fields_with_issues(good_request()) == []


def test_each_missing_document_is_reported_on_its_own_field():
    req = good_request(work_order="", mat_do="", mat_coil="", die="", emp="", cart="")
    assert sorted(fields_with_issues(req)) == sorted(["work_order", "mat_do", "mat_coil", "die", "emp", "cart"])


def test_do_and_coil_swapped_by_hand_are_both_reported():
    req = good_request(mat_do="OF26ZZ10000001", mat_coil="OP26ZZ000001")
    assert sorted(fields_with_issues(req)) == ["mat_coil", "mat_do"]


def test_unknown_machine_is_reported():
    assert "machine" in fields_with_issues(good_request(machine="Q1"))


def test_operator_must_be_in_list_when_list_exists():
    assert fields_with_issues(good_request(emp="T9999")) == ["emp"]


def test_any_operator_and_cart_accepted_when_lists_are_empty():
    master = MasterData(machines=MASTER.machines, operators={}, carts=set())
    assert fields_with_issues(good_request(emp="T9999", cart="X99"), master) == []


def test_cart_must_be_in_list_when_list_exists():
    assert fields_with_issues(good_request(cart="M99")) == ["cart"]


def test_partial_quantity_must_be_positive():
    assert fields_with_issues(good_request(full=False, qty=0)) == ["qty"]


def test_die_with_wrong_format_is_reported():
    assert fields_with_issues(good_request(die="4")) == ["die"]


def test_machine_color_is_the_default_when_work_order_color_is_unknown():
    assert resolve_color(good_request(), MASTER, wo_color=None) == "ชมพู"


def test_color_remembered_for_the_work_order_wins_over_machine_default():
    assert resolve_color(good_request(), MASTER, wo_color="เขียว") == "เขียว"


def test_multi_type_machine_uses_color_remembered_for_the_work_order():
    assert resolve_color(good_request(machine="C4"), MASTER, wo_color="เขียว") == "เขียว"


def test_multi_type_machine_without_remembered_color_needs_a_choice():
    req = good_request(machine="C4")
    assert resolve_color(req, MASTER, wo_color=None) is None
    assert fields_with_issues(req) == ["color"]


def test_machine_color_missing_from_color_list_is_reported():
    assert fields_with_issues(good_request(machine="Z9")) == ["color"]


def test_machine_speed_that_is_not_a_number_is_reported_before_any_typing():
    machines = dict(MASTER.machines)
    machines["A2"] = Machine("A2", "", "ชมพู", False, "350 spm", "X04", 1)
    master = MasterData(machines=machines, operators=MASTER.operators, carts=MASTER.carts)
    assert fields_with_issues(good_request(), master) == ["machine"]
