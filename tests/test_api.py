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
    from PySide6 import QtWidgets
    from app.desktop_gui import create_desktop_window

    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    installer = dl / "DiscordSetup.exe"
    installer.write_bytes(b"MZ-fake-installer")
    pdf = vida / "02_Areas" / "Trabalho_ADS.pdf"
    pdf.write_bytes(b"pdf-content")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "desktop_ui.db",
    )

    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = create_desktop_window(cfg, auto_scan_async=False)
    win.ctrl.refresh(force=True)
    win.render_all()

    # 1. Table has both items rendered
    assert win.table.rowCount() >= 2

    # 2. Real-time search filters table rows
    win.search_input.setText("Trabalho_ADS")
    win.apply_filters()
    visible_rows = [r for r in range(win.table.rowCount()) if not win.table.isRowHidden(r)]
    assert len(visible_rows) == 1

    win.search_input.setText("")
    win.apply_filters()

    # 3. Multi-select checkboxes work
    win.set_all_visible_checked(True)
    selected_ids = win.get_selected_item_ids()
    assert len(selected_ids) >= 2

    # 4. Vida Tree tab is populated with F:\Vida folders and incoming count
    assert win.vida_tree_widget.topLevelItemCount() >= 1

    # 5. Ignore/Pin item removes it from queue and stores in ignored_paths
    first_id = selected_ids[0]
    win.ctrl.ignore_items([first_id])
    assert all(i["id"] != first_id for i in win.ctrl.state["queue"])
    assert len(win.ctrl.state["ignored_paths"]) == 1
    win.close()


def test_desktop_controller_edit_target_multiselect_and_rules_crud(tmp_path: Path):
    from app.desktop_gui import DesktopController

    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    f1 = dl / "nota_fiscal_1.pdf"
    f2 = dl / "nota_fiscal_2.pdf"
    f1.write_bytes(b"nf1")
    f2.write_bytes(b"nf2")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "crud.db",
    )
    ctrl = DesktopController(cfg)

    # 1. Create a new rule via visual Rule Editor API
    new_rule_id = ctrl.save_rule(
        {
            "name": "Notas Fiscais Financeiro",
            "priority": 15,
            "category_folder": "02_Areas",
            "target_subpath": "02_Areas/02_Financeiro/Notas",
            "folcolor_index": 6,
            "keywords": ["nota_fiscal"],
            "extensions": ["pdf"],
            "source_scopes": ["*"],
            "min_age_days": 0,
            "enabled": 1,
        }
    )
    assert new_rule_id > 0
    state = ctrl.refresh(force=True)
    items = [i for i in state["queue"] if "nota_fiscal" in i["source_path"]]
    assert len(items) == 2

    # 2. Edit target name/path of first item before moving
    custom_dst = str(vida / "02_Areas" / "02_Financeiro" / "Notas" / "NF_Janeiro_Renomeada.pdf")
    updated = ctrl.update_item_target(items[0]["id"], custom_dst)
    assert updated is not None
    assert updated["target_path"] == custom_dst

    # 3. Execute single edited item
    res1 = ctrl.execute_items([items[0]["id"]])
    assert res1["executed_count"] == 1
    assert Path(custom_dst).exists()

    # 4. Move remaining selected item(s) to any custom folder in batch
    custom_folder = vida / "03_Recursos" / "Arquivo_Especial"
    res2 = ctrl.move_items_to_folder([items[1]["id"]], str(custom_folder))
    assert res2["executed_count"] == 1
    assert (custom_folder / "nota_fiscal_2.pdf").exists()

    # 5. Delete rule
    ctrl.delete_rule(new_rule_id)
    assert all(r["id"] != new_rule_id for r in ctrl.state["rules"])







