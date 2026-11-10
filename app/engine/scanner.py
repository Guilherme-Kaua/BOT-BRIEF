import hashlib
import shutil
import time
from pathlib import Path
from app.config import AppConfig, FOLCOLOR_CATEGORY_MAP
from app.db import Database
from app.engine.duplicates import (
    find_duplicates_and_revisions,
    find_installers,
    find_redundant_archives,
)
from app.engine.folcolor import scan_missing_icons
from app.engine.protector import is_active_download, is_protected_path
from app.engine.rules import (
    evaluate_file,
    is_unstandardized_folder_name,
    suggest_clean_name,
)


def _item_id(category: str, source_path: str) -> str:
    raw = f"{category}::{source_path}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def scan_all(config: AppConfig, db: Database, now_ts: float | None = None) -> dict:
    current_ts = now_ts if now_ts is not None else time.time()
    rules = db.list_rules()
    queue: list[dict] = []
    seen_sources: set[str] = set()

    # 1. Recoverable space items in Downloads and Vida category roots
    vida_cat_dirs = [
        config.vida_root / cat
        for cat in FOLCOLOR_CATEGORY_MAP
        if (config.vida_root / cat).exists()
    ]
    scan_dirs = [config.downloads_dir, *vida_cat_dirs]

    recoverable_items = (
        find_redundant_archives(config.downloads_dir)
        + find_installers(config.downloads_dir)
        + find_duplicates_and_revisions(scan_dirs, prefer_keep_root=config.vida_root)
    )

    for rec in recoverable_items:
        sp = rec["source_path"]
        if sp in seen_sources:
            continue
        seen_sources.add(sp)
        queue.append(
            {
                "id": _item_id("espaco_recuperavel", sp),
                "category": "espaco_recuperavel",
                "source_path": sp,
                "target_path": str(config.vida_root / "04_Arquivo_Morto" / "Limpeza_Downloads" / Path(sp).name),
                "suggested_name": None,
                "reason": rec["reason"],
                "size_bytes": int(rec.get("size_bytes", 0)),
                "cooldown_ready": False,
                "rule_name": "Limpeza de Espaço (Instaladores / Duplicados / Zips)",
                "folcolor_index": 15,
            }
        )

    # 2. Scan Downloads, Desktop, Documents & Vida category roots for routing rules & clean renames
    scope_dirs: list[tuple[str, Path, int]] = [
        ("Downloads", config.downloads_dir, config.downloads_cooldown_minutes),
        ("Desktop", config.desktop_dir, config.downloads_cooldown_minutes),
        ("Documents", config.documents_dir, config.downloads_cooldown_minutes),
    ]
    for cat in FOLCOLOR_CATEGORY_MAP:
        cat_path = config.vida_root / cat
        if cat_path.exists():
            scope_dirs.append((cat, cat_path, config.vida_root_cooldown_minutes))

    unstandardized_by_scope: dict[str, list[Path]] = {}

    for scope_name, directory, cooldown_min in scope_dirs:
        if not directory.exists():
            continue
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue

        for entry in entries:
            if entry.name.lower() in {"desktop.ini", ".directory"} or entry.name.startswith("."):
                continue
            if is_active_download(entry) or is_protected_path(entry, config.projetos_dir):
                continue

            sp = str(entry)
            if sp in seen_sources:
                continue

            if entry.is_dir():
                if is_unstandardized_folder_name(entry.name):
                    unstandardized_by_scope.setdefault(scope_name, []).append(entry)
                    clean_folder = f"Projeto_{entry.name.replace(' ', '_')}"
                    seen_sources.add(sp)
                    queue.append(
                        {
                            "id": _item_id("renomear_sugerido", sp),
                            "category": "renomear_sugerido",
                            "source_path": sp,
                            "target_path": str(entry.parent / clean_folder),
                            "suggested_name": clean_folder,
                            "reason": f"Pasta com nome fora do padrão em {scope_name}",
                            "size_bytes": 0,
                            "cooldown_ready": False,
                            "rule_name": "Padronização de Pastas",
                            "folcolor_index": FOLCOLOR_CATEGORY_MAP.get(scope_name, 6),
                        }
                    )
                    continue
                # Only evaluate top-level folders in Downloads (like ghidra, SDIO), never category subfolders in Vida
                if scope_name != "Downloads":
                    continue

            clean_name = suggest_clean_name(entry) if entry.is_file() else None
            matched_rule = evaluate_file(entry, scope_name, rules, now_ts=current_ts)

            try:
                stat = entry.stat()
                size_bytes = stat.st_size if entry.is_file() else 0
                idle_minutes = max(0.0, (current_ts - stat.st_mtime) / 60.0)
            except OSError:
                size_bytes = 0
                idle_minutes = 0.0

            cooldown_ready = idle_minutes >= cooldown_min

            if matched_rule:
                dest_dir = config.vida_root / matched_rule["target_subpath"]
                final_name = clean_name or entry.name
                target_path = dest_dir / final_name
                if target_path.resolve() == entry.resolve():
                    continue
                seen_sources.add(sp)
                cat_type = "renomear_sugerido" if clean_name else "pronto_para_mover"
                reason_txt = (
                    f"Renomear para '{clean_name}' → {matched_rule['target_subpath']}"
                    if clean_name
                    else f"Regra '{matched_rule['rule_name']}' → {matched_rule['target_subpath']}"
                )
                queue.append(
                    {
                        "id": _item_id(cat_type, sp),
                        "category": cat_type,
                        "source_path": sp,
                        "target_path": str(target_path),
                        "suggested_name": clean_name,
                        "reason": reason_txt,
                        "size_bytes": size_bytes,
                        "cooldown_ready": cooldown_ready,
                        "rule_name": matched_rule["rule_name"],
                        "folcolor_index": matched_rule["folcolor_index"],
                    }
                )
            elif clean_name:
                seen_sources.add(sp)
                queue.append(
                    {
                        "id": _item_id("renomear_sugerido", sp),
                        "category": "renomear_sugerido",
                        "source_path": sp,
                        "target_path": str(entry.parent / clean_name),
                        "suggested_name": clean_name,
                        "reason": f"Nome ilegível → sugerido '{clean_name}'",
                        "size_bytes": size_bytes,
                        "cooldown_ready": False,
                        "rule_name": "Padronização de Nomes",
                        "folcolor_index": FOLCOLOR_CATEGORY_MAP.get(scope_name, 8),
                    }
                )

    # 3. Missing Folcolor icons inside F:\Vida
    missing_icons = scan_missing_icons(config.vida_root, config.folcolor_exe, max_depth=2)
    for icon_item in missing_icons:
        sp = icon_item["path"]
        queue.append(
            {
                "id": _item_id("icone_pendente", sp),
                "category": "icone_pendente",
                "source_path": sp,
                "target_path": sp,
                "suggested_name": None,
                "reason": f"Aplicar ícone Folcolor #{icon_item['folcolor_index']} ({icon_item['category_folder']})",
                "size_bytes": 0,
                "cooldown_ready": True,
                "rule_name": f"Cor Folcolor ({icon_item['category_folder']})",
                "folcolor_index": icon_item["folcolor_index"],
            }
        )

    # 4. Build Folder Health Cards
    folder_cards = _build_folder_cards(config, queue, unstandardized_by_scope)

    recoverable_bytes = sum(
        item["size_bytes"] for item in queue if item["category"] == "espaco_recuperavel"
    )
    auto_ready_count = sum(
        1
        for item in queue
        if item["category"] in {"pronto_para_mover", "icone_pendente"} and item["cooldown_ready"]
    )
    try:
        c_free_bytes = shutil.disk_usage(config.downloads_dir.anchor or "C:\\").free
    except OSError:
        c_free_bytes = 0

    return {
        "summary": {
            "total_disorganized": len(queue),
            "recoverable_bytes": recoverable_bytes,
            "auto_ready_count": auto_ready_count,
            "c_free_bytes": c_free_bytes,
        },
        "folder_cards": folder_cards,
        "queue": queue,
    }


