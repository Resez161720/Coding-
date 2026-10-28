from tagbot.screen import Field, Screen


def make_screen(rows, fields):
    padded = [row.ljust(80) for row in rows] + [" " * 80] * (24 - len(rows))
    return Screen(padded, fields)


ROWS = [
    "DTNOG1L2",
    " M/C No.    A2         Cart No. M04",
    " Good Qty.         60",
]
FIELDS = [
    Field(row=2, col=13, length=6, protected=False, numeric=False, text="A2"),
    Field(row=2, col=31, length=10, protected=False, numeric=False, text="M04"),
    Field(row=3, col=13, length=9, protected=False, numeric=True, text="       60"),
]


def test_input_after_label_is_the_nearest_open_field_on_the_same_row():
    screen = make_screen(ROWS, FIELDS)
    assert screen.input_after(r"M/C\s*No").col == 13
    assert screen.input_after(r"Cart\s*No").col == 31


def test_protected_field_is_never_returned_as_input():
    fields = [Field(row=2, col=13, length=6, protected=True, numeric=False, text="A2")] + FIELDS[1:]
    screen = make_screen(ROWS, fields)
    assert screen.input_after(r"M/C\s*No").col == 31


def test_input_after_missing_label_is_none():
    assert make_screen(ROWS, FIELDS).input_after(r"Die\s*No") is None


def test_value_after_label_skips_spaces_and_stops_at_next_label():
    screen = make_screen(ROWS, FIELDS)
    assert screen.value_after(r"Good\s*Qty") == "60"
    assert screen.value_after(r"M/C\s*No", until=r"Cart\s*No") == "A2"


def test_value_after_label_with_empty_value_does_not_return_next_label():
    screen = make_screen([" M/C No.               Cart No. M04"], [])
    assert screen.value_after(r"M/C\s*No", until=r"Cart\s*No") == ""


def test_contains_searches_whole_screen():
    screen = make_screen(ROWS, FIELDS)
    assert screen.contains("DTNOG1L2")
    assert not screen.contains("DTNOG1L4")


def test_text_after_label_keeps_the_whole_rest_of_the_row():
    screen = make_screen(["    ITEM NAME STACK ASSY REV.F       "], [])
    assert screen.text_after(r"ITEM NAME") == "STACK ASSY REV.F"
