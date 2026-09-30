from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import Settings

LINK_RE = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


def parse_link_header(header: str | None) -> dict[str, str]:
    """Parse Canvas/GitHub-style Link header into rel -> url map."""
    if not header:
        return {}
    links: dict[str, str] = {}
    for match in LINK_RE.finditer(header):
        url, rel = match.group(1), match.group(2)
        links[rel] = url
    return links


class CanvasAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CanvasClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base_url = settings.canvas_base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {settings.canvas_access_token}",
                "Accept": "application/json",
            },
            timeout=60.0,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> CanvasClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))
        retries = 4
        delay = 1.0
        for attempt in range(retries):
            response = await self._client.request(method, url, **kwargs)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                await asyncio.sleep(wait)
                delay = min(delay * 2, 30.0)
                continue
            if response.status_code >= 500 and attempt < retries - 1:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if response.status_code >= 400:
                raise CanvasAPIError(
                    f"Canvas API {response.status_code}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            return response
        raise CanvasAPIError("Canvas API request failed after retries")

    async def get_paginated(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        items: list[dict[str, Any]] = []
        next_url: str | None = path if not path.startswith("http") else path
        query = params

        while next_url:
            response = await self._request("GET", next_url, params=query)
            data = response.json()
            if isinstance(data, list):
                items.extend(data)
            else:
                # Some endpoints wrap payloads; keep raw object as single item.
                items.append(data)
            links = parse_link_header(response.headers.get("Link"))
            next_url = links.get("next")
            query = None  # next URL already includes query string
        return items

    async def get_courses(self, enrollment_state: str = "active") -> list[dict[str, Any]]:
        return await self.get_paginated(
            "/api/v1/courses",
            params={
                "enrollment_state": enrollment_state,
                "include[]": ["term"],
            },
        )

    async def get_assignments(self, course_id: int) -> list[dict[str, Any]]:
        return await self.get_paginated(
            f"/api/v1/courses/{course_id}/assignments",
            params={"order_by": "due_at", "include[]": ["submission"]},
        )

    async def get_planner_items(self) -> list[dict[str, Any]]:
        return await self.get_paginated("/api/v1/planner/items")
