from pathlib import Path
from app.config import AppConfig
from app.db import Database
from app.engine.duplicates import find_redundant_archives, find_duplicates_and_revisions
from app.engine.scanner import scan_all


def test_archive_with_extracted_folder_collapses_whitespace(tmp_path: Path):
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "VALORANT FPSPACK   2.0").mkdir()
    rar = dl / "VALORANT FPSPACK 2.0.rar"
    rar.write_bytes(b"x" * 1024)

    redundant = find_redundant_archives(dl)
    assert len(redundant) == 1
    assert Path(redundant[0]["source_path"]) == rar


def test_duplicates_and_older_revisions_detected(tmp_path: Path):
    d1 = tmp_path / "02_Areas"
    d2 = tmp_path / "03_Recursos"
    d1.mkdir()
    d2.mkdir()
    v5 = d1 / "Ata_de_Reuniao_Sprint1-4-v5.pdf"
    v4 = d2 / "Ata_de_Reuniao_Sprint1-4-v4.pdf"
    v5.write_bytes(b"new content")
    v4.write_bytes(b"old content")

    items = find_duplicates_and_revisions([d1, d2])
    assert any(Path(i["source_path"]) == v4 for i in items)


def test_duplicates_keeps_vida_copy_over_downloads(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida_sub = tmp_path / "Vida" / "02_Areas"
    dl.mkdir(parents=True)
    vida_sub.mkdir(parents=True)

    # Shorter name in Downloads, longer name in Vida — Vida must still be kept!
    f_dl = dl / "a.pdf"
    f_vida = vida_sub / "AlumiGest_Completo.pdf"
    f_dl.write_bytes(b"identical-pdf-payload")
    f_vida.write_bytes(b"identical-pdf-payload")

    items = find_duplicates_and_revisions([dl, vida_sub], prefer_keep_root=tmp_path / "Vida")
    flagged = {Path(i["source_path"]) for i in items}
    assert f_dl in flagged
    assert f_vida not in flagged


def test_scanner_includes_desktop_dir(tmp_path: Path):
    desktop = tmp_path / "Desktop"
    vida = tmp_path / "Vida"
    desktop.mkdir()
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)

    loose_desk = desktop / "AlumiGest_Desktop.pdf"
    loose_desk.write_bytes(b"pdf")

    cfg = AppConfig(
        downloads_dir=tmp_path / "Downloads",
        desktop_dir=desktop,
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "desk.db",
    )
    db = Database(cfg.db_path)
    db.init_db()

    report = scan_all(cfg, db)
    sources = {Path(i["source_path"]) for i in report["queue"]}
    assert loose_desk in sources



def test_scan_all_classifies_downloads_and_vida_roots(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    (vida / "03_Recursos" / "01.2_Biblioteca_Concursos").mkdir(parents=True)
    (vida / "01_Projetos" / "Nova pasta").mkdir(parents=True)
    dl.mkdir()

    # Loose college PDF in 02_Areas root
    pdf = vida / "02_Areas" / "AlumiGest.pdf"
    pdf.write_bytes(b"pdf-data")
    # Heavy installer in Downloads
    exe = dl / "Obsidian-1.14.5.exe"
    exe.write_bytes(b"0" * 2048)

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "scan.db",
    )
    db = Database(cfg.db_path)
    db.init_db()

    report = scan_all(cfg, db)
    categories = {item["category"] for item in report["queue"]}
    assert "pronto_para_mover" in categories
    assert "espaco_recuperavel" in categories
    assert "icone_pendente" in categories
    assert report["summary"]["recoverable_bytes"] >= 2048


def test_scanner_triages_99_inbox_downloads_empty_dirs_abandoned_parts_and_ignored_paths(tmp_path: Path):
    import os
    import time

    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    inbox_dl = vida / "99_Inbox" / "Downloads"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    (vida / "03_Recursos" / "01_Biblioteca_Tech" / "Ferramentas").mkdir(parents=True)
    (vida / "01_Projetos" / "Projeto_Nova_pasta").mkdir(parents=True)
    (vida / "00_Jogos").mkdir(parents=True)
    inbox_dl.mkdir(parents=True)
    dl.mkdir()

    # 1. Items sitting inside 99_Inbox/Downloads
    waz = inbox_dl / "Raul Sidnei Wazlawick.pdf"
    waz.write_bytes(b"book")
    fira_dir = inbox_dl / "FiraCode"
    fira_dir.mkdir()
    (fira_dir / "FiraCode-Regular.ttf").write_bytes(b"font")

    # 2. Abandoned .part file (> 48 hours old)
    old_part = inbox_dl / "abandoned.htm.part"
    old_part.write_bytes(b"partial")
    old_ts = time.time() - (48 * 3600)
    os.utime(old_part, (old_ts, old_ts))

    # 3. Loose files in category roots
    loose_md = vida / "01_Projetos" / "daily-summary.md"
    loose_md.write_bytes(b"# summary")
    loose_txt = vida / "00_Jogos" / "teste.txt"
    loose_txt.write_bytes(b"oi")

    # 4. Ignored file in Downloads
    pinned = dl / "AlumiGest_NaoMover.pdf"
    pinned.write_bytes(b"keep-here")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "deep.db",
    )
    db = Database(cfg.db_path)
    db.init_db()
    db.add_ignored_path(str(pinned), "Fixado no local")

    report = scan_all(cfg, db)
    by_src = {Path(i["source_path"]): i for i in report["queue"]}

    assert waz in by_src and "01_Faculdade" in by_src[waz]["target_path"]
    assert fira_dir in by_src and "Ferramentas" in by_src[fira_dir]["target_path"]
    assert old_part in by_src and by_src[old_part]["category"] == "espaco_recuperavel"
    assert (vida / "01_Projetos" / "Projeto_Nova_pasta") in by_src
    assert loose_md in by_src and "Prompts_e_Docs" in by_src[loose_md]["target_path"]
    assert loose_txt in by_src and "Outros_Arquivos" in by_src[loose_txt]["target_path"]
    assert pinned not in by_src


