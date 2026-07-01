from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models import AppSettings, Finding
from app.schemas import AIAnalysisResult
from app.services import save_analysis

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты аналитик конкурентной разведки. Проанализируй найденный контент и верни ТОЛЬКО валидный JSON без markdown.
Поля:
- entity_type: ad | mention | organic_result | post
- offer: коммерческое предложение или null
- cta: призыв к действию или null
- pain_points: массив болей аудитории
- tone: тональность
- hooks: массив ключевых триггеров
- intent: намерение (commercial, informational, brand, other)
- sentiment: positive | negative | neutral | mixed
- summary: краткое резюме 1-2 предложения
- is_competitor_related: true/false
"""


def _build_user_prompt(finding: Finding, competitor_name: str | None) -> str:
    parts = [
        f"Источник: {finding.source}",
        f"Тип: {finding.result_type}",
        f"Конкурент: {competitor_name or 'неизвестен'}",
        f"Заголовок: {finding.title or ''}",
        f"Текст: {finding.raw_text or finding.snippet or ''}",
        f"URL: {finding.url or ''}",
    ]
    return "\n".join(parts)


def _get_ai_config(app_settings: AppSettings | None) -> tuple[str, str, str]:
    env = get_settings()
    base_url = (app_settings.ai_base_url if app_settings else None) or env.ai_base_url
    api_key = (app_settings.ai_api_key if app_settings else None) or env.ai_api_key
    model = (app_settings.ai_model if app_settings else None) or env.ai_model
    return base_url, api_key, model


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
async def _call_llm(client: AsyncOpenAI, model: str, prompt: str) -> str:
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return response.choices[0].message.content or "{}"


def _parse_analysis(raw: str) -> AIAnalysisResult:
    data: dict[str, Any] = json.loads(raw)
    return AIAnalysisResult.model_validate(data)


async def analyze_finding(
    db: AsyncSession,
    finding: Finding,
    app_settings: AppSettings | None = None,
) -> AIAnalysisResult | None:
    base_url, api_key, model = _get_ai_config(app_settings)
    if not api_key:
        logger.warning("AI API key not configured, skipping analysis")
        return None

    competitor_name = finding.competitor.name if finding.competitor else None
    prompt = _build_user_prompt(finding, competitor_name)

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    try:
        raw = await _call_llm(client, model, prompt)
        result = _parse_analysis(raw)
    except (json.JSONDecodeError, ValidationError, httpx.HTTPError) as exc:
        logger.error("Failed to parse AI response: %s", exc)
        return None

    await save_analysis(db, finding.id, result.model_dump(), model)
    return result
