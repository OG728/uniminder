from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Assignment, Base, Course, StudyBlock, StudyPlan
from app.services.calendar import build_month
from app.services.dates import local_date


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_calendar_places_due_date_in_local_day_and_skips_completed():
    db = _session()
    course = Course(canvas_id=2, name="History", course_code="HIST 210", active=True)
    db.add(course)
    db.flush()
    open_due = datetime(2026, 10, 2, 5, 59)
    done_due = open_due - timedelta(days=1)
    db.add(
        Assignment(
            canvas_id=20,
            course_id=course.id,
            name="Essay",
            due_at=open_due,
            canvas_completed=False,
        )
    )
    db.add(
        Assignment(
            canvas_id=21,
            course_id=course.id,
            name="Reading",
            due_at=done_due,
            canvas_completed=True,
            submission_state="submitted",
            submitted_at=done_due - timedelta(hours=5),
        )
    )
    db.commit()

    due_day = local_date(open_due)
    month = build_month(
        db,
        year=due_day.year,
        month=due_day.month,
        include_done=False,
        selected_day=due_day,
        today=due_day,
    )
    titles = [
        event.title
        for week in month.weeks
        for cell in week
        if cell.iso == due_day.isoformat()
        for event in cell.events
    ]
    assert titles == ["Essay"]
    assert month.selected_events[0].status in {"due_soon", "later", "overdue"}
    assert all(event.title != "Reading" for week in month.weeks for cell in week for event in cell.events)

    with_done = build_month(
        db,
        year=local_date(done_due).year,
        month=local_date(done_due).month,
        include_done=True,
        selected_day=local_date(done_due),
        today=local_date(done_due),
    )
    reading = [
        event
        for week in with_done.weeks
        for cell in week
        for event in cell.events
        if event.title == "Reading"
    ]
    assert len(reading) == 1
    assert reading[0].status == "completed"
    db.close()


def test_calendar_includes_pending_study_session():
    db = _session()
    course = Course(canvas_id=3, name="Math", course_code="MATH 140", active=True)
    db.add(course)
    db.flush()
    due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
    assignment = Assignment(
        canvas_id=30,
        course_id=course.id,
        name="Problem set",
        due_at=due,
        canvas_completed=False,
    )
    db.add(assignment)
    db.flush()
    plan = StudyPlan(assignment_id=assignment.id, title="Plan", backend="rules")
    db.add(plan)
    db.flush()
    session_day = datetime(2026, 10, 15, 0, 0)
    db.add(
        StudyBlock(
            plan_id=plan.id,
            scheduled_date=session_day,
            duration_min=45,
            topic="Practice / problem sets",
            status="pending",
            sort_order=0,
        )
    )
    db.commit()

    month = build_month(
        db,
        year=2026,
        month=10,
        selected_day=session_day.date(),
        today=session_day.date(),
    )
    study = [
        event
        for week in month.weeks
        for cell in week
        if cell.iso == "2026-10-15"
        for event in cell.events
        if event.kind == "study"
    ]
    assert len(study) == 1
    assert study[0].title == "Practice / problem sets"
    assert study[0].time_label == "45 min"
    db.close()
