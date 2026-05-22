"""Port for job persistence."""

from __future__ import annotations

from typing import Protocol

from agent.domain.jobs import JobRecord, JobStatus


class JobStore(Protocol):
    """Repository for storing and querying job metadata and state."""

    def create(self, job: JobRecord) -> None:
        """Create a new job record."""
        ...

    def get(self, job_id: str) -> JobRecord | None:
        """Retrieve a job by its ID."""
        ...

    def update_status(
        self, 
        job_id: str, 
        status: JobStatus, 
        error: str | None = None,
        reason: str | None = None
    ) -> None:
        """Update the status of a job."""
        ...

    def list_by_session(self, session_id: str) -> list[JobRecord]:
        """List all jobs belonging to a session."""
        ...
