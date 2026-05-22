"""Service for managing tool execution jobs."""

from __future__ import annotations

import uuid

from agent.application.ports import JobStore, TaskOutputStore
from agent.domain.jobs import JobRecord, JobStatus, JobHandle


class JobService:
    """Application service for managing the lifecycle of tool execution jobs."""

    def __init__(self, job_store: JobStore, output_store: TaskOutputStore):
        self._job_store = job_store
        self._output_store = output_store

    def create_job(
        self,
        session_id: str,
        request_id: str,
        tool_call_id: str,
        tool_name: str,
        metadata: dict | None = None
    ) -> JobHandle:
        """Create a new job record and return its handle."""
        job_id = str(uuid.uuid4())
        job = JobRecord(
            job_id=job_id,
            session_id=session_id,
            request_id=request_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status="pending",
            output_ref=self._output_store.get_path(job_id),
            metadata=metadata or {}
        )
        self._job_store.create(job)
        return JobHandle(
            job_id=job_id,
            status="pending",
            output_ref=job.output_ref
        )

    def get_job(self, job_id: str) -> JobRecord | None:
        """Retrieve a job's details."""
        return self._job_store.get(job_id)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        error: str | None = None,
        reason: str | None = None
    ) -> None:
        """Update a job's status."""
        self._job_store.update_status(job_id, status, error, reason)

    def append_output(self, job_id: str, content: str, stream_type: str = "stdout") -> None:
        """Append incremental output to a job's log."""
        self._output_store.append(job_id, content, stream_type)

    def read_output(self, job_id: str, offset: int = 0, limit: int = -1) -> tuple[str, int]:
        """Read incremental output from a job's log."""
        return self._output_store.read(job_id, offset, limit)

    def list_session_jobs(self, session_id: str) -> list[JobRecord]:
        """List all jobs for a session."""
        return self._job_store.list_by_session(session_id)
