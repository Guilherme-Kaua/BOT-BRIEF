from pathlib import Path
from app.config import AppConfig, FOLCOLOR_CATEGORY_MAP
from app.db import Database
from app.engine.protector import is_protected_path, is_active_download, is_file_locked


def test_protector_blocks_git_node_modules_and_games(tmp_path: Path):
    repo = tmp_path / "meu_app"
    (repo / ".git").mkdir(parents=True)
    code_file = repo / "main.py"
    code_file.write_text("print(1)")

    steam_file = tmp_path / "SteamLibrary" / "steamapps" / "game.exe"
    steam_file.parent.mkdir(parents=True)
    steam_file.write_text("bin")

    normal_file = tmp_path / "Downloads" / "aula.pdf"
    normal_file.parent.mkdir(parents=True)
    normal_file.write_text("pdf")

    assert is_protected_path(code_file) is True
    assert is_protected_path(steam_file) is True
    assert is_protected_path(normal_file) is False


def test_active_download_detection(tmp_path: Path):
    part = tmp_path / "video.mp4.crdownload"
    part.write_text("partial")
    done = tmp_path / "video.mp4"
    done.write_text("done")

    assert is_active_download(part) is True
    assert is_active_download(done) is False


def test_database_seeds_default_rules_and_tracks_batches(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.init_db()

    rules = db.list_rules()
    assert len(rules) >= 6
    assert any("01_Faculdade" in r["target_subpath"] for r in rules)
    assert any("01.2_Biblioteca_Concursos" in r["target_subpath"] for r in rules)

    batch_id = db.record_batch(
        "Organizar Downloads",
        [{"action_type": "move", "source_path": "C:/a.pdf", "target_path": "F:/Vida/a.pdf", "meta_json": "{}"}],
    )
    last = db.get_last_undoable_batch()
    assert last is not None
    assert last["id"] == batch_id
    assert len(last["items"]) == 1

    db.mark_batch_undone(batch_id)
    assert db.get_last_undoable_batch() is None


def test_get_last_undoable_batch_skips_trash_only_batches(tmp_path: Path):
    db = Database(tmp_path / "undo_trash.db")
    db.init_db()

    move_batch_id = db.record_batch(
        "Mover PDF",
        [{"action_type": "move", "source_path": "C:/a.pdf", "target_path": "F:/Vida/a.pdf", "meta_json": "{}"}],
    )
    _trash_batch_id = db.record_batch(
        "Lixeira Instalador",
        [{"action_type": "trash", "source_path": "C:/setup.exe", "target_path": "RecycleBin", "meta_json": "{}"}],
    )

    last_undoable = db.get_last_undoable_batch()
    assert last_undoable is not None
    assert last_undoable["id"] == move_batch_id


