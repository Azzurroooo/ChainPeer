"""JSONL-based implementation of JobStore."""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path
from filelock import FileLock

from agent.application.ports import JobStore
from agent.domain.jobs import JobRecord, JobStatus


class JobStoreJsonl(JobStore):
    """Stores job records in a JSONL file."""

    def __init__(self, directory: str | Path):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self._dir / "jobs.jsonl"
        self._lock_path = self._dir / "jobs.jsonl.lock"

    def _append_jsonl(self, data: dict) -> None:
        with FileLock(str(self._lock_path)):
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def _read_all(self) -> dict[str, JobRecord]:
        if not self._file_path.exists():
            return {}
            
        jobs = {}
        with open(self._file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    job_id = data["job_id"]
                    if job_id in jobs:
                        # Update existing job with new status/metadata
                        job = jobs[job_id]
                        if "status" in data:
                            job.status = data["status"]
                        if "started_at" in data:
                            job.started_at = data["started_at"]
                        if "ended_at" in data:
                            job.ended_at = data["ended_at"]
                        if "metadata" in data:
                            job.metadata.update(data["metadata"])
                    else:
                        jobs[job_id] = JobRecord(**data)
                except json.JSONDecodeError:
                    continue
        return jobs

    def create(self, job: JobRecord) -> None:
        self._append_jsonl(dataclasses.asdict(job))

    def get(self, job_id: str) -> JobRecord | None:
        jobs = self._read_all()
        return jobs.get(job_id)

    def update_status(
        self, 
        job_id: str, 
        status: JobStatus, 
        error: str | None = None,
        reason: str | None = None
    ) -> None:
        update_data = {"job_id": job_id, "status": status}
        
        metadata = {}
        if error is not None:
            metadata["error"] = error
        if reason is not None:
            metadata["cancel_reason"] = reason
            
        if metadata:
            update_data["metadata"] = metadata

        if status == "running":
            update_data["started_at"] = str(time.time())
        elif status in ("completed", "failed", "cancelled"):
            update_data["ended_at"] = str(time.time())
            
        self._append_jsonl(update_data)

    def list_by_session(self, session_id: str) -> list[JobRecord]:
        jobs = self._read_all()
        return [job for job in jobs.values() if job.session_id == session_id]
