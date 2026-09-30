from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models import Assignment, StudyBlock, StudyPlan


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


class RuleBasedPlanner:
    """Deterministic spaced study plan — no LLM required."""

    def generate(self, context: PlanContext) -> StudyPlanResult:
        session = max(15, min(context.session_minutes, 180))
        total_minutes = max(session, int(context.hours_available * 60))
        num_sessions = max(1, total_minutes // session)

        days = list(context.study_days)
        if not days:
            days = _default_study_days(context.due_at, num_sessions)

        # Spread sessions across available days.
        blocks: list[PlannedBlock] = []
        for i in range(num_sessions):
            day = days[i % len(days)]
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


def _default_study_days(due_at: datetime | None, num_sessions: int) -> list[datetime]:
    now = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    if due_at is None:
        return [now + timedelta(days=i) for i in range(max(1, num_sessions))]
    due_day = due_at.replace(hour=0, minute=0, second=0, microsecond=0)
    if due_day <= now:
        return [now]
    span = (due_day - now).days
    # Use days before due (exclude due day evening crunch as last optional).
    usable = max(1, span)
    count = min(max(num_sessions, 1), usable)
    if count == 1:
        return [now]
    step = usable / count
    return [now + timedelta(days=int(i * step)) for i in range(count)]


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
