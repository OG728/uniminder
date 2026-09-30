from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Assignment, Base, Course, PlannerItem
from app.services.dates import to_local
from app.services.due_dates import apply_calendar_due_dates, parse_due_from_title, titles_match


def test_titles_match_quiz_number_boundary():
    assert titles_match("Content Quiz 4 (Due Oct 1, 2026 at 11:59 p.m.)", "Content Quiz 4")
    assert titles_match("Content Quiz 10 (Due Dec 7, 2026 at 11:59 p.m.)", "Content Quiz 10")
    assert not titles_match("Content Quiz 10 (Due Dec 7, 2026 at 11:59 p.m.)", "Content Quiz 1")
    assert titles_match("Midterm 1", "Midterm 1")


def test_parse_due_from_title_keeps_local_clock_time():
    parsed = parse_due_from_title("Content Quiz 4 (Due Oct 1, 2026 at 11:59 p.m.)")
    assert parsed is not None
    local = to_local(parsed)
    assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 10, 1, 23, 59)

    reading = parse_due_from_title("Reading Quiz 5 (Due Oct 19, 2026; 9:30 a.m.)")
    assert reading is not None
    local = to_local(reading)
    assert (local.month, local.day, local.hour, local.minute) == (10, 19, 9, 30)

    messy = parse_due_from_title("Reading Quiz 4 (Due Sept 28, 2026) at 9:30 a.m.)")
    assert messy is not None
    local = to_local(messy)
    assert (local.month, local.day, local.hour, local.minute) == (9, 28, 9, 30)


def test_apply_calendar_event_due_date_without_overwriting_real_due():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    course = Course(canvas_id=33885, name="PHYS 124", course_code="PHYS 124", active=True)
    db.add(course)
    db.flush()
    quiz = Assignment(
        canvas_id=1,
        course_id=course.id,
        name="Content Quiz 4 (Due Oct 1, 2026 at 11:59 p.m.)",
        due_at=None,
    )
    already = Assignment(
        canvas_id=2,
        course_id=course.id,
        name="Lab report",
        due_at=datetime(2026, 10, 3, 18, 0),
    )
    db.add_all([quiz, already])
    db.add(
        PlannerItem(
            plannable_type="calendar_event",
            plannable_id=180685,
            course_canvas_id=33885,
            title="Content Quiz 4",
            due_at=datetime(2026, 10, 2, 5, 59),
        )
    )
    db.commit()

    filled = apply_calendar_due_dates(db)
    db.commit()
    assert filled == 1
    assert quiz.due_at == datetime(2026, 10, 2, 5, 59)
    assert already.due_at == datetime(2026, 10, 3, 18, 0)
    db.close()
