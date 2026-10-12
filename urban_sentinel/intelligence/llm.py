from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from urban_sentinel.core.config import Settings
from urban_sentinel.intelligence.exceptions import LlmTimeoutError


class LLMClient(Protocol):
    provider: str
    model_version: str
    available: bool

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout: float,
    ) -> BaseModel: ...


class NullLLM:
    provider = "none"
    model_version = "deterministic-v1"
    available = False

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout: float,
    ) -> BaseModel:
        raise LlmTimeoutError("LLM provider is not configured")


class ScriptedLLM:
    """Test double that returns queued Pydantic-compatible payloads."""

    provider = "scripted"
    model_version = "scripted-v1"
    available = True

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, str]] = []
        self.force_timeout = False
        self.invalid_once = False

    def queue(self, payload: dict[str, Any]) -> None:
        self._responses.append(payload)

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout: float,
    ) -> BaseModel:
        self.calls.append({"system": system, "user": user})
        if self.force_timeout:
            raise LlmTimeoutError("scripted LLM timeout")
        if self.invalid_once:
            self.invalid_once = False
            raise ValueError("scripted invalid output")
        if not self._responses:
            raise LlmTimeoutError("scripted LLM has no queued responses")
        payload = self._responses.pop(0)
        return schema.model_validate(payload)


class OpenAILLM:
    provider = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model_version = model
        self.available = bool(api_key)

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout: float,
    ) -> BaseModel:
        if not self.available:
            raise LlmTimeoutError("OpenAI API key missing")
        body = {
            "model": self.model_version,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError("OpenAI request timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise LlmTimeoutError(f"OpenAI request failed: {exc}") from exc
        return schema.model_validate(json.loads(content))


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model_version = model
        self.available = bool(api_key)

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout: float,
    ) -> BaseModel:
        if not self.available:
            raise LlmTimeoutError("Anthropic API key missing")
        body = {
            "model": self.model_version,
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                content = response.json()["content"][0]["text"]
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError("Anthropic request timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise LlmTimeoutError(f"Anthropic request failed: {exc}") from exc
        return schema.model_validate(json.loads(content))


def build_llm(settings: Settings, override: LLMClient | None = None) -> LLMClient:
    if override is not None:
        return override
    provider = settings.llm_provider
    if provider == "openai" and settings.openai_api_key:
        return OpenAILLM(settings.openai_api_key, settings.openai_model)
    if provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicLLM(settings.anthropic_api_key, settings.anthropic_model)
    return NullLLM()
