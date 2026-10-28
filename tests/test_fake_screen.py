from datetime import datetime

from tagbot.driver.fake import FakeGreenScreen, WorkOrder

WO = WorkOrder("OCT26AA", "DEMO-ITEM-1", "DEMO STACK", 63, 1000, "0010", "STAMPING 1")
NOW = datetime(2026, 10, 27, 16, 3, 0)


def fake():
    return FakeGreenScreen([WO], now=lambda: NOW)


def fill(screen_fake, label, text):
    field = screen_fake.snapshot().input_after(label)
    screen_fake.fill(field, text)


def test_unknown_work_order_leaves_first_screen_without_message():
    green = fake()
    fill(green, r"MFG ORDER NO\.", "OCT26ZZ")
    green.press("enter")
    assert green.snapshot().contains("DEP012G1")


def test_f5_creates_a_new_lot_and_opens_result_entry():
    green = fake()
    fill(green, r"MFG ORDER NO\.", "OCT26AA")
    green.press("enter")
    fill(green, r"LOT M/O QTY\.", "63")
    green.press("enter")
    assert green.snapshot().contains("DEP012G4")
    green.press("pf5")
    screen = green.snapshot()
    assert screen.contains("DTNOG1L2")
    assert screen.value_after(r"M/O\s*No\.?") == "OCT26AA27AA"


def test_letters_in_a_numeric_field_lock_the_keyboard_until_reset():
    green = fake()
    fill(green, r"MFG ORDER NO\.", "OCT26AA")
    green.press("enter")
    fill(green, r"LOT M/O QTY\.", "6X")
    assert green.snapshot().input_inhibited
    green.press("enter")
    assert green.snapshot().contains("DEP012G3")
    green.press("reset")
    assert not green.snapshot().input_inhibited


def test_enter_on_confirm_screen_prints_a_tag_and_returns_to_first_screen():
    green = fake()
    fill(green, r"MFG ORDER NO\.", "OCT26AA")
    green.press("enter")
    green.press("enter")
    green.press("pf5")
    fill(green, r"Emp\s*No\.?", "T0001")
    fill(green, r"Good\s*Qty\.?", "63")
    green.press("enter")
    assert green.snapshot().contains("DTNOG1L4")
    green.press("enter")
    assert green.snapshot().contains("DEP012G1")
    [tag] = green.printed
    assert (tag["mo_no"], tag["emp"], tag["good"]) == ("OCT26AA27AA", "T0001", "63")
