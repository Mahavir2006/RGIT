"""The source-adapter contract.

An adapter's whole job is: **obtain records, normalise them, report diagnostics.** It must not
touch the database, must not write files, and must not decide whether a record is a duplicate.
Persistence and idempotency are the event service's concern.

Failure model
-------------
* A **record-level** problem (one malformed row) is reported as a rejected/quarantined outcome.
  The batch continues.
* A **source-level** problem (bad credentials, timeout, provider down) raises an
  :class:`AppError` subclass. The ingestion runner converts it into a failed/partial run for
  *this source only* and leaves other sources untouched.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.errors import AppError
from app.core.timeutil import utc_now
from app.schemas.common import SourceCategory
from app.schemas.event import CanonicalEvent
from app.schemas.ingestion import RecordOutcome, RunError
from app.schemas.source import CredentialState, SourceDescriptor

__all__ = ["FetchRequest", "AdapterResult", "SourceAdapter", "AdapterOutcome"]


@dataclass(slots=True)
class FetchRequest:
    """Parameters for one adapter invocation."""

    source_id: str
    correlation_id: str
    dry_run: bool = False
    limit: int | None = None
    # Replay-only knobs, ignored by live adapters.
    fixture: str | None = None
    shuffle: bool = False
    shuffle_seed: int | None = None
    rebase: bool | None = None
    since: datetime | None = None


@dataclass(slots=True)
class AdapterOutcome:
    """Mutable accumulator an adapter builds while it works."""

    events: list[CanonicalEvent] = field(default_factory=list)
    outcomes: list[RecordOutcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)
    pages_fetched: int = 0
    truncated: bool = False
    provider_meta: dict[str, Any] = field(default_factory=dict)

    def accept(self, event: CanonicalEvent) -> None:
        self.events.append(event)
        self.outcomes.append(
            RecordOutcome(
                outcome="accepted",
                event_id=event.event_id,
                source_event_id=event.source_event_id,
            )
        )

    def reject(
        self,
        *,
        reason_code: str,
        message: str,
        source_event_id: str | None = None,
        field_errors: list[dict[str, Any]] | None = None,
        outcome: str = "rejected",
    ) -> None:
        self.outcomes.append(
            RecordOutcome(
                outcome=outcome,  # type: ignore[arg-type]
                source_event_id=source_event_id,
                reason_code=reason_code,
                message=message,
                field_errors=field_errors or [],
            )
        )

    def warn(self, code: str, message: str) -> None:
        self.errors.append(
            RunError(category=code, message=message, retryable=False, occurred_at=utc_now())
        )


@dataclass(slots=True)
class AdapterResult:
    """What an adapter returns: canonical events plus actionable diagnostics."""

    source_id: str
    events: list[CanonicalEvent] = field(default_factory=list)
    outcomes: list[RecordOutcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)
    pages_fetched: int = 0
    truncated: bool = False
    provider_meta: dict[str, Any] = field(default_factory=dict)
    fetch_started_at: datetime = field(default_factory=utc_now)
    fetch_finished_at: datetime = field(default_factory=utc_now)

    @property
    def records_fetched(self) -> int:
        return len(self.events)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @classmethod
    def from_outcome(
        cls, source_id: str, outcome: AdapterOutcome, started_at: datetime
    ) -> "AdapterResult":
        return cls(
            source_id=source_id,
            events=outcome.events,
            outcomes=outcome.outcomes,
            warnings=outcome.warnings,
            errors=outcome.errors,
            pages_fetched=outcome.pages_fetched,
            truncated=outcome.truncated,
            provider_meta=outcome.provider_meta,
            fetch_started_at=started_at,
            fetch_finished_at=utc_now(),
        )


class SourceAdapter(abc.ABC):
    """Base class every source adapter implements."""

    #: Stable identifier, namespaced "<category>.<mode>".
    source_id: str = ""
    display_name: str = ""
    category: SourceCategory = SourceCategory.SYSTEM
    provider: str = ""
    supports_live: bool = False
    supports_replay: bool = True
    documentation_url: str | None = None
    unit_notes: str = ""
    caveats: tuple[str, ...] = ()

    @abc.abstractmethod
    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        """Obtain records and return them as canonical events.

        Raises:
            AppError: for source-level failure (auth, timeout, rate limit, unavailability).
        """

    # ------------------------------------------------------------ metadata
    def required_settings(self) -> list[str]:
        """Environment variable names this adapter needs for its live mode."""
        return []

    def missing_settings(self) -> list[str]:
        """Which of :meth:`required_settings` are absent.

        Reported by name only. Never inspect a value here.
        """
        from app.core.config import get_settings

        settings = get_settings()
        return [name for name in self.required_settings() if not getattr(settings, name, None)]

    def credential_states(self) -> list[CredentialState]:
        from app.core.config import get_settings

        settings = get_settings()
        states = []
        for name in self.required_settings():
            value = getattr(settings, name, None)
            states.append(
                CredentialState(
                    variable=name,
                    configured=bool(value),
                    placeholder=(not value) or str(value).strip().lower().startswith("your-"),
                )
            )
        return states

    def can_run_live(self) -> bool:
        return not self.missing_settings()

    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id=self.source_id,
            display_name=self.display_name,
            category=self.category,
            provider=self.provider,
            mode=self.effective_mode(),
            enabled=True,
            description=(self.__doc__ or "").strip().splitlines()[0] if self.__doc__ else "",
            supports_live=self.supports_live,
            supports_replay=self.supports_replay,
            credentials=self.credential_states(),
            required_settings=self.required_settings(),
            missing_settings=self.missing_settings(),
            unit_notes=self.unit_notes,
            documentation_url=self.documentation_url,
            caveats=list(self.caveats),
        )

    def effective_mode(self) -> str:
        """Report the mode this adapter would actually use right now."""
        from app.schemas.common import SourceMode

        if self.supports_live and self.can_run_live():
            return SourceMode.LIVE.value
        if self.supports_replay:
            return SourceMode.REPLAY.value
        return SourceMode.DISABLED.value

    # -------------------------------------------------------------- helpers
    def missing_credential_error(self) -> AppError:
        """Build a safe error naming the absent variables, never their values."""
        from app.core.errors import CredentialMissingError

        missing = self.missing_settings()
        names = ", ".join(missing)
        return CredentialMissingError(
            f"{self.display_name} live mode requires configuration that is not set: {names}. "
            f"Set {names} in your environment, or run this source in replay mode "
            f"(POST /api/v1/ingest/{self.source_id}).",
            details={"source_id": self.source_id, "missing_settings": missing},
        )
