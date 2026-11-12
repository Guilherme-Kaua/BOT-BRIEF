import os
import shutil
import time
from pathlib import Path
from typing import Any

from app.config import AppConfig, FOLCOLOR_CATEGORY_MAP
from app.db import Database
from app.engine.protector import ACTIVE_DOWNLOAD_SUFFIXES, is_active_download, is_protected_path

TEMP_FILE_EXTENSIONS: set[str] = {
    ".tmp",
    ".temp",
    ".dmp",
    ".hdmp",
    ".mdmp",
    ".bak",
    ".old",
    ".log",
    ".chk",
}

ABANDONED_DOWNLOAD_EXTENSIONS: set[str] = {
    ".part",
    ".crdownload",
    ".download",
    ".opdownload",
}


def _fast_dir_stats(directory: Path, max_depth: int = 3, max_entries: int = 6000) -> tuple[int, int]:
    """Fast non-blocking directory size & file count using os.scandir."""
    if not directory.exists():
        return 0, 0
    total_bytes = 0
    file_count = 0
    visited = 0

    def _walk(cur_str: str, depth: int) -> None:
        nonlocal total_bytes, file_count, visited
        if depth > max_depth or visited >= max_entries:
            return
        try:
            with os.scandir(cur_str) as it:
                for entry in it:
                    visited += 1
                    if visited >= max_entries:
                        break
                    name_low = entry.name.lower()
                    if name_low in {"desktop.ini", ".git", "node_modules", ".venv"}:
                        continue
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            _walk(entry.path, depth + 1)
                    except OSError:
                        continue
        except (PermissionError, OSError):
            return

    _walk(str(directory), 0)
    return total_bytes, file_count


