"""Operating system / CPU detection and helpers for running external programs quietly."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MACOS

# Apps started from the macOS Dock / Linux launchers get a minimal PATH, so tools
# installed with Homebrew or similar wouldn't be found. These folders are searched too.
_EXTRA_SEARCH_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", str(Path.home() / ".deno" / "bin")]


def os_name() -> str:
    """'windows', 'macos' or 'linux'."""
    return "windows" if IS_WINDOWS else "macos" if IS_MACOS else "linux"


def cpu_arch() -> str:
    """'x86_64', 'arm64', 'x86' or 'armv7' (the real OS architecture where detectable)."""
    if IS_WINDOWS:
        machine = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or ""
    else:
        machine = platform.machine()
    machine = machine.lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    if machine.startswith("armv7") or machine == "arm":
        return "armv7"
    if machine in ("x86", "i386", "i686"):
        return "x86"
    return machine or "x86_64"


def exe_name(base: str) -> str:
    """Add '.exe' on Windows."""
    return base + ".exe" if IS_WINDOWS else base


def find_on_path(name: str) -> Path | None:
    """Like shutil.which, but also looks in common install folders missing from GUI PATHs."""
    found = shutil.which(name)
    if not found:
        found = shutil.which(name, path=os.pathsep.join(_EXTRA_SEARCH_DIRS))
    return Path(found) if found else None


def hidden_process_kwargs() -> dict:
    """Extra subprocess arguments: no console window pops up on Windows."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run_quietly(args: list[str], timeout: float = 20) -> str:
    """Run a program and return its combined output ('' if it can't be run)."""
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, **hidden_process_kwargs())
        return result.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def make_executable(path: Path) -> None:
    if not IS_WINDOWS:
        path.chmod(path.stat().st_mode | 0o755)
