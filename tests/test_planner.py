from datetime import date, datetime, timedelta, timezone

from app.services.planner import PlanContext, RuleBasedPlanner, schedule_sessions


def _utc(local: datetime) -> datetime:
    return local.astimezone().astimezone(timezone.utc).replace(tzinfo=None)


def test_schedule_never_goes_past_evening_due_date():
    today = date(2026, 9, 30)
    due = _utc(datetime(2026, 10, 1, 23, 59))
    days = [d.date() for d in schedule_sessions(due, 5, today=today)]
    assert days == [today, today, today, date(2026, 10, 1), date(2026, 10, 1)]


def test_schedule_morning_deadline_stops_the_day_before():
    today = date(2026, 9, 30)
    due = _utc(datetime(2026, 10, 3, 9, 30))
    days = [d.date() for d in schedule_sessions(due, 3, today=today)]
    assert days[0] == today
    assert max(days) == date(2026, 10, 2)


def test_schedule_spreads_out_when_there_is_time():
    today = date(2026, 9, 30)
    due = _utc(datetime(2026, 10, 9, 23, 59))
    days = [d.date() for d in schedule_sessions(due, 4, today=today)]
    assert days == [today, date(2026, 10, 3), date(2026, 10, 6), date(2026, 10, 9)]


def test_schedule_overdue_puts_everything_today():
    today = date(2026, 9, 30)
    due = _utc(datetime(2026, 9, 28, 23, 59))
    days = {d.date() for d in schedule_sessions(due, 3, today=today)}
    assert days == {today}


def test_rule_planner_creates_sessions_from_hours():
    due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=10)
    ctx = PlanContext(
        assignment_title="Midterm Review",
        course_name="CS 101",
        due_at=due,
        description_excerpt="Chapters 1-4",
        hours_available=3.0,
        session_minutes=45,
    )
    result = RuleBasedPlanner().generate(ctx)
    assert result.backend == "rules"
    assert "Midterm Review" in result.title
    assert len(result.blocks) == 4  # 180 min / 45
    assert all(b.duration_min == 45 for b in result.blocks)
    assert result.blocks[-1].topic == "Final pass & self-check"
    assert result.guide_outline is not None


def test_rule_planner_respects_study_days():
    day1 = datetime(2026, 9, 16)
    day2 = datetime(2026, 9, 18)
    ctx = PlanContext(
        assignment_title="Essay",
        course_name="ENG 200",
        due_at=datetime(2026, 9, 20),
        description_excerpt=None,
        hours_available=1.5,
        session_minutes=45,
        study_days=[day1, day2],
    )
    result = RuleBasedPlanner().generate(ctx)
    assert len(result.blocks) == 2
    assert result.blocks[0].scheduled_date.date() == day1.date()
    assert result.blocks[1].scheduled_date.date() == day2.date()


def test_rule_planner_minimum_one_session():
    ctx = PlanContext(
        assignment_title="Quiz",
        course_name="MATH",
        due_at=None,
        description_excerpt=None,
        hours_available=0.5,
        session_minutes=60,
    )
    result = RuleBasedPlanner().generate(ctx)
    assert len(result.blocks) >= 1
