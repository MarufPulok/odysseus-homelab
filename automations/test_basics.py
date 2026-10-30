"""Run: python3 automations/test_basics.py  (no config or network needed)"""
import datetime as dt

from slack_todos import off_hours

TZ = dt.timezone(dt.timedelta(hours=6))
SHIFT = {"work_start": 13, "work_end": 2, "off_days": ["Sat", "Sun"]}  # 13:00 → 02:00, past midnight
DAY = {"work_start": 9, "work_end": 18, "off_days": ["Sat", "Sun"]}   # ordinary 9 → 18


def at(day, hour):  # 2026-10-26 is a Monday
    return dt.datetime(2026, 10, 26 + day, hour, 30, tzinfo=TZ)


assert not off_hours(at(0, 14), SHIFT)  # Mon 14:30 in shift
assert not off_hours(at(1, 1), SHIFT)   # Tue 01:30 still Monday's shift
assert off_hours(at(1, 3), SHIFT)       # Tue 03:30 off
assert off_hours(at(0, 12), SHIFT)      # Mon 12:30 before shift
assert not off_hours(at(5, 1), SHIFT)   # Sat 01:30 belongs to Friday's shift
assert off_hours(at(5, 14), SHIFT)      # Sat afternoon off
assert not off_hours(at(0, 10), DAY)    # Mon 10:30 at work
assert off_hours(at(0, 18), DAY)        # Mon 18:30 off
assert off_hours(at(1, 8), DAY)         # Tue 08:30 off
assert off_hours(at(5, 10), DAY)        # Sat off
print("ok")
