import hashlib
import re
import time
from pathlib import Path
from app.engine.protector import ACTIVE_DOWNLOAD_SUFFIXES, is_active_download, is_protected_path

ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}
INSTALLER_EXTENSIONS = {".exe", ".msi", ".msix"}
REVISION_RE = re.compile(r"^(.*?)(?:[-_\s]+v(\d+)|\s*\((\d+)\))$", re.IGNORECASE)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _sha256_file(path: Path, max_bytes: int = 64 * 1024 * 1024) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            read_total = 0
            while chunk := f.read(65536):
                h.update(chunk)
                read_total += len(chunk)
                if read_total >= max_bytes:
                    break
        return h.hexdigest()
    except OSError:
        return None


def find_redundant_archives(directory: Path) -> list[dict]:
    d = Path(directory)
    if not d.exists():
        return []
    try:
        entries = list(d.iterdir())
    except OSError:
        return []

    dir_map = {_collapse_ws(e.name): e for e in entries if e.is_dir()}
    results: list[dict] = []

    for entry in entries:
        if not entry.is_file() or entry.suffix.lower() not in ARCHIVE_EXTENSIONS:
            continue
        norm_stem = _collapse_ws(entry.stem)
        if norm_stem in dir_map:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            results.append(
                {
                    "source_path": str(entry),
                    "extracted_dir": str(dir_map[norm_stem]),
                    "reason": f"Arquivo compactado redundante (pasta '{dir_map[norm_stem].name}' já extraída)",
                    "size_bytes": size,
                    "subtype": "redundant_archive",
                }
            )
    return results


def find_installers(directory: Path) -> list[dict]:
    d = Path(directory)
    if not d.exists():
        return []
    try:
        entries = [e for e in d.iterdir() if e.is_file() and e.suffix.lower() in INSTALLER_EXTENSIONS]
    except OSError:
        return []

    results: list[dict] = []
    # Group portable apps by prefix to detect multiple versions of the same portable executable
    portable_groups: dict[str, list[Path]] = {}
    for entry in entries:
        lower_name = entry.stem.lower()
        if "portable" in lower_name:
            prefix = lower_name.split("-")[0].split("_")[0]
            portable_groups.setdefault(prefix, []).append(entry)
            continue

        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        results.append(
            {
                "source_path": str(entry),
                "reason": "Instalador em Downloads (pode ir para Lixeira ou Arquivo Morto)",
                "size_bytes": size,
                "subtype": "installer",
            }
        )

    for prefix, group in portable_groups.items():
        if len(group) > 1:
            sorted_group = sorted(group, key=lambda p: p.stat().st_mtime, reverse=True)
            for older in sorted_group[1:]:
                results.append(
                    {
                        "source_path": str(older),
                        "reason": f"Versão duplicada/antiga de executável portátil ({sorted_group[0].name} é mais recente)",
                        "size_bytes": older.stat().st_size,
                        "subtype": "duplicate_portable",
                    }
                )
    return results


def find_duplicates_and_revisions(
    directories: list[Path],
    prefer_keep_root: Path | None = None,
) -> list[dict]:
    files: list[Path] = []
    keep_root_resolved = Path(prefer_keep_root).resolve() if prefer_keep_root else None

    def _is_preferred(p: Path) -> bool:
        if keep_root_resolved is None:
            return False
        try:
            p.resolve().relative_to(keep_root_resolved)
            return True
        except ValueError:
            return False
    for d in directories:
        dp = Path(d)
        if not dp.exists():
            continue
        try:
            for e in dp.iterdir():
                if (
                    e.is_file()
                    and e.name.lower() != "desktop.ini"
                    and not is_active_download(e)
                    and not is_protected_path(e)
                ):
                    files.append(e)
        except OSError:
            continue

    results: list[dict] = []
    flagged_paths: set[str] = set()

    # 1. Exact duplicates by (size, sha256)
    by_size: dict[int, list[Path]] = {}
    for f in files:
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        if sz > 0:
            by_size.setdefault(sz, []).append(f)

    for sz, group in by_size.items():
        if len(group) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for f in group:
            digest = _sha256_file(f)
            if digest:
                by_hash.setdefault(digest, []).append(f)
        for digest, dup_group in by_hash.items():
            if len(dup_group) < 2:
                continue
            sorted_dups = sorted(
                dup_group,
                key=lambda p: (not _is_preferred(p), len(p.name), -p.stat().st_mtime),
            )
            keeper = sorted_dups[0]
            for extra in sorted_dups[1:]:
                if _is_preferred(extra) and not _is_preferred(keeper):
                    continue
                sp = str(extra)
                if sp not in flagged_paths:
                    flagged_paths.add(sp)
                    results.append(
                        {
                            "source_path": sp,
                            "reason": f"Duplicado idêntico de '{keeper.name}'",
                            "size_bytes": sz,
                            "subtype": "exact_duplicate",
                        }
                    )

    # 2. Versioned revisions (e.g. Sprint1-4-v4.pdf vs Sprint1-4-v5.pdf)
    revision_groups: dict[tuple[str, str], list[tuple[int, Path]]] = {}
    for f in files:
        m = REVISION_RE.match(f.stem)
        if m:
            base = _collapse_ws(m.group(1))
            ver = int(m.group(2) or m.group(3) or 0)
            revision_groups.setdefault((base, f.suffix.lower()), []).append((ver, f))

    for (base, ext), rev_list in revision_groups.items():
        if len(rev_list) < 2:
            continue
        rev_list.sort(key=lambda item: item[0], reverse=True)
        newest_ver, newest_file = rev_list[0]
        for ver, older_file in rev_list[1:]:
            sp = str(older_file)
            if sp not in flagged_paths:
                flagged_paths.add(sp)
                try:
                    sz = older_file.stat().st_size
                except OSError:
                    sz = 0
                results.append(
                    {
                        "source_path": sp,
                        "reason": f"Versão anterior v{ver} (existe '{newest_file.name}')",
                        "size_bytes": sz,
                        "subtype": "older_revision",
                    }
                )

    return results


