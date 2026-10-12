"""Secret redaction and API-key authorisation.

Two invariants:

* A credential value is never rendered into a log line, an API response, or an exception
  message. Redaction is centralised here so there is exactly one implementation to audit.
* Redaction is *defence in depth*: even if a provider payload or URL is logged wholesale, the
  filter scrubs it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from fastapi import Header, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

__all__ = [
    "REDACTED",
    "SecretRedactor",
    "redact",
    "redact_text",
    "require_write_key",
    "require_read_key",
    "api_key_header",
]

REDACTED = "***redacted***"

# Keys whose *values* must never be emitted, matched case-insensitively on the key name.
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|apikey|secret|password|passwd|token|authorization|auth|credential|"
    r"private[_-]?key|session[_-]?id|bearer)",
    re.IGNORECASE,
)

# Query-string parameters that leak credentials through URLs and logs.
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?i)\b(appid|apikey|api_key|key|token|secret|password|access_token)=([^&\s\"']+)"
)

# Bearer-style tokens and long opaque secrets in free text.
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}")

_PLACEHOLDER_VALUES = {"", "none", "null", "changeme", "your-key-here", "placeholder"}


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in _PLACEHOLDER_VALUES or lowered.startswith("your-")


class SecretRedactor:
    """Collects the live credential values and scrubs them from arbitrary output.

    Registering actual values means that even if they appear somewhere unexpected (inside a
    provider's echoed error body, for example) they are still masked.
    """

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str | None) -> None:
        """Register a secret value for masking. Placeholder values are ignored."""
        if not value:
            return
        candidate = value.strip()
        # Very short strings would cause false positives across unrelated text.
        if len(candidate) < 6 or _is_placeholder(candidate):
            return
        self._values.add(candidate)

    def register_from_settings(self, settings: Settings) -> None:
        """Register every credential present in settings, by attribute name."""
        for name in (
            "openweather_api_key",
            "openaq_api_key",
            "tomtom_api_key",
            "water_api_key",
            "api_write_key",
            "api_read_key",
        ):
            self.register(getattr(settings, name, None))

    def scrub_text(self, text: str) -> str:
        """Mask registered secrets and credential-shaped query parameters in free text."""
        if not text:
            return text
        result = text
        for secret in self._values:
            if secret in result:
                result = result.replace(secret, REDACTED)
        result = _SENSITIVE_QUERY_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTED}", result)
        result = _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}{REDACTED}", result)
        return result

    def scrub(self, value: Any, _depth: int = 0) -> Any:
        """Recursively redact a JSON-like structure.

        Keys that look sensitive have their whole value replaced. Strings are scrubbed for
        registered secret values. Structure and non-sensitive data are preserved so logs stay
        useful for debugging.
        """
        if _depth > 12:
            return "<max-depth>"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, dict):
            out: dict[Any, Any] = {}
            for key, item in value.items():
                if isinstance(key, str) and _SENSITIVE_KEY_PATTERN.search(key):
                    out[key] = REDACTED
                else:
                    out[key] = self.scrub(item, _depth + 1)
            return out
        if isinstance(value, (list, tuple, set)):
            return [self.scrub(item, _depth + 1) for item in value]
        return self.scrub_text(str(value))


# Process-wide redactor, populated at application startup.
redactor = SecretRedactor()


def redact(value: Any) -> Any:
    """Redact a JSON-like structure using the process-wide redactor."""
    return redactor.scrub(value)


def redact_text(text: str) -> str:
    """Redact a string using the process-wide redactor."""
    return redactor.scrub_text(text)


# --------------------------------------------------------------------------- auth
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_key(
    settings: Settings,
    provided: str | None,
    expected: str | None,
    required: bool,
) -> None:
    """Compare a presented API key against the configured one using a constant-time compare."""
    if not settings.auth_enabled:
        return
    if not required and provided is None:
        return
    if expected is None:
        # Auth is enabled but no key is configured: refuse writes rather than allow-all.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "auth_not_configured",
                "message": (
                    "Write operations are disabled because API_WRITE_KEY is not configured. "
                    "Set it in the environment, or set AUTH_ENABLED=false for local development."
                ),
            },
        )
    if provided is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_api_key", "message": "An API key is required for this endpoint."},
            headers={"WWW-Authenticate": "APIKey"},
        )
    import hmac

    if not hmac.compare_digest(provided.strip(), expected.strip()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "invalid_api_key", "message": "The supplied API key is not valid."},
        )


def require_write_key(
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str | None:
    """FastAPI dependency enforcing write scope on mutating endpoints."""
    settings = get_settings()
    _check_key(settings, api_key, settings.api_write_key, required=True)
    return api_key


def require_read_key(
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str | None:
    """FastAPI dependency enforcing read scope. Reads are public unless a read key is set."""
    settings = get_settings()
    _check_key(settings, api_key, settings.api_read_key, required=False)
    return api_key


def configured_scopes(settings: Settings | None = None) -> Iterable[str]:
    """Describe the scopes currently enforced, for documentation and diagnostics."""
    current = settings or get_settings()
    if not current.auth_enabled:
        return ("read:public", "write:open")
    read_scope = "read:keyed" if current.api_read_key else "read:public"
    write_scope = "write:keyed" if current.api_write_key else "write:disabled"
    return (read_scope, write_scope)
