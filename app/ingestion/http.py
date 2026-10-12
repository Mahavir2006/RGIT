"""Shared async HTTP client for provider calls.

Centralising this gives every adapter the same guarantees:

* explicit, configurable timeouts
* bounded retries with exponential backoff and jitter
* provider rate-limit detection with ``Retry-After`` support
* credential failures that are **never** retried
* URLs scrubbed of credentials before they reach a log line
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Any, Mapping

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import (
    CredentialMissingError,
    RateLimitError,
    UpstreamAuthError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from app.core.logging import get_logger
from app.core.timeutil import utc_now
from app.schemas.ingestion import RunError

__all__ = ["ProviderClient", "build_client", "classify_status"]

logger = get_logger(__name__)

# Status codes worth retrying. Everything else is either terminal or a caller error.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def classify_status(status_code: int, provider: str, retry_after: str | None = None) -> None:
    """Map an HTTP status onto the right domain error, or return if retryable.

    Raises:
        UpstreamAuthError: 401/403 — never retried, because retrying bad credentials is
            pointless and can lock an account.
        RateLimitError: 429.
        UpstreamUnavailableError: other 4xx/5xx that are terminal.
    """
    if status_code in (401, 403):
        raise UpstreamAuthError(
            f"{provider} rejected the request as unauthorised (HTTP {status_code}). "
            f"Check the configured API key and that the plan permits this endpoint.",
            details={"provider": provider, "status_code": status_code},
        )
    if status_code == 429:
        raise RateLimitError(
            f"{provider} rate limit reached (HTTP 429)."
            + (f" Retry after {retry_after}s." if retry_after else ""),
            details={"provider": provider, "status_code": status_code, "retry_after": retry_after},
        )
    if status_code not in RETRYABLE_STATUS:
        raise UpstreamUnavailableError(
            f"{provider} returned an unusable response (HTTP {status_code}).",
            details={"provider": provider, "status_code": status_code},
        )


class ProviderClient:
    """Thin wrapper around ``httpx.AsyncClient`` with retry and error classification."""

    def __init__(
        self,
        provider: str,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(self.settings.http_timeout_seconds)
            self._client = httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": self.settings.http_user_agent},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "ProviderClient":
        self._ensure_client()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _backoff_delay(self, attempt: int, retry_after: str | None = None) -> float:
        """Exponential backoff with full jitter, honouring ``Retry-After`` when present."""
        if retry_after:
            try:
                return min(float(retry_after), self.settings.http_backoff_max_seconds)
            except (TypeError, ValueError):
                pass
        window = min(
            self.settings.http_backoff_base_seconds * (2 ** attempt),
            self.settings.http_backoff_max_seconds,
        )
        return random.uniform(0.0, window)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        max_attempts: int | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> httpx.Response:
        """Perform a request with bounded retries.

        Args:
            allow_status: status codes to return instead of raising (e.g. 404 for a
                single-record lookup).

        Raises:
            UpstreamTimeoutError, UpstreamAuthError, RateLimitError, UpstreamUnavailableError.
        """
        client = self._ensure_client()
        attempts = max_attempts or (self.settings.http_max_retries + 1)
        started = utc_now()
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await client.request(
                    method,
                    url,
                    headers=dict(headers or {}),
                    params=dict(params or {}),
                    timeout=timeout or self.settings.http_timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                last_error = UpstreamTimeoutError(
                    f"{self.provider} request timed out after "
                    f"{timeout or self.settings.http_timeout_seconds}s.",
                    details={"provider": self.provider, "attempt": attempt + 1},
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                # Connection reset, DNS failure, protocol error: safe to retry.
                last_error = UpstreamUnavailableError(
                    f"{self.provider} request failed: {type(exc).__name__}.",
                    details={"provider": self.provider, "attempt": attempt + 1},
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise last_error from exc

            if response.status_code in allow_status:
                return response

            # Success: return before any error classification.
            if 200 <= response.status_code < 300:
                return response

            if response.status_code == 429 or (
                response.status_code >= 500 and response.status_code in RETRYABLE_STATUS
            ):
                if attempt < attempts - 1:
                    delay = self._backoff_delay(attempt, response.headers.get("Retry-After"))
                    logger.warning(
                        "provider retryable error",
                        extra={
                            "provider": self.provider,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                            "delay_seconds": round(delay, 2),
                        },
                    )
                    await asyncio.sleep(delay)
                    continue

            classify_status(
                response.status_code,
                self.provider,
                retry_after=response.headers.get("Retry-After"),
            )
            return response

        # Only reachable if the loop exhausted without returning or raising.
        raise last_error or UpstreamUnavailableError(
            f"{self.provider} request failed after {attempts} attempts.",
            details={"provider": self.provider},
        )

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET a JSON document, raising a typed error on any failure."""
        response = await self.request("GET", url, **kwargs)
        if not response.content:
            raise UpstreamUnavailableError(
                f"{self.provider} returned an empty body.",
                details={"provider": self.provider},
            )
        try:
            return response.json()
        except ValueError as exc:
            # Do not echo the body: it may contain provider echoes of the request.
            raise UpstreamUnavailableError(
                f"{self.provider} returned a body that is not valid JSON.",
                details={"provider": self.provider, "content_length": len(response.content)},
            ) from exc


def build_client(provider: str, settings: Settings | None = None) -> ProviderClient:
    return ProviderClient(provider, settings=settings)


def require_credential(value: str | None, variable: str, provider: str) -> str:
    """Return a credential or raise a safe error naming only the variable."""
    if not value:
        raise CredentialMissingError(
            f"{provider} live mode requires the {variable} environment variable, which is not set. "
            f"Set {variable} in your environment, or use replay mode instead.",
            details={"provider": provider, "missing_settings": [variable]},
        )
    return value


def error_to_run_error(exc: Exception) -> RunError:
    """Convert an exception into a redacted, storable run error."""
    from app.core.errors import AppError

    if isinstance(exc, AppError):
        return RunError(
            category=exc.code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            occurred_at=utc_now(),
            context=dict(exc.details),
        )
    return RunError(
        category="unexpected_error",
        message=f"{type(exc).__name__}: {exc}",
        retryable=False,
        occurred_at=datetime.now(utc_now().tzinfo),
    )
