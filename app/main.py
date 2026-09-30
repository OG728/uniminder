from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.canvas.sync import get_meta, sync_canvas
from app.config import get_settings
from app.db.database import get_db, init_db
from app.services import calendar as calendar_service
from app.services import planner as planner_service
from app.services import tracker as tracker_service
from app.services.dates import to_local

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


async def _background_sync_loop() -> None:
    settings = get_settings()
    interval = max(5, settings.sync_interval_minutes) * 60
    while True:
        await asyncio.sleep(interval)
        try:
            from app.db.database import SessionLocal

            db = SessionLocal()
            try:
                await sync_canvas(db, settings)
            finally:
                db.close()
        except Exception:
            # Background sync failures are non-fatal; user can Sync Now.
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_background_sync_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="UNI Reminder", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

DbDep = Annotated[Session, Depends(get_db)]


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%a %b %d, %Y %H:%M")


def _fmt_due(value: datetime | None) -> str:
    """Format a Canvas due/submitted timestamp in local time."""
    if value is None:
        return "—"
    local = to_local(value)
    return local.strftime("%a %b %d, %Y %H:%M")


templates.env.filters["fmt_dt"] = _fmt_dt
templates.env.filters["fmt_due"] = _fmt_due


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _query_builder(
    *,
    view: str,
    range_filter: str,
    course_id: int | None,
    include_done: bool,
    month: str | None,
    day: str | None,
):
    base: dict[str, Any] = {
        "view": view,
        "range": range_filter,
        "course_id": course_id,
        "include_done": "1" if include_done else None,
        "month": month,
        "day": day,
    }

    def build(**overrides: Any) -> str:
        merged = dict(base)
        for key, value in overrides.items():
            if value is None and key in overrides:
                merged.pop(key, None)
            else:
                merged[key] = value
        pairs = [(key, value) for key, value in merged.items() if value is not None and value != ""]
        return urlencode(pairs)

    return build


def _page_context(
    db: Session,
    *,
    view: Literal["calendar", "list"],
    range_filter: Literal["all", "week", "overdue", "later"],
    course_id: int | None,
    include_done: bool,
    month: str | None,
    day: str | None,
    selected_id: int | None,
    selected_assignment,
    plan,
    panel_open: bool,
) -> dict[str, Any]:
    assignments = tracker_service.list_assignments(
        db,
        range_filter=range_filter,
        course_id=course_id,
        include_done=include_done,
    )
    courses = tracker_service.list_courses(db)
    year, month_num = calendar_service.parse_month(month)
    selected_day = calendar_service.parse_day(day)
    calendar = None
    if view == "calendar":
        calendar = calendar_service.build_month(
            db,
            year=year,
            month=month_num,
            course_id=course_id,
            include_done=include_done,
            selected_day=selected_day,
        )
        month_key = calendar.month_key
        day_key = day if selected_day else None
    else:
        month_key = f"{year:04d}-{month_num:02d}"
        day_key = day
    settings = get_settings()
    return {
        "assignments": assignments,
        "courses": courses,
        "range": range_filter,
        "course_id": course_id,
        "include_done": include_done,
        "last_sync": get_meta(db, "last_sync_at"),
        "planner_backend": settings.planner_backend,
        "selected_id": selected_id,
        "plan": plan,
        "selected_assignment": selected_assignment,
        "panel_open": panel_open,
        "view": view,
        "calendar": calendar,
        "month_key": month_key,
        "q": _query_builder(
            view=view,
            range_filter=range_filter,
            course_id=course_id,
            include_done=include_done,
            month=month_key if view == "calendar" else month,
            day=day_key if view == "calendar" else day,
        ),
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: DbDep,
    view: Literal["calendar", "list"] = Query("calendar"),
    range: Literal["all", "week", "overdue", "later"] = Query("week"),
    course_id: str | None = None,
    include_done: bool = False,
    month: str | None = None,
    day: str | None = None,
):
    cid = parse_optional_int(course_id)
    return templates.TemplateResponse(
        request,
        "index.html",
        _page_context(
            db,
            view=view,
            range_filter=range,
            course_id=cid,
            include_done=include_done,
            month=month,
            day=day,
            selected_id=None,
            selected_assignment=None,
            plan=None,
            panel_open=False,
        ),
    )


