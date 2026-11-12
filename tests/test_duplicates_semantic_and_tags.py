import os
import time
from pathlib import Path
from app.config import AppConfig
from app.db import Database
from app.engine.duplicates import build_duplicate_groups, archive_duplicate_extras
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.semantic_search import semantic_search_files
from app.engine.scanner import scan_all


def test_duplicate_center_groups_and_reversible_manual_archive(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    ads = vida / "02_Areas" / "01_Faculdade" / "ADS"
    ads.mkdir(parents=True)
    dl.mkdir()

    # Identical files: one in F:\Vida (must be preserved as keeper) and two copies in Downloads
    payload = b"conteudo-identico-apostila-ads" * 100
    f_vida = ads / "Apostila_ADS.pdf"
    f_dl1 = dl / "Apostila_ADS (1).pdf"
    f_dl2 = dl / "copia_apostila.pdf"
    f_vida.write_bytes(payload)
    f_dl1.write_bytes(payload)
    f_dl2.write_bytes(payload)

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "dup_center.db",
    )
    db = Database(cfg.db_path)
    db.init_db()

    groups = build_duplicate_groups(cfg)
    assert len(groups) >= 1
    grp = groups[0]
    assert Path(grp["keeper"]["path"]) == f_vida
    extra_paths = {Path(c["path"]) for c in grp["extras"]}
    assert f_dl1 in extra_paths
    assert f_dl2 in extra_paths
    assert grp["wasted_bytes"] == len(payload) * 2
    assert grp["total_bytes"] == len(payload) * 3

    # Manual reversible action on the group
    res = archive_duplicate_extras([str(f_dl1), str(f_dl2)], db, cfg)
    assert res["executed_count"] == 2
    assert f_vida.exists()
    assert not f_dl1.exists()
    assert not f_dl2.exists()

    # Reversible with 1-click Undo
    undo_res = undo_batch(int(res["batch_id"]), db)
    assert undo_res["undone_count"] == 2
    assert f_dl1.exists()
    assert f_dl2.exists()


def test_smart_tags_independent_of_location_and_preserved_on_move(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    pdf = dl / "AlumiGest_Entrega.pdf"
    pdf.write_bytes(b"trabalho-faculdade")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "tags.db",
    )
    db = Database(cfg.db_path)
    db.init_db()

    # Attach smart tags "Estudar" and "Importante" while file is in Downloads
    db.add_file_tag(str(pdf), "Estudar")
    db.add_file_tag(str(pdf), "Importante")
    assert set(db.get_tags_for_path(str(pdf))) == {"Estudar", "Importante"}

    # Move file to F:\Vida via executor -> tags must automatically migrate to the new path!
    report = scan_all(cfg, db)
    move_items = [i for i in report["queue"] if Path(i["source_path"]) == pdf]
    assert len(move_items) == 1
    exec_res = execute_queue_items(move_items, db, cfg)
    new_path = exec_res["results"][0]["target_path"]

    assert set(db.get_tags_for_path(new_path)) == {"Estudar", "Importante"}
    by_study = db.list_files_by_tag("Estudar")
    assert any(Path(entry["path"]) == Path(new_path) for entry in by_study)


def test_semantic_search_understands_meaning_file_type_tags_and_time_expressions(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    ads = vida / "02_Areas" / "01_Faculdade" / "ADS"
    fin = vida / "02_Areas" / "03_Financeiro"
    ads.mkdir(parents=True)
    fin.mkdir(parents=True)
    dl.mkdir()

    now_ts = time.time()
    last_month_ts = now_ts - (32 * 86400)  # ~1 month ago

    # Target PDF about data structures / algorithms downloaded last month
    target_pdf = ads / "Apostila_Algoritmos_e_Arvores_Binarias.pdf"
    target_pdf.write_bytes(b"%PDF-1.4 Estruturas de Dados, Listas Encadeadas, Pilhas e Grafos")
    os.utime(target_pdf, (last_month_ts, last_month_ts))

    # Unrelated recent spreadsheet
    recent_xlsx = fin / "Orcamento_Mensal.xlsx"
    recent_xlsx.write_bytes(b"planilha gastos")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "semantic.db",
    )
    db = Database(cfg.db_path)
    db.init_db()
    db.add_file_tag(str(target_pdf), "Estudar")

    results = semantic_search_files(
        "aquele PDF sobre estruturas de dados que baixei mês passado",
        cfg,
        db,
        now_ts=now_ts,
    )
    assert len(results) >= 1
    assert Path(results[0]["path"]) == target_pdf
    assert results[0]["score"] >= 50


def test_api_and_desktop_ui_wire_duplicates_semantic_search_and_tags(tmp_path: Path):
    from fastapi.testclient import TestClient
    from PySide6 import QtWidgets
    from app.api.routes import create_app
    from app.desktop_gui import create_desktop_window

    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    ads = vida / "02_Areas" / "01_Faculdade" / "ADS"
    ads.mkdir(parents=True)
    dl.mkdir()

    payload = b"PDF-estruturas-de-dados-arvore-b" * 30
    keep_pdf = ads / "Estruturas_Dados.pdf"
    dup_pdf = dl / "Estruturas_Dados (1).pdf"
    keep_pdf.write_bytes(payload)
    dup_pdf.write_bytes(payload)

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "ui_wire.db",
    )

    # 1. API endpoints test
    client = TestClient(create_app(cfg))
    r_dup = client.get("/api/duplicates")
    assert r_dup.status_code == 200
    assert len(r_dup.json()) == 1

    r_tag = client.post("/api/tags", json={"path": str(keep_pdf), "tag": "Estudar"})
    assert r_tag.status_code == 200
    assert "Estudar" in r_tag.json()["tags"]

    r_search = client.get("/api/search", params={"q": "pdf estruturas de dados", "tag": "Estudar"})
    assert r_search.status_code == 200
    body = r_search.json()
    assert len(body["results"]) >= 1
    assert Path(body["results"][0]["path"]) == keep_pdf

    # 2. PySide6 Desktop UI tabs render duplicate groups, tags & semantic search results
    _qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = create_desktop_window(cfg, auto_scan_async=False)
    win.ctrl.refresh(force=True)
    win.render_all()

    assert win.dup_groups_tree.topLevelItemCount() == 1
    win.semantic_search_input.setText("estruturas de dados")
    win.set_semantic_tag_filter("Estudar")
    assert win.semantic_results_table.rowCount() >= 1

    # Check all extras in UI and archive reversibly
    win._set_all_dup_extras_checked(True)
    checked = win._get_checked_dup_extra_paths()
    assert len(checked) == 1
    win.on_archive_selected_duplicates(mode="archive")
    assert keep_pdf.exists()
    assert not dup_pdf.exists()
    win.close()

