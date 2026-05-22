"""Quanora CLI logo renderer.

Renders the Quanora ASCII logo with a cool blue → cyan gradient that evokes
quantitative finance and aurora light. Replaces the previous rainbow renderer
used by the Quanora brand.

Color stops (top → bottom):
- deep blue   #0c4a6e (sky-900)
- ocean blue  #0369a1 (sky-700)
- cyan        #0891b2 (cyan-600)
- ice cyan    #06b6d4 (cyan-500)
- frost       #67e8f9 (cyan-300)

The tagline line (last non-empty line) is rendered in a pale frost tone so the
mark stays the visual focus.
"""

from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.style import Style


# Cool gradient stops, top → bottom (RGB tuples 0-255).
_COOL_STOPS: list[tuple[int, int, int]] = [
    (0x0C, 0x4A, 0x6E),   # deep blue
    (0x03, 0x69, 0xA1),   # ocean blue
    (0x08, 0x91, 0xB2),   # cyan
    (0x06, 0xB6, 0xD4),   # ice cyan
    (0x67, 0xE8, 0xF9),   # frost
]

_TAGLINE_COLOR = "#a5f3fc"  # cyan-200, used for the tagline row.


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _interpolate_stops(stops: list[tuple[int, int, int]], t: float) -> tuple[int, int, int]:
    """Sample the multi-stop gradient at position t in [0, 1]."""
    if t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    segments = len(stops) - 1
    scaled = t * segments
    idx = int(scaled)
    local_t = scaled - idx
    r1, g1, b1 = stops[idx]
    r2, g2, b2 = stops[idx + 1]
    return _lerp(r1, r2, local_t), _lerp(g1, g2, local_t), _lerp(b1, b2, local_t)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def print_quanora_logo() -> None:
    """Print the Quanora logo with a cool blue → cyan vertical gradient."""
    path = Path(__file__).parent / "assets" / "logo.txt"
    try:
        if not path.exists():
            print(f"[Warning] Logo file not found at: {path}")
            return

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        if not lines:
            return

        console = Console()
        # Identify the tagline row (last non-empty line) so we can color it differently.
        tagline_index: int | None = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                tagline_index = i
                break

        # Use the number of mark rows (excluding tagline) for the gradient span.
        mark_rows = tagline_index if tagline_index is not None else len(lines)
        denom = max(mark_rows - 1, 1)

        print()
        for i, line in enumerate(lines):
            if i == tagline_index:
                style = Style(color=_TAGLINE_COLOR, bold=False, italic=True)
            else:
                t = i / denom
                color_hex = _rgb_to_hex(_interpolate_stops(_COOL_STOPS, t))
                style = Style(color=color_hex, bold=True)
            console.print(Text(line, style=style))
        print()

    except Exception as e:
        print(f"[Error] Failed to display logo: {e}")


# Backwards-compatible alias so older imports `print_rainbow_logo` keep working.
print_rainbow_logo = print_quanora_logo


if __name__ == "__main__":
    print_quanora_logo()
