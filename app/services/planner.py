from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models import Assignment, StudyBlock, StudyPlan
from app.services.dates import to_local


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class PlanContext:
    assignment_title: str
    course_name: str
    due_at: datetime | None
    description_excerpt: str | None
    hours_available: float
    session_minutes: int
    study_days: list[datetime] = field(default_factory=list)


@dataclass
class PlannedBlock:
    scheduled_date: datetime | None
    duration_min: int
    topic: str
    sort_order: int


@dataclass
class StudyPlanResult:
    title: str
    guide_outline: str | None
    blocks: list[PlannedBlock]
    backend: str = "rules"


class StudyPlanner(Protocol):
    def generate(self, context: PlanContext) -> StudyPlanResult: ...


PHASE_TOPICS = (
    "Overview & gather materials",
    "Core concepts review",
    "Practice / problem sets",
    "Weak spots drill",
    "Final pass & self-check",
)


def session_length(context: PlanContext) -> int:
    return max(15, min(context.session_minutes, 180))


def session_count(context: PlanContext) -> int:
    session = session_length(context)
    total_minutes = max(session, int(context.hours_available * 60))
    return max(1, total_minutes // session)


class RuleBasedPlanner:
    """Deterministic spaced study plan — no LLM required."""

    def generate(self, context: PlanContext) -> StudyPlanResult:
        session = session_length(context)
        total_minutes = max(session, int(context.hours_available * 60))
        num_sessions = session_count(context)

        if context.study_days:
            days = [context.study_days[i % len(context.study_days)] for i in range(num_sessions)]
        else:
            days = schedule_sessions(context.due_at, num_sessions)

        blocks: list[PlannedBlock] = []
        for i in range(num_sessions):
            day = days[i]
            topic = PHASE_TOPICS[min(i * len(PHASE_TOPICS) // num_sessions, len(PHASE_TOPICS) - 1)]
            # Last session always final pass when multi-session.
            if i == num_sessions - 1 and num_sessions > 1:
                topic = PHASE_TOPICS[-1]
            blocks.append(
                PlannedBlock(
                    scheduled_date=day.replace(hour=0, minute=0, second=0, microsecond=0),
                    duration_min=session,
                    topic=topic,
                    sort_order=i,
                )
            )

        due_label = context.due_at.strftime("%Y-%m-%d %H:%M") if context.due_at else "no due date"
        outline_lines = [
            f"Prepare for: {context.assignment_title} ({context.course_name})",
            f"Due: {due_label}",
            f"Total study time: ~{total_minutes} min across {num_sessions} session(s).",
            "",
            "Suggested focus order:",
        ]
        for topic in PHASE_TOPICS[: min(5, num_sessions)]:
            outline_lines.append(f"- {topic}")
        if context.description_excerpt:
            outline_lines.extend(["", "From assignment notes:", context.description_excerpt[:500]])

        return StudyPlanResult(
            title=f"Study plan: {context.assignment_title}",
            guide_outline="\n".join(outline_lines),
            blocks=blocks,
            backend="rules",
        )


def available_days(due_at: datetime | None, today: date | None = None) -> list[date]:
    """Local calendar days you can study on, from today through the due date.

    The due day only counts when the deadline is in the afternoon or later, so a
    9:30 a.m. quiz gets its last session the day before.
    """
    today = today or datetime.now().astimezone().date()
    if due_at is None:
        return []
    due_local = to_local(due_at)
    last = due_local.date()
    if due_local.hour < 12:
        last -= timedelta(days=1)
    if last <= today:
        return [today]
    return [today + timedelta(days=i) for i in range((last - today).days + 1)]


def schedule_sessions(
    due_at: datetime | None,
    count: int,
    today: date | None = None,
) -> list[datetime]:
    """Give each session a day, never after the due date.

    Sessions are spread from today to the last available day. When there are more
    sessions than days, some days get more than one.
    """
    today = today or datetime.now().astimezone().date()
    count = max(1, count)
    days = available_days(due_at, today)
    if not days:
        days = [today + timedelta(days=i) for i in range(count)]
    if count == 1:
        picked = [days[0]]
    else:
        last = len(days) - 1
        picked = [days[round(i * last / (count - 1))] for i in range(count)]
    return [datetime.combine(day, time.min) for day in picked]


def get_planner(backend: str) -> StudyPlanner:
    if backend == "ollama":
        from app.services.ai.ollama import OllamaPlanner

        return OllamaPlanner()
    if backend == "api":
        from app.services.ai.api import ApiPlanner

        return ApiPlanner()
    return RuleBasedPlanner()


def create_study_plan(
    db: Session,
    assignment_id: int,
    *,
    hours_available: float,
    session_minutes: int,
    study_days: list[datetime] | None = None,
    backend: str = "rules",
) -> StudyPlan:
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    assignment = db.scalar(
        select(Assignment)
        .options(joinedload(Assignment.course))
        .where(Assignment.id == assignment_id)
    )
    if assignment is None:
        raise ValueError(f"Assignment {assignment_id} not found")

    course_name = assignment.course.name if assignment.course else ""
    context = PlanContext(
        assignment_title=assignment.name,
        course_name=course_name,
        due_at=assignment.due_at,
        description_excerpt=assignment.description,
        hours_available=hours_available,
        session_minutes=session_minutes,
        study_days=study_days or [],
    )

    planner = get_planner(backend)
    try:
        result = planner.generate(context)
    except Exception:
        if backend != "rules":
            result = RuleBasedPlanner().generate(context)
        else:
            raise

    plan = StudyPlan(
        assignment_id=assignment.id,
        title=result.title,
        guide_outline=result.guide_outline,
        backend=result.backend,
        hours_available=hours_available,
        session_minutes=session_minutes,
    )
    db.add(plan)
    db.flush()

    for block in result.blocks:
        db.add(
            StudyBlock(
                plan_id=plan.id,
                scheduled_date=block.scheduled_date,
                duration_min=block.duration_min,
                topic=block.topic,
                status="pending",
                sort_order=block.sort_order,
            )
        )
    db.commit()
    db.refresh(plan)
    return plan


def get_latest_plan(db: Session, assignment_id: int) -> StudyPlan | None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(StudyPlan)
        .options(selectinload(StudyPlan.blocks))
        .where(StudyPlan.assignment_id == assignment_id)
        .order_by(StudyPlan.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def set_block_status(db: Session, block_id: int, status: str) -> StudyBlock:
    block = db.get(StudyBlock, block_id)
    if block is None:
        raise ValueError(f"Block {block_id} not found")
    if status not in {"pending", "done", "skipped"}:
        raise ValueError("Invalid status")
    block.status = status
    db.commit()
    db.refresh(block)
    return block
