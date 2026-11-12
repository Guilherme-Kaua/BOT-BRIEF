import json
import os
import shutil
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig, FOLCOLOR_CATEGORY_MAP, VIDA_ROOT_ICON_INDEX
from app.db import Database
from app.engine.duplicates import build_duplicate_groups
from app.engine.folcolor import apply_folcolor_icon, parse_folcolor_index_from_ini
from app.engine.storage_monitor import analyze_storage


# ==============================================================================
# 18. RELATÓRIO DE ORGANIZAÇÃO (Semanal / Mensal)
# ==============================================================================
def build_organization_report(
    config: AppConfig,
    db: Database,
    period_days: int = 7,
    scan_state: dict[str, Any] | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    now_dt = (
        datetime.fromtimestamp(now_ts, tz=timezone.utc)
        if now_ts is not None
        else datetime.now(timezone.utc)
    )
    cutoff_dt = now_dt - timedelta(days=max(1, int(period_days)))

    batches = db.list_batches(limit=500)
    organized_count = 0
    recovered_bytes = 0
    undone_batches_count = 0
    undone_items_count = 0
    rule_counter: Counter[str] = Counter()

    for b in batches:
        try:
            b_dt = datetime.fromisoformat(b["created_at"])
            if b_dt.tzinfo is None:
                b_dt = b_dt.replace(tzinfo=timezone.utc)
        except Exception:
            b_dt = now_dt
        if b_dt < cutoff_dt:
            continue

        items = b.get("items", [])
        if b.get("undone"):
            undone_batches_count += 1
            undone_items_count += len(items)
            continue

        for it in items:
            atype = it.get("action_type", "")
            sz = int(it.get("size_bytes", 0))
            if atype in {"move", "rename", "archive", "trash"}:
                organized_count += 1
            if atype in {"archive", "trash"}:
                recovered_bytes += sz
            try:
                meta = json.loads(it.get("meta_json") or "{}")
            except Exception:
                meta = {}
            rname = str(meta.get("rule_name") or "").strip()
            if rname:
                rule_counter[rname] += 1

    # Duplicates & pending metrics
    if scan_state:
        dup_groups = scan_state.get("duplicate_groups", [])
        pending_count = len(scan_state.get("queue", []))
        storage_mon = scan_state.get("storage_monitor") or analyze_storage(config, db, now_ts=now_ts)
    else:
        dup_groups = build_duplicate_groups(config)
        pending_count = 0
        storage_mon = analyze_storage(config, db, now_ts=now_ts)

    dup_wasted = sum(int(g.get("wasted_bytes", 0)) for g in dup_groups)
    growth_folders = sorted(
        storage_mon.get("folder_growth", []),
        key=lambda g: int(g.get("delta_bytes", 0)),
        reverse=True,
    )
    top_growing = [g for g in growth_folders if int(g.get("delta_bytes", 0)) > 0][:5]
    if not top_growing:
        top_growing = sorted(
            growth_folders,
            key=lambda g: int(g.get("current_bytes", 0)),
            reverse=True,
        )[:5]

    period_label = "Semanal (Últimos 7 dias)" if period_days <= 7 else f"Mensal (Últimos {period_days} dias)"

    return {
        "period_days": int(period_days),
        "period_label": period_label,
        "generated_at": now_dt.isoformat(),
        "organized_count": organized_count,
        "recovered_bytes": recovered_bytes,
        "duplicates_groups_count": len(dup_groups),
        "duplicates_wasted_bytes": dup_wasted,
        "pending_count": pending_count,
        "undone_batches_count": undone_batches_count,
        "undone_items_count": undone_items_count,
        "top_rules": [{"rule_name": k, "count": v} for k, v in rule_counter.most_common(8)],
        "top_growing_folders": top_growing,
    }


def format_report_markdown(report: dict[str, Any]) -> str:
    def _fmt(b: int) -> str:
        val = float(b)
        for u in ["B", "KB", "MB", "GB", "TB"]:
            if val < 1024 or u == "TB":
                return f"{val:.2f} {u}" if u in {"MB", "GB", "TB"} else f"{int(val)} {u}"
            val /= 1024.0
        return f"{b} B"

    lines = [
        f"# Relatório de Organização — Vida Organizer ({report['period_label']})",
        f"Gerado em: `{report['generated_at'][:19]}`",
        "",
        "## Resumo",
        f"- **Arquivos organizados:** {report['organized_count']}",
        f"- **Espaço recuperado (arquivado/limpo):** {_fmt(report['recovered_bytes'])}",
        f"- **Duplicados identificados:** {report['duplicates_groups_count']} grupos ({_fmt(report['duplicates_wasted_bytes'])} economizáveis)",
        f"- **Arquivos pendentes na fila:** {report['pending_count']}",
        f"- **Operações desfeitas (Undo):** {report['undone_batches_count']} lotes ({report['undone_items_count']} itens)",
        "",
        "## Regras Mais Utilizadas",
    ]
    if report["top_rules"]:
        for r in report["top_rules"]:
            lines.append(f"- **{r['rule_name']}**: {r['count']} vez(es)")
    else:
        lines.append("- Nenhuma regra registrada no período.")

    lines.append("")
    lines.append("## Pastas que Mais Cresceram / Maiores Pastas")
    for f in report.get("top_growing_folders", []):
        lines.append(
            f"- **{f['name']}** (`{f['path']}`): Atual {_fmt(int(f.get('current_bytes', 0)))} | Δ +{_fmt(int(f.get('delta_bytes', 0)))}"
        )
    return "\n".join(lines)


# ==============================================================================
# 19. GERENCIADOR DE APLICATIVOS E FERRAMENTAS
# ==============================================================================
def _clean_display_icon(raw_icon: str | None) -> str:
    if not raw_icon:
        return ""
    cleaned = str(raw_icon).split(",")[0].strip().strip('"')
    return cleaned


def _scan_windows_installed_apps(max_items: int = 250) -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    import winreg

    apps: dict[str, dict[str, str]] = {}
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, subkey in reg_paths:
        try:
            with winreg.OpenKey(hive, subkey) as root:
                count = winreg.QueryInfoKey(root)[0]
                for i in range(count):
                    try:
                        name_key = winreg.EnumKey(root, i)
                        with winreg.OpenKey(root, name_key) as app_key:
                            try:
                                disp_name = str(winreg.QueryValueEx(app_key, "DisplayName")[0]).strip()
                            except OSError:
                                continue
                            if not disp_name:
                                continue

                            def _q(val: str) -> str:
                                try:
                                    return str(winreg.QueryValueEx(app_key, val)[0]).strip()
                                except OSError:
                                    return ""

                            icon_exe = _clean_display_icon(_q("DisplayIcon"))
                            inst_loc = _q("InstallLocation").strip('"')
                            exe_path = ""
                            if icon_exe.lower().endswith(".exe") and Path(icon_exe).exists():
                                exe_path = icon_exe
                            elif inst_loc and Path(inst_loc).exists():
                                exes = list(Path(inst_loc).glob("*.exe"))
                                if exes:
                                    exe_path = str(exes[0])

                            apps.setdefault(
                                disp_name.lower(),
                                {
                                    "name": disp_name,
                                    "version": _q("DisplayVersion"),
                                    "publisher": _q("Publisher"),
                                    "exe_path": exe_path,
                                    "install_location": inst_loc,
                                    "source": "Instalado (Windows)",
                                },
                            )
                    except OSError:
                        continue
        except OSError:
            continue
        if len(apps) >= max_items:
            break
    return list(apps.values())[:max_items]


def build_app_catalog(config: AppConfig, include_registry: bool = True) -> list[dict[str, Any]]:
    # 1. Gather archived/downloaded installers
    installer_dirs = [
        config.vida_root / "04_Arquivo_Morto" / "Instaladores",
        config.vida_root / "04_Arquivo_Morto" / "Limpeza_Downloads",
        config.downloads_dir,
    ]
    installers: list[Path] = []
    for idir in installer_dirs:
        if idir.exists():
            for f in idir.iterdir():
                if f.is_file() and f.suffix.lower() in {".exe", ".msi", ".msix", ".bat"}:
                    installers.append(f)

    # 2. Gather portable tools inside F:\Vida\03_Recursos\Ferramentas_Tech
    portable_tools: list[Path] = []
    tech_dir = config.vida_root / "03_Recursos" / "Ferramentas_Tech"
    if tech_dir.exists():
        for root_dir, _dirs, files in os.walk(tech_dir):
            depth = len(Path(root_dir).relative_to(tech_dir).parts)
            if depth > 2:
                continue
            for fn in files:
                fp = Path(root_dir) / fn
                if fp.suffix.lower() in {".exe", ".bat", ".cmd"}:
                    portable_tools.append(fp)

    # 3. Gather docs and projects for smart association
    docs_pool: list[Path] = []
    for doc_dir in (
        config.vida_root / "03_Recursos",
        config.vida_root / "02_Areas",
    ):
        if doc_dir.exists():
            for f in doc_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in {".pdf", ".md", ".txt", ".docx"}:
                    docs_pool.append(f)
                    if len(docs_pool) >= 300:
                        break

    projects_pool: list[Path] = []
    for pdir in (config.projetos_dir, config.vida_root / "01_Projetos"):
        if pdir.exists():
            for child in pdir.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    projects_pool.append(child)

    catalog: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    def _associate(app_name: str, extra_tokens: list[str] | None = None) -> tuple[list[str], list[str], list[str]]:
        tokens = [
            t.lower()
            for t in app_name.replace("-", " ").replace("_", " ").split()
            if len(t) >= 3
        ]
        if extra_tokens:
            tokens.extend(t.lower() for t in extra_tokens if len(t) >= 3)
        matched_inst = [str(p) for p in installers if any(tok in p.name.lower() for tok in tokens)]
        matched_docs = [str(p) for p in docs_pool if any(tok in p.name.lower() for tok in tokens)][:4]
        matched_proj = [str(p) for p in projects_pool if any(tok in p.name.lower() for tok in tokens)][:4]
        return matched_inst, matched_docs, matched_proj

    # Add Portable tools from F:\Vida\03_Recursos\Ferramentas_Tech
    for tool in portable_tools:
        key = tool.stem.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        inst, docs, projs = _associate(tool.stem)
        catalog.append(
            {
                "name": tool.stem,
                "version": "Portátil",
                "publisher": "F:\\Vida Ferramentas",
                "exe_path": str(tool),
                "install_location": str(tool.parent),
                "archived_installers": inst,
                "related_docs": docs,
                "related_projects": projs,
                "source": "Ferramenta Portátil (F:\\Vida)",
            }
        )

    # Add Windows Registry apps
    if include_registry:
        for app_info in _scan_windows_installed_apps():
            key = app_info["name"].lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            inst, docs, projs = _associate(app_info["name"])
            catalog.append(
                {
                    **app_info,
                    "archived_installers": inst,
                    "related_docs": docs,
                    "related_projects": projs,
                }
            )

    # Add standalone archived installers not yet represented in catalog
    for inst_p in installers:
        stem_low = inst_p.stem.lower()
        already = any(
            any(tok in str(inst_p).lower() for tok in c["name"].lower().split() if len(tok) >= 4)
            or str(inst_p) in c["archived_installers"]
            for c in catalog
        )
        if not already and stem_low not in seen_names:
            seen_names.add(stem_low)
            _, docs, projs = _associate(inst_p.stem)
            catalog.append(
                {
                    "name": inst_p.stem,
                    "version": "Instalador",
                    "publisher": inst_p.parent.name,
                    "exe_path": str(inst_p),
                    "install_location": str(inst_p.parent),
                    "archived_installers": [str(inst_p)],
                    "related_docs": docs,
                    "related_projects": projs,
                    "source": "Instalador Arquivado",
                }
            )

    catalog.sort(
        key=lambda c: (
            0 if c["archived_installers"] or c["related_projects"] else 1,
            c["name"].lower(),
        )
    )
    return catalog


# ==============================================================================
# 20. COFRE DE CONFIGURAÇÕES (Exportar / Importar ZIP Portátil)
# ==============================================================================
def _scan_vida_folder_structure_and_folcolor(vida_root: Path) -> tuple[list[str], dict[str, int]]:
    folders: list[str] = []
    folcolor_map: dict[str, int] = {}
    if not vida_root.exists():
        return folders, folcolor_map

    for root_dir, _dirs, _files in os.walk(vida_root):
        rp = Path(root_dir)
        try:
            rel = rp.relative_to(vida_root)
        except ValueError:
            continue
        if len(rel.parts) > 3:
            continue
        rel_str = "." if str(rel) == "." else str(rel).replace("\\", "/")
        if rel_str != ".":
            folders.append(rel_str)
        ini_idx = parse_folcolor_index_from_ini(rp)
        if ini_idx is not None:
            folcolor_map[rel_str] = ini_idx
    return sorted(set(folders)), folcolor_map


def export_config_vault(
    output_zip_path: Path,
    db: Database,
    config: AppConfig,
    options: dict[str, bool] | None = None,
) -> dict[str, Any]:
    opts = {
        "rules": True,
        "folcolor": True,
        "ignored_paths": True,
        "workspaces": True,
        "tags": True,
        "preferences": True,
        "folder_structure": True,
        "history_db": False,
    }
    if options:
        opts.update({k: bool(v) for k, v in options.items()})

    out_path = Path(output_zip_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    folders, folcolor_detected = _scan_vida_folder_structure_and_folcolor(config.vida_root)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "options": opts,
        "vida_root": str(config.vida_root),
    }

    if opts["rules"]:
        payload["rules"] = db.list_rules()
    if opts["folcolor"]:
        payload["folcolor"] = {
            "root_index": VIDA_ROOT_ICON_INDEX,
            "category_map": FOLCOLOR_CATEGORY_MAP,
            "folder_icons": folcolor_detected,
        }
    if opts["ignored_paths"]:
        payload["ignored_paths"] = db.list_ignored_paths()
    if opts["workspaces"]:
        payload["workspaces"] = db.list_workspaces()
    if opts["tags"]:
        payload["tags"] = db.list_files_by_tag()
    if opts["preferences"]:
        payload["preferences"] = {
            "settings": db.list_settings(),
            "downloads_cooldown_minutes": config.downloads_cooldown_minutes,
            "vida_root_cooldown_minutes": config.vida_root_cooldown_minutes,
        }
    if opts["folder_structure"]:
        payload["folder_structure"] = folders

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("vault_config.json", json.dumps(payload, indent=2, ensure_ascii=False))
        if opts["history_db"] and config.db_path.exists():
            zf.write(config.db_path, arcname="vida_organizer.db")

    return {
        "zip_path": str(out_path),
        "size_bytes": out_path.stat().st_size,
        "included_sections": [k for k, v in opts.items() if v],
    }


def import_config_vault(
    input_zip_path: Path,
    db: Database,
    config: AppConfig,
    options: dict[str, bool] | None = None,
) -> dict[str, Any]:
    in_path = Path(input_zip_path)
    if not in_path.exists():
        raise FileNotFoundError(f"Arquivo do cofre não encontrado: {in_path}")

    with zipfile.ZipFile(in_path, "r") as zf:
        names = set(zf.namelist())
        if "vault_config.json" not in names:
            raise ValueError("ZIP inválido: 'vault_config.json' ausente.")
        payload = json.loads(zf.read("vault_config.json").decode("utf-8"))

        opts = dict(payload.get("options", {}))
        if options:
            for k, v in options.items():
                opts[k] = bool(v)

        restored: dict[str, int] = {
            "rules": 0,
            "ignored_paths": 0,
            "workspaces": 0,
            "tags": 0,
            "preferences": 0,
            "folders_created": 0,
            "folcolor_applied": 0,
            "history_db": 0,
        }

        if opts.get("history_db") and "vida_organizer.db" in names:
            config.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config.db_path, "wb") as f_db:
                f_db.write(zf.read("vida_organizer.db"))
            db.init_db()
            restored["history_db"] = 1
            # Refresh folder structure/folcolor if requested, then return
            if not (opts.get("folder_structure") or opts.get("folcolor")):
                return {"restored": restored, "zip_path": str(in_path)}

        if opts.get("rules") and "rules" in payload:
            existing_rules = {r["name"].lower(): r["id"] for r in db.list_rules()}
            for rule in payload["rules"]:
                r_copy = dict(rule)
                r_copy["id"] = existing_rules.get(r_copy["name"].lower())
                db.upsert_rule(r_copy)
                restored["rules"] += 1

        if opts.get("ignored_paths") and "ignored_paths" in payload:
            for entry in payload["ignored_paths"]:
                db.add_ignored_path(entry["path"], entry.get("reason", "Importado do Cofre"))
                restored["ignored_paths"] += 1

        if opts.get("workspaces") and "workspaces" in payload:
            existing_ws = {w["name"].lower(): w["id"] for w in db.list_workspaces()}
            for ws in payload["workspaces"]:
                w_copy = dict(ws)
                w_copy["id"] = existing_ws.get(w_copy["name"].lower())
                db.upsert_workspace(w_copy)
                if ws.get("is_active"):
                    db.set_active_workspace(ws["name"])
                restored["workspaces"] += 1

        if opts.get("tags") and "tags" in payload:
            for entry in payload["tags"]:
                for t in entry.get("tags", []):
                    db.add_file_tag(entry["path"], t)
                    restored["tags"] += 1

        if opts.get("preferences") and "preferences" in payload:
            for k, v in payload["preferences"].get("settings", {}).items():
                db.set_setting(k, v)
                restored["preferences"] += 1

        if opts.get("folder_structure") and "folder_structure" in payload:
            for rel_dir in payload["folder_structure"]:
                target_dir = config.vida_root / rel_dir
                if not target_dir.exists():
                    target_dir.mkdir(parents=True, exist_ok=True)
                    restored["folders_created"] += 1

        if opts.get("folcolor") and "folcolor" in payload:
            fc = payload["folcolor"]
            for rel_dir, icon_idx in fc.get("folder_icons", {}).items():
                target_dir = config.vida_root if rel_dir == "." else (config.vida_root / rel_dir)
                if target_dir.exists():
                    icon_res = (
                        f"{config.folcolor_exe},{int(icon_idx)}"
                        if config.folcolor_exe.exists()
                        else f"C:\\Windows\\System32\\shell32.dll,3"
                    )
                    apply_folcolor_icon(target_dir, icon_res)
                    restored["folcolor_applied"] += 1

    return {"restored": restored, "zip_path": str(in_path)}
