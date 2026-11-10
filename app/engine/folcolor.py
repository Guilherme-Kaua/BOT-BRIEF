import ctypes
import os
from pathlib import Path
from app.config import FOLCOLOR_CATEGORY_MAP
from app.engine.protector import is_protected_path

FILE_ATTRIBUTE_READONLY = 0x01
FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def _set_attrs(path: Path, attrs: int) -> None:
    if os.name == "nt":
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)


def _get_attrs(path: Path) -> int:
    if os.name == "nt":
        val = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if val != INVALID_FILE_ATTRIBUTES:
            return int(val)
    return 0


def get_category_icon_resource(folder: Path, vida_root: Path, folcolor_exe: Path) -> str | None:
    try:
        rel = Path(folder).resolve().relative_to(Path(vida_root).resolve())
    except ValueError:
        return None
    if not rel.parts:
        return None
    top_cat = rel.parts[0]
    if top_cat not in FOLCOLOR_CATEGORY_MAP:
        return None
    idx = FOLCOLOR_CATEGORY_MAP[top_cat]
    exe = Path(folcolor_exe)
    if exe.exists():
        return f"{exe},{idx}"
    return "C:\\Windows\\System32\\shell32.dll,3"


def needs_folcolor_icon(folder: Path, vida_root: Path, folcolor_exe: Path) -> bool:
    resource = get_category_icon_resource(folder, vida_root, folcolor_exe)
    if not resource:
        return False
    ini_path = Path(folder) / "desktop.ini"
    if not ini_path.exists():
        return True
    try:
        content = ini_path.read_text(encoding="utf-8", errors="ignore")
        if f"IconResource={resource}" not in content:
            return True
    except OSError:
        return True
    if os.name == "nt":
        folder_attrs = _get_attrs(Path(folder))
        if not (folder_attrs & FILE_ATTRIBUTE_READONLY):
            return True
    return False


def apply_folcolor_icon(folder: Path, icon_resource: str) -> dict:
    folder_path = Path(folder)
    ini_path = folder_path / "desktop.ini"
    previous_content: str | None = None

    if ini_path.exists():
        _set_attrs(ini_path, FILE_ATTRIBUTE_NORMAL)
        try:
            previous_content = ini_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            previous_content = None

    content = f"[.ShellClassInfo]\nIconResource={icon_resource}\n"
    ini_path.write_text(content, encoding="utf-8")
    _set_attrs(ini_path, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)

    folder_attrs = _get_attrs(folder_path)
    _set_attrs(folder_path, folder_attrs | FILE_ATTRIBUTE_READONLY)

    return {
        "folder": str(folder_path),
        "previous_content": previous_content,
        "applied_resource": icon_resource,
    }


def restore_folcolor_icon(folder: Path, previous_content: str | None) -> None:
    folder_path = Path(folder)
    ini_path = folder_path / "desktop.ini"
    if ini_path.exists():
        _set_attrs(ini_path, FILE_ATTRIBUTE_NORMAL)
    if previous_content is None:
        if ini_path.exists():
            ini_path.unlink()
    else:
        ini_path.write_text(previous_content, encoding="utf-8")
        _set_attrs(ini_path, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)


def scan_missing_icons(vida_root: Path, folcolor_exe: Path, max_depth: int = 2) -> list[dict]:
    root = Path(vida_root)
    if not root.exists():
        return []
    missing: list[dict] = []

    def _walk(current: Path, depth: int, cat_name: str) -> None:
        cat_limit = 1 if cat_name in {"04_Arquivo_Morto", "99_Inbox"} else max_depth
        if depth > cat_limit:
            return
        try:
            children = [c for c in current.iterdir() if c.is_dir() and not c.name.startswith(".")]
        except (PermissionError, OSError):
            return
        for child in sorted(children, key=lambda p: p.name.lower()):
            if is_protected_path(child):
                continue
            if needs_folcolor_icon(child, root, folcolor_exe):
                resource = get_category_icon_resource(child, root, folcolor_exe)
                missing.append(
                    {
                        "path": str(child),
                        "category_folder": cat_name,
                        "folcolor_index": FOLCOLOR_CATEGORY_MAP.get(cat_name, 13),
                        "icon_resource": resource,
                    }
                )
            _walk(child, depth + 1, cat_name)

    for cat_name in FOLCOLOR_CATEGORY_MAP:
        cat_dir = root / cat_name
        if cat_dir.exists() and cat_dir.is_dir():
            if needs_folcolor_icon(cat_dir, root, folcolor_exe):
                resource = get_category_icon_resource(cat_dir, root, folcolor_exe)
                missing.append(
                    {
                        "path": str(cat_dir),
                        "category_folder": cat_name,
                        "folcolor_index": FOLCOLOR_CATEGORY_MAP[cat_name],
                        "icon_resource": resource,
                    }
                )
            _walk(cat_dir, 1, cat_name)

    return missing

