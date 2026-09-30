from datetime import datetime, timezone
from typing import Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canvas_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    course_code: Mapped[str] = mapped_column(String(128), default="")
    term: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="course")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canvas_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    unlock_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    html_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    submission_types: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submission_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    canvas_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    course: Mapped["Course"] = relationship(back_populates="assignments")
    override: Mapped[Optional["UserOverride"]] = relationship(
        back_populates="assignment",
        uselist=False,
    )
    study_plans: Mapped[list["StudyPlan"]] = relationship(back_populates="assignment")


class PlannerItem(Base):
    __tablename__ = "planner_items"
    __table_args__ = (UniqueConstraint("plannable_type", "plannable_id", name="uq_planner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plannable_type: Mapped[str] = mapped_column(String(64), default="")
    plannable_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    course_canvas_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    html_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    context_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class UserOverride(Base):
    __tablename__ = "user_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id"),
        unique=True,
        index=True,
    )
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    assignment: Mapped["Assignment"] = relationship(back_populates="override")


class StudyPlan(Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    guide_outline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    backend: Mapped[str] = mapped_column(String(32), default="rules")
    hours_available: Mapped[float] = mapped_column(Float, default=4.0)
    session_minutes: Mapped[int] = mapped_column(Integer, default=45)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    assignment: Mapped["Assignment"] = relationship(back_populates="study_plans")
    blocks: Mapped[list["StudyBlock"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="StudyBlock.scheduled_date",
    )


class StudyBlock(Base):
    __tablename__ = "study_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id"), index=True)
    scheduled_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_min: Mapped[int] = mapped_column(Integer, default=45)
    topic: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|done|skipped
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped["StudyPlan"] = relationship(back_populates="blocks")
