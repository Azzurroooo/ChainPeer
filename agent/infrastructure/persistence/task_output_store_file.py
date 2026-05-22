"""File-based implementation of TaskOutputStore."""

from __future__ import annotations

import os
from pathlib import Path
from filelock import FileLock

from agent.application.ports import TaskOutputStore


class TaskOutputStoreFile(TaskOutputStore):
    """Stores task output in append-only files."""

    def __init__(self, directory: str | Path):
        self._dir = Path(directory) / "task_outputs"
        self._dir.mkdir(parents=True, exist_ok=True)
        
        # Max 50MB per task output as specified in migration plan
        self._max_file_size = 50 * 1024 * 1024

    def get_path(self, job_id: str) -> str:
        return str(self._dir / f"{job_id}.log")

    def _get_lock_path(self, job_id: str) -> str:
        return str(self._dir / f"{job_id}.log.lock")

    def append(self, job_id: str, content: str, stream_type: str = "stdout") -> None:
        if not content:
            return
            
        file_path = self.get_path(job_id)
        lock_path = self._get_lock_path(job_id)
        
        # Check size limit before appending
        if os.path.exists(file_path):
            if os.path.getsize(file_path) >= self._max_file_size:
                return
                
        with FileLock(lock_path):
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)

    def read(self, job_id: str, offset: int = 0, limit: int = -1) -> tuple[str, int]:
        file_path = self.get_path(job_id)
        if not os.path.exists(file_path):
            return "", offset
            
        with open(file_path, "r", encoding="utf-8") as f:
            f.seek(offset)
            if limit > 0:
                content = f.read(limit)
            else:
                content = f.read()
            new_offset = f.tell()
            
        return content, new_offset
