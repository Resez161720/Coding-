import pytest

from tagbot.driver.pcomm import PcommDriver
from tagbot.screen import Field


class FakeHaclField:
    def __init__(self, row, col, length, protected, numeric, text):
        self.StartRow, self.StartCol, self.Length = row, col, length
        self.Protected, self.Numeric, self._text = protected, numeric, text

    def GetText(self):
        return self._text


class FakeHaclFieldList:
    def __init__(self, fields):
        self._fields = fields
        self.Count = len(fields)

    def Refresh(self, *flags):
        pass

    def Item(self, index):
        return self._fields[index - 1]


class FakeHaclPS:
    """เลียนแบบ PCOMM.autECLPS เท่าที่ driver ใช้"""

    NumRows, NumCols = 24, 80

    def __init__(self, text, fields):
        self._text = text
        self.autECLFieldList = FakeHaclFieldList(fields)
        self.CursorPosRow, self.CursorPosCol = 7, 45
        self.calls = []

    def GetText(self, row, col, length):
        start = (row - 1) * self.NumCols + (col - 1)
        return self._text[start:start + length]

    def SetCursorPos(self, row, col):
        self.calls.append(("SetCursorPos", row, col))

    def SendKeys(self, keys, *position):
        self.calls.append(("SendKeys", keys))


class FakeHaclOIA:
    def __init__(self, inhibited=0, ready=True):
        self.InputInhibited = inhibited
        self._ready = ready

    def WaitForInputReady(self, timeout_ms):
        return self._ready


def screen_text():
    rows = ["DEP012G1".ljust(80), ("  MFG ORDER NO.  " + "\x00" * 10).ljust(80)]
    return "".join(rows) + " " * 80 * 22


def test_snapshot_turns_presentation_space_into_rows_and_fields():
    ps = FakeHaclPS(screen_text(), [FakeHaclField(2, 18, 10, 0, 0, "\x00" * 10)])
    snap = PcommDriver(ps=ps, oia=FakeHaclOIA(inhibited=1)).snapshot()
    assert len(snap.rows) == 24
    assert snap.rows[0].startswith("DEP012G1")
    assert "\x00" not in snap.rows[1]
    assert snap.fields == [Field(row=2, col=18, length=10, protected=False, numeric=False, text=" " * 10)]
    assert snap.cursor == (7, 45)
    assert snap.input_inhibited is True


def test_short_number_is_typed_then_field_exit_right_adjusts_it():
    ps = FakeHaclPS(screen_text(), [])
    PcommDriver(ps=ps, oia=FakeHaclOIA()).fill(Field(14, 13, 9, False, True, ""), "60")
    assert ps.calls == [("SetCursorPos", 14, 13), ("SendKeys", "[eraseeof]"), ("SendKeys", "60"), ("SendKeys", "[fldext]")]


def test_value_that_fills_the_whole_field_gets_no_field_exit():
    # พิมพ์เต็มช่องแล้วเคอร์เซอร์ข้ามไปช่องถัดไปเอง Field Exit จะไปลบช่องถัดไป
    ps = FakeHaclPS(screen_text(), [])
    PcommDriver(ps=ps, oia=FakeHaclOIA()).fill(Field(5, 50, 1, False, True, ""), "7")
    assert ("SendKeys", "[fldext]") not in ps.calls


def test_text_field_is_erased_then_typed_without_field_exit():
    ps = FakeHaclPS(screen_text(), [])
    PcommDriver(ps=ps, oia=FakeHaclOIA()).fill(Field(19, 46, 20, False, False, ""), "OF26ZZ10000001")
    assert ps.calls == [("SetCursorPos", 19, 46), ("SendKeys", "[eraseeof]"), ("SendKeys", "OF26ZZ10000001")]


def test_square_bracket_is_escaped_so_pcomm_does_not_read_it_as_a_key():
    ps = FakeHaclPS(screen_text(), [])
    PcommDriver(ps=ps, oia=FakeHaclOIA()).fill(Field(1, 1, 10, False, False, ""), "A[1")
    assert ("SendKeys", "A[[1") in ps.calls


def test_function_keys_use_pcomm_mnemonics():
    ps = FakeHaclPS(screen_text(), [])
    driver = PcommDriver(ps=ps, oia=FakeHaclOIA())
    driver.press("pf5")
    driver.press("enter")
    assert ps.calls == [("SendKeys", "[pf5]"), ("SendKeys", "[enter]")]
    with pytest.raises(ValueError):
        driver.press("pf24")


def test_wait_ready_reports_timeout_when_keyboard_stays_locked():
    ps = FakeHaclPS(screen_text(), [])
    driver = PcommDriver(ps=ps, oia=FakeHaclOIA(inhibited=1, ready=False), sleep=lambda s: None)
    assert driver.wait_ready(0.5) is False


def test_wait_ready_succeeds_when_screen_is_stable_and_unlocked():
    ps = FakeHaclPS(screen_text(), [])
    driver = PcommDriver(ps=ps, oia=FakeHaclOIA(), sleep=lambda s: None)
    assert driver.wait_ready(2.0) is True
