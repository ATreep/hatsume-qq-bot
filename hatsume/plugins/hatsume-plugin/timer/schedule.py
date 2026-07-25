"""Pure schedule calculation for timer-v2 tasks."""

from __future__ import annotations

import heapq
import math
import re
import time as time_module
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Iterator, Literal, Mapping, Sequence

from ..config import (
    TIMER_MAX_EXACT_POINTS,
    TIMER_MAX_FREQUENCY_POINTS,
)

SHANGHAI = timezone(timedelta(hours=8))
ScheduleMode = Literal["daily", "weekly", "monthly", "at"]


class ScheduleValidationError(ValueError):
    """Raised when a requested schedule cannot be created."""


@dataclass(frozen=True)
class SchedulePointPlan:
    """One independently scheduled point within a finite task."""

    period_value: int | None
    clock_time: str | None
    exact_at: float | None
    first_fire_at: float | None
    last_fire_at: float | None
    planned_count: int


@dataclass(frozen=True)
class SchedulePlan:
    """Validated finite task plan used by persistence and scheduling."""

    mode: ScheduleMode
    start_at: float | None
    end_at: float | None
    step: int | None
    total_occurrences: int
    points: tuple[SchedulePointPlan, ...]


def parse_clock(value: str) -> time:
    """Parse an exact zero-padded HH:MM:SS clock value."""
    if not isinstance(value, str) or re.fullmatch(r"\d{2}:\d{2}:\d{2}", value) is None:
        raise ScheduleValidationError("错误：时间点必须严格使用 HH:MM:SS 格式。")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleValidationError(f"错误：无效时间点 {value}。") from exc
    if parsed.microsecond:
        raise ScheduleValidationError("错误：时间点必须严格使用 HH:MM:SS 格式。")
    return parsed


