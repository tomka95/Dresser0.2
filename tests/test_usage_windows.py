"""Pure user-local time-window helpers (SCRUM-44 quota boundaries).

These back the "month" (photo) and "day" (chat) boundaries a quota resets on. The rule:
user-local when facts.location.timezone is set, else UTC — the same rule the calendar
read path uses. Assertions here are wall-clock-independent (they check structure/typing/
ordering, not a specific date)."""
from datetime import datetime, timezone

from app.core.usage_windows import (
    day_reset_at,
    month_reset_at,
    month_start_local,
    today_local,
    tz_name_from_facts,
    tzinfo_for,
)


def test_tz_name_from_facts_variants():
    assert tz_name_from_facts({"location": {"timezone": "Europe/Paris"}}) == "Europe/Paris"
    assert tz_name_from_facts({"location": {"timezone": "  "}}) is None  # blank ignored
    assert tz_name_from_facts({"location": {}}) is None
    assert tz_name_from_facts({}) is None
    assert tz_name_from_facts(None) is None


def test_tzinfo_for_unknown_falls_back_to_utc():
    assert tzinfo_for(None) is timezone.utc
    assert tzinfo_for("Not/ARealZone") is timezone.utc  # unparseable -> UTC, never errors


def test_month_start_local_is_first_of_month():
    assert month_start_local(None).day == 1
    assert month_start_local("Asia/Tokyo").day == 1


def test_day_reset_at_is_future_aware_midnight():
    now = datetime.now(timezone.utc)
    reset = day_reset_at(None)
    assert reset.tzinfo is not None            # aware
    assert reset > now                          # in the future
    assert (reset.hour, reset.minute, reset.second) == (0, 0, 0)


def test_month_reset_at_is_first_of_next_month():
    reset = month_reset_at(None)
    assert reset.tzinfo is not None
    assert reset.day == 1
    assert reset > datetime.now(timezone.utc)
    # It is the month AFTER the current local month.
    this_month = month_start_local(None)
    assert (reset.year, reset.month) != (this_month.year, this_month.month)