def _build_folder_cards(
    config: AppConfig,
    queue: list[dict],
    unstandardized_by_scope: dict[str, list[Path]],
) -> list[dict]:
    cards_spec = [
        ("downloads", "C:\\Downloads", config.downloads_dir),
        ("02_Areas", "F:\\Vida\\02_Areas", config.vida_root / "02_Areas"),
        ("01_Projetos", "F:\\Vida\\01_Projetos", config.vida_root / "01_Projetos"),
        ("03_Recursos", "F:\\Vida\\03_Recursos", config.vida_root / "03_Recursos"),
        ("00_Jogos", "F:\\Vida\\00_Jogos", config.vida_root / "00_Jogos"),
        ("99_Inbox", "F:\\Vida\\99_Inbox", config.vida_root / "99_Inbox"),
    ]
    cards: list[dict] = []
    for card_id, label, path in cards_spec:
        path_str = str(path).lower()
        related = [
            q
            for q in queue
            if q["source_path"].lower().startswith(path_str)
            and q["category"] != "icone_pendente"
        ]
        icon_issues = [
            q
            for q in queue
            if q["source_path"].lower().startswith(path_str)
            and q["category"] == "icone_pendente"
        ]
        count = len(related)
        if card_id == "downloads" and count > 5:
            badge = "DESORGANIZADO"
            level = "red"
            score = max(15, 100 - count * 3)
            headline = f"{count} itens soltos"
            rec_count = sum(1 for q in related if q["category"] == "espaco_recuperavel")
            move_count = count - rec_count
            detail = f"{rec_count} p/ limpar · {move_count} p/ mover ao F:\\Vida"
        elif count > 0:
            has_unstd = any(q["category"] == "renomear_sugerido" for q in related)
            badge = "FORA DO PADRÃO" if has_unstd else f"{count} SOLTOS NA RAIZ"
            level = "amber"
            score = max(55, 95 - count * 5)
            headline = f"{score}% Organizado"
            detail = f"{count} arquivo(s)/pasta(s) fora do lugar · {len(icon_issues)} ícones pendentes"
        else:
            badge = "ORGANIZADO"
            level = "green"
            score = 100 if not icon_issues else 92
            headline = f"{score}% Limpo"
            detail = (
                "Ícones Folcolor ativos · Tudo no lugar"
                if not icon_issues
                else f"{len(icon_issues)} subpasta(s) aguardando ícone Folcolor"
            )

        cards.append(
            {
                "id": card_id,
                "name": label,
                "path": str(path),
                "badge": badge,
                "status_level": level,
                "score_pct": score,
                "headline": headline,
                "detail": detail,
            }
        )
    return cards

