from tagbot.config import BarcodePatterns
from tagbot.scan_parser import parse_scans

PATTERNS = BarcodePatterns()
JOB = ["MC-A2", "OCT26XY", "OP26ZZ000001", "OF26ZZ10000001", "DIE.4", "EMP-T0001"]


def test_full_basket_sequence_builds_one_request():
    result = parse_scans(JOB + ["CT-M04", "CMD-FULL"], PATTERNS)
    assert result.problems == []
    [req] = result.requests
    assert (req.machine, req.work_order, req.mat_do, req.mat_coil, req.die, req.emp, req.cart) == (
        "A2", "OCT26XY", "OP26ZZ000001", "OF26ZZ10000001", "DIE.4", "T0001", "M04")
    assert req.full is True
    assert req.qty is None
    assert req.ng == 0


def test_next_basket_of_same_job_reuses_scanned_documents():
    result = parse_scans(JOB + ["CT-M04", "CMD-FULL", "CT-M05", "CMD-FULL"], PATTERNS)
    first, second = result.requests
    assert first.cart == "M04"
    assert second.cart == "M05"
    assert second.work_order == "OCT26XY"
    assert second.mat_coil == "OF26ZZ10000001"


def test_partial_basket_quantity_comes_from_digit_cards():
    result = parse_scans(JOB + ["CT-M04", "NUM-1", "NUM-5", "NUM-0", "CMD-END"], PATTERNS)
    [req] = result.requests
    assert req.full is False
    assert req.qty == 150


def test_ng_count_applies_to_the_last_basket():
    result = parse_scans(JOB + ["CT-M04", "CMD-FULL", "CMD-NG", "NUM-3", "CMD-END"], PATTERNS)
    [req] = result.requests
    assert req.full is True
    assert req.ng == 3


def test_scanning_a_new_machine_clears_documents_of_previous_machine():
    result = parse_scans(JOB + ["CT-M04", "CMD-FULL", "MC-C4", "CT-M07", "CMD-FULL"], PATTERNS)
    second = result.requests[1]
    assert second.machine == "C4"
    assert second.cart == "M07"
    assert (second.work_order, second.mat_do, second.mat_coil, second.die, second.emp) == ("", "", "", "", "")


def test_undo_removes_the_last_basket():
    result = parse_scans(JOB + ["CT-M04", "CMD-FULL", "CT-M05", "CMD-FULL", "CMD-UNDO"], PATTERNS)
    assert [r.cart for r in result.requests] == ["M04"]


def test_undo_while_typing_digits_clears_only_the_number():
    result = parse_scans(JOB + ["CT-M04", "NUM-1", "NUM-2", "CMD-UNDO", "NUM-6", "CMD-END"], PATTERNS)
    [req] = result.requests
    assert req.qty == 6


def test_unknown_barcode_is_reported_with_its_line_number():
    result = parse_scans(["MC-A2", "W26ZZ0000001"], PATTERNS)
    [problem] = result.problems
    assert (problem.line, problem.raw, problem.kind) == (2, "W26ZZ0000001", "unknown")


def test_number_without_end_card_is_reported():
    result = parse_scans(JOB + ["CT-M04", "NUM-5"], PATTERNS)
    assert result.requests == []
    assert [p.kind for p in result.problems] == ["unfinished_number"]


def test_ng_before_any_basket_is_reported():
    result = parse_scans(["MC-A2", "CMD-NG", "NUM-1", "CMD-END"], PATTERNS)
    assert result.requests == []
    assert [p.kind for p in result.problems] == ["ng_without_basket"]


def test_scans_typed_with_thai_keyboard_layout_are_understood():
    # "MC-A2" typed while the Windows keyboard was Thai
    result = parse_scans(["?ฉขฤ/", "CT-M04", "CMD-FULL"], PATTERNS)
    assert result.requests[0].machine == "A2"


def test_code39_asterisks_spaces_and_lowercase_are_normalised():
    result = parse_scans(["mc-a2", " *OCT26XY* ", "CT-M04", "CMD-FULL"], PATTERNS)
    req = result.requests[0]
    assert (req.machine, req.work_order) == ("A2", "OCT26XY")


def test_blank_lines_are_ignored():
    result = parse_scans(["", "MC-A2", "   ", "CT-M04", "CMD-FULL"], PATTERNS)
    assert result.problems == []
    assert len(result.requests) == 1


def test_end_card_without_digits_is_reported():
    result = parse_scans(JOB + ["CT-M04", "CMD-END"], PATTERNS)
    assert result.requests == []
    assert [p.kind for p in result.problems] == ["empty_number"]


def test_undo_with_nothing_to_undo_is_reported():
    result = parse_scans(["MC-A2", "CMD-UNDO"], PATTERNS)
    assert [p.kind for p in result.problems] == ["nothing_to_undo"]


def test_full_card_after_unfinished_digits_reports_the_dropped_number():
    result = parse_scans(JOB + ["CT-M04", "NUM-4", "CMD-FULL"], PATTERNS)
    [req] = result.requests
    assert req.full is True
    assert [(p.kind, p.line) for p in result.problems] == [("unfinished_number", 8)]
