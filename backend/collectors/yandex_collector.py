from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from collectors.base import BaseCollector

logger = logging.getLogger(__name__)

YANDEX_SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"


class YandexCollector(BaseCollector):
    name = "yandex"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    async def _search(
        self,
        client: httpx.AsyncClient,
        query: str,
        api_key: str,
        folder_id: str,
        region: str | None,
        page: int,
    ) -> dict[str, Any]:
        body = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": query,
                "familyMode": "FAMILY_MODE_MODERATE",
                "page": str(page),
            },
            "sortSpec": {"sortMode": "SORT_MODE_BY_RELEVANCE"},
            "groupSpec": {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": "10"},
            "maxPassages": 3,
            "region": region or "225",
            "l10n": "LOCALIZATION_RU",
            "responseFormat": "FORMAT_XML",
        }
        headers = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
        }
        response = await client.post(
            YANDEX_SEARCH_URL,
            json=body,
            headers=headers,
            params={"folderId": folder_id},
            timeout=45,
        )
        response.raise_for_status()
        return response.json()

    def _parse_xml_results(self, raw_xml: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            root = ElementTree.fromstring(raw_xml)
        except ElementTree.ParseError:
            return results

        for idx, doc in enumerate(root.iter("doc"), start=1):
            url_el = doc.find(".//url")
            title_el = doc.find(".//title")
            passage_el = doc.find(".//passage")
            is_ad = doc.find(".//ad") is not None or "adv" in (url_el.text or "").lower()

            results.append(
                {
                    "position": idx,
                    "url": url_el.text if url_el is not None else None,
                    "title": title_el.text if title_el is not None else None,
                    "snippet": passage_el.text if passage_el is not None else None,
                    "result_type": "ad" if is_ad else "organic_result",
                }
            )
        return results

    async def collect(self) -> int:
        total_saved = 0
        async with self.session_factory() as db:
            app_settings = await self._get_runtime_settings(db)
            if not app_settings.yandex_enabled:
                logger.info("Yandex collector disabled")
                return 0

            api_key = app_settings.yandex_api_key or self.settings.yandex_api_key
            folder_id = app_settings.yandex_folder_id or self.settings.yandex_folder_id
            if not api_key or not folder_id:
                raise ValueError("Yandex API key and folder ID are required")

            competitors = await self._get_competitors(db)

            async with httpx.AsyncClient() as client:
                for competitor in competitors:
                    queries = competitor.yandex_queries or []
                    if not queries:
                        queries = (competitor.brand_keywords or []) + (
                            competitor.money_keywords or []
                        )

                    for query in queries:
                        if not query.strip():
                            continue
                        try:
                            data = await self._search(
                                client,
                                query,
                                api_key,
                                folder_id,
                                competitor.region,
                                page=0,
                            )
                        except httpx.HTTPError as exc:
                            logger.warning("Yandex search failed for %s: %s", query, exc)
                            continue

                        raw_xml = data.get("rawData", "")
                        for item in self._parse_xml_results(raw_xml):
                            finding_data = {
                                "competitor_id": competitor.id,
                                "source": "yandex",
                                "result_type": item["result_type"],
                                "external_id": item.get("url"),
                                "title": item.get("title"),
                                "snippet": item.get("snippet"),
                                "raw_text": f"{item.get('title', '')}\n{item.get('snippet', '')}",
                                "url": item.get("url"),
                                "position": item.get("position"),
                                "raw_json": item,
                            }
                            if await self._save_and_analyze(db, finding_data, app_settings):
                                total_saved += 1

        return total_saved