def find_abandoned_partials_and_empty_dirs(
    directories: list[Path],
    now_ts: float | None = None,
    skip_dirs: set[str] | None = None,
) -> list[dict]:
    cur_ts = now_ts if now_ts is not None else time.time()
    skip_norm = {s.lower() for s in (skip_dirs or set())}
    results: list[dict] = []

    for d in directories:
        dp = Path(d)
        if not dp.exists():
            continue
        try:
            entries = sorted(dp.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue

        for entry in entries:
            if entry.name.lower() == "desktop.ini" or entry.name.startswith("."):
                continue
            if is_protected_path(entry):
                continue

            if entry.is_file() and entry.suffix.lower() in ACTIVE_DOWNLOAD_SUFFIXES:
                if not is_active_download(entry, now_ts=cur_ts):
                    try:
                        sz = entry.stat().st_size
                    except OSError:
                        sz = 0
                    results.append(
                        {
                            "source_path": str(entry),
                            "reason": "Download incompleto abandonado (> 24h)",
                            "size_bytes": sz,
                            "subtype": "abandoned_partial",
                        }
                    )
            elif entry.is_dir():
                if str(entry).lower() in skip_norm:
                    continue
                try:
                    children = [
                        c for c in entry.iterdir() if c.name.lower() not in {"desktop.ini", ".directory"}
                    ]
                except OSError:
                    continue
                if len(children) == 0:
                    results.append(
                        {
                            "source_path": str(entry),
                            "reason": f"Pasta vazia sem arquivos em {dp.name}",
                            "size_bytes": 0,
                            "subtype": "empty_folder",
                        }
                    )

    return results


def _collect_candidate_files_for_duplicate_center(config) -> list[Path]:
    from app.config import FOLCOLOR_CATEGORY_MAP

    roots = [
        config.downloads_dir,
        config.desktop_dir,
        config.documents_dir,
    ]
    for cat in FOLCOLOR_CATEGORY_MAP:
        roots.append(config.vida_root / cat)

    files: list[Path] = []
    seen: set[str] = set()

    def _walk(d: Path, depth: int, max_depth: int) -> None:
        if depth > max_depth or not d.exists():
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            return
        for e in entries:
            if e.name.lower() == "desktop.ini" or e.name.startswith("."):
                continue
            if is_protected_path(e, getattr(config, "projetos_dir", None)):
                continue
            if e.is_file() and not is_active_download(e):
                key = str(e).lower()
                if key not in seen:
                    seen.add(key)
                    files.append(e)
            elif e.is_dir() and depth < max_depth:
                # Skip 04_Arquivo_Morto/Limpeza_Downloads so already-archived duplicates aren't re-grouped
                if e.name.lower() in {"limpeza_downloads", "duplicados_arquivados"}:
                    continue
                _walk(e, depth + 1, max_depth)

    for r in roots:
        depth_limit = 2 if str(r).lower().startswith(str(config.vida_root).lower()) else 1
        _walk(r, 0, depth_limit)
    return files


def build_duplicate_groups(config) -> list[dict]:
    """
    Builds detailed duplicate & similar file groups for the Central de Duplicados:
    - Exact SHA-256 duplicate groups
    - Versioned / similar revision groups (v1, v2, (1))
    Each group reports total_bytes, wasted_bytes, keeper (preserved version), and extras.
    """
    files = _collect_candidate_files_for_duplicate_center(config)
    vida_resolved = Path(config.vida_root).resolve() if config.vida_root else None

    def _is_in_organized_vida(p: Path) -> bool:
        if vida_resolved is None:
            return False
        try:
            rel = p.resolve().relative_to(vida_resolved)
            return bool(rel.parts and rel.parts[0] not in {"99_Inbox", "04_Arquivo_Morto"})
        except ValueError:
            return False

    groups: list[dict] = []
    grouped_paths: set[str] = set()

    # 1. Exact SHA-256 duplicates
    by_size: dict[int, list[Path]] = {}
    for f in files:
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        if sz > 0:
            by_size.setdefault(sz, []).append(f)

    for sz, same_size_files in by_size.items():
        if len(same_size_files) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for f in same_size_files:
            digest = _sha256_file(f)
            if digest:
                by_hash.setdefault(digest, []).append(f)

        for digest, dup_list in by_hash.items():
            if len(dup_list) < 2:
                continue
            sorted_dups = sorted(
                dup_list,
                key=lambda p: (not _is_in_organized_vida(p), len(p.name), -p.stat().st_mtime),
            )
            keeper = sorted_dups[0]
            extras = sorted_dups[1:]
            for p in sorted_dups:
                grouped_paths.add(str(p).lower())

            keep_reason = (
                "Preservado no F:\\Vida (cópia organizada principal)"
                if _is_in_organized_vida(keeper)
                else "Preservado (nome mais limpo / mais recente)"
            )
            groups.append(
                {
                    "group_id": f"sha256_{digest[:10]}",
                    "group_type": "exact_sha256",
                    "group_label": f"Cópia Idêntica (SHA-256: {digest[:8]})",
                    "title": keeper.name,
                    "copy_count": len(sorted_dups),
                    "total_bytes": sz * len(sorted_dups),
                    "wasted_bytes": sz * len(extras),
                    "keeper": {
                        "name": keeper.name,
                        "path": str(keeper),
                        "folder": str(keeper.parent),
                        "size_bytes": sz,
                        "reason": keep_reason,
                    },
                    "extras": [
                        {
                            "name": ex.name,
                            "path": str(ex),
                            "folder": str(ex.parent),
                            "size_bytes": sz,
                            "reason": f"Duplicado exato de '{keeper.name}'",
                        }
                        for ex in extras
                    ],
                }
            )

    # 2. Similar / Versioned Revisions (v1/v2 or (1)/(2))
    rev_groups: dict[tuple[str, str], list[tuple[int, Path]]] = {}
    for f in files:
        if str(f).lower() in grouped_paths:
            continue
        m = REVISION_RE.match(f.stem)
        if m:
            base = _collapse_ws(m.group(1))
            ver = int(m.group(2) or m.group(3) or 0)
            rev_groups.setdefault((base, f.suffix.lower()), []).append((ver, f))

    for (base, ext), rev_list in rev_groups.items():
        if len(rev_list) < 2:
            continue
        rev_list.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
        newest_ver, keeper = rev_list[0]
        extras = [item[1] for item in rev_list[1:]]
        try:
            keeper_sz = keeper.stat().st_size
        except OSError:
            keeper_sz = 0
        extra_entries = []
        wasted = 0
        for ver, ex in rev_list[1:]:
            try:
                esz = ex.stat().st_size
            except OSError:
                esz = 0
            wasted += esz
            extra_entries.append(
                {
                    "name": ex.name,
                    "path": str(ex),
                    "folder": str(ex.parent),
                    "size_bytes": esz,
                    "reason": f"Versão anterior v{ver} (preservando '{keeper.name}')",
                }
            )
        groups.append(
            {
                "group_id": f"rev_{hashlib.sha1(f'{base}{ext}'.encode()).hexdigest()[:10]}",
                "group_type": "version_revision",
                "group_label": "Versões Semelhantes / Revisões",
                "title": f"{base}{ext}",
                "copy_count": len(rev_list),
                "total_bytes": keeper_sz + wasted,
                "wasted_bytes": wasted,
                "keeper": {
                    "name": keeper.name,
                    "path": str(keeper),
                    "folder": str(keeper.parent),
                    "size_bytes": keeper_sz,
                    "reason": f"Versão mais recente (v{newest_ver}) preservada",
                },
                "extras": extra_entries,
            }
        )

    groups.sort(key=lambda g: g["wasted_bytes"], reverse=True)
    return groups


def archive_duplicate_extras(
    extra_paths: list[str],
    db,
    config,
    mode: str = "archive",
) -> dict:
    """
    Manual and reversible action for the Central de Duplicados:
    Moves selected extra copies into 04_Arquivo_Morto/Duplicados_Arquivados (or RecycleBin)
    and records a reversible batch in SQLite.
    """
    from app.engine.executor import execute_queue_items

    archive_dir = config.vida_root / "04_Arquivo_Morto" / "Duplicados_Arquivados"
    items_to_run = []
    for sp in extra_paths:
        p = Path(sp)
        if not p.exists():
            continue
        try:
            sz = p.stat().st_size
        except OSError:
            sz = 0
        items_to_run.append(
            {
                "id": hashlib.sha1(sp.encode("utf-8")).hexdigest()[:12],
                "category": "espaco_recuperavel",
                "source_path": str(p),
                "target_path": str(archive_dir / p.name),
                "size_bytes": sz,
                "reason": "Cópia extra arquivada pela Central de Duplicados",
                "rule_name": "Central de Duplicados",
            }
        )
    return execute_queue_items(
        items_to_run,
        db,
        config,
        include_destructive_trash=True,
        recoverable_mode=mode,
    )



