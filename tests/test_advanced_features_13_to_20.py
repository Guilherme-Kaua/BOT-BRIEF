from pathlib import Path
from fastapi.testclient import TestClient

from app.api.routes import create_app
from app.config import AppConfig
from app.db import Database
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.explorer_integration import build_context_menu_spec, execute_context_menu_action
from app.engine.reporting_catalog_vault import (
    build_app_catalog,
    build_organization_report,
    export_config_vault,
    format_report_markdown,
    import_config_vault,
)
from app.engine.scanner import scan_all


def _make_cfg(tmp_path: Path, name: str = "adv") -> AppConfig:
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    proj = tmp_path / "Projetos"
    dl.mkdir(parents=True, exist_ok=True)
    vida.mkdir(parents=True, exist_ok=True)
    proj.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=proj,
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / f"{name}.db",
    )


def test_13_file_memory_tracks_origin_rule_count_and_reason(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "mem")
    (cfg.vida_root / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    pdf = cfg.downloads_dir / "AlumiGest_Arquitetura.pdf"
    pdf.write_bytes(b"doc-ads")

    db = Database(cfg.db_path)
    db.init_db()

    report = scan_all(cfg, db)
    item = [i for i in report["queue"] if Path(i["source_path"]) == pdf][0]
    res = execute_queue_items([item], db, cfg)
    moved_dst = Path(res["results"][0]["target_path"])
    assert moved_dst.exists()

    mem = db.get_file_memory(str(moved_dst))
    assert mem is not None
    assert Path(mem["original_path"]) == pdf
    assert "Faculdade" in mem["rule_name"]
    assert mem["move_count"] == 1
    assert len(mem["events"]) == 1

    # Undo increments move_count & appends undo event preserving original_path
    undo_batch(int(res["batch_id"]), db)
    mem_after_undo = db.get_file_memory(str(pdf))
    assert mem_after_undo is not None
    assert mem_after_undo["move_count"] == 2
    assert len(mem_after_undo["events"]) == 2
    assert mem_after_undo["events"][0]["event_type"] == "undo"


def test_14_decision_learning_requires_user_authorization_before_creating_rule(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "learn")
    (cfg.vida_root / "01_Projetos" / "Robotica").mkdir(parents=True)
    db = Database(cfg.db_path)
    db.init_db()

    initial_rules_count = len(db.list_rules())

    # User overrides 2 similar ".pdf" files with prefix "Robotica" to 01_Projetos/Robotica
    f1 = cfg.downloads_dir / "Robotica_Placa1.pdf"
    f2 = cfg.downloads_dir / "Robotica_Placa2.pdf"
    suggested = str(cfg.vida_root / "03_Recursos" / "Robotica_Placa.pdf")
    chosen1 = str(cfg.vida_root / "01_Projetos" / "Robotica" / f1.name)
    chosen2 = str(cfg.vida_root / "01_Projetos" / "Robotica" / f2.name)

    db.record_user_correction(str(f1), suggested, "Recursos", chosen1, vida_root=cfg.vida_root)
    db.record_user_correction(str(f2), suggested, "Recursos", chosen2, vida_root=cfg.vida_root)

    # Rule is NOT auto-created without explicit authorization
    assert len(db.list_rules()) == initial_rules_count
    suggestions = db.list_rule_suggestions(min_occurrences=2)
    assert len(suggestions) == 1
    assert suggestions[0]["requires_confirmation"] is True
    assert suggestions[0]["target_subpath"] == "01_Projetos/Robotica"

    # Explicit confirmation creates the rule
    new_rid = db.accept_suggested_rule(suggestions[0]["signature_key"])
    assert new_rid is not None
    assert len(db.list_rules()) == initial_rules_count + 1
    assert len(db.list_rule_suggestions(min_occurrences=2)) == 0


def test_15_16_17_kanban_explorer_context_and_workspaces_ui(tmp_path: Path):
    from PySide6 import QtWidgets
    from app.desktop_gui import create_desktop_window

    cfg = _make_cfg(tmp_path, "ui_adv")
    (cfg.vida_root / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    f_ads = cfg.downloads_dir / "Sprint_ADS_Kanban.pdf"
    f_ads.write_bytes(b"sprint-ads")
    f_other = cfg.downloads_dir / "Comprovante_Pix_Energia.pdf"
    f_other.write_bytes(b"comprovante-pix")

    # 16. Explorer Context Menu spec & headless actions
    spec = build_context_menu_spec("pythonw.exe", "main.py")
    flags = [e["flag"] for e in spec["entries"]]
    assert flags == [
        "--ctx-organize",
        "--ctx-send-vida",
        "--ctx-pin",
        "--ctx-duplicates",
        "--ctx-open-target",
    ]
    assert "HKEY_CURRENT_USER\\Software\\Classes\\*\\shell\\VidaOrganizer" in spec["reg_content"]

    db = Database(cfg.db_path)
    db.init_db()
    pin_res = execute_context_menu_action("pin", str(f_other), cfg, db, open_explorer=False)
    assert pin_res["status"] == "ok"
    assert str(f_other).lower() in db.get_ignored_set()

    target_preview = execute_context_menu_action("open_target", str(f_ads), cfg, db, open_explorer=False)
    assert "01_Faculdade" in target_preview["target_dir"]

    # 15 & 17. PySide6 UI Kanban + Workspaces
    _qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = create_desktop_window(cfg, auto_scan_async=False)
    win.ctrl.refresh(force=True)
    win.render_all()

    # Workspaces preset check
    workspaces = win.ctrl.db.list_workspaces()
    assert {w["name"] for w in workspaces} >= {"Faculdade", "Desenvolvimento", "Pessoal", "Entretenimento"}
    win.on_activate_workspace("Faculdade")
    assert win.ctrl.get_active_workspace()["name"] == "Faculdade"
    win.on_activate_workspace("__ALL__")

    # Kanban move column & execute confirmed
    q_ids = [i["id"] for i in win.ctrl.state["queue"] if Path(i["source_path"]) == f_ads]
    assert len(q_ids) == 1
    win.ctrl.set_kanban_column(q_ids[0], "em_analise")
    win._populate_inbox_zero_tab()
    assert win.kanban_lists["em_analise"].count() >= 1
    win.ctrl.set_kanban_column(q_ids[0], "organizado")
    win._populate_inbox_zero_tab()
    win.on_kanban_execute_confirmed()
    assert not f_ads.exists()
    win.close()


def test_18_19_20_report_app_catalog_and_config_vault_roundtrip(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "rcv")
    (cfg.vida_root / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    (cfg.vida_root / "04_Arquivo_Morto" / "Instaladores").mkdir(parents=True)
    (cfg.vida_root / "03_Recursos" / "Ferramentas_Tech" / "MyTool").mkdir(parents=True)
    (cfg.projetos_dir / "MyTool_Automation").mkdir(parents=True)

    # Portable tool + archived installer + doc + project for App Catalog
    (cfg.vida_root / "03_Recursos" / "Ferramentas_Tech" / "MyTool" / "MyTool.exe").write_bytes(b"MZ")
    (cfg.vida_root / "04_Arquivo_Morto" / "Instaladores" / "MyTool_Setup.exe").write_bytes(b"MZ-setup")
    (cfg.vida_root / "03_Recursos" / "Guia_MyTool.md").write_text("# Guia MyTool", encoding="utf-8")

    # Organize + undo one batch for Report
    f1 = cfg.downloads_dir / "Aula_ADS_Relatorio.pdf"
    f2 = cfg.downloads_dir / "Old_Setup.exe"
    f1.write_bytes(b"ads-pdf")
    f2.write_bytes(b"setup" * 50)

    db = Database(cfg.db_path)
    db.init_db()
    db.add_file_tag(str(f1), "Estudar")
    db.add_ignored_path(str(cfg.projetos_dir / "MyTool_Automation"), "Projeto ativo")

    report_scan = scan_all(cfg, db)
    exec_res = execute_queue_items(
        report_scan["queue"],
        db,
        cfg,
        include_destructive_trash=True,
        recoverable_mode="archive",
    )
    assert exec_res["executed_count"] >= 2

    # 18. Report
    rep = build_organization_report(cfg, db, period_days=7, scan_state=scan_all(cfg, db))
    assert rep["organized_count"] >= 2
    assert rep["recovered_bytes"] >= 250
    md = format_report_markdown(rep)
    assert "Relatório de Organização" in md

    # 19. App Catalog
    catalog = build_app_catalog(cfg, include_registry=False)
    mytool_entries = [c for c in catalog if "mytool" in c["name"].lower()]
    assert len(mytool_entries) >= 1
    assert len(mytool_entries[0]["archived_installers"]) >= 1
    assert len(mytool_entries[0]["related_docs"]) >= 1
    assert len(mytool_entries[0]["related_projects"]) >= 1

    # 20. Config Vault Export & Import into brand-new instance
    vault_zip = tmp_path / "backup" / "VidaVault.zip"
    exp = export_config_vault(vault_zip, db, cfg)
    assert Path(exp["zip_path"]).exists()

    cfg2 = _make_cfg(tmp_path / "pc2", "pc2")
    db2 = Database(cfg2.db_path)
    db2.init_db()
    imp = import_config_vault(vault_zip, db2, cfg2)
    assert imp["restored"]["folders_created"] >= 1
    assert imp["restored"]["ignored_paths"] >= 1
    assert (cfg2.vida_root / "02_Areas" / "01_Faculdade" / "ADS").exists()

    # Verify API endpoints respond cleanly
    client = TestClient(create_app(cfg))
    assert client.get("/api/file-memory").status_code == 200
    assert client.get("/api/learning/suggestions").status_code == 200
    assert client.get("/api/workspaces").status_code == 200
    assert client.get("/api/report").status_code == 200
    assert client.get("/api/apps", params={"include_registry": 0}).status_code == 200

