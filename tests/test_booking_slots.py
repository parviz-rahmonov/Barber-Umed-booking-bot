from datetime import date, datetime, time, timezone, timedelta
import pytest
from services.booking import build_day_slots, _aware_utc


def test_hourly_slots_and_break():
    slots = build_day_slots(date(2026, 10, 26), [(time(9), time(13)), (time(14), time(18))], 'Asia/Dushanbe')
    assert len(slots) == 8
    assert [s.starts_at.hour for s in slots] == [4,5,6,7,9,10,11,12]
    assert all(s.ends_at - s.starts_at == timedelta(hours=1) for s in slots)


def test_partial_hour_opening_is_respected():
    slots = build_day_slots(date(2026, 10, 26), [(time(9,30), time(11))], 'Asia/Dushanbe')
    assert len(slots) == 1
    assert slots[0].starts_at.hour == 4 and slots[0].starts_at.minute == 30


def test_short_opening_produces_no_slots():
    assert build_day_slots(date(2026, 10, 26), [(time(9), time(9,45))], 'Asia/Dushanbe') == []


def test_naive_timestamps_forbidden():
    with pytest.raises(ValueError):
        _aware_utc(datetime(2026, 10, 26, 10))


def test_dst_ambiguous_hour_not_offered():
    slots = build_day_slots(date(2026, 11, 1), [(time(1), time(3))], 'America/New_York')
    assert all(s.starts_at.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).hour != 1 for s in slots)
