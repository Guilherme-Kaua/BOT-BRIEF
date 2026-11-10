from pathlib import Path
from fastapi.testclient import TestClient
from app.config import AppConfig
from app.api.routes import create_app


def test_api_scan_execute_and_undo_flow(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    pdf = vida / "02_Areas" / "AlumiGest.pdf"
    pdf.write_bytes(b"conteudo-aula")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "api.db",
    )
    app = create_app(cfg)
    client = TestClient(app)

    # 1. Dashboard HTML loads
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "Vida Organizer" in r_home.text

    # 2. Scan reports loose PDF ready to move
    r_scan = client.get("/api/scan")
    assert r_scan.status_code == 200
    data = r_scan.json()
    move_items = [i for i in data["queue"] if i["category"] == "pronto_para_mover"]
    assert len(move_items) == 1

    # 3. Execute move via API
    r_exec = client.post("/api/execute", json={"categories": ["pronto_para_mover"]})
    assert r_exec.status_code == 200
    assert r_exec.json()["executed_count"] == 1
    assert not pdf.exists()
    assert (vida / "02_Areas" / "01_Faculdade" / "ADS" / "AlumiGest.pdf").exists()

    # 4. Undo via API restores file
    r_undo = client.post("/api/undo", json={})
    assert r_undo.status_code == 200
    assert r_undo.json()["undone_count"] == 1
    assert pdf.exists()


def test_app_js_and_open_folder_escaping():
    app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openInExplorer(${JSON.stringify' not in app_js
    routes_py = (Path(__file__).resolve().parent.parent / "app" / "api" / "routes.py").read_text(encoding="utf-8")
    assert 'f"/select,{p}"' in routes_py


def test_windowless_pythonw_uvicorn_config_does_not_crash(monkeypatch):
    import sys
    import uvicorn
    from app.main import ensure_stdio_streams

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    ensure_stdio_streams()
    cfg = uvicorn.Config("app.api.routes:create_app", host="127.0.0.1", port=18420, log_config=None)
    cfg.configure_logging()
    assert sys.stdout is not None
    assert sys.stderr is not None


def test_api_execute_uses_in_memory_cache_and_returns_updated_state(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    pdf = vida / "02_Areas" / "Aula_Cache.pdf"
    pdf.write_bytes(b"cache-test")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "cache.db",
    )
    app = create_app(cfg)
    client = TestClient(app)

    r_scan = client.get("/api/scan")
    item_id = [i["id"] for i in r_scan.json()["queue"] if i["category"] == "pronto_para_mover"][0]

    r_exec = client.post("/api/execute", json={"item_ids": [item_id]})
    body = r_exec.json()
    assert body["executed_count"] == 1
    assert "scan" in body
    assert all(i["id"] != item_id for i in body["scan"]["queue"])


def test_desktop_gui_controller_instant_execute_and_undo(tmp_path: Path):
    from app.desktop_gui import DesktopController

    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    pdf = vida / "02_Areas" / "AlumiGest_DesktopApp.pdf"
    pdf.write_bytes(b"native-desktop")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "desktop_ctrl.db",
    )
    ctrl = DesktopController(cfg)
    state1 = ctrl.refresh(force=True)
    move_items = [i for i in state1["queue"] if i["category"] == "pronto_para_mover"]
    assert len(move_items) == 1

    # Instant in-memory execution without full rescan
    res = ctrl.execute_item(move_items[0]["id"], include_trash=False, recoverable_mode="archive")
    assert res["executed_count"] == 1
    assert len([i for i in ctrl.state["queue"] if i["id"] == move_items[0]["id"]]) == 0
    assert (vida / "02_Areas" / "01_Faculdade" / "ADS" / "AlumiGest_DesktopApp.pdf").exists()

    # Instant undo
    undo_res = ctrl.undo_last()
    assert undo_res["undone_count"] == 1
    assert pdf.exists()


def test_launch_desktop_app_builds_ui_without_tcl_error(tmp_path: Path, monkeypatch):
    import customtkinter as ctk
    from app.desktop_gui import launch_desktop_app

    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    # Create a recoverable installer (.exe) so rec_batch_frame is packed on startup
    installer = dl / "DiscordSetup.exe"
    installer.write_bytes(b"MZ-fake-installer")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "desktop_ui.db",
    )

    monkeypatch.setattr(ctk.CTk, "mainloop", lambda self: self.destroy())
    launch_desktop_app(cfg)






