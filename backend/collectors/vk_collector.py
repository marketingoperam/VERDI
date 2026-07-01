from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import vk_api
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models import Competitor
from collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class VKCollector(BaseCollector):
    name = "vk"

    def _resolve_owner_id(self, competitor: Competitor, domain: str) -> str | int | None:
        if domain.lstrip("-").isdigit():
            return int(domain)
        for oid in competitor.vk_owner_ids or []:
            if oid == domain:
                return oid
        return domain

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def _wall_get(self, vk, owner: str | int, count: int = 50) -> list[dict[str, Any]]:
        return vk.wall.get(owner_id=owner, count=count).get("items", [])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def _newsfeed_search(self, vk, query: str, count: int = 50) -> list[dict[str, Any]]:
        try:
            return vk.newsfeed.search(q=query, count=count).get("items", [])
        except vk_api.exceptions.ApiError as exc:
            if exc.code in {15, 28}:
                logger.warning("VK newsfeed.search unavailable: %s", exc)
                return []
            raise

    def _post_url(self, owner_id: int, post_id: int) -> str:
        return f"https://vk.com/wall{owner_id}_{post_id}"

    def _matches_keywords(self, text: str, keywords: list[str]) -> bool:
        if not keywords:
            return True
        lower = text.lower()
        return any(kw.lower() in lower for kw in keywords if kw)

    async def collect(self) -> int:
        total_saved = 0
        async with self.session_factory() as db:
            app_settings = await self._get_runtime_settings(db)
            if not app_settings.vk_enabled:
                logger.info("VK collector disabled")
                return 0

            token = app_settings.vk_access_token or self.settings.vk_access_token
            if not token:
                raise ValueError("VK access token is required")

            session = vk_api.VkApi(token=token)
            vk = session.get_api()
            competitors = await self._get_competitors(db)

            for competitor in competitors:
                keywords = (competitor.brand_keywords or []) + (
                    competitor.money_keywords or []
                )

                owners: list[str | int] = []
                for domain in competitor.vk_domains or []:
                    owners.append(self._resolve_owner_id(competitor, domain))
                for oid in competitor.vk_owner_ids or []:
                    if oid not in owners:
                        owners.append(oid)

                for owner in owners:
                    try:
                        posts = self._wall_get(vk, owner)
                    except Exception as exc:
                        logger.warning("VK wall.get failed for %s: %s", owner, exc)
                        continue

                    for post in posts:
                        text = post.get("text", "")
                        if not self._matches_keywords(text, keywords):
                            continue

                        owner_id = post.get("owner_id", owner)
                        post_id = post.get("id")
                        published = datetime.fromtimestamp(
                            post.get("date", 0), tz=timezone.utc
                        ).replace(tzinfo=None)

                        finding_data = {
                            "competitor_id": competitor.id,
                            "source": "vk",
                            "result_type": "post",
                            "external_id": f"{owner_id}_{post_id}",
                            "title": text[:120] if text else None,
                            "raw_text": text,
                            "url": self._post_url(owner_id, post_id),
                            "channel_name": str(owner),
                            "likes": post.get("likes", {}).get("count"),
                            "reposts": post.get("reposts", {}).get("count"),
                            "comments": post.get("comments", {}).get("count"),
                            "views": post.get("views", {}).get("count")
                            if isinstance(post.get("views"), dict)
                            else post.get("views"),
                            "published_at": published,
                            "raw_json": post,
                        }
                        if await self._save_and_analyze(db, finding_data, app_settings):
                            total_saved += 1

                search_queries = keywords[:5]
                for query in search_queries:
                    if not query.strip():
                        continue
                    try:
                        items = self._newsfeed_search(vk, query)
                    except Exception as exc:
                        logger.warning("VK search failed for %s: %s", query, exc)
                        continue

                    for post in items:
                        text = post.get("text", "")
                        owner_id = post.get("owner_id", 0)
                        post_id = post.get("id", 0)
                        finding_data = {
                            "competitor_id": competitor.id,
                            "source": "vk",
                            "result_type": "mention",
                            "external_id": f"search_{owner_id}_{post_id}",
                            "title": text[:120] if text else None,
                            "raw_text": text,
                            "url": self._post_url(owner_id, post_id),
                            "channel_name": str(owner_id),
                            "published_at": datetime.fromtimestamp(
                                post.get("date", 0), tz=timezone.utc
                            ).replace(tzinfo=None),
                            "raw_json": post,
                        }
                        if await self._save_and_analyze(db, finding_data, app_settings):
                            total_saved += 1

        return total_saved
