from datetime import time

import pytest

from tagbot.shifts import shift_for

SHIFTS = {"A": "08:00", "B": "16:00", "C": "00:00"}


@pytest.mark.parametrize("now, expected", [
    (time(11, 1), "A"),
    (time(8, 0), "A"),
    (time(16, 3), "B"),
    (time(23, 59), "B"),
    (time(0, 0), "C"),
    (time(7, 59), "C"),
])
def test_shift_is_the_latest_shift_that_has_started(now, expected):
    assert shift_for(now, SHIFTS) == expected


def test_shift_before_first_start_wraps_to_last_shift_of_previous_day():
    assert shift_for(time(5, 0), {"D": "07:00", "N": "19:00"}) == "N"
