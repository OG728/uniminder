from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Assignment, PlannerItem

_DUE_IN_TITLE = re.compile(
    r"Due\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s*(?:\)\s*at|at|;)\s*(\d{1,2}):(\d{2})\s*([ap])\.?m\.?",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def titles_match(assignment_name: str, event_title: str) -> bool:
    """True when a calendar event title is the assignment, not a longer sibling.

    "Content Quiz 1" matches "Content Quiz 1 (Due ...)" and does not match
    "Content Quiz 10".
    """
    name = " ".join(assignment_name.lower().split())
    title = " ".join(event_title.lower().split())
    if len(title) < 4 or not name:
        return False
    if name == title:
        return True
    if name.startswith(title) and name[len(title)] in " ([:-\u2013":
        return True
    return False


def parse_due_from_title(name: str) -> datetime | None:
    """Read a due date written into an assignment title and store it as naive UTC.

    Instructors sometimes leave Canvas due_at empty and put the deadline in the
    name, for example "Content Quiz 4 (Due Oct 1, 2026 at 11:59 p.m.)".
    The clock time is interpreted in the machine's local timezone.
    """
    match = _DUE_IN_TITLE.search(name)
    if match is None:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    day = int(match.group(2))
    year = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    if match.group(6).lower() == "p" and hour < 12:
        hour += 12
    elif match.group(6).lower() == "a" and hour == 12:
        hour = 0
    try:
        local = datetime(year, month, day, hour, minute).astimezone()
    except ValueError:
        return None
    # astimezone() on a naive datetime assumes local time, then we store UTC.
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def apply_calendar_due_dates(db: Session) -> int:
    """Fill assignment due dates that Canvas left blank.

    Prefer the course calendar event. If none matches, use a due date written
    into the assignment title. Assignments that already have due_at are left
    alone so a real Canvas due date always wins.
    """
    events = list(
        db.scalars(
            select(PlannerItem).where(
                PlannerItem.plannable_type == "calendar_event",
                PlannerItem.due_at.is_not(None),
            )
        ).all()
    )
    assignments = list(
        db.scalars(
            select(Assignment)
            .options(joinedload(Assignment.course))
            .where(Assignment.due_at.is_(None))
        )
        .unique()
        .all()
    )
    updated = 0
    for assignment in assignments:
        course_canvas_id = assignment.course.canvas_id if assignment.course else None
        matches = [event for event in events if titles_match(assignment.name, event.title or "")]
        same_course = [
            event
            for event in matches
            if course_canvas_id is not None and event.course_canvas_id == course_canvas_id
        ]
        pool = same_course or matches
        if pool:
            pool.sort(key=lambda event: (-len(event.title or ""), event.due_at or datetime.max))
            assignment.due_at = pool[0].due_at
            updated += 1
            continue
        parsed = parse_due_from_title(assignment.name)
        if parsed is not None:
            assignment.due_at = parsed
            updated += 1
    return updated
