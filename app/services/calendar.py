from __future__ import annotations

import calendar as cal
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Assignment, Course, StudyBlock, StudyPlan
from app.services.dates import local_date, to_local
from app.services.tracker import is_completed, status_for, utc_now

WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


@dataclass
class CalendarEvent:
    kind: str  # due | study
    title: str
    subtitle: str
    status: str
    assignment_id: int
    time_label: str


@dataclass
class DayCell:
    iso: str
    day_num: int
    in_month: bool
    is_today: bool
    is_selected: bool
    events: list[CalendarEvent] = field(default_factory=list)

    @property
    def aria_label(self) -> str:
        count = len(self.events)
        noun = "item" if count == 1 else "items"
        return f"{self.iso}, {count} {noun}"


@dataclass
class MonthCalendar:
    label: str
    month_key: str
    prev_month: str
    next_month: str
    today_month: str
    weekday_labels: list[str]
    weeks: list[list[DayCell]]
    selected_label: str | None
    selected_iso: str | None
    selected_events: list[CalendarEvent]
    undated_count: int
    event_count: int


def parse_month(value: str | None, today: date | None = None) -> tuple[int, int]:
    today = today or datetime.now().astimezone().date()
    if value:
        try:
            year_s, month_s = value.split("-", 1)
            year, month = int(year_s), int(month_s)
            if 1 <= month <= 12 and 2000 <= year <= 2100:
                return year, month
        except ValueError:
            pass
    return today.year, today.month


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def build_month(
    db: Session,
    *,
    year: int,
    month: int,
    course_id: int | None = None,
    include_done: bool = False,
    selected_day: date | None = None,
    today: date | None = None,
) -> MonthCalendar:
    today = today or datetime.now().astimezone().date()
    now = utc_now()
    month_cal = cal.Calendar(firstweekday=6)
    week_dates = month_cal.monthdatescalendar(year, month)
    grid_start = week_dates[0][0]
    grid_end = week_dates[-1][-1]

    if selected_day is None and (year, month) == (today.year, today.month):
        selected_day = today

    events_by_day: dict[date, list[CalendarEvent]] = {}
    undated_count = 0

    stmt = (
        select(Assignment)
        .options(joinedload(Assignment.course), joinedload(Assignment.override))
        .join(Course)
        .where(Course.active.is_(True))
    )
    if course_id is not None:
        stmt = stmt.where(Assignment.course_id == course_id)
    assignments = list(db.scalars(stmt).unique().all())

    for assignment in assignments:
        override = assignment.override
        ignored = bool(override and override.ignored)
        if ignored:
            continue
        completed = is_completed(bool(assignment.canvas_completed), bool(override and override.done))
        if assignment.due_at is None:
            if not completed or include_done:
                undated_count += 1
            continue
        if completed and not include_done:
            continue
        due_day = local_date(assignment.due_at)
        if due_day < grid_start or due_day > grid_end:
            continue
        course_label = ""
        if assignment.course:
            course_label = assignment.course.course_code or assignment.course.name
        events_by_day.setdefault(due_day, []).append(
            CalendarEvent(
                kind="due",
                title=assignment.name,
                subtitle=course_label,
                status=status_for(assignment.due_at, now, completed=completed),
                assignment_id=assignment.id,
                time_label=to_local(assignment.due_at).strftime("%H:%M"),
            )
        )

    _add_study_events(
        db,
        events_by_day,
        grid_start=grid_start,
        grid_end=grid_end,
        course_id=course_id,
        assignments=assignments,
    )

    for day_events in events_by_day.values():
        day_events.sort(key=lambda event: (0 if event.kind == "due" else 1, event.time_label, event.title))

    weeks: list[list[DayCell]] = []
    for week in week_dates:
        cells: list[DayCell] = []
        for day in week:
            cells.append(
                DayCell(
                    iso=day.isoformat(),
                    day_num=day.day,
                    in_month=day.month == month,
                    is_today=day == today,
                    is_selected=day == selected_day,
                    events=events_by_day.get(day, []),
                )
            )
        weeks.append(cells)

    selected_events = events_by_day.get(selected_day, []) if selected_day else []
    selected_label = selected_day.strftime("%A, %b %d") if selected_day else None
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    event_count = sum(len(events) for events in events_by_day.values())

    return MonthCalendar(
        label=date(year, month, 1).strftime("%B %Y"),
        month_key=_month_key(year, month),
        prev_month=_month_key(prev_year, prev_month),
        next_month=_month_key(next_year, next_month),
        today_month=_month_key(today.year, today.month),
        weekday_labels=WEEKDAY_LABELS,
        weeks=weeks,
        selected_label=selected_label,
        selected_iso=selected_day.isoformat() if selected_day else None,
        selected_events=selected_events,
        undated_count=undated_count,
        event_count=event_count,
    )


def _add_study_events(
    db: Session,
    events_by_day: dict[date, list[CalendarEvent]],
    *,
    grid_start: date,
    grid_end: date,
    course_id: int | None,
    assignments: list[Assignment],
) -> None:
    completed_ids = {
        assignment.id
        for assignment in assignments
        if is_completed(
            bool(assignment.canvas_completed),
            bool(assignment.override and assignment.override.done),
        )
    }
    ignored_ids = {
        assignment.id
        for assignment in assignments
        if assignment.override and assignment.override.ignored
    }
    latest_ids = select(func.max(StudyPlan.id)).group_by(StudyPlan.assignment_id)
    stmt = (
        select(StudyBlock)
        .join(StudyPlan, StudyBlock.plan_id == StudyPlan.id)
        .join(Assignment, StudyPlan.assignment_id == Assignment.id)
        .options(joinedload(StudyBlock.plan).joinedload(StudyPlan.assignment).joinedload(Assignment.course))
        .where(StudyBlock.plan_id.in_(latest_ids))
        .where(StudyBlock.status == "pending")
        .where(StudyBlock.scheduled_date.is_not(None))
    )
    if course_id is not None:
        stmt = stmt.where(Assignment.course_id == course_id)

    window_start = datetime.combine(grid_start, datetime.min.time()) - timedelta(days=1)
    window_end = datetime.combine(grid_end, datetime.max.time()) + timedelta(days=1)
    stmt = stmt.where(StudyBlock.scheduled_date >= window_start, StudyBlock.scheduled_date <= window_end)

    for block in db.scalars(stmt).unique().all():
        plan = block.plan
        if plan is None or block.scheduled_date is None:
            continue
        if plan.assignment_id in completed_ids or plan.assignment_id in ignored_ids:
            continue
        # Study dates are calendar days chosen by the planner, not UTC instants.
        day = block.scheduled_date.date()
        if day < grid_start or day > grid_end:
            continue
        course_label = ""
        title = block.topic
        if plan.assignment is not None:
            title = f"{block.topic}"
            if plan.assignment.course:
                course_label = plan.assignment.course.course_code or plan.assignment.course.name
            if plan.assignment.name:
                course_label = (
                    f"{course_label} · {plan.assignment.name}" if course_label else plan.assignment.name
                )
        events_by_day.setdefault(day, []).append(
            CalendarEvent(
                kind="study",
                title=title,
                subtitle=course_label,
                status="study",
                assignment_id=plan.assignment_id,
                time_label=f"{block.duration_min} min",
            )
        )
