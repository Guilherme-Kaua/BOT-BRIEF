from functools import lru_cache
import os
from pathlib import Path
import time

PROTECTED_MARKER_ENTRIES: set[str] = {
    ".git",
    "node_modules",
    ".venv",
    "pyproject.toml",
    "package.json",
    "cargo.toml",
}

PROTECTED_PATH_PARTS: set[str] = {
    "steamlibrary",
    "riot games",
    "xboxgames",
    "windowsapps",
    "$recycle.bin",
    "system volume information",
    "program files",
    "program files (x86)",
    "windows",
    ".git",
    "node_modules",
    ".venv",
}

ACTIVE_DOWNLOAD_SUFFIXES: set[str] = {
    ".crdownload",
    ".part",
    ".tmp",
    ".download",
    ".opdownload",
}


@lru_cache(maxsize=4096)
def _dir_has_project_marker(dir_str: str) -> bool:
    try:
        for marker in PROTECTED_MARKER_ENTRIES:
            if os.path.exists(os.path.join(dir_str, marker)):
                return True
        with os.scandir(dir_str) as it:
            for entry in it:
                if entry.name.lower().endswith(".sln") and entry.is_file(follow_symlinks=False):
                    return True
    except (PermissionError, OSError):
        return False
    return False


def is_protected_path(path: Path, projetos_dir: Path | None = None) -> bool:
    p = Path(path)
    parts_lower = {part.lower() for part in p.parts}
    if parts_lower & PROTECTED_PATH_PARTS:
        return True

    if projetos_dir is not None:
        try:
            p.resolve().relative_to(Path(projetos_dir).resolve())
            return True
        except ValueError:
            pass

    check_dir = p if p.is_dir() else p.parent
    for current in [check_dir, *check_dir.parents]:
        # Skip scanning root drive letters like C:\ or F:\
        if current.parent == current:
            continue
        if _dir_has_project_marker(str(current)):
            return True

    return False


def is_active_download(path: Path, now_ts: float | None = None, max_active_hours: float = 24.0) -> bool:
    p = Path(path)
    if p.suffix.lower() not in ACTIVE_DOWNLOAD_SUFFIXES:
        return False
    if p.exists():
        try:
            cur = now_ts if now_ts is not None else time.time()
            age_hours = (cur - p.stat().st_mtime) / 3600.0
            if age_hours > max_active_hours:
                return False
        except OSError:
            pass
    return True


def is_file_locked(path: Path) -> bool:
    p = Path(path)
    if not p.exists() or p.is_dir():
        return False
    try:
        with open(p, "rb+"):
            return False
    except (PermissionError, OSError):
        return True
