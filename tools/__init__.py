from typing import Callable

from .file_ops import read_file, write_file, list_files
from .bash import bash, kill_shell
from .schemas import TOOL_SCHEMAS

TOOLS: dict[str, Callable] = {

    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "bash": bash,
    "kill_shell": kill_shell,
}

__all__ = ["TOOLS", "TOOL_SCHEMAS"]