@app.post("/api/sync")
async def api_sync(db: DbDep):
    try:
        stats = await sync_canvas(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Canvas sync failed: {exc}") from exc
    return {"ok": True, "stats": stats, "last_sync": get_meta(db, "last_sync_at")}


@app.get("/api/assignments")
async def api_assignments(
    db: DbDep,
    range: Literal["all", "week", "overdue", "later"] = Query("week"),
    course_id: str | None = None,
    include_done: bool = False,
):
    items = tracker_service.list_assignments(
        db,
        range_filter=range,
        course_id=parse_optional_int(course_id),
        include_done=include_done,
    )
    return [
        {
            "id": a.id,
            "name": a.name,
            "course_name": a.course_name,
            "course_code": a.course_code,
            "due_at": a.due_at.isoformat() if a.due_at else None,
            "status": a.status,
            "done": a.done,
            "ignored": a.ignored,
            "canvas_completed": a.canvas_completed,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "html_url": a.html_url,
            "points": a.points,
        }
        for a in items
    ]


class OverrideBody(BaseModel):
    done: bool | None = None
    ignored: bool | None = None
    priority: int | None = None
    notes: str | None = None


@app.post("/api/assignments/{assignment_id}/override")
async def api_override(assignment_id: int, body: OverrideBody, db: DbDep):
    try:
        override = tracker_service.upsert_override(
            db,
            assignment_id,
            done=body.done,
            ignored=body.ignored,
            priority=body.priority,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "assignment_id": override.assignment_id,
        "done": override.done,
        "ignored": override.ignored,
        "priority": override.priority,
        "notes": override.notes,
    }


class PlanBody(BaseModel):
    hours_available: float = Field(default=4.0, ge=0.5, le=80)
    session_minutes: int = Field(default=45, ge=15, le=180)
    study_days: list[str] | None = None


@app.post("/api/assignments/{assignment_id}/plan")
async def api_create_plan(assignment_id: int, body: PlanBody, db: DbDep):
    settings = get_settings()
    study_days: list[datetime] = []
    if body.study_days:
        for day in body.study_days:
            try:
                study_days.append(datetime.fromisoformat(day))
            except ValueError:
                continue
    try:
        plan = planner_service.create_study_plan(
            db,
            assignment_id,
            hours_available=body.hours_available,
            session_minutes=body.session_minutes,
            study_days=study_days or None,
            backend=settings.planner_backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _plan_payload(plan)


@app.get("/api/assignments/{assignment_id}/plan")
async def api_get_plan(assignment_id: int, db: DbDep):
    plan = planner_service.get_latest_plan(db, assignment_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No study plan yet")
    return _plan_payload(plan)


@app.post("/api/blocks/{block_id}/status")
async def api_block_status(
    block_id: int,
    db: DbDep,
    status: Literal["pending", "done", "skipped"] = Form(...),
):
    try:
        block = planner_service.set_block_status(db, block_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": block.id, "status": block.status}


@app.get("/plan/{assignment_id}", response_class=HTMLResponse)
async def plan_panel(
    request: Request,
    assignment_id: int,
    db: DbDep,
    view: Literal["calendar", "list"] = Query("calendar"),
    range: Literal["all", "week", "overdue", "later"] = Query("week"),
    course_id: str | None = None,
    include_done: bool = False,
    month: str | None = None,
    day: str | None = None,
):
    cid = parse_optional_int(course_id)
    visible = tracker_service.list_assignments(
        db,
        range_filter=range,
        course_id=cid,
        include_done=include_done,
    )
    selected = next((a for a in visible if a.id == assignment_id), None)
    if selected is None:
        all_items = tracker_service.list_assignments(
            db, range_filter="all", include_done=True, include_ignored=True
        )
        selected = next((a for a in all_items if a.id == assignment_id), None)
    plan = planner_service.get_latest_plan(db, assignment_id)
    context = _page_context(
        db,
        view=view,
        range_filter=range,
        course_id=cid,
        include_done=include_done,
        month=month,
        day=day,
        selected_id=assignment_id,
        selected_assignment=selected,
        plan=plan,
        panel_open=True,
    )
    return templates.TemplateResponse(request, "index.html", context)


def _plan_payload(plan) -> dict:
    return {
        "id": plan.id,
        "assignment_id": plan.assignment_id,
        "title": plan.title,
        "guide_outline": plan.guide_outline,
        "backend": plan.backend,
        "hours_available": plan.hours_available,
        "session_minutes": plan.session_minutes,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "blocks": [
            {
                "id": b.id,
                "scheduled_date": b.scheduled_date.isoformat() if b.scheduled_date else None,
                "duration_min": b.duration_min,
                "topic": b.topic,
                "status": b.status,
                "sort_order": b.sort_order,
            }
            for b in plan.blocks
        ],
    }


@app.get("/health")
async def health():
    return {"ok": True}
