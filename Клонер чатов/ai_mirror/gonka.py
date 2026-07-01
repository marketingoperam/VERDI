"""OpenAI-compatible client for https://proxy.gonka.gg/v1"""

from __future__ import annotations

import os

import httpx

DEFAULT_BASE = "https://proxy.gonka.gg/v1"
DEFAULT_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"


class GonkaClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GONKA_API_KEY", "")
        self.base_url = (base_url or os.environ.get("GONKA_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.model = model or os.environ.get("GONKA_MODEL") or DEFAULT_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("GONKA_API_KEY не задан в ai_mirror/.env")

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
