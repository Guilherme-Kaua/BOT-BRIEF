import os
import time
from pathlib import Path
from app.config import AppConfig
from app.db import Database
from app.engine.storage_monitor import analyze_storage


def test_storage_monitor_detects_disk_alert_abnormal_growth_and_temp_files_non_destructively(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "00_Jogos").mkdir(parents=True)
    (vida / "02_Areas").mkdir(parents=True)
    dl.mkdir()

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "storage.db",
    )
    db = Database(cfg.db_path)
    db.init_db()

    now_ts = time.time()

    # 1. Initial baseline scan with small folder size (1 KB)
    f_initial = vida / "00_Jogos" / "save1.dat"
    f_initial.write_bytes(b"a" * 1024)
    rep1 = analyze_storage(cfg, db, now_ts=now_ts - 3600, growth_threshold_bytes=10 * 1024)
    assert any(g["name"] == "00_Jogos" and not g["abnormal_growth"] for g in rep1["folder_growth"])

    # 2. Simulate abnormal growth (+50 KB > 10 KB threshold) + temp files + abandoned download
    f_huge = vida / "00_Jogos" / "shader_cache_dump.bin"
    f_huge.write_bytes(b"x" * 50 * 1024)

    temp_file = dl / "crash_dump_991.tmp"
    temp_file.write_bytes(b"t" * 4096)
    old_ts = now_ts - (30 * 3600)  # 30h old (> 24h)
    os.utime(temp_file, (old_ts, old_ts))

    abandoned_part = dl / "iso_ubuntu.iso.crdownload"
    abandoned_part.write_bytes(b"p" * 8192)
    os.utime(abandoned_part, (old_ts, old_ts))

    # Active download (< 1h old) must NOT be flagged as abandoned
    active_part = dl / "aula_atual.mp4.part"
    active_part.write_bytes(b"a" * 2048)

    rep2 = analyze_storage(
        cfg,
        db,
        now_ts=now_ts,
        growth_threshold_bytes=10 * 1024,
        low_disk_free_bytes_threshold=10**18,  # force low-space alert in test
    )

    # Check disk alert was generated
    alert_types = {a["type"] for a in rep2["alerts"]}
    assert "disk_space" in alert_types
    assert "abnormal_growth" in alert_types
    assert "temp_and_abandoned" in alert_types

    # Check abnormal growth on 00_Jogos
    jogos_growth = next(g for g in rep2["folder_growth"] if g["name"] == "00_Jogos")
    assert jogos_growth["abnormal_growth"] is True
    assert jogos_growth["delta_bytes"] >= 50 * 1024

    # Check temp and abandoned files detected
    detected_paths = {Path(i["path"]) for i in rep2["temp_and_abandoned"]["items"]}
    assert temp_file in detected_paths
    assert abandoned_part in detected_paths
    assert active_part not in detected_paths

    # NON-DESTRUCTIVE INVARIANT: All files must still exist untouched on disk!
    assert f_initial.exists()
    assert f_huge.exists()
    assert temp_file.exists()
    assert abandoned_part.exists()
    assert active_part.exists()
