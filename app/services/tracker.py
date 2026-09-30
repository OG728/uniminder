from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Assignment, Course, UserOverride

RangeFilter = Literal["all", "week", "overdue", "later"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class AssignmentView:
    id: int
    canvas_id: int
    name: str
    course_name: str
    course_code: str
    course_id: int
    due_at: datetime | None
    points: float | None
    html_url: str | None
    description: str | None
    done: bool
    ignored: bool
    canvas_completed: bool
    submitted_at: datetime | None
    priority: int | None
    notes: str | None
    status: str  # completed | overdue | due_soon | later | none


def is_completed(canvas_completed: bool, local_done: bool) -> bool:
    return canvas_completed or local_done


def status_for(
    due_at: datetime | None,
    now: datetime,
    *,
    completed: bool = False,
) -> str:
    if completed:
        return "completed"
    if due_at is None:
        return "none"
    if due_at < now:
        return "overdue"
    if due_at <= now + timedelta(days=3):
        return "due_soon"
    return "later"


def list_assignments(
    db: Session,
    *,
    range_filter: RangeFilter = "all",
    course_id: int | None = None,
    include_done: bool = False,
    include_ignored: bool = False,
) -> list[AssignmentView]:
    now = utc_now()
    week_end = now + timedelta(days=7)

    stmt = (
        select(Assignment)
        .options(joinedload(Assignment.course), joinedload(Assignment.override))
        .join(Course)
        .where(Course.active.is_(True))
    )
    if course_id is not None:
        stmt = stmt.where(Assignment.course_id == course_id)

    rows = list(db.scalars(stmt).unique().all())
    views: list[AssignmentView] = []

    for a in rows:
        override = a.override
        done = bool(override and override.done)
        ignored = bool(override and override.ignored)
        canvas_completed = bool(a.canvas_completed)
        completed = is_completed(canvas_completed, done)
        if completed and not include_done:
            continue
        if ignored and not include_ignored:
            continue

        due = a.due_at
        if range_filter == "week":
            if due is None or due > week_end:
                continue
        elif range_filter == "overdue":
            # Submitted or locally finished work is never overdue.
            if completed or due is None or due >= now:
                continue
        elif range_filter == "later":
            if due is None or due <= week_end:
                continue

        views.append(
            AssignmentView(
                id=a.id,
                canvas_id=a.canvas_id,
                name=a.name,
                course_name=a.course.name if a.course else "",
                course_code=a.course.course_code if a.course else "",
                course_id=a.course_id,
                due_at=due,
                points=a.points,
                html_url=a.html_url,
                description=a.description,
                done=done,
                ignored=ignored,
                canvas_completed=canvas_completed,
                submitted_at=a.submitted_at,
                priority=override.priority if override else None,
                notes=override.notes if override else None,
                status=status_for(due, now, completed=completed),
            )
        )

    views.sort(key=lambda v: (v.due_at is None, v.due_at or datetime.max, v.name))
    return views


def upsert_override(
    db: Session,
    assignment_id: int,
    *,
    done: bool | None = None,
    ignored: bool | None = None,
    priority: int | None = None,
    notes: str | None = None,
) -> UserOverride:
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise ValueError(f"Assignment {assignment_id} not found")

    override = assignment.override
    if override is None:
        override = UserOverride(assignment_id=assignment_id)
        db.add(override)

    if done is not None:
        override.done = done
    if ignored is not None:
        override.ignored = ignored
    if priority is not None:
        override.priority = priority
    if notes is not None:
        override.notes = notes
    override.updated_at = utc_now()
    db.commit()
    db.refresh(override)
    return override


def list_courses(db: Session) -> list[Course]:
    return list(
        db.scalars(select(Course).where(Course.active.is_(True)).order_by(Course.name)).all()
    )
