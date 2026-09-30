from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from app.config import get_settings
from app.services.dates import to_local
from app.services.planner import (
    PHASE_TOPICS,
    PlanContext,
    PlannedBlock,
    RuleBasedPlanner,
    StudyPlanResult,
    schedule_sessions,
    session_count,
    session_length,
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
    due = to_local(context.due_at).strftime("%A %b %d, %I:%M %p") if context.due_at else "no due date"
    today = datetime.now().astimezone().strftime("%A %b %d")
    count = session_count(context)
    days = sorted({day.date() for day in schedule_sessions(context.due_at, count)})
    day_list = ", ".join(day.strftime("%a %b %d") for day in days)
    return f"""You are a study coach. Return ONLY valid JSON with this shape:
{{"title": str, "guide_outline": str, "blocks": [{{"topic": str}}]}}

Assignment: {context.assignment_title}
Course: {context.course_name}
Due: {due}
Today: {today}
Study days: {day_list}
Description excerpt: {(context.description_excerpt or "")[:800]}

Make exactly {count} blocks, in the order they should be studied. Each block is one
{session_length(context)}-minute session with a different, specific topic. The last block
should be a final review. Do not put dates or times in the topics. Do not include
markdown fences.
"""


def plan_from_text(context: PlanContext, raw: str, *, backend: str) -> StudyPlanResult:
    parsed = _extract_json(raw)
    title = parsed.get("title") or f"Study plan: {context.assignment_title}"
    outline = parsed.get("guide_outline") or ""
    count = session_count(context)
    topics = [
        str(b.get("topic") or "").strip()
        for b in parsed.get("blocks") or []
        if isinstance(b, dict) and str(b.get("topic") or "").strip()
    ][:count]
    if not topics:
        return RuleBasedPlanner().generate(context)
    while len(topics) < count:
        topics.append(PHASE_TOPICS[-1] if len(topics) == count - 1 else PHASE_TOPICS[2])

    days = schedule_sessions(context.due_at, count)
    blocks = [
        PlannedBlock(
            scheduled_date=days[i],
            duration_min=session_length(context),
            topic=topic,
            sort_order=i,
        )
        for i, topic in enumerate(topics)
    ]

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
