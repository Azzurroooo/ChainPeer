"""Port for task output persistence."""

from __future__ import annotations

from typing import Protocol


class TaskOutputStore(Protocol):
    """Repository for storing and retrieving incremental task output logs."""

    def append(self, job_id: str, content: str, stream_type: str = "stdout") -> None:
        """Append new content to the task's output log."""
        ...

    def read(self, job_id: str, offset: int = 0, limit: int = -1) -> tuple[str, int]:
        """
        Read content from the task's output log starting at `offset`.
        Returns a tuple of (content, new_offset).
        """
        ...

    def get_path(self, job_id: str) -> str:
        """Get the physical or logical path reference for the output."""
        ...
