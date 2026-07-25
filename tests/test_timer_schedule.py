"""Tests for finite timer-v2 schedule calculation."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
SCHEDULE_PATH = PLUGIN_DIR / "timer/schedule.py"
MODULE_NAME = "hatsume.plugins.hatsume-plugin.timer.schedule"
SHANGHAI = timezone(timedelta(hours=8))


def _load_schedule_module():
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
        ("hatsume.plugins.hatsume-plugin.timer", PLUGIN_DIR / "timer"),
    ):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package

    config_name = "hatsume.plugins.hatsume-plugin.config"
    config = types.ModuleType(config_name)
    config.TIMER_MAX_FREQUENCY_POINTS = 5
    config.TIMER_MAX_EXACT_POINTS = 10
    sys.modules[config_name] = config

    sys.modules.pop(MODULE_NAME, None)
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCHEDULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def schedule():
    return _load_schedule_module()


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _iso_at(day: int, hour: int = 9) -> str:
    return f"2026-08-{day:02d}T{hour:02d}:00:00+08:00"


def test_daily_step_and_inclusive_bounds(schedule):
    plan = schedule.build_daily_plan(
        "2026-07-25T10:00:00+08:00",
        "2026-07-29T18:00:00+08:00",
        ["09:00:00", "18:00:00"],
        step=2,
        now=_timestamp("2026-07-25T09:00:00+08:00"),
    )

    assert schedule.flatten_occurrences(plan) == [
        _timestamp("2026-07-25T18:00:00+08:00"),
        _timestamp("2026-07-27T09:00:00+08:00"),
        _timestamp("2026-07-27T18:00:00+08:00"),
        _timestamp("2026-07-29T09:00:00+08:00"),
        _timestamp("2026-07-29T18:00:00+08:00"),
    ]
    assert plan.mode == "daily"
    assert plan.step == 2


def test_weekly_range_ending_before_now_reports_no_future_trigger(schedule):
    with pytest.raises(
        schedule.ScheduleValidationError,
        match="范围内没有未来触发时间",
    ):
        schedule.build_weekly_plan(
            "2026-07-01T00:00:00+08:00",
            "2026-07-31T23:59:59+08:00",
            [{"weekday": 1, "time": "09:00:00"}],
            now=_timestamp("2026-08-15T00:00:00+08:00"),
        )


@pytest.mark.parametrize(
    "clock",
    ["9:00:00", "09:00", "09:00:00.000", "24:00:00", "not-a-time"],
)
def test_clock_requires_exact_hh_mm_ss(schedule, clock):
    with pytest.raises(schedule.ScheduleValidationError, match="HH:MM:SS|无效"):
        schedule.build_daily_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
            [clock],
            step=1,
            now=0,
        )


def test_boundaries_require_timezone_and_valid_order(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="时区"):
        schedule.build_daily_plan(
            "2026-07-25T00:00:00",
            "2026-07-26T23:59:59+08:00",
            ["09:00:00"],
            step=1,
            now=0,
        )
    with pytest.raises(schedule.ScheduleValidationError, match="结束"):
        schedule.build_daily_plan(
            "2026-07-27T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
            ["09:00:00"],
            step=1,
            now=0,
        )


def test_frequency_raw_list_and_duplicates_are_rejected(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="最多 5"):
        schedule.build_daily_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
            [f"0{hour}:00:00" for hour in range(6)],
            step=1,
            now=0,
        )
    with pytest.raises(schedule.ScheduleValidationError, match="重复"):
        schedule.build_daily_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
            ["09:00:00", "09:00:00"],
            step=1,
            now=0,
        )


@pytest.mark.parametrize("step", [0, -1, 1.5, True])
def test_step_must_be_positive_integer(schedule, step):
    with pytest.raises(schedule.ScheduleValidationError, match="step"):
        schedule.build_daily_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
            ["09:00:00"],
            step=step,
            now=0,
        )


@pytest.mark.parametrize(
    ("builder_name", "time_points"),
    [
        ("build_daily_plan", ["09:00:00"]),
        ("build_weekly_plan", [{"weekday": 1, "time": "09:00:00"}]),
        ("build_monthly_plan", [{"day": 3, "time": "09:00:00"}]),
    ],
)
def test_frequency_plan_accepts_huge_step_without_date_overflow(
    schedule, builder_name, time_points
):
    builder = getattr(schedule, builder_name)

    plan = builder(
        "2026-08-03T00:00:00+08:00",
        "2026-08-03T23:59:59+08:00",
        time_points,
        10**9,
        now=0,
    )

    assert plan.total_occurrences == 1
    assert plan.step == 10**9


def test_weekly_step_is_anchored_to_start_week(schedule):
    plan = schedule.build_weekly_plan(
        "2026-07-29T00:00:00+08:00",  # Wednesday
        "2026-08-25T23:59:59+08:00",
        [
            {"weekday": 1, "time": "09:00:00"},
            {"weekday": 5, "time": "18:00:00"},
        ],
        step=2,
        now=0,
    )

    assert schedule.flatten_occurrences(plan) == [
        _timestamp("2026-07-31T18:00:00+08:00"),
        _timestamp("2026-08-10T09:00:00+08:00"),
        _timestamp("2026-08-14T18:00:00+08:00"),
        _timestamp("2026-08-24T09:00:00+08:00"),
    ]


def test_weekly_rejects_invalid_or_duplicate_complete_points(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="weekday"):
        schedule.build_weekly_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-08-25T00:00:00+08:00",
            [{"weekday": 0, "time": "09:00:00"}],
            step=1,
            now=0,
        )
    with pytest.raises(schedule.ScheduleValidationError, match="重复"):
        schedule.build_weekly_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-08-25T00:00:00+08:00",
            [
                {"weekday": 1, "time": "09:00:00"},
                {"weekday": 1, "time": "09:00:00"},
            ],
            step=1,
            now=0,
        )


def test_monthly_skips_nonexistent_day(schedule):
    plan = schedule.build_monthly_plan(
        "2026-01-01T00:00:00+08:00",
        "2026-04-30T23:59:59+08:00",
        [{"day": 31, "time": "08:00:00"}],
        step=1,
        now=0,
    )

    assert schedule.flatten_occurrences(plan) == [
        _timestamp("2026-01-31T08:00:00+08:00"),
        _timestamp("2026-03-31T08:00:00+08:00"),
    ]


def test_monthly_step_is_anchored_to_start_month(schedule):
    plan = schedule.build_monthly_plan(
        "2026-02-15T12:00:00+08:00",
        "2026-08-31T23:59:59+08:00",
        [{"day": 10, "time": "09:00:00"}, {"day": 20, "time": "18:00:00"}],
        step=2,
        now=0,
    )

    assert schedule.flatten_occurrences(plan) == [
        _timestamp("2026-02-20T18:00:00+08:00"),
        _timestamp("2026-04-10T09:00:00+08:00"),
        _timestamp("2026-04-20T18:00:00+08:00"),
        _timestamp("2026-06-10T09:00:00+08:00"),
        _timestamp("2026-06-20T18:00:00+08:00"),
        _timestamp("2026-08-10T09:00:00+08:00"),
        _timestamp("2026-08-20T18:00:00+08:00"),
    ]


def test_monthly_rejects_invalid_day(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="day"):
        schedule.build_monthly_plan(
            "2026-01-01T00:00:00+08:00",
            "2026-04-30T23:59:59+08:00",
            [{"day": 32, "time": "08:00:00"}],
            step=1,
            now=0,
        )


def test_exact_rejects_raw_list_longer_than_ten_and_duplicates(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="最多 10"):
        schedule.build_at_plan([_iso_at(day) for day in range(1, 12)], now=0)
    with pytest.raises(schedule.ScheduleValidationError, match="重复"):
        schedule.build_at_plan([_iso_at(1), _iso_at(1)], now=0)


def test_exact_rejects_naive_and_past_timestamps(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="时区"):
        schedule.build_at_plan(["2026-08-01T09:00:00"], now=0)
    with pytest.raises(schedule.ScheduleValidationError, match="未来"):
        schedule.build_at_plan(
            ["2026-08-01T09:00:00+08:00"],
            now=_timestamp("2026-08-01T09:00:00+08:00"),
        )


def test_exact_plan_sorts_points(schedule):
    plan = schedule.build_at_plan([_iso_at(2, 18), _iso_at(1, 9)], now=0)

    assert schedule.flatten_occurrences(plan) == [
        _timestamp(_iso_at(1, 9)),
        _timestamp(_iso_at(2, 18)),
    ]
    assert all(point.planned_count == 1 for point in plan.points)


def test_frequency_keeps_all_occurrences_beyond_fifty(schedule):
    plan = schedule.build_daily_plan(
        "2026-07-25T00:00:00+08:00",
        "2027-07-25T23:59:59+08:00",
        ["09:00:00", "18:00:00"],
        step=1,
        now=0,
    )

    occurrences = schedule.flatten_occurrences(plan)
    assert len(occurrences) == 732
    assert plan.total_occurrences == 732
    assert [point.planned_count for point in plan.points] == [366, 366]


def test_frequency_plan_does_not_materialize_task_wide_occurrences(schedule):
    plan = schedule.build_daily_plan(
        "2026-01-01T00:00:00+08:00",
        "2126-12-31T23:59:59+08:00",
        ["09:00:00"],
        step=1,
        now=0,
    )

    assert plan.total_occurrences == 36889
    assert not hasattr(plan, "occurrences")


def test_frequency_plan_keeps_requested_point_with_no_future_occurrence(schedule):
    plan = schedule.build_daily_plan(
        "2026-08-01T00:00:00+08:00",
        "2026-08-01T23:59:59+08:00",
        ["09:00:00", "18:00:00"],
        step=1,
        now=_timestamp("2026-08-01T12:00:00+08:00"),
    )

    assert [point.clock_time for point in plan.points] == ["09:00:00", "18:00:00"]
    assert [point.planned_count for point in plan.points] == [0, 1]
    assert plan.points[0].first_fire_at is None
    assert plan.points[0].last_fire_at is None


def test_frequency_rejects_range_with_no_future_occurrence(schedule):
    with pytest.raises(schedule.ScheduleValidationError, match="未来"):
        schedule.build_daily_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-07-25T23:59:59+08:00",
            ["09:00:00"],
            step=1,
            now=_timestamp("2026-07-26T00:00:00+08:00"),
        )
