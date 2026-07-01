from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models import AppSettings, Competitor
from collectors.base import BaseCollector

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


class GoogleCollector(BaseCollector):
    name = "google"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    async def _search(
        self,
        client: httpx.AsyncClient,
        query: str,
        api_key: str,
        cx: str,
        start: int,
        num: int,
    ) -> dict[str, Any]:
        params = {
            "key": api_key,
            "cx": cx,
            "q": query,
            "start": start,
            "num": min(num, 10),
            "lr": "lang_ru|lang_en",
        }
        response = await client.get(GOOGLE_SEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    async def collect(self) -> int:
        total_saved = 0
        async with self.session_factory() as db:
            app_settings = await self._get_runtime_settings(db)
            if not app_settings.google_enabled:
                logger.info("Google collector disabled")
                return 0

            api_key = app_settings.google_api_key or self.settings.google_api_key
            cx = app_settings.google_cx or self.settings.google_cx
            if not api_key or not cx:
                raise ValueError("Google API key and CX are required")

            competitors = await self._get_competitors(db)
            max_results = self.settings.max_results_per_query

            async with httpx.AsyncClient() as client:
                for competitor in competitors:
                    queries = competitor.google_queries or []
                    if not queries:
                        queries = (competitor.brand_keywords or []) + (
                            competitor.money_keywords or []
                        )

                    for query in queries:
                        if not query.strip():
                            continue
                        position = 0
                        for start in range(1, max_results + 1, 10):
                            try:
                                data = await self._search(
                                    client, query, api_key, cx, start, 10
                                )
                            except httpx.HTTPError as exc:
                                logger.warning("Google search failed for %s: %s", query, exc)
                                break

                            items = data.get("items", [])
                            if not items:
                                break

                            for item in items:
                                position += 1
                                finding_data = {
                                    "competitor_id": competitor.id,
                                    "source": "google",
                                    "result_type": "organic_result",
                                    "external_id": item.get("cacheId") or item.get("link"),
                                    "title": item.get("title"),
                                    "snippet": item.get("snippet"),
                                    "raw_text": f"{item.get('title', '')}\n{item.get('snippet', '')}",
                                    "url": item.get("link"),
                                    "position": position,
                                    "published_at": None,
                                    "raw_json": item,
                                }
                                if await self._save_and_analyze(db, finding_data, app_settings):
                                    total_saved += 1

                            if position >= max_results:
                                break

        return total_saved
