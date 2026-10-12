"""Application error taxonomy and the single response envelope.

Every error that leaves the API — validation failure, provider failure, missing credential,
authorisation denial — is expressed as an :class:`AppError` so the client sees one stable shape.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "AppError",
    "ValidationError",
    "NotFoundError",
    "UnauthorizedError",
    "ForbiddenError",
    "ConflictError",
    "UpstreamError",
    "CredentialMissingError",
    "RateLimitError",
    "UpstreamTimeoutError",
    "UpstreamAuthError",
    "UpstreamUnavailableError",
    "PayloadTooLargeError",
]


class ErrorCode:
    """Stable, machine-readable error codes."""

    VALIDATION_FAILED = "validation_failed"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    CONFLICT = "conflict"
    UPSTREAM_ERROR = "upstream_error"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_AUTH = "upstream_auth_error"
    UPSTREAM_RATE_LIMIT = "upstream_rate_limit"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CREDENTIAL_MISSING = "credential_missing"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_EVENT_TYPE = "unsupported_event_type"
    INTERNAL_ERROR = "internal_error"


class ErrorDetail:
    """Machine-readable reason codes used for validation and quarantine outcomes.

    These are stable identifiers: automation may branch on them, so they must not be reworded
    casually.
    """

    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_COORDINATE = "invalid_coordinate"
    INVALID_MEASUREMENT_VALUE = "invalid_measurement_value"
    UNSUPPORTED_UNIT = "unsupported_unit"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    MALFORMED_PAYLOAD = "malformed_payload"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    LOCATION_NOT_PERMITTED = "location_not_permitted"
    NEGATIVE_VALUE_NOT_ALLOWED = "negative_value_not_allowed"
    UNKNOWN_SOURCE = "unknown_source"
    RUN_ALREADY_ACTIVE = "run_already_active"


class AppError(Exception):
    """Base class for all application errors mapped onto an HTTP response."""

    status_code: int = 500
    code: str = ErrorCode.INTERNAL_ERROR
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        field_errors: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        self.field_errors = field_errors or []
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_errors": self.field_errors,
            "details": self.details,
            "retryable": self.retryable,
        }


class ValidationError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_FAILED


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND


class UnauthorizedError(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED


class ForbiddenError(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT


class UpstreamError(AppError):
    status_code = 502
    code = ErrorCode.UPSTREAM_ERROR
    retryable = True


class CredentialMissingError(AppError):
    """Raised when a connector's credential is absent.

    The message names the environment variable only. It must never contain a credential value.
    """

    status_code = 503
    code = ErrorCode.CREDENTIAL_MISSING
    retryable = False


class RateLimitError(UpstreamError):
    status_code = 429
    code = ErrorCode.UPSTREAM_RATE_LIMIT
    retryable = True


class UpstreamTimeoutError(UpstreamError):
    status_code = 504
    code = ErrorCode.UPSTREAM_TIMEOUT


class UpstreamAuthError(UpstreamError):
    status_code = 502
    code = ErrorCode.UPSTREAM_AUTH
    retryable = False  # Retrying bad credentials is pointless and can lock an account.


class UpstreamUnavailableError(UpstreamError):
    status_code = 503
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    retryable = True


class PayloadTooLargeError(AppError):
    status_code = 413
    code = ErrorCode.PAYLOAD_TOO_LARGE
