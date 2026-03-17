
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.style import Style
import colorsys

def print_rainbow_logo():
    """
    Reads the logo file and prints it to the console with a rainbow gradient effect.
    """
    file_path: str = "./utils/logo.txt"
    try:
        # Resolve the path relative to the project root
        project_root = Path(__file__).parent.parent
        path = project_root / file_path

        if not path.exists():
            # Fallback: check if absolute path provided
            path = Path(file_path)
            if not path.exists():
                print(f"[Warning] Logo file not found at: {path}")
                return

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        
        if not lines:
            return

        console = Console()
        total_lines = len(lines)
        
        # Calculate max width for centering if needed, but let's stick to left align for ASCII art usually
        print()
        for i, line in enumerate(lines):
            # Calculate hue based on line number (0.0 to 1.0)
            # We cycle through the spectrum once from top to bottom
            hue = i / total_lines
            # Convert HLS to RGB (H, L, S) -> (R, G, B)
            # Saturation 1.0 for vivid colors, Lightness 0.5 for standard brightness
            r, g, b = colorsys.hls_to_rgb(hue, 0.6, 1.0)
            
            color_hex = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            
            # Create text with this color style
            text = Text(line, style=Style(color=color_hex, bold=True))
            console.print(text)
            
        print() # Add a newline after logo

    except Exception as e:
        print(f"[Error] Failed to display logo: {e}")

if __name__ == "__main__":
    print_rainbow_logo()
