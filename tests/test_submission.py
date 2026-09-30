from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.canvas.sync import read_submission
from app.db.models import Assignment, Base, Course
from app.services.tracker import list_assignments


def test_read_submission_submitted():
    completed, state, submitted_at = read_submission(
        {
            "submission": {
                "workflow_state": "submitted",
                "submitted_at": "2026-09-28T18:00:00Z",
            }
        }
    )
    assert completed is True
    assert state == "submitted"
    assert submitted_at == datetime(2026, 9, 28, 18, 0)


def test_read_submission_unsubmitted_is_open():
    completed, state, submitted_at = read_submission(
        {"submission": {"workflow_state": "unsubmitted", "missing": True}}
    )
    assert completed is False
    assert state == "unsubmitted"
    assert submitted_at is None


def test_read_submission_excused_and_graded():
    assert read_submission({"submission": {"workflow_state": "unsubmitted", "excused": True}})[0] is True
    assert read_submission({"submission": {"workflow_state": "graded"}})[0] is True
    assert read_submission({})[0] is False


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_canvas_completed_is_not_overdue():
    db = _session()
    course = Course(canvas_id=1, name="Biology", course_code="BIO 101", active=True)
    db.add(course)
    db.flush()
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
    db.add(
        Assignment(
            canvas_id=10,
            course_id=course.id,
            name="Lab report",
            due_at=past,
            canvas_completed=True,
            submission_state="graded",
            submitted_at=past - timedelta(days=1),
        )
    )
    db.add(
        Assignment(
            canvas_id=11,
            course_id=course.id,
            name="Quiz",
            due_at=past,
            canvas_completed=False,
            submission_state="unsubmitted",
        )
    )
    db.commit()

    overdue = list_assignments(db, range_filter="overdue", include_done=True)
    assert [item.name for item in overdue] == ["Quiz"]
    assert overdue[0].status == "overdue"

    hidden = list_assignments(db, range_filter="all")
    assert [item.name for item in hidden] == ["Quiz"]

    shown = list_assignments(db, range_filter="all", include_done=True)
    by_name = {item.name: item for item in shown}
    assert by_name["Lab report"].status == "completed"
    assert by_name["Lab report"].canvas_completed is True
    db.close()
