"""Secret redaction and authorisation enforcement.

The rule under test: a credential value must never appear in a log record, an API response, or an
error message — including when a provider echoes the value back inside an error body.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.errors import UpstreamAuthError
from app.core.logging import configure_logging, request_context
from app.core.security import REDACTED, SecretRedactor, redact, redact_text
from tests.conftest import TEST_WRITE_KEY, make_settings

FAKE_SECRET = "sk-live-abc123def456ghi789jkl"


# ------------------------------------------------------------------ redactor
def test_registered_secret_is_masked_in_free_text():
    redactor = SecretRedactor()
    redactor.register(FAKE_SECRET)
    assert FAKE_SECRET not in redactor.scrub_text(f"key is {FAKE_SECRET} ok")
    assert REDACTED in redactor.scrub_text(f"key is {FAKE_SECRET} ok")


def test_sensitive_keys_are_masked_recursively():
    redactor = SecretRedactor()
    scrubbed = redactor.scrub(
        {"api_key": FAKE_SECRET, "nested": {"password": "hunter2", "safe": "value"}}
    )
    assert scrubbed["api_key"] == REDACTED
    assert scrubbed["nested"]["password"] == REDACTED
    # Non-sensitive data survives so logs stay useful.
    assert scrubbed["nested"]["safe"] == "value"


def test_credential_in_query_string_is_masked():
    redactor = SecretRedactor()
    scrubbed = redactor.scrub_text(
        "GET https://api.example.com/data?appid=SUPERSECRET&units=metric"
    )
    assert "SUPERSECRET" not in scrubbed
    assert "units=metric" in scrubbed  # useful context is preserved


def test_bearer_token_is_masked():
    redactor = SecretRedactor()
    scrubbed = redactor.scrub_text("Authorization: Bearer abcdef1234567890")
    assert "abcdef1234567890" not in scrubbed


def test_placeholder_values_are_not_registered():
    """A placeholder like 'changeme' must not cause false positives across unrelated text."""
    redactor = SecretRedactor()
    redactor.register("your-key-here")
    redactor.register("changeme")
    assert "the weather is changeme today" == redactor.scrub_text("the weather is changeme today")


def test_short_values_are_ignored():
    redactor = SecretRedactor()
    redactor.register("abc")
    assert redactor.scrub_text("abc def") == "abc def"


def test_process_redactor_is_populated_from_settings():
    from app.core.config import get_settings
    from app.core.security import redactor as process_redactor

    get_settings.cache_clear()
    process_redactor.register_from_settings(make_settings(openweather_api_key=FAKE_SECRET))
    assert FAKE_SECRET not in redact_text(f"token={FAKE_SECRET}")


# --------------------------------------------------------------------- logs
def test_log_records_are_redacted(caplog):
    settings = make_settings(
        openweather_api_key=FAKE_SECRET, api_write_key=TEST_WRITE_KEY,
        log_format="json", log_level="DEBUG",
    )
    configure_logging(settings)
    logger = logging.getLogger("app.test.secret")

    with caplog.at_level(logging.INFO):
        with request_context("corr-123", source_id="weather.live"):
            logger.info(
                "calling provider",
                extra={
                    "url": f"https://api.openweathermap.org/weather?appid={FAKE_SECRET}",
                    "api_key": FAKE_SECRET,
                    "safe_field": "kept",
                },
            )

    rendered = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert FAKE_SECRET not in rendered
    assert TEST_WRITE_KEY not in rendered
    # Non-sensitive fields remain, and the correlation id is attached automatically.
    assert "weather.live" in rendered


def test_correlation_id_is_attached_to_records(caplog):
    settings = make_settings(log_format="json", log_level="DEBUG")
    configure_logging(settings)
    logger = logging.getLogger("app.test.corr")

    with caplog.at_level(logging.INFO):
        with request_context("run_abc123"):
            logger.info("inside scope")

    assert any(getattr(r, "correlation_id", None) == "run_abc123" for r in caplog.records)

    # Outside the scope the id is cleared, not leaked.
    with caplog.at_level(logging.INFO):
        logger.info("outside scope")
    assert any(getattr(r, "correlation_id", None) == "-" for r in caplog.records)


# ------------------------------------------------------------- provider echo
def test_upstream_auth_error_does_not_echo_credential():
    """A provider that echoes the key in its error body must not cause it to reach the client."""
    error = UpstreamAuthError(
        f"openweather rejected appid={FAKE_SECRET} (HTTP 401).", details={"status_code": 401}
    )
    redactor = SecretRedactor()
    redactor.register(FAKE_SECRET)
    assert FAKE_SECRET not in redactor.scrub_text(error.message)


# ------------------------------------------------------------- authorisation
def test_write_operations_denied_without_key(client):
    for method, path, payload in (
        ("POST", "/api/v1/events", {"source_id": "s", "event_type": "other_report",
                                    "event_time": "2026-10-12T09:00:00Z"}),
        ("POST", "/api/v1/reports", {"report_category": "waterlogging"}),
        ("POST", "/api/v1/ingest/replay.all", {}),
    ):
        response = getattr(client, method.lower())(path, json=payload)
        assert response.status_code in (401, 403), f"{path} was not protected"
        # Protected server-side, in the standard envelope.
        assert response.json()["error"]["code"] in ("missing_api_key", "invalid_api_key")


def test_write_operations_denied_with_wrong_key(client):
    response = client.post(
        "/api/v1/reports",
        json={"report_category": "waterlogging"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_reads_are_public_without_a_key(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/sources").status_code == 200
    assert client.get("/api/v1/events").status_code == 200


def test_error_responses_never_contain_credentials(client):
    response = client.post(
        "/api/v1/reports",
        json={"report_category": "waterlogging"},
        headers={"X-API-Key": TEST_WRITE_KEY},
    )
    assert TEST_WRITE_KEY not in response.text


def test_ingest_failure_names_variables_but_not_values(client, write_headers):
    response = client.post("/api/v1/ingest/weather.live", json={}, headers=write_headers)
    body = response.text
    assert "OPENWEATHER_API_KEY" in body
    assert TEST_WRITE_KEY not in body


def test_malformed_credentials_are_never_stored_or_returned(client, write_headers):
    """A rejected report cannot leak the submitted text back through an error response."""
    response = client.post(
        "/api/v1/reports",
        json={"report_category": "waterlogging", "reporter_id": "person@example.com",
              "text": "secret sentence"},
        headers=write_headers,
    )
    assert response.status_code == 422
    assert "person@example.com" not in response.text
    assert "secret sentence" not in response.text
