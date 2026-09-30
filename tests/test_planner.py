from datetime import datetime, timedelta, timezone

from app.services.planner import PlanContext, RuleBasedPlanner


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
