from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.services.planner import (
    PHASE_TOPICS,
    PlanContext,
    PlannedBlock,
    RuleBasedPlanner,
    StudyPlanResult,
)


class OllamaPlanner:
    """Local Ollama-backed planner. Falls back to rules if Ollama is unreachable."""

    def generate(self, context: PlanContext) -> StudyPlanResult:
        settings = get_settings()
        try:
            return self._generate_via_ollama(context, settings.ollama_base_url, settings.ollama_model)
        except Exception:
            return fallback_plan(context, "Ollama")

    def _generate_via_ollama(
        self,
        context: PlanContext,
        base_url: str,
        model: str,
    ) -> StudyPlanResult:
        payload = {
            "model": model,
            "prompt": build_prompt(context),
            "stream": False,
            "format": "json",
            "think": False,
        }
        # First request after startup loads the model into memory, which can take minutes.
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=240.0) as client:
            response = client.post("/api/generate", json=payload)
            if response.status_code == 400:
                # Models without a thinking mode reject the think option.
                payload.pop("think")
                response = client.post("/api/generate", json=payload)
            response.raise_for_status()
            raw = response.json().get("response") or ""
        return plan_from_text(context, raw, backend="ollama")


def build_prompt(context: PlanContext) -> str:
    due = context.due_at.isoformat() if context.due_at else "unknown"
    today = datetime.now(timezone.utc).date().isoformat()
    sessions = max(1, int(context.hours_available * 60) // max(15, context.session_minutes))
    return f"""You are a study coach. Return ONLY valid JSON with this shape:
{{"title": str, "guide_outline": str, "blocks": [{{"day_offset": int, "duration_min": int, "topic": str}}]}}

Assignment: {context.assignment_title}
Course: {context.course_name}
Due: {due}
Hours available: {context.hours_available}
Session minutes: {context.session_minutes}
Description excerpt: {(context.description_excerpt or "")[:800]}

Today is {today}. Make exactly {sessions} blocks of {context.session_minutes} minutes each,
spread across the days before the due date. day_offset is days from today (0 = today).
Give each block a different, specific topic. Do not include markdown fences.
"""


def plan_from_text(context: PlanContext, raw: str, *, backend: str) -> StudyPlanResult:
    parsed = _extract_json(raw)
    title = parsed.get("title") or f"Study plan: {context.assignment_title}"
    outline = parsed.get("guide_outline") or ""
    blocks_raw = parsed.get("blocks") or []
    now = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    blocks: list[PlannedBlock] = []
    for i, b in enumerate(blocks_raw):
        if not isinstance(b, dict):
            continue
        offset = int(b.get("day_offset") or 0)
        duration = int(b.get("duration_min") or context.session_minutes)
        topic = str(b.get("topic") or PHASE_TOPICS[min(i, len(PHASE_TOPICS) - 1)])
        blocks.append(
            PlannedBlock(
                scheduled_date=now + timedelta(days=max(0, offset)),
                duration_min=max(15, duration),
                topic=topic,
                sort_order=i,
            )
        )
    if not blocks:
        return RuleBasedPlanner().generate(context)

    return StudyPlanResult(
        title=title,
        guide_outline=outline,
        blocks=blocks,
        backend=backend,
    )


def fallback_plan(context: PlanContext, source: str) -> StudyPlanResult:
    fallback = RuleBasedPlanner().generate(context)
    fallback.guide_outline = (
        f"({source} unavailable — used rule-based plan)\n\n" + (fallback.guide_outline or "")
    )
    return fallback


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
