from typing import Callable

from .file_ops import read_file, write_file, edit_file, list_files, grep
from .bash import bash, kill_shell
from .web import search_web, fetch_web_page
from .schemas import TOOL_SCHEMAS

TOOLS: dict[str, Callable] = {

    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "grep": grep,
    "bash": bash,
    "kill_shell": kill_shell,
    "search_web": search_web,
    "fetch_web_page": fetch_web_page,
}

__all__ = ["TOOLS", "TOOL_SCHEMAS"]
