from datetime import datetime


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def shift_for(now, shifts: dict) -> str:
    """ชื่อกะที่เริ่มล่าสุดก่อนเวลา now (ก่อนกะแรกของวัน = กะสุดท้ายของเมื่อวาน)"""
    if isinstance(now, datetime):
        now = now.time()
    current_minutes = now.hour * 60 + now.minute
    starts = sorted((_minutes(start), name) for name, start in shifts.items())
    current = starts[-1][1]
    for start, name in starts:
        if current_minutes >= start:
            current = name
    return current
