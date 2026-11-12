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
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.scanner import _build_folder_cards, scan_all
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
                item["target_path"] = str(Path(req.target_path))
                if req.category:
                    item["category"] = req.category
                elif item["category"] == "espaco_recuperavel":
                    item["category"] = "pronto_para_mover"
                item["reason"] = f"Destino personalizado → {Path(req.target_path).name}"
                item["rule_name"] = "Edição Manual"
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
                cloned = dict(item)
                cloned["category"] = "pronto_para_mover"
                cloned["target_path"] = str(dest_dir / src_name)
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
