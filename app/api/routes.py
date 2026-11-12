import os
import subprocess
import time
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.config import AppConfig
from app.db import Database
from app.engine.duplicates import archive_duplicate_extras, build_duplicate_groups
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.explorer_integration import (
    build_context_menu_spec,
    install_context_menu,
    is_context_menu_installed,
    uninstall_context_menu,
)
from app.engine.reporting_catalog_vault import (
    build_app_catalog,
    build_organization_report,
    export_config_vault,
    import_config_vault,
)
from app.engine.scanner import _build_folder_cards, scan_all
from app.engine.semantic_search import SMART_TAGS_CATALOG, parse_natural_query, semantic_search_files
from app.engine.storage_monitor import analyze_storage


class ExecuteRequest(BaseModel):
    item_ids: list[str] | None = None
    categories: list[str] | None = None
    include_trash: bool = False
    recoverable_mode: str = "archive"


class UndoRequest(BaseModel):
    batch_id: int | None = None


class RulePayload(BaseModel):
    id: int | None = None
    name: str
    priority: int = 50
    category_folder: str
    target_subpath: str
    folcolor_index: int = 13
    keywords: list[str] = []
    extensions: list[str] = []
    source_scopes: list[str] = ["*"]
    min_age_days: int = 0
    enabled: int = 1


class OpenFolderRequest(BaseModel):
    path: str


class UpdateTargetRequest(BaseModel):
    target_path: str
    category: str | None = None


class MoveToFolderRequest(BaseModel):
    item_ids: list[str]
    target_folder: str


class ArchiveDuplicatesRequest(BaseModel):
    extra_paths: list[str]
    mode: str = "archive"


class TagActionRequest(BaseModel):
    path: str
    tag: str


class LearningDecisionRequest(BaseModel):
    signature_key: str
    folcolor_index: int = 9


class TriageStateRequest(BaseModel):
    item_id: str
    column_name: str
    custom_name: str | None = None
    custom_target: str | None = None


class WorkspaceActivateRequest(BaseModel):
    name: str


class WorkspacePayload(BaseModel):
    id: int | None = None
    name: str
    icon: str = "📁"
    color: str = "#3b82f6"
    description: str = ""
    favorite_folders: list[str] = []
    keywords: list[str] = []
    shortcuts: list[dict[str, str]] = []