def parse_boundary(value: str) -> datetime:
    """Parse a timezone-bearing ISO timestamp and normalize it to UTC+08:00."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleValidationError(f"错误：无法解析时间 {value}。") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScheduleValidationError("错误：起止时间必须包含时区偏移。")
    return parsed.astimezone(SHANGHAI)


def _validate_step(step: int) -> None:
    if isinstance(step, bool) or not isinstance(step, int) or step <= 0:
        raise ScheduleValidationError("错误：step 必须是正整数。")


def _validate_boundaries(start_at: str, end_at: str) -> tuple[datetime, datetime]:
    start = parse_boundary(start_at)
    end = parse_boundary(end_at)
    if start > end:
        raise ScheduleValidationError("错误：结束时间不得早于开始时间。")
    return start, end


def _validate_raw_size(values: Sequence[object], maximum: int) -> None:
    if not values:
        raise ScheduleValidationError("错误：至少需要一个时间点。")
    if len(values) > maximum:
        raise ScheduleValidationError(f"错误：时间点最多 {maximum} 个。")


def _combine(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=SHANGHAI)


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + month - 1 + offset
    return absolute // 12, absolute % 12 + 1


def _summarize_daily(
    start: datetime,
    end: datetime,
    clock: time,
    step: int,
    now: float,
) -> tuple[float | None, float | None, int]:
    maximum_offset = (end.date() - start.date()).days
    if maximum_offset < 0 or now == float("inf"):
        return None, None, 0

    target_offset = 0
    if math.isfinite(now):
        now_local = datetime.fromtimestamp(now, tz=SHANGHAI)
        target_offset = max((now_local.date() - start.date()).days, 0)
    offset = target_offset // step * step
    while offset <= maximum_offset:
        candidate = _combine(start.date() + timedelta(days=offset), clock)
        if candidate >= start and candidate.timestamp() > now:
            break
        offset += step
    if offset > maximum_offset:
        return None, None, 0

    first = _combine(start.date() + timedelta(days=offset), clock)
    if first > end:
        return None, None, 0
    last_offset = maximum_offset // step * step
    last = _combine(start.date() + timedelta(days=last_offset), clock)
    if last > end:
        last_offset -= step
        if last_offset < offset:
            return None, None, 0
        last = _combine(start.date() + timedelta(days=last_offset), clock)
    count = (last_offset - offset) // step + 1
    return first.timestamp(), last.timestamp(), count


def _summarize_weekly(
    start: datetime,
    end: datetime,
    weekday: int,
    clock: time,
    step: int,
    now: float,
) -> tuple[float | None, float | None, int]:
    week_start = start.date() - timedelta(days=start.isoweekday() - 1)
    maximum_offset_weeks = (end.date() - week_start).days // 7
    if maximum_offset_weeks < 0 or now == float("inf"):
        return None, None, 0

    target_offset_weeks = 0
    if math.isfinite(now):
        now_local = datetime.fromtimestamp(now, tz=SHANGHAI)
        target_offset_weeks = max(
            (now_local.date() - week_start).days // 7,
            0,
        )
    offset_weeks = target_offset_weeks // step * step
    candidate: datetime | None = None
    while offset_weeks <= maximum_offset_weeks:
        current_day = (
            week_start
            + timedelta(weeks=offset_weeks)
            + timedelta(days=weekday - 1)
        )
        candidate = _combine(current_day, clock)
        if candidate >= start and candidate.timestamp() > now:
            break
        offset_weeks += step
    if candidate is None or offset_weeks > maximum_offset_weeks or candidate > end:
        return None, None, 0

    last_offset_weeks = maximum_offset_weeks // step * step
    last_day = (
        week_start
        + timedelta(weeks=last_offset_weeks)
        + timedelta(days=weekday - 1)
    )
    last = _combine(last_day, clock)
    if last > end:
        last_offset_weeks -= step
        if last_offset_weeks < offset_weeks:
            return None, None, 0
        last = _combine(
            week_start
            + timedelta(weeks=last_offset_weeks)
            + timedelta(days=weekday - 1),
            clock,
        )
    count = (last_offset_weeks - offset_weeks) // step + 1
    return candidate.timestamp(), last.timestamp(), count


def _iter_monthly(
    start: datetime,
    end: datetime,
    month_day: int,
    clock: time,
    step: int,
    now: float,
) -> Iterator[float]:
    offset_months = 0
    maximum_offset_months = (
        (end.year - start.year) * 12 + end.month - start.month
    )
    while offset_months <= maximum_offset_months:
        year, month = _add_months(start.year, start.month, offset_months)
        if date(year, month, 1) > end.date().replace(day=1):
            return
        if month_day <= monthrange(year, month)[1]:
            candidate = _combine(date(year, month, month_day), clock)
            if candidate > end:
                return
            timestamp = candidate.timestamp()
            if candidate >= start and timestamp > now:
                yield timestamp
        offset_months += step


def _summarize_iterator(
    iterator: Iterator[float],
) -> tuple[float | None, float | None, int]:
    first = next(iterator, None)
    if first is None:
        return None, None, 0
    last = first
    count = 1
    for timestamp in iterator:
        last = timestamp
        count += 1
    return first, last, count


def _allocate(
    mode: ScheduleMode,
    start: datetime | None,
    end: datetime | None,
    step: int | None,
    definitions: Sequence[tuple[int | None, str | None, float | None]],
    summaries: Sequence[tuple[float | None, float | None, int]],
) -> SchedulePlan:
    total_occurrences = sum(summary[2] for summary in summaries)
    if total_occurrences == 0:
        raise ScheduleValidationError("错误：任务范围内没有未来触发时间。")

    points: list[SchedulePointPlan] = []
    for definition, summary in zip(definitions, summaries):
        period_value, clock_time, exact_at = definition
        first_fire_at, last_fire_at, planned_count = summary
        points.append(
            SchedulePointPlan(
                period_value=period_value,
                clock_time=clock_time,
                exact_at=exact_at,
                first_fire_at=first_fire_at,
                last_fire_at=last_fire_at,
                planned_count=planned_count,
            )
        )

    return SchedulePlan(
        mode=mode,
        start_at=start.timestamp() if start is not None else None,
        end_at=end.timestamp() if end is not None else None,
        step=step,
        total_occurrences=total_occurrences,
        points=tuple(points),
    )


def _current_timestamp(now: float | None) -> float:
    return time_module.time() if now is None else now


def build_daily_plan(
    start_at: str,
    end_at: str,
    time_points: list[str],
    step: int = 1,
    *,
    now: float | None = None,
) -> SchedulePlan:
    """Build a finite daily schedule anchored to the start calendar date."""
    _validate_step(step)
    _validate_raw_size(time_points, TIMER_MAX_FREQUENCY_POINTS)
    clocks = [(value, parse_clock(value)) for value in time_points]
    if len({value for value, _ in clocks}) != len(clocks):
        raise ScheduleValidationError("错误：时间点不能重复。")
    clocks.sort(key=lambda item: item[1])
    start, end = _validate_boundaries(start_at, end_at)
    current = _current_timestamp(now)
    definitions = [(None, value, None) for value, _ in clocks]
    summaries = [
        _summarize_daily(start, end, clock, step, current) for _, clock in clocks
    ]
    return _allocate("daily", start, end, step, definitions, summaries)


def build_weekly_plan(
    start_at: str,
    end_at: str,
    time_points: Sequence[Mapping[str, object]],
    step: int = 1,
    *,
    now: float | None = None,
) -> SchedulePlan:
    """Build a finite weekly schedule anchored to the start ISO week."""
    _validate_step(step)
    _validate_raw_size(time_points, TIMER_MAX_FREQUENCY_POINTS)
    normalized: list[tuple[int, str, time]] = []
    for point in time_points:
        weekday = point.get("weekday")
        value = point.get("time")
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 1 <= weekday <= 7:
            raise ScheduleValidationError("错误：weekday 必须是 1 到 7。")
        if not isinstance(value, str):
            raise ScheduleValidationError("错误：time 必须使用 HH:MM:SS 格式。")
        normalized.append((weekday, value, parse_clock(value)))
    if len({(weekday, value) for weekday, value, _ in normalized}) != len(normalized):
        raise ScheduleValidationError("错误：时间点不能重复。")
    normalized.sort(key=lambda item: (item[0], item[2]))
    start, end = _validate_boundaries(start_at, end_at)
    current = _current_timestamp(now)
    definitions = [(weekday, value, None) for weekday, value, _ in normalized]
    summaries = [
        _summarize_weekly(start, end, weekday, clock, step, current)
        for weekday, _, clock in normalized
    ]
    return _allocate("weekly", start, end, step, definitions, summaries)


def build_monthly_plan(
    start_at: str,
    end_at: str,
    time_points: Sequence[Mapping[str, object]],
    step: int = 1,
    *,
    now: float | None = None,
) -> SchedulePlan:
    """Build a finite monthly schedule anchored to the start month."""
    _validate_step(step)
    _validate_raw_size(time_points, TIMER_MAX_FREQUENCY_POINTS)
    normalized: list[tuple[int, str, time]] = []
    for point in time_points:
        month_day = point.get("day")
        value = point.get("time")
        if (
            isinstance(month_day, bool)
            or not isinstance(month_day, int)
            or not 1 <= month_day <= 31
        ):
            raise ScheduleValidationError("错误：day 必须是 1 到 31。")
        if not isinstance(value, str):
            raise ScheduleValidationError("错误：time 必须使用 HH:MM:SS 格式。")
        normalized.append((month_day, value, parse_clock(value)))
    if len({(month_day, value) for month_day, value, _ in normalized}) != len(normalized):
        raise ScheduleValidationError("错误：时间点不能重复。")
    normalized.sort(key=lambda item: (item[0], item[2]))
    start, end = _validate_boundaries(start_at, end_at)
    current = _current_timestamp(now)
    definitions = [(month_day, value, None) for month_day, value, _ in normalized]
    summaries = [
        _summarize_iterator(_iter_monthly(start, end, month_day, clock, step, current))
        for month_day, _, clock in normalized
    ]
    return _allocate("monthly", start, end, step, definitions, summaries)


def build_at_plan(
    trigger_times: list[str],
    *,
    now: float | None = None,
) -> SchedulePlan:
    """Build a finite exact-time schedule."""
    _validate_raw_size(trigger_times, TIMER_MAX_EXACT_POINTS)
    parsed = [parse_boundary(value).timestamp() for value in trigger_times]
    if len(set(parsed)) != len(parsed):
        raise ScheduleValidationError("错误：触发时间不能重复。")
    current = _current_timestamp(now)
    if any(timestamp <= current for timestamp in parsed):
        raise ScheduleValidationError("错误：触发时间必须在未来。")
    parsed.sort()
    definitions = [(None, None, timestamp) for timestamp in parsed]
    summaries = [(timestamp, timestamp, 1) for timestamp in parsed]
    return _allocate("at", None, None, None, definitions, summaries)


def flatten_occurrences(plan: SchedulePlan) -> list[float]:
    """Materialize a plan's occurrences on demand for diagnostics and tests."""
    task = {
        "schedule_type": plan.mode,
        "step": plan.step,
    }
    point_records = [
        {
            "period_value": point.period_value,
            "clock_time": point.clock_time,
            "exact_at": point.exact_at,
            "first_fire_at": point.first_fire_at,
            "planned_occurrences": point.planned_count,
        }
        for point in plan.points
    ]
    heap: list[tuple[float, int, int]] = []
    for point_index, point in enumerate(point_records):
        if point["planned_occurrences"]:
            first = occurrence_at_index(task, point, 0)
            heapq.heappush(heap, (first, point_index, 0))

    occurrences: list[float] = []
    while heap:
        timestamp, point_index, occurrence_index = heapq.heappop(heap)
        occurrences.append(timestamp)
        following_index = occurrence_index + 1
        point = point_records[point_index]
        if following_index < point["planned_occurrences"]:
            following = occurrence_at_index(task, point, following_index)
            heapq.heappush(
                heap,
                (following, point_index, following_index),
            )
    return occurrences


