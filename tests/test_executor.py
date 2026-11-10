from pathlib import Path
from app.config import AppConfig
from app.db import Database
from app.engine.executor import execute_queue_items, undo_batch


def _make_cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        downloads_dir=tmp_path / "Downloads",
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=tmp_path / "Vida",
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "exec.db",
    )


def test_execute_move_resolves_name_collision_without_overwrite(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    db = Database(cfg.db_path)
    db.init_db()

    src = tmp_path / "Downloads" / "AlumiGest.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"version-new")

    dst_dir = cfg.vida_root / "02_Areas" / "01_Faculdade" / "ADS"
    dst_dir.mkdir(parents=True)
    existing = dst_dir / "AlumiGest.pdf"
    existing.write_bytes(b"version-old")

    res = execute_queue_items(
        [
            {
                "id": "1",
                "category": "pronto_para_mover",
                "source_path": str(src),
                "target_path": str(existing),
                "folcolor_index": 9,
            }
        ],
        db,
        cfg,
    )
    assert res["executed_count"] == 1
    assert existing.read_bytes() == b"version-old"
    v2 = dst_dir / "AlumiGest_v2.pdf"
    assert v2.exists()
    assert v2.read_bytes() == b"version-new"

    # Undo restores AlumiGest_v2.pdf back to Downloads/AlumiGest.pdf
    undo_res = undo_batch(res["batch_id"], db)
    assert undo_res["undone_count"] == 1
    assert src.exists()
    assert not v2.exists()


def test_undo_batch_handles_missing_file_gracefully(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    db = Database(cfg.db_path)
    db.init_db()

    src = tmp_path / "Downloads" / "nota.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"123")
    dst = cfg.vida_root / "02_Areas" / "nota.pdf"

    res = execute_queue_items(
        [{"id": "2", "category": "pronto_para_mover", "source_path": str(src), "target_path": str(dst)}],
        db,
        cfg,
    )
    # Simulate user manually deleting the moved file before clicking Undo
    dst.unlink()

    undo_res = undo_batch(res["batch_id"], db)
    assert undo_res["undone_count"] == 0
    assert undo_res["skipped_count"] == 1