class VaultRequest(BaseModel):
    zip_path: str
    options: dict[str, bool] = {}


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    db.init_db()

    app = FastAPI(title="Vida Organizer — BOT-BRIEF")
    app.state.config = cfg
    app.state.db = db
    app.state.auto_watch_enabled = True
    app.state.cached_scan = None
    app.state.cached_at = 0.0

    def _enrich_scan(report: dict[str, Any]) -> dict[str, Any]:
        report["last_undoable_batch"] = db.get_last_undoable_batch()
        report["auto_watch_enabled"] = app.state.auto_watch_enabled
        report["vida_root"] = str(cfg.vida_root)
        report["rules"] = db.list_rules()
        report["history"] = db.list_batches(limit=25)
        return report

    def _get_or_refresh_scan(force: bool = False) -> dict[str, Any]:
        if force or app.state.cached_scan is None or (time.time() - app.state.cached_at) > 30.0:
            app.state.cached_scan = scan_all(cfg, db)
            app.state.cached_at = time.time()
        return _enrich_scan(app.state.cached_scan)

    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/api/scan")
    def api_scan(force: int = 0) -> dict[str, Any]:
        return _get_or_refresh_scan(force=bool(force))

    @app.post("/api/execute")
    def api_execute(req: ExecuteRequest) -> dict[str, Any]:
        report = _get_or_refresh_scan(force=False)
        queue = report["queue"]

        selected = queue
        if req.item_ids is not None:
            wanted_ids = set(req.item_ids)
            selected = [item for item in selected if item["id"] in wanted_ids]
        if req.categories is not None:
            wanted_cats = set(req.categories)
            selected = [item for item in selected if item["category"] in wanted_cats]

        res = execute_queue_items(
            selected,
            db,
            cfg,
            include_destructive_trash=req.include_trash,
            recoverable_mode=req.recoverable_mode,
        )

        # Update in-memory cache immediately so response is <20ms without rescanning the disk
        executed_ids = {r["id"] for r in res.get("results", []) if r.get("status") == "executed"}
        if app.state.cached_scan is not None and executed_ids:
            remaining = [i for i in app.state.cached_scan["queue"] if i["id"] not in executed_ids]
            app.state.cached_scan["queue"] = remaining
            app.state.cached_scan["summary"]["total_disorganized"] = len(remaining)
            app.state.cached_scan["summary"]["recoverable_bytes"] = sum(
                i["size_bytes"] for i in remaining if i["category"] == "espaco_recuperavel"
            )
            app.state.cached_scan["folder_cards"] = _build_folder_cards(cfg, remaining, {})

        res["scan"] = _enrich_scan(app.state.cached_scan or scan_all(cfg, db))
        return res

    @app.post("/api/undo")
    def api_undo(req: UndoRequest) -> dict[str, Any]:
        target_id = req.batch_id
        if target_id is None:
            last = db.get_last_undoable_batch()
            if not last:
                return {
                    "undone_count": 0,
                    "skipped_count": 0,
                    "details": [],
                    "message": "Nenhuma ação pendente para desfazer",
                    "scan": _get_or_refresh_scan(force=False),
                }
            target_id = int(last["id"])
        res = undo_batch(target_id, db)
        res["scan"] = _get_or_refresh_scan(force=True)
        return res

    @app.get("/api/rules")
    def api_list_rules() -> list[dict]:
        return db.list_rules()

    @app.post("/api/rules")
    def api_upsert_rule(payload: RulePayload) -> dict[str, Any]:
        rule_id = db.upsert_rule(payload.model_dump())
        return {"id": rule_id, "rules": db.list_rules(), "scan": _get_or_refresh_scan(force=True)}

    @app.delete("/api/rules/{rule_id}")
    def api_delete_rule(rule_id: int) -> dict[str, Any]:
        db.delete_rule(rule_id)
        return {"deleted": rule_id, "rules": db.list_rules(), "scan": _get_or_refresh_scan(force=True)}

    @app.get("/api/history")
    def api_history() -> list[dict]:
        return db.list_batches(limit=25)

    @app.get("/api/storage")
    def api_storage(reset_baseline: int = 0) -> dict[str, Any]:
        return analyze_storage(cfg, db, reset_baseline=bool(reset_baseline))

    @app.get("/api/duplicates")
    def api_duplicates() -> list[dict[str, Any]]:
        return build_duplicate_groups(cfg)

    @app.post("/api/duplicates/archive")
    def api_archive_duplicates(req: ArchiveDuplicatesRequest) -> dict[str, Any]:
        res = archive_duplicate_extras(req.extra_paths, db, cfg, mode=req.mode)
        res["scan"] = _get_or_refresh_scan(force=True)
        return res

    @app.get("/api/search")
    def api_semantic_search(q: str = "", tag: str | None = None, limit: int = 80) -> dict[str, Any]:
        return {
            "query": q,
            "tag": tag,
            "parsed": parse_natural_query(q),
            "results": semantic_search_files(q, cfg, db, tag_filter=tag, limit=limit),
        }

    @app.get("/api/tags")
    def api_list_tags(tag: str | None = None) -> dict[str, Any]:
        return {
            "catalog": SMART_TAGS_CATALOG,
            "files": db.list_files_by_tag(tag),
        }

    @app.post("/api/tags")
    def api_add_tag(req: TagActionRequest) -> dict[str, Any]:
        db.add_file_tag(req.path, req.tag)
        return {
            "path": req.path,
            "tags": db.get_tags_for_path(req.path),
            "files": db.list_files_by_tag(),
        }

    @app.delete("/api/tags")
    def api_remove_tag(req: TagActionRequest) -> dict[str, Any]:
        db.remove_file_tag(req.path, req.tag)
        return {
            "path": req.path,
            "tags": db.get_tags_for_path(req.path),
            "files": db.list_files_by_tag(),
        }

    # --- 13. Memória dos arquivos ---
    @app.get("/api/file-memory")
    def api_file_memory(q: str = "", limit: int = 200) -> list[dict[str, Any]]:
        return db.list_file_memories(limit=limit, search=q)

    # --- 14. Aprendizado com decisões ---
    @app.get("/api/learning/suggestions")
    def api_learning_suggestions() -> dict[str, Any]:
        return {
            "suggestions": db.list_rule_suggestions(min_occurrences=2),
            "feedback_history": db.list_decision_feedback(limit=50),
        }

    @app.post("/api/learning/accept")
    def api_learning_accept(req: LearningDecisionRequest) -> dict[str, Any]:
        rule_id = db.accept_suggested_rule(req.signature_key, folcolor_index=req.folcolor_index)
        return {
            "rule_id": rule_id,
            "suggestions": db.list_rule_suggestions(min_occurrences=2),
            "scan": _get_or_refresh_scan(force=True),
        }

    @app.post("/api/learning/dismiss")
    def api_learning_dismiss(req: LearningDecisionRequest) -> dict[str, Any]:
        db.dismiss_rule_suggestion(req.signature_key)
        return {"suggestions": db.list_rule_suggestions(min_occurrences=2)}

    # --- 15. Inbox Zero Kanban ---
    @app.post("/api/inbox-zero/state")
    def api_set_triage_state(req: TriageStateRequest) -> dict[str, Any]:
        db.set_triage_state(
            req.item_id,
            req.column_name,
            custom_name=req.custom_name,
            custom_target=req.custom_target,
        )
        return {"triage_states": db.get_triage_states_map()}

    # --- 16. Integração com Windows Explorer ---
    @app.get("/api/explorer/status")
    def api_explorer_status() -> dict[str, Any]:
        return {
            "installed": is_context_menu_installed(),
            "spec": build_context_menu_spec(),
        }

    @app.post("/api/explorer/install")
    def api_explorer_install() -> dict[str, Any]:
        return install_context_menu()

    @app.post("/api/explorer/uninstall")
    def api_explorer_uninstall() -> dict[str, Any]:
        return uninstall_context_menu()

    # --- 17. Espaços de trabalho ---
    @app.get("/api/workspaces")
    def api_list_workspaces() -> list[dict[str, Any]]:
        return db.list_workspaces()

    @app.post("/api/workspaces/activate")
    def api_activate_workspace(req: WorkspaceActivateRequest) -> dict[str, Any]:
        ws = db.set_active_workspace(req.name)
        return {"active": ws, "workspaces": db.list_workspaces()}

    @app.post("/api/workspaces")
    def api_upsert_workspace(req: WorkspacePayload) -> dict[str, Any]:
        ws_id = db.upsert_workspace(req.model_dump())
        return {"id": ws_id, "workspaces": db.list_workspaces()}

    # --- 18. Relatório de Organização ---
    @app.get("/api/report")
    def api_organization_report(period_days: int = 7) -> dict[str, Any]:
        report = _get_or_refresh_scan(force=False)
        return build_organization_report(cfg, db, period_days=period_days, scan_state=report)

    # --- 19. Gerenciador de Aplicativos e Ferramentas ---
    @app.get("/api/apps")
    def api_app_catalog(include_registry: int = 1) -> list[dict[str, Any]]:
        return build_app_catalog(cfg, include_registry=bool(include_registry))

    # --- 20. Cofre de Configurações ---
    @app.post("/api/vault/export")
    def api_vault_export(req: VaultRequest) -> dict[str, Any]:
        return export_config_vault(Path(req.zip_path), db, cfg, options=req.options)

    @app.post("/api/vault/import")
    def api_vault_import(req: VaultRequest) -> dict[str, Any]:
        res = import_config_vault(Path(req.zip_path), db, cfg, options=req.options)
        res["scan"] = _get_or_refresh_scan(force=True)
        return res

    @app.post("/api/toggle-watch")
    def api_toggle_watch() -> dict[str, Any]:
        app.state.auto_watch_enabled = not app.state.auto_watch_enabled
        return {"auto_watch_enabled": app.state.auto_watch_enabled}

    @app.post("/api/open-folder")
    def api_open_folder(req: OpenFolderRequest) -> dict[str, Any]:
        p = Path(req.path)
        target = p if p.is_dir() else p.parent
        if not target.exists():
            raise HTTPException(status_code=404, detail="Pasta não encontrada")
        if os.name == "nt":
            if p.exists() and p.is_file():
                subprocess.Popen(["explorer", f"/select,{p}"])
            else:
                os.startfile(str(target))
        return {"opened": str(target)}

    @app.patch("/api/queue/{item_id}")
    def api_update_queue_item(item_id: str, req: UpdateTargetRequest) -> dict[str, Any]:
        report = _get_or_refresh_scan(force=False)
        for item in report["queue"]:
            if item["id"] == item_id:
                old_target = item.get("target_path", "")
                old_rule = item.get("rule_name", "")
                new_dst = str(Path(req.target_path))
                if old_target and Path(old_target).parent != Path(new_dst).parent:
                    db.record_user_correction(
                        item["source_path"],
                        old_target,
                        old_rule,
                        new_dst,
                        vida_root=cfg.vida_root,
                    )
                item["target_path"] = new_dst
                if req.category:
                    item["category"] = req.category
                elif item["category"] == "espaco_recuperavel":
                    item["category"] = "pronto_para_mover"
                item["reason"] = f"Destino personalizado → {Path(req.target_path).name}"
                item["rule_name"] = "Edição Manual"
                report["rule_suggestions"] = db.list_rule_suggestions(min_occurrences=2)
                return {"updated": item, "scan": _enrich_scan(report)}
        raise HTTPException(status_code=404, detail="Item não encontrado na fila")

    @app.post("/api/move-to-folder")
    def api_move_to_folder(req: MoveToFolderRequest) -> dict[str, Any]:
        report = _get_or_refresh_scan(force=False)
        dest_dir = Path(req.target_folder)
        wanted = set(req.item_ids)
        custom_items = []
        for item in report["queue"]:
            if item["id"] in wanted:
                src_name = Path(item["source_path"]).name
                new_dst = str(dest_dir / src_name)
                if item.get("target_path") and Path(item["target_path"]).parent != dest_dir:
                    db.record_user_correction(
                        item["source_path"],
                        item["target_path"],
                        item.get("rule_name", ""),
                        new_dst,
                        vida_root=cfg.vida_root,
                    )
                cloned = dict(item)
                cloned["category"] = "pronto_para_mover"
                cloned["target_path"] = new_dst
                cloned["rule_name"] = f"Movido em lote p/ {dest_dir.name}"
                custom_items.append(cloned)
        res = execute_queue_items(custom_items, db, cfg, include_destructive_trash=False)
        executed_ids = {r["id"] for r in res.get("results", []) if r.get("status") == "executed"}
        if app.state.cached_scan is not None and executed_ids:
            remaining = [i for i in app.state.cached_scan["queue"] if i["id"] not in executed_ids]
            app.state.cached_scan["queue"] = remaining
            app.state.cached_scan["summary"]["total_disorganized"] = len(remaining)
            app.state.cached_scan["folder_cards"] = _build_folder_cards(cfg, remaining, {})
        res["scan"] = _enrich_scan(app.state.cached_scan or scan_all(cfg, db))
        return res

    return app
