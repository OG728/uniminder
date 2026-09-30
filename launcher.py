"""Source for UniMinder.exe.

The exe only starts desktop.py with the project's virtual environment, so code
changes show up the next time you open it without rebuilding the exe.
"""

import ctypes
import subprocess
import sys
from pathlib import Path


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "UniMinder", 0x10)


def main() -> None:
    folder = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    python = folder / ".venv" / "Scripts" / "pythonw.exe"
    script = folder / "desktop.py"
    if not python.exists():
        show_error(f"Couldn't find {python}.\n\nSet up the .venv first (see README).")
        return
    if not script.exists():
        show_error(f"Couldn't find {script}.\n\nKeep UniMinder.exe in the project folder.")
        return
    subprocess.Popen([str(python), str(script)], cwd=folder)


if __name__ == "__main__":
    main()
