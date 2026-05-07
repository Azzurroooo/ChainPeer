import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)


def test_resume_mode_flag_is_removed() -> None:
    result = subprocess.run(
        [sys.executable, "main.py", "--resume-mode", "summary"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        raise AssertionError("Expected main.py to reject the removed --resume-mode flag.")
    combined = f"{result.stdout}\n{result.stderr}"
    if "unrecognized arguments: --resume-mode summary" not in combined:
        raise AssertionError(f"Expected argparse unknown-flag error, got: {combined}")


def main() -> int:
    test_resume_mode_flag_is_removed()
    print("Main CLI arg tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
