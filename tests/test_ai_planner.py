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
    raw = '{"title": "Essay plan", "guide_outline": "Outline", "blocks": [{"day_offset": 1, "duration_min": 60, "topic": "Draft"}]}'
    result = plan_from_text(_context(), raw, backend="api")
    assert result.backend == "api"
    assert result.title == "Essay plan"
    assert [b.topic for b in result.blocks] == ["Draft"]


def test_api_planner_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "")
    get_settings.cache_clear()
    try:
        result = ApiPlanner().generate(_context())
    finally:
        get_settings.cache_clear()
    assert result.backend == "rules"
    assert "AI API key unavailable" in (result.guide_outline or "")
