from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canvas.client import CanvasClient
from app.config import Settings, get_settings
from app.db.models import Assignment, Course, Meta, PlannerItem
from app.services.due_dates import apply_calendar_due_dates


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _strip_html(html: str | None, max_chars: int) -> str | None:
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text or None


_COMPLETE_STATES = {"submitted", "graded", "pending_review", "complete"}


def read_submission(raw: dict[str, Any]) -> tuple[bool, str | None, datetime | None]:
    """Return (completed, workflow_state, submitted_at) from an assignment payload.

    Canvas includes the current user's submission when assignments are requested
    with include[]=submission. Submitted, graded, pending review, or excused
    work counts as completed so it is not treated as overdue.
    """
    submission = raw.get("submission")
    if not isinstance(submission, dict):
        return False, None, None
    state = submission.get("workflow_state")
    state = state.lower() if isinstance(state, str) else None
    submitted_at = _parse_dt(submission.get("submitted_at"))
    excused = bool(submission.get("excused"))
    completed = excused or submitted_at is not None or state in _COMPLETE_STATES
    return completed, state, submitted_at


def _term_name(course: dict[str, Any]) -> str | None:
    term = course.get("term")
    if isinstance(term, dict):
        return term.get("name")
    return None


def set_meta(db: Session, key: str, value: str) -> None:
    row = db.get(Meta, key)
    if row is None:
        db.add(Meta(key=key, value=value))
    else:
        row.value = value


def get_meta(db: Session, key: str) -> str | None:
    row = db.get(Meta, key)
    return row.value if row else None


async def sync_canvas(db: Session, settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    if not settings.canvas_access_token or "your_token" in settings.canvas_access_token:
        raise ValueError(
            "Set CANVAS_ACCESS_TOKEN in .env (copy from .env.example). "
            "Create a token in Canvas → Account → Settings → New Access Token."
        )
    if "YOUR_SCHOOL" in settings.canvas_base_url:
        raise ValueError("Set CANVAS_BASE_URL in .env to your school's Canvas URL.")

    now = _utc_now()
    stats = {"courses": 0, "assignments": 0, "planner_items": 0}

    async with CanvasClient(settings) as client:
        courses_raw = await client.get_courses()
        for raw in courses_raw:
            canvas_id = raw.get("id")
            if canvas_id is None:
                continue
            course = db.scalar(select(Course).where(Course.canvas_id == canvas_id))
            if course is None:
                course = Course(canvas_id=canvas_id)
                db.add(course)
            course.name = raw.get("name") or course.name or ""
            course.course_code = raw.get("course_code") or course.course_code or ""
            course.term = _term_name(raw)
            course.active = True
            course.synced_at = now
            stats["courses"] += 1

        db.flush()

        courses = list(db.scalars(select(Course).where(Course.active.is_(True))).all())
        seen_assignment_ids: set[int] = set()

        for course in courses:
            try:
                assignments_raw = await client.get_assignments(course.canvas_id)
            except Exception:
                # Skip courses that deny assignment access (concluded/restricted).
                continue
            for raw in assignments_raw:
                canvas_id = raw.get("id")
                if canvas_id is None:
                    continue
                seen_assignment_ids.add(int(canvas_id))
                assignment = db.scalar(
                    select(Assignment).where(Assignment.canvas_id == canvas_id)
                )
                if assignment is None:
                    assignment = Assignment(canvas_id=canvas_id, course_id=course.id)
                    db.add(assignment)
                assignment.course_id = course.id
                assignment.name = raw.get("name") or ""
                assignment.due_at = _parse_dt(raw.get("due_at"))
                assignment.unlock_at = _parse_dt(raw.get("unlock_at"))
                assignment.points = raw.get("points_possible")
                assignment.html_url = raw.get("html_url")
                types = raw.get("submission_types") or []
                assignment.submission_types = ",".join(types) if isinstance(types, list) else str(types)
                assignment.description = _strip_html(
                    raw.get("description"),
                    settings.description_max_chars,
                )
                completed, state, submitted_at = read_submission(raw)
                assignment.canvas_completed = completed
                assignment.submission_state = state
                assignment.submitted_at = submitted_at
                assignment.synced_at = now
                stats["assignments"] += 1

        try:
            planner_raw = await client.get_planner_items()
        except Exception:
            planner_raw = []

        for raw in planner_raw:
            plannable = raw.get("plannable") or {}
            plannable_type = raw.get("plannable_type") or plannable.get("type") or "item"
            plannable_id = raw.get("plannable_id") or plannable.get("id")
            existing = None
            if plannable_id is not None:
                existing = db.scalar(
                    select(PlannerItem).where(
                        PlannerItem.plannable_type == plannable_type,
                        PlannerItem.plannable_id == plannable_id,
                    )
                )
            if existing is None:
                existing = PlannerItem(
                    plannable_type=plannable_type,
                    plannable_id=plannable_id,
                )
                db.add(existing)
            existing.course_canvas_id = raw.get("course_id") or raw.get("context_id")
            existing.title = (
                plannable.get("title")
                or plannable.get("name")
                or raw.get("plannable_type")
                or "Planner item"
            )
            existing.due_at = _parse_dt(
                raw.get("plannable_date")
                or plannable.get("due_at")
                or plannable.get("todo_date")
            )
            existing.html_url = raw.get("html_url") or plannable.get("html_url")
            existing.context_name = raw.get("context_name")
            existing.synced_at = now
            stats["planner_items"] += 1

    db.flush()
    stats["due_dates_filled"] = apply_calendar_due_dates(db)

    set_meta(db, "last_sync_at", now.isoformat(timespec="seconds") + "Z")
    db.commit()
    return stats
