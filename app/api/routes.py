import os
import subprocess
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.config import AppConfig
from app.db import Database
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.scanner import scan_all


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


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or AppConfig()
    db = Database(cfg.db_path)
    db.init_db()

    app = FastAPI(title="Vida Organizer — BOT-BRIEF")
    app.state.config = cfg
    app.state.db = db
    app.state.auto_watch_enabled = True

    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/api/scan")
    def api_scan() -> dict[str, Any]:
        report = scan_all(cfg, db)
        report["last_undoable_batch"] = db.get_last_undoable_batch()
        report["auto_watch_enabled"] = app.state.auto_watch_enabled
        report["vida_root"] = str(cfg.vida_root)
        return report

    @app.post("/api/execute")
    def api_execute(req: ExecuteRequest) -> dict[str, Any]:
        report = scan_all(cfg, db)
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
        return res

    @app.post("/api/undo")
    def api_undo(req: UndoRequest) -> dict[str, Any]:
        target_id = req.batch_id
        if target_id is None:
            last = db.get_last_undoable_batch()
            if not last:
                return {"undone_count": 0, "skipped_count": 0, "details": [], "message": "Nenhuma ação pendente para desfazer"}
            target_id = int(last["id"])
        return undo_batch(target_id, db)

    @app.get("/api/rules")
    def api_list_rules() -> list[dict]:
        return db.list_rules()

    @app.post("/api/rules")
    def api_upsert_rule(payload: RulePayload) -> dict[str, Any]:
        rule_id = db.upsert_rule(payload.model_dump())
        return {"id": rule_id, "rules": db.list_rules()}

    @app.delete("/api/rules/{rule_id}")
    def api_delete_rule(rule_id: int) -> dict[str, Any]:
        db.delete_rule(rule_id)
        return {"deleted": rule_id, "rules": db.list_rules()}

    @app.get("/api/history")
    def api_history() -> list[dict]:
        return db.list_batches(limit=25)

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

    return app

