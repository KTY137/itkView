"""Schedule evaluation for the unattended mirror refresh.

"How often and when" is institute-specific, so it lives in the institute
profile (hard rule 4) and is edited in Admin Settings. These tests pin the
decision logic itself — the part that is easy to get subtly wrong, above all a
window that crosses midnight, which is exactly what "sync overnight" means.
"""

from datetime import datetime, timedelta

import pytest

from app.auto_sync import (
    MIN_INTERVAL_MINUTES,
    AutoSyncSchedule,
    read_auto_sync_schedule,
)


def at(text: str) -> datetime:
    """A local wall-clock instant, written the way a person would read it."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


# -- reading the profile block ----------------------------------------------


def test_a_profile_without_the_block_never_syncs_unattended():
    schedule = read_auto_sync_schedule({})

    # The default has to be "off": a site that configured nothing must never
    # generate PDB traffic with nobody watching.
    assert schedule.enabled is False
    assert schedule.is_due(
        local_now=at("2026-08-27 12:00"),
        utc_now=at("2026-08-27 12:00"),
        last_success=None,
    ) is False


def test_an_explicitly_disabled_block_never_syncs():
    schedule = read_auto_sync_schedule(
        {"auto_sync": {"enabled": False, "interval_minutes": 60}}
    )

    assert schedule.enabled is False
    assert schedule.is_due(
        local_now=at("2026-08-27 12:00"),
        utc_now=at("2026-08-27 12:00"),
        last_success=None,
    ) is False


@pytest.mark.parametrize(
    "broken",
    [
        {"auto_sync": "yes"},
        {"auto_sync": {"enabled": "false", "interval_minutes": 60}},
        {"auto_sync": {"enabled": 1, "interval_minutes": 60}},
        {"auto_sync": {"enabled": True}},
        {"auto_sync": {"enabled": True, "interval_minutes": "often"}},
        {"auto_sync": {"enabled": True, "interval_minutes": MIN_INTERVAL_MINUTES - 1}},
        {"auto_sync": {"enabled": True, "interval_minutes": 10_081}},
        {"auto_sync": {"enabled": True, "interval_minutes": 60, "timezone": "UTC"}},
        {
            "auto_sync": {
                "enabled": True,
                "interval_minutes": 60,
                "window_start": "25:00",
                "window_end": "07:00",
            }
        },
        {
            "auto_sync": {
                "enabled": True,
                "interval_minutes": 60,
                "window_start": "7:00",
                "window_end": "19:00",
            }
        },
        {
            "auto_sync": {
                "enabled": True,
                "interval_minutes": 60,
                "window_start": "07:00",
            }
        },
        {
            "auto_sync": {
                "enabled": True,
                "interval_minutes": 60,
                "window_start": "07:00",
                "window_end": "07:00",
            }
        },
        {"auto_sync": {"enabled": True, "interval_minutes": 60, "weekdays": []}},
        {"auto_sync": {"enabled": True, "interval_minutes": 60, "weekdays": [1, 1]}},
        {"auto_sync": {"enabled": True, "interval_minutes": 60, "weekdays": [0, 9]}},
        {"auto_sync": {"enabled": True, "interval_minutes": 60, "weekdays": (1, 2)}},
    ],
)
def test_a_malformed_block_is_read_as_off_rather_than_guessed(broken):
    schedule = read_auto_sync_schedule(broken)

    # This reader is the last boundary before unattended PDB traffic. It must
    # accept exactly the API validator's shape, never repair broader input.
    assert schedule.enabled is False


def test_a_valid_schedule_is_normalised_without_broadening_it():
    schedule = read_auto_sync_schedule(
        {
            "auto_sync": {
                "enabled": True,
                "interval_minutes": MIN_INTERVAL_MINUTES,
                "window_start": " 07:00 ",
                "window_end": " 19:00 ",
                "weekdays": [5, 1, 3],
            }
        }
    )

    assert schedule == AutoSyncSchedule(
        enabled=True,
        interval_minutes=MIN_INTERVAL_MINUTES,
        window_start="07:00",
        window_end="19:00",
        weekdays=(1, 3, 5),
    )


def test_the_reader_agrees_with_the_shape_the_validator_actually_stores():
    """Lock the reader against the validator so the two cannot drift apart.

    `normalize_institute_settings_update` stores all five keys, always, with
    `window_start`/`window_end`/`weekdays` set to `null` when unrestricted —
    it never omits them. A reader that only handled *absent* keys would treat
    an explicit `null` as malformed and silently disable a schedule the screen
    shows as enabled.
    """
    stored = {
        "auto_sync": {
            "enabled": True,
            "interval_minutes": 60,
            "window_start": None,
            "window_end": None,
            "weekdays": None,
        }
    }

    schedule = read_auto_sync_schedule(stored)

    assert schedule.enabled is True
    assert schedule.interval_minutes == 60
    assert schedule.window_start is None and schedule.window_end is None
    assert schedule.weekdays == ()
    # Unrestricted really means unrestricted: any hour, any day.
    assert schedule.allows(at("2026-08-30 03:00")) is True  # a Sunday, at night


def test_the_reader_keeps_its_guards_even_though_the_validator_makes_them_unreachable():
    """Defence against a hand-edited database, not against the API.

    The validator rejects an interval below the floor, an empty weekday list
    and an identical window pair, so none of these can be written through the
    product. A profile edited directly in SQLite can still contain them, and
    then the reader is the only thing standing between a person and a
    schedule nobody chose.
    """
    # Every one of these reads as *off*. Rejecting rather than repairing is the
    # conservative direction: a hand-edited profile disables the schedule
    # instead of quietly running at a cadence or in a window nobody chose.
    for hand_edited in (
        {"enabled": True, "interval_minutes": 2},
        {"enabled": True, "interval_minutes": 60, "weekdays": []},
        {
            "enabled": True,
            "interval_minutes": 60,
            "window_start": "09:00",
            "window_end": "09:00",
        },
        {"enabled": True, "interval_minutes": 60, "window_start": "09:00"},
        {"enabled": True, "interval_minutes": 60, "smuggled": "field"},
    ):
        assert read_auto_sync_schedule({"auto_sync": hand_edited}).enabled is False, (
            hand_edited
        )

    # The dataclass itself stays permissive about equal bounds — only the
    # reader refuses them — so a caller constructing a schedule directly still
    # gets "no window" rather than one that never opens.
    assert (
        AutoSyncSchedule(
            enabled=True,
            interval_minutes=60,
            window_start="09:00",
            window_end="09:00",
        ).allows(at("2026-08-27 23:00"))
        is True
    )


# -- how often ---------------------------------------------------------------


def test_a_sweep_is_due_once_the_interval_has_elapsed():
    schedule = AutoSyncSchedule(enabled=True, interval_minutes=60)
    now = at("2026-08-27 12:00")

    assert schedule.is_due(
        local_now=now,
        utc_now=now,
        last_success=now - timedelta(minutes=61),
    ) is True
    assert schedule.is_due(
        local_now=now,
        utc_now=now,
        last_success=now - timedelta(minutes=59),
    ) is False


def test_an_institute_never_swept_is_due_immediately():
    schedule = AutoSyncSchedule(enabled=True, interval_minutes=60)

    assert schedule.is_due(
        local_now=at("2026-08-27 12:00"),
        utc_now=at("2026-08-27 12:00"),
        last_success=None,
    ) is True


def test_a_last_success_in_the_future_does_not_block_forever():
    schedule = AutoSyncSchedule(enabled=True, interval_minutes=60)
    now = at("2026-08-27 12:00")

    # A clock change must not park the schedule until the timestamp is passed.
    assert schedule.is_due(
        local_now=now,
        utc_now=now,
        last_success=now + timedelta(hours=5),
    ) is False


# -- when: the daily window --------------------------------------------------


def test_a_daytime_window_admits_only_daytime():
    schedule = AutoSyncSchedule(
        enabled=True, interval_minutes=60, window_start="07:00", window_end="19:00"
    )

    assert schedule.is_due(
        local_now=at("2026-08-27 12:00"),
        utc_now=at("2026-08-27 12:00"),
        last_success=None,
    ) is True
    assert schedule.is_due(
        local_now=at("2026-08-27 06:59"),
        utc_now=at("2026-08-27 06:59"),
        last_success=None,
    ) is False
    assert schedule.is_due(
        local_now=at("2026-08-27 19:01"),
        utc_now=at("2026-08-27 19:01"),
        last_success=None,
    ) is False


@pytest.mark.parametrize(
    "moment, expected",
    [
        ("2026-08-27 22:00", True),  # exactly at the start
        ("2026-08-27 23:30", True),  # before midnight
        ("2026-08-28 02:00", True),  # after midnight — the whole point
        ("2026-08-28 06:00", True),  # exactly at the end
        ("2026-08-28 06:01", False),
        ("2026-08-27 12:00", False),  # the middle of the working day
    ],
)
def test_a_window_across_midnight_is_a_night_shift_not_an_empty_set(moment, expected):
    # "Sync overnight, when nobody is working" is the most likely reason to set
    # a window at all. A naive start <= now <= end would make this never true.
    schedule = AutoSyncSchedule(
        enabled=True, interval_minutes=60, window_start="22:00", window_end="06:00"
    )

    assert schedule.is_due(local_now=at(moment), utc_now=at(moment), last_success=None) is expected


def test_a_window_with_equal_bounds_means_the_whole_day():
    schedule = AutoSyncSchedule(
        enabled=True, interval_minutes=60, window_start="00:00", window_end="00:00"
    )

    assert schedule.is_due(
        local_now=at("2026-08-27 03:00"),
        utc_now=at("2026-08-27 03:00"),
        last_success=None,
    ) is True
    assert schedule.is_due(
        local_now=at("2026-08-27 15:00"),
        utc_now=at("2026-08-27 15:00"),
        last_success=None,
    ) is True


# -- when: weekdays ----------------------------------------------------------


def test_weekdays_restrict_the_schedule_to_working_days():
    schedule = AutoSyncSchedule(
        enabled=True, interval_minutes=60, weekdays=(1, 2, 3, 4, 5)
    )

    # 2026-08-27 is a Thursday, 2026-08-29 a Saturday.
    assert at("2026-08-27 12:00").isoweekday() == 4
    assert schedule.is_due(
        local_now=at("2026-08-27 12:00"),
        utc_now=at("2026-08-27 12:00"),
        last_success=None,
    ) is True
    assert schedule.is_due(
        local_now=at("2026-08-29 12:00"),
        utc_now=at("2026-08-29 12:00"),
        last_success=None,
    ) is False


def test_no_weekday_restriction_means_every_day():
    schedule = AutoSyncSchedule(enabled=True, interval_minutes=60)

    assert schedule.is_due(
        local_now=at("2026-08-29 12:00"),
        utc_now=at("2026-08-29 12:00"),
        last_success=None,
    ) is True
    assert schedule.is_due(
        local_now=at("2026-08-30 12:00"),
        utc_now=at("2026-08-30 12:00"),
        last_success=None,
    ) is True


def test_the_weekday_is_the_one_the_window_started_on(tmp_path):
    """A night window belongs to the evening that opened it.

    Friday 22:00–06:00 must still be running at 02:00 on Saturday, or "weekend
    nights off" would silently also cancel half of Friday night.
    """
    schedule = AutoSyncSchedule(
        enabled=True,
        interval_minutes=60,
        window_start="22:00",
        window_end="06:00",
        weekdays=(1, 2, 3, 4, 5),
    )

    # Saturday 02:00 — the window that admits it opened on Friday evening.
    assert at("2026-08-29 02:00").isoweekday() == 6
    assert schedule.is_due(
        local_now=at("2026-08-29 02:00"),
        utc_now=at("2026-08-29 02:00"),
        last_success=None,
    ) is True
    # Sunday 02:00 belongs to Saturday evening, which is not a configured day.
    assert schedule.is_due(
        local_now=at("2026-08-30 02:00"),
        utc_now=at("2026-08-30 02:00"),
        last_success=None,
    ) is False


# -- the two clocks ----------------------------------------------------------


def test_the_window_reads_local_time_while_the_interval_reads_utc():
    """The one mistake that would look right in every test but be two hours off.

    "When" is a wall-clock answer a person gave in their own local time.
    "How often" is a duration against `finished_at`, which is stored in UTC.
    Judging both by one clock is wrong by the UTC offset — in Berlin summer
    that silently shifts an overnight window into the morning.
    """
    schedule = AutoSyncSchedule(
        enabled=True, interval_minutes=60, window_start="22:00", window_end="06:00"
    )
    # A site at UTC+2: local 23:00 is 21:00 UTC.
    local_now = at("2026-08-27 23:00")
    utc_now = at("2026-08-27 21:00")

    # Inside the window by local time, and swept 90 UTC-minutes ago.
    assert (
        schedule.is_due(
            local_now=local_now,
            utc_now=utc_now,
            last_success=utc_now - timedelta(minutes=90),
        )
        is True
    )
    # Had the interval been measured against the local clock, this 90-minute
    # gap would have read as 210 minutes and passed regardless — so pin the
    # opposite direction too: swept 30 UTC-minutes ago is NOT due.
    assert (
        schedule.is_due(
            local_now=local_now,
            utc_now=utc_now,
            last_success=utc_now - timedelta(minutes=30),
        )
        is False
    )
    # And the UTC clock must never be the one judging the window: 21:00 UTC
    # falls outside 22:00-06:00, yet the moment is legitimately inside it.
    assert schedule.allows(utc_now) is False
    assert schedule.allows(local_now) is True


# -- the combination ---------------------------------------------------------


def test_every_condition_must_hold_at_once():
    schedule = AutoSyncSchedule(
        enabled=True,
        interval_minutes=60,
        window_start="07:00",
        window_end="19:00",
        weekdays=(1, 2, 3, 4, 5),
    )
    thursday_noon = at("2026-08-27 12:00")

    assert schedule.is_due(
        local_now=thursday_noon,
        utc_now=thursday_noon,
        last_success=None,
    ) is True
    # Right day, right time, but swept ten minutes ago.
    assert (
        schedule.is_due(
            local_now=thursday_noon,
            utc_now=thursday_noon,
            last_success=thursday_noon - timedelta(minutes=10),
        )
        is False
    )