def _record_int(record: Mapping[str, object], key: str) -> int:
    value = record[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _record_float(record: Mapping[str, object], key: str) -> float:
    value = record[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def occurrence_at_index(
    task: Mapping[str, object],
    point: Mapping[str, object],
    index: int,
) -> float:
    """Return a point's zero-based retained occurrence timestamp."""
    if index < 0 or index >= _record_int(point, "planned_occurrences"):
        raise IndexError(index)
    mode_value = task["schedule_type"]
    if not isinstance(mode_value, str):
        raise TypeError("schedule_type must be a string")
    mode = mode_value
    first = _record_float(point, "first_fire_at")
    if mode == "at":
        return _record_float(point, "exact_at")
    step = _record_int(task, "step")
    if mode == "daily":
        return first + index * step * 24 * 60 * 60
    if mode == "weekly":
        return first + index * step * 7 * 24 * 60 * 60
    if mode != "monthly":
        raise ValueError(f"unsupported schedule type: {mode}")

    first_local = datetime.fromtimestamp(first, tz=SHANGHAI)
    wanted_index = index
    valid_index = 0
    offset = 0
    while True:
        year, month = _add_months(first_local.year, first_local.month, offset)
        if first_local.day <= monthrange(year, month)[1]:
            if valid_index == wanted_index:
                candidate = datetime(
                    year,
                    month,
                    first_local.day,
                    first_local.hour,
                    first_local.minute,
                    first_local.second,
                    tzinfo=SHANGHAI,
                )
                return candidate.timestamp()
            valid_index += 1
        offset += step


def _build_internal_at_plan(times: Iterable[float]) -> SchedulePlan:
    """Build an exact plan from trusted internal timestamps."""
    unique_times = sorted(set(float(timestamp) for timestamp in times))
    if not unique_times:
        raise ScheduleValidationError("错误：至少需要一个时间点。")
    points = tuple(
        SchedulePointPlan(None, None, timestamp, timestamp, timestamp, 1)
        for timestamp in unique_times
    )
    return SchedulePlan(
        mode="at",
        start_at=None,
        end_at=None,
        step=None,
        total_occurrences=len(unique_times),
        points=points,
    )
