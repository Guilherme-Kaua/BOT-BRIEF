from pathlib import Path

PROTECTED_MARKER_ENTRIES: set[str] = {
    ".git",
    "node_modules",
    ".venv",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
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
        try:
            for marker in PROTECTED_MARKER_ENTRIES:
                if (current / marker).exists():
                    return True
            if any(child.suffix.lower() == ".sln" for child in current.iterdir() if child.is_file()):
                return True
        except (PermissionError, OSError):
            continue

    return False


def is_active_download(path: Path) -> bool:
    p = Path(path)
    return p.suffix.lower() in ACTIVE_DOWNLOAD_SUFFIXES


def is_file_locked(path: Path) -> bool:
    p = Path(path)
    if not p.exists() or p.is_dir():
        return False
    try:
        with open(p, "rb+"):
            return False
    except (PermissionError, OSError):
        return True
