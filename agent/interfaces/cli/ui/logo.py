"""Startup header for the interactive CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent.interfaces.cli.ui.prompt_chrome import GitPromptStatus
from agent.version import __version__


@dataclass(frozen=True)
class HeaderProfile:
    """Runtime product profile for the startup header."""

    name: str = "ChainPeer"
    version: str = __version__
    mark: str = ">_"
    tagline: str = "Ready for engineering work"
    accent: str = "#3ecfbd"
    command_hint: str = "Type /help"


def startup_header(
    *,
    version: str = __version__,
    debug: bool = False,
    model: object = None,
    cwd: str | Path | None = None,
    git_status: GitPromptStatus | None = None,
) -> RenderableType:
    """Build the startup header renderable."""
    profile = _header_profile(version)
    body = Table.grid(expand=True)
    body.add_column(ratio=1)
    body.add_row(_brand_line(profile=profile, debug=debug))
    body.add_row(Text(f"  {profile.tagline}", style="dim"))
    body.add_row(_context_line(model=model, cwd=cwd, git_status=git_status))
    body.add_row(_shortcut_line(profile=profile))
    body.add_row(Text("Ctrl+O history  |  Ctrl+L clear  |  Ctrl+C drafts", style="dim"))

    return Panel(
        body,
        box=box.ROUNDED,
        border_style=profile.accent,
        expand=False,
        padding=(0, 2),
    )


def _brand_line(*, profile: HeaderProfile, debug: bool) -> Text:
    title = Text(f"{profile.mark} ", style=f"bold {profile.accent}")
    title.append(profile.name, style="bold white")
    title.append(f"  v{profile.version}", style="dim")
    if debug:
        title.append("  debug", style="bold #ffd166")
    return title


def _shortcut_line(*, profile: HeaderProfile) -> Text:
    line = Text()
    line.append(profile.command_hint, style=f"bold {profile.accent}")
    line.append("  |  Enter send  |  Ctrl+J newline", style="dim")
    return line


def _header_profile(default_version: str) -> HeaderProfile:
    return HeaderProfile(
        name=_env_text("CHAINPEER_HEADER_NAME", "ChainPeer"),
        version=_env_text("CHAINPEER_HEADER_VERSION", default_version),
        mark=_env_text("CHAINPEER_HEADER_MARK", ">_"),
        tagline=_env_text("CHAINPEER_HEADER_TAGLINE", "Ready for engineering work"),
        accent=_env_text("CHAINPEER_HEADER_ACCENT", "#3ecfbd"),
        command_hint=_env_text("CHAINPEER_HEADER_COMMAND_HINT", "Type /help"),
    )


def _env_text(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def print_startup_header(
    *,
    version: str = __version__,
    debug: bool = False,
    model: object = None,
    cwd: str | Path | None = None,
    git_status: GitPromptStatus | None = None,
) -> None:
    console = Console()
    console.print()
    console.print(
        startup_header(
            version=version,
            debug=debug,
            model=model,
            cwd=cwd,
            git_status=git_status,
        )
    )


def _context_line(
    *,
    model: object = None,
    cwd: str | Path | None = None,
    git_status: GitPromptStatus | None = None,
) -> Text:
    line = Text()
    line.append("model ", style="dim")
    line.append(_clip(_value(model), 24), style="white")
    line.append("  |  workspace ", style="dim")
    line.append(_clip(_workspace_name(cwd), 28), style="white")
    if git_status and git_status.branch:
        marker = "*" if git_status.dirty else ""
        line.append("  |  git ", style="dim")
        line.append(_clip(f"{git_status.branch}{marker}", 22), style="white")
    return line


def _workspace_name(cwd: str | Path | None = None) -> str:
    path = Path(cwd or Path.cwd())
    return path.name or str(path)


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 3)]}..."


def _value(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


if __name__ == "__main__":
    print_startup_header()
