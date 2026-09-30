from __future__ import annotations

import httpx

from app.config import get_settings
from app.services.ai.ollama import build_prompt, fallback_plan, plan_from_text
from app.services.planner import PlanContext, StudyPlanResult


class ApiPlanner:
    """Planner for any OpenAI-compatible chat API. Falls back to rules on failure."""

    def generate(self, context: PlanContext) -> StudyPlanResult:
        settings = get_settings()
        if not settings.ai_api_key:
            return fallback_plan(context, "AI API key")
        try:
            payload = {
                "model": settings.ai_model,
                "messages": [{"role": "user", "content": build_prompt(context)}],
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {settings.ai_api_key}"}
            with httpx.Client(base_url=settings.ai_base_url.rstrip("/"), timeout=60.0) as client:
                response = client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"] or ""
            return plan_from_text(context, raw, backend="api")
        except Exception:
            return fallback_plan(context, "AI API")
