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


