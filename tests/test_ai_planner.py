from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.services.ai.api import ApiPlanner
from app.services.ai.ollama import plan_from_text
from app.services.planner import PlanContext, get_planner


def _context() -> PlanContext:
    return PlanContext(
        assignment_title="Essay",
        course_name="ENG 200",
        due_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5),
        description_excerpt=None,
        hours_available=2.0,
        session_minutes=60,
    )


def test_get_planner_api_backend():
    assert isinstance(get_planner("api"), ApiPlanner)


def test_plan_from_text_reads_model_json():
    raw = '{"title": "Essay plan", "guide_outline": "Outline", "blocks": [{"topic": "Outline"}, {"topic": "Draft"}]}'
    result = plan_from_text(_context(), raw, backend="api")
    assert result.backend == "api"
    assert result.title == "Essay plan"
    assert [b.topic for b in result.blocks] == ["Outline", "Draft"]
    assert all(b.duration_min == 60 for b in result.blocks)


def test_plan_from_text_ignores_model_dates_past_due():
    due = datetime.now().astimezone().replace(hour=23, minute=59, second=0, microsecond=0) + timedelta(days=1)
    ctx = PlanContext(
        assignment_title="Content Quiz 4",
        course_name="PHYS 124",
        due_at=due.astimezone(timezone.utc).replace(tzinfo=None),
        description_excerpt=None,
        hours_available=4.0,
        session_minutes=45,
    )
    blocks = ",".join(f'{{"day_offset": {i}, "topic": "Topic {i}"}}' for i in range(5))
    result = plan_from_text(ctx, f'{{"title": "Plan", "blocks": [{blocks}]}}', backend="ollama")
    assert len(result.blocks) == 5
    assert max(b.scheduled_date.date() for b in result.blocks) <= due.date()


def test_api_planner_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "")
    get_settings.cache_clear()
    try:
        result = ApiPlanner().generate(_context())
    finally:
        get_settings.cache_clear()
    assert result.backend == "rules"
    assert "AI API key unavailable" in (result.guide_outline or "")