def analyze_storage(
    config: AppConfig,
    db: Database,
    now_ts: float | None = None,
    growth_threshold_bytes: int = 500 * 1024 * 1024,  # 500 MB default
    low_disk_free_bytes_threshold: int = 20 * 1024 * 1024 * 1024,  # 20 GB default
    reset_baseline: bool = False,
) -> dict[str, Any]:
    """
    Non-destructive storage monitor:
    1. Disk full / low space alerts (C:\\ and F:\\)
    2. Abnormal folder growth detection against SQLite baseline snapshots
    3. Temporary files & abandoned downloads (>24h) inventory without automatic deletion
    """
    cur_ts = now_ts if now_ts is not None else time.time()
    alerts: list[dict[str, Any]] = []

    # 1. Disk Space Analysis
    drives: list[dict[str, Any]] = []
    seen_anchors: set[str] = set()
    drive_candidates = [
        ("Sistema (C:)", config.downloads_dir),
        ("Central Vida (F:)", config.vida_root),
    ]
    for label, path_obj in drive_candidates:
        anchor = (path_obj.anchor or str(path_obj)[:3] or "C:\\").upper()
        if anchor in seen_anchors:
            continue
        target_check = Path(anchor) if Path(anchor).exists() else path_obj
        if not target_check.exists():
            continue
        try:
            usage = shutil.disk_usage(target_check)
        except OSError:
            continue
        seen_anchors.add(anchor)

        used_pct = round((usage.used / usage.total) * 100.0, 1) if usage.total > 0 else 0.0
        critical_threshold = min(10 * 1024 * 1024 * 1024, low_disk_free_bytes_threshold // 2)
        if usage.free < critical_threshold or used_pct >= 92.0:
            level = "red"
        elif usage.free < low_disk_free_bytes_threshold or used_pct >= 85.0:
            level = "amber"
        else:
            level = "green"

        drive_info = {
            "anchor": anchor,
            "label": label,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": used_pct,
            "status_level": level,
        }
        drives.append(drive_info)

        if level in {"red", "amber"}:
            free_gb = usage.free / (1024**3)
            alerts.append(
                {
                    "type": "disk_space",
                    "severity": "critical" if level == "red" else "warning",
                    "title": f"Alerta de Espaço em Disco ({anchor})",
                    "detail": (
                        f"{label} está com {used_pct:.1f}% ocupado "
                        f"({free_gb:.2f} GB livres). Nenhuma exclusão automática foi feita."
                    ),
                    "path": anchor,
                }
            )

    # 2. Abnormal Folder Growth Analysis
    monitored_folders: list[tuple[str, Path]] = [
        ("Downloads", config.downloads_dir),
        ("Desktop", config.desktop_dir),
        ("Documents", config.documents_dir),
    ]
    for cat_name in FOLCOLOR_CATEGORY_MAP:
        monitored_folders.append((cat_name, config.vida_root / cat_name))

    snapshots = db.get_folder_snapshots()
    folder_growth: list[dict[str, Any]] = []

    for name, folder_path in monitored_folders:
        if not folder_path.exists():
            continue
        cur_bytes, cur_files = _fast_dir_stats(folder_path)
        key = str(folder_path).lower()
        prev = snapshots.get(key)

        if prev is None or reset_baseline:
            db.upsert_folder_snapshot(str(folder_path), name, cur_bytes, cur_files, cur_ts)
            delta_bytes = 0
            delta_files = 0
            baseline_bytes = cur_bytes
            abnormal = False
        else:
            baseline_bytes = int(prev["size_bytes"])
            delta_bytes = cur_bytes - baseline_bytes
            delta_files = cur_files - int(prev["file_count"])
            abnormal = delta_bytes >= growth_threshold_bytes
            # If the user cleaned up files and folder shrank, update the baseline downward
            if cur_bytes < baseline_bytes:
                db.upsert_folder_snapshot(str(folder_path), name, cur_bytes, cur_files, cur_ts)
                baseline_bytes = cur_bytes
                delta_bytes = 0

        growth_item = {
            "name": name,
            "path": str(folder_path),
            "current_bytes": cur_bytes,
            "baseline_bytes": baseline_bytes,
            "delta_bytes": delta_bytes,
            "file_count": cur_files,
            "delta_files": delta_files,
            "abnormal_growth": abnormal,
        }
        folder_growth.append(growth_item)

        if abnormal:
            delta_mb = delta_bytes / (1024 * 1024)
            alerts.append(
                {
                    "type": "abnormal_growth",
                    "severity": "warning",
                    "title": f"Crescimento Anormal na Pasta {name}",
                    "detail": (
                        f"A pasta '{name}' cresceu +{delta_mb:.1f} MB "
                        f"({delta_files:+d} arquivo(s)) desde a última linha de base."
                    ),
                    "path": str(folder_path),
                }
            )

    # 3. Temporary Files & Abandoned Downloads (> 24h) — Strictly Read-Only Detection
    ignored_set = db.get_ignored_set()
    temp_scan_dirs = [
        config.downloads_dir,
        config.desktop_dir,
        config.documents_dir,
        config.vida_root / "99_Inbox",
        config.vida_root / "99_Inbox" / "Downloads",
    ]
    seen_temp_paths: set[str] = set()
    temp_items: list[dict[str, Any]] = []

    for d in temp_scan_dirs:
        if not d.exists():
            continue
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue

        for entry in entries:
            if not entry.is_file() or entry.name.lower() == "desktop.ini":
                continue
            sp_low = str(entry).lower()
            if sp_low in seen_temp_paths or sp_low in ignored_set:
                continue
            if is_protected_path(entry, config.projetos_dir):
                continue

            ext = entry.suffix.lower()
            is_office_lock = entry.name.startswith("~$")
            is_abandoned_dl = ext in ABANDONED_DOWNLOAD_EXTENSIONS
            is_temp_ext = ext in TEMP_FILE_EXTENSIONS or is_office_lock

            if not (is_abandoned_dl or is_temp_ext):
                continue

            try:
                st = entry.stat()
                age_hours = max(0.0, (cur_ts - st.st_mtime) / 3600.0)
                sz = st.st_size
            except OSError:
                continue

            if is_abandoned_dl:
                # Active download (< 24h) must NOT be touched or flagged as abandoned
                if is_active_download(entry, now_ts=cur_ts, max_active_hours=24.0):
                    continue
                kind = "abandoned_download"
                kind_label = "Download Abandonado (> 24h)"
            else:
                if is_office_lock and age_hours < 24.0:
                    continue
                kind = "temp_file"
                kind_label = f"Arquivo Temporário ({ext or '~$'})"

            seen_temp_paths.add(sp_low)
            temp_items.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "folder": str(entry.parent),
                    "kind": kind,
                    "kind_label": kind_label,
                    "size_bytes": sz,
                    "age_hours": round(age_hours, 1),
                }
            )

    temp_items.sort(key=lambda i: i["size_bytes"], reverse=True)
    temp_total_bytes = sum(i["size_bytes"] for i in temp_items)
    abandoned_count = sum(1 for i in temp_items if i["kind"] == "abandoned_download")
    temp_count = sum(1 for i in temp_items if i["kind"] == "temp_file")

    if temp_items:
        alerts.append(
            {
                "type": "temp_and_abandoned",
                "severity": "info",
                "title": (
                    f"{len(temp_items)} Arquivo(s) Temporário(s) / Download(s) Abandonado(s) Detectado(s)"
                ),
                "detail": (
                    f"{abandoned_count} download(s) abandonado(s) e {temp_count} temporário(s) "
                    "aguardando revisão manual (sem limpeza automática destrutiva)."
                ),
                "path": str(config.downloads_dir),
            }
        )

    return {
        "safe_mode_non_destructive": True,
        "drives": drives,
        "alerts": alerts,
        "folder_growth": folder_growth,
        "temp_and_abandoned": {
            "total_count": len(temp_items),
            "abandoned_count": abandoned_count,
            "temp_count": temp_count,
            "total_bytes": temp_total_bytes,
            "items": temp_items,
        },
    }
