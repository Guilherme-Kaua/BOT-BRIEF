# Vida Organizer (BOT-BRIEF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight Windows background file organizer and System Tray assistant (`BOT-BRIEF`) that routes messy files from `C:\Downloads`, `Desktop`, `Documents`, and loose category roots into `F:\Vida`, standardizes folder icons via `Folcolor` (`desktop.ini`), and serves a dark-mode local web dashboard showing **Organizado vs. Desorganizado** health, visual rules, and 1-click Undo.

**Architecture:** A Python 3.15 background service combining a non-destructive Simulation & Classification scanner (`app/engine`), a SQLite rule and Undo ledger (`app/db.py`), a FastAPI web server (`app/api/routes.py` + `app/static/*`) bound to `127.0.0.1:18420`, and a `pystray` Windows System Tray controller (`app/tray/tray_agent.py`). All destructive or ambiguous operations (installers, duplicates, redundant `.zip` files) are staged in `espaco_recuperavel` for user-confirmed Recycle Bin (`send2trash`) or archive actions, while high-confidence moves execute after an idle cooldown or on 1-click command.

**Tech Stack:** Python 3.15, FastAPI, Uvicorn, SQLite3 (`sqlite3`), Watchdog (`watchdog`), Pystray (`pystray`), Pillow (`Pillow`), Send2Trash (`Send2Trash`), Pytest (`pytest`, `httpx`).

**Spec:** `docs/superpowers/specs/2026-11-09-pc-file-organizer-design.md`

## Global Constraints

- **Target OS & Runtime:** Windows 10/11 (`nt`), Python `>= 3.12` (running on `3.15.2`).
- **Default Central Hub:** `F:\Vida` with existing PARA categories (`00_Jogos`, `01_Projetos`, `02_Areas`, `03_Recursos`, `04_Arquivo_Morto`, `99_Inbox`).
- **Folcolor Resource Map:** `C:\Program Files (x86)\Folcolor\Folcolor.exe` with indices: root `F:\Vida` = `13`, `00_Jogos` = `4`, `01_Projetos` = `6`, `02_Areas` = `9`, `03_Recursos` = `8`, `04_Arquivo_Morto` = `15`, `99_Inbox` = `2` (fallback to `C:\Windows\System32\shell32.dll,3` if `Folcolor.exe` does not exist).
- **Anti-Goal Protection:** Never scan, move, or rename anything inside directories containing `.git`, `node_modules`, `.venv`, `pyproject.toml`, `package.json`, `.sln`, or paths matching `SteamLibrary`, `Riot Games`, `XboxGames`, `WindowsApps`, or subfolders inside `C:\Projetos`.
- **Cooldown & Safety:** Ignore `.crdownload`, `.part`, `.tmp` and locked files. Automatic background moves require `>= 120` minutes idle in `C:\Downloads` and `>= 15` minutes idle in `F:\Vida` category roots. Never call `os.unlink` on user files; confirmed cleanup uses `send2trash`.
- **Test Isolation:** Automated tests in `tests/` must exclusively use `tmp_path` fixtures and never touch real `C:\Users\kauam\Downloads` or `F:\Vida`.

## Review Focus

1. **Case-insensitive and accent-insensitive rule matching on Windows (`Curriculo_Guilherme.docx` vs `Currículo`, `.PDF` uppercase):** Keyword and extension matching must strip accents via `unicodedata.normalize("NFKD", ...)` and lowercase both filenames and extensions (`test_accent_and_case_insensitive_rule_matching` in Task 3).
2. **Archive + extracted folder with irregular spacing (`VALORANT FPSPACK 2.0.rar` next to `VALORANT FPSPACK   2.0/`):** Stem comparison must collapse whitespace runs (`re.sub(r"\s+", " ", stem).strip().lower()`) before checking if an extracted sibling folder exists (`test_archive_with_extracted_folder_collapses_whitespace` in Task 4).
3. **Name collision at destination during move:** If the target directory already contains a file with the same name and a different SHA-256 hash, the executor must append `_v2` (`_v3`, etc.) before the extension rather than overwriting or raising `FileExistsError` (`test_execute_move_resolves_name_collision_without_overwrite` in Task 5).
4. **Overwriting an existing Windows `desktop.ini` that already has `FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM`:** On Windows, opening a hidden+system `desktop.ini` with `"w"` raises `PermissionError`. `apply_folcolor_icon` must reset attributes to `FILE_ATTRIBUTE_NORMAL` (0x80) before writing, then set `FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM` (0x06) on `desktop.ini` and `FILE_ATTRIBUTE_READONLY` (0x01) on the folder (`test_apply_folcolor_overwrites_existing_hidden_system_desktop_ini` in Task 2).
5. **Undo batch when a moved file was later deleted or moved manually by the user:** `undo_batch` must recreate missing source parent folders, skip any file that no longer exists at `target_path` without aborting the rest of the batch, and report skipped items in the result summary (`test_undo_batch_handles_missing_file_gracefully` in Task 5).

---

### Task 1: Config, SQLite Database, and Anti-Goal Protector

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/db.py`
- Create: `app/engine/__init__.py`
- Create: `app/engine/protector.py`
- Test: `tests/test_protector_and_db.py`

**Interfaces:**
- Consumes: Python stdlib (`sqlite3`, `pathlib`, `os`, `time`, `dataclasses`, `json`)
- Produces:
  - `app.config.AppConfig`: dataclass with `downloads_dir: Path`, `desktop_dir: Path`, `documents_dir: Path`, `vida_root: Path`, `projetos_dir: Path`, `folcolor_exe: Path`, `db_path: Path`, `downloads_cooldown_minutes: int = 120`, `vida_root_cooldown_minutes: int = 15`, `port: int = 18420`
  - `app.config.FOLCOLOR_CATEGORY_MAP: dict[str, int]`
  - `app.db.Database(db_path: Path)`:
    - `init_db() -> None` (creates tables `rules`, `action_batches`, `action_items`, `settings` and seeds the 6 default `F:\Vida` rules if `rules` is empty)
    - `list_rules() -> list[dict]`
    - `upsert_rule(rule: dict) -> int`
    - `delete_rule(rule_id: int) -> None`
    - `record_batch(description: str, items: list[dict]) -> int`
    - `get_batch(batch_id: int) -> dict | None`
    - `get_last_undoable_batch() -> dict | None`
    - `mark_batch_undone(batch_id: int) -> None`
    - `list_batches(limit: int = 20) -> list[dict]`
  - `app.engine.protector`:
    - `is_protected_path(path: Path, projetos_dir: Path | None = None) -> bool`
    - `is_active_download(path: Path) -> bool`
    - `is_file_locked(path: Path) -> bool`

- [ ] **Step 1: Create `requirements.txt` and install dependencies**

Create `requirements.txt` with:
```
fastapi>=0.115.0
uvicorn>=0.32.0
watchdog>=6.0.0
pystray>=0.19.5
Pillow>=11.0.0
Send2Trash>=1.8.3
pytest>=8.3.0
httpx>=0.27.0
```
Run: `python -m pip install -r requirements.txt`
Expected: Successfully installed packages.

- [ ] **Step 2: Write the failing tests in `tests/test_protector_and_db.py`**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_protector_and_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 4: Implement `app/config.py`, `app/db.py`, and `app/engine/protector.py`**

In `app/config.py`:
- Define `FOLCOLOR_CATEGORY_MAP = {"00_Jogos": 4, "01_Projetos": 6, "02_Areas": 9, "03_Recursos": 8, "04_Arquivo_Morto": 15, "99_Inbox": 2}` and `VIDA_ROOT_ICON_INDEX = 13`.
- Define `AppConfig` defaulting `downloads_dir` to `Path.home() / "Downloads"`, `desktop_dir` to `Path.home() / "Desktop"`, `documents_dir` to `Path.home() / "Documents"`, `vida_root` to `Path("F:/Vida")`, `projetos_dir` to `Path("C:/Projetos")`, `folcolor_exe` to `Path("C:/Program Files (x86)/Folcolor/Folcolor.exe")`, `db_path` to `Path(__file__).resolve().parent.parent / "data" / "vida_organizer.db"`.

In `app/db.py`:
- Implement `Database` with SQLite tables `rules(id, name, priority, category_folder, target_subpath, folcolor_index, keywords_json, extensions_json, source_scopes_json, min_age_days, enabled)` and `action_batches(id, created_at, description, undone)` + `action_items(id, batch_id, action_type, source_path, target_path, meta_json)`.
- Seed the 6 default rules from Spec Section 5.3 on first `init_db()`.

In `app/engine/protector.py`:
- `is_protected_path`: returns `True` if any ancestor or self contains `.git`, `node_modules`, `.venv`, `pyproject.toml`, `package.json`, `.sln`, or has path parts matching `{"SteamLibrary", "Riot Games", "XboxGames", "WindowsApps", "$Recycle.Bin", "$RECYCLE.BIN", "System Volume Information"}`, or is inside `projetos_dir` (except `BOT-BRIEF` data dir).
- `is_active_download`: returns `True` if suffix (lowercased) is in `{".crdownload", ".part", ".tmp", ".download", ".opdownload"}`.
- `is_file_locked`: attempts `open(path, "rb+")` on existing files; returns `True` on `PermissionError` or `OSError`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_protector_and_db.py -v`
Expected: PASS (3 passed)

---

### Task 2: Windows `Folcolor` Standardization Engine (`folcolor.py`)

**Files:**
- Create: `app/engine/folcolor.py`
- Test: `tests/test_folcolor.py`

**Interfaces:**
- Consumes: `app.config.FOLCOLOR_CATEGORY_MAP`, `app.engine.protector.is_protected_path`
- Produces:
  - `get_category_icon_resource(folder: Path, vida_root: Path, folcolor_exe: Path) -> str | None`
  - `needs_folcolor_icon(folder: Path, vida_root: Path, folcolor_exe: Path) -> bool`
  - `apply_folcolor_icon(folder: Path, icon_resource: str) -> dict` (returns `{"folder": str, "previous_content": str | None, "applied_resource": str}`)
  - `restore_folcolor_icon(folder: Path, previous_content: str | None) -> None`
  - `scan_missing_icons(vida_root: Path, folcolor_exe: Path, max_depth: int = 2) -> list[dict]`

- [ ] **Step 1: Write the failing tests in `tests/test_folcolor.py`**

```python
import ctypes
from pathlib import Path
from app.engine.folcolor import (
    get_category_icon_resource,
    needs_folcolor_icon,
    apply_folcolor_icon,
    scan_missing_icons,
)


def test_apply_folcolor_overwrites_existing_hidden_system_desktop_ini(tmp_path: Path):
    vida = tmp_path / "Vida"
    sub = vida / "02_Areas" / "01_Faculdade"
    sub.mkdir(parents=True)
    fake_folcolor = tmp_path / "Folcolor.exe"
    fake_folcolor.write_text("exe")

    resource = get_category_icon_resource(sub, vida, fake_folcolor)
    assert resource == f"{fake_folcolor},9"
    assert needs_folcolor_icon(sub, vida, fake_folcolor) is True

    # First application sets HIDDEN | SYSTEM on desktop.ini
    res1 = apply_folcolor_icon(sub, resource)
    assert res1["previous_content"] is None
    ini_path = sub / "desktop.ini"
    assert ini_path.exists()
    assert needs_folcolor_icon(sub, vida, fake_folcolor) is False

    # Second application must succeed without PermissionError even when desktop.ini is Hidden+System
    new_resource = f"{fake_folcolor},6"
    res2 = apply_folcolor_icon(sub, new_resource)
    assert "IconResource=" in (res2["previous_content"] or "")
    assert new_resource in ini_path.read_text(encoding="utf-8")


def test_scan_missing_icons_covers_first_and_second_level_subfolders(tmp_path: Path):
    vida = tmp_path / "Vida"
    sub1 = vida / "03_Recursos" / "01.2_Biblioteca_Concursos"
    sub2 = sub1 / "Matematica"
    sub2.mkdir(parents=True)
    fake_folcolor = tmp_path / "Folcolor.exe"
    fake_folcolor.write_text("exe")

    missing = scan_missing_icons(vida, fake_folcolor, max_depth=2)
    paths = {Path(item["path"]) for item in missing}
    assert sub1 in paths
    assert sub2 in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_folcolor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.folcolor'`

- [ ] **Step 3: Implement `app/engine/folcolor.py`**

Implement `app/engine/folcolor.py`:
- Resolve which top-level category in `FOLCOLOR_CATEGORY_MAP` is an ancestor of `folder` relative to `vida_root`. If `folcolor_exe.exists()`, format `f"{folcolor_exe},{index}"`; else fall back to `"C:\\Windows\\System32\\shell32.dll,3"`.
- Before writing `desktop.ini`, if `ini_path.exists()`, call `ctypes.windll.kernel32.SetFileAttributesW(str(ini_path), 0x80)` (`FILE_ATTRIBUTE_NORMAL`) and read `previous_content`.
- Write:
  ```ini
  [.ShellClassInfo]
  IconResource=<icon_resource>
  ```
- Set `FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM` (`0x02 | 0x04 = 0x06`) on `ini_path`, and add `FILE_ATTRIBUTE_READONLY` (`0x01`) to `folder`'s existing attributes via `GetFileAttributesW` / `SetFileAttributesW`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_folcolor.py -v`
Expected: PASS (2 passed)

---

### Task 3: Rule Matching & Smart Rename Engine (`rules.py`)

**Files:**
- Create: `app/engine/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `unicodedata`, `re`, `datetime`, `pathlib.Path`
- Produces:
  - `normalize_text(text: str) -> str` (NFKD accent removal + lowercase)
  - `suggest_clean_name(path: Path) -> str | None` (detects hex-hash filenames like `3270425600f6bde5b7f8e4a2917a6339.jpg`, numeric-only `5525899.webp`, `WhatsApp Image YYYY-MM-DD at HH.MM.SS.jpeg`, `Imagem do WhatsApp de YYYY-MM-DD...`, and `Gemini_Generated_Image_...`, returning a clean `Img_YYYY-MM-DD_<short>.ext` or `WhatsApp_YYYY-MM-DD_HHhMM.ext`, or `None` if already clean)
  - `is_unstandardized_folder_name(name: str) -> bool` (matches `Nova pasta*`, `Projet`, `Projet [0-9]+`, `teste*`, `prova amanha`, `estudo prova`)
  - `evaluate_file(path: Path, source_scope: str, rules: list[dict], now_ts: float | None = None) -> dict | None` (returns matched rule dict with `target_dir_rel`, `folcolor_index`, `rule_name`, `rule_id`, or `None`)

- [ ] **Step 1: Write the failing tests in `tests/test_rules.py`**

```python
from pathlib import Path
from app.db import Database
from app.engine.rules import (
    suggest_clean_name,
    is_unstandardized_folder_name,
    evaluate_file,
)


def test_accent_and_case_insensitive_rule_matching(tmp_path: Path):
    db = Database(tmp_path / "rules.db")
    db.init_db()
    rules = db.list_rules()

    f1 = tmp_path / "Curriculo_Guilherme_Kaua.DOCX"
    f1.write_text("doc")
    m1 = evaluate_file(f1, "02_Areas", rules)
    assert m1 is not None
    assert "04_Docs_Pessoais" in m1["target_subpath"]

    f2 = tmp_path / "Testes Não Funcionais — Usabilidade.PPTX"
    f2.write_text("ppt")
    m2 = evaluate_file(f2, "Downloads", rules)
    assert m2 is not None
    assert "01_Faculdade" in m2["target_subpath"]

    f3 = tmp_path / "TJPB.apkg"
    f3.write_text("anki")
    m3 = evaluate_file(f3, "02_Areas", rules)
    assert m3 is not None
    assert "01.2_Biblioteca_Concursos" in m3["target_subpath"]


def test_suggest_clean_name_handles_hash_whatsapp_and_gemini(tmp_path: Path):
    p1 = tmp_path / "3270425600f6bde5b7f8e4a2917a6339.jpg"
    p1.write_text("img")
    clean1 = suggest_clean_name(p1)
    assert clean1 is not None
    assert clean1.startswith("Img_") and clean1.endswith("_327042.jpg")

    p2 = tmp_path / "WhatsApp Image 2026-10-27 at 12.17.06.jpeg"
    p2.write_text("img")
    assert suggest_clean_name(p2) == "WhatsApp_2026-10-27_12h17.jpeg"

    p3 = tmp_path / "AlumiGest_Resumo.pdf"
    p3.write_text("pdf")
    assert suggest_clean_name(p3) is None


def test_unstandardized_folder_detection():
    assert is_unstandardized_folder_name("Nova pasta") is True
    assert is_unstandardized_folder_name("Projet 2") is True
    assert is_unstandardized_folder_name("01_Faculdade") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.rules'`

- [ ] **Step 3: Implement `app/engine/rules.py`**

Implement `normalize_text`, `suggest_clean_name`, `is_unstandardized_folder_name`, and `evaluate_file` sorted by rule `priority` ascending. Ensure `evaluate_file` skips rules where `enabled == 0`, checks `source_scope` against `source_scopes_json` (supporting `"*"` or specific scopes like `"Downloads"`, `"02_Areas"`), matches normalized keywords or extensions, and checks `min_age_days` against file `st_mtime`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rules.py -v`
Expected: PASS (3 passed)

---

### Task 4: Duplicate, Installer, Redundant Archive & Folder Health Scanner (`duplicates.py` & `scanner.py`)

**Files:**
- Create: `app/engine/duplicates.py`
- Create: `app/engine/scanner.py`
- Test: `tests/test_scanner_and_duplicates.py`

**Interfaces:**
- Consumes: `app.config.AppConfig`, `app.db.Database`, `app.engine.protector`, `app.engine.rules`, `app.engine.folcolor`
- Produces:
  - `app.engine.duplicates`:
    - `find_redundant_archives(directory: Path) -> list[dict]` (detects `.zip`/`.rar`/`.7z` where a sibling folder with normalized matching stem exists)
    - `find_installers(directory: Path) -> list[dict]` (detects `.exe`, `.msi`, `.msix` in `Downloads`, excluding portable apps matching `"portable"` when they have no installer sibling)
    - `find_duplicates_and_revisions(directories: list[Path]) -> list[dict]` (detects exact SHA-256 duplicates and versioned siblings like `Sprint1-4-v4.pdf` vs `Sprint1-4-v5.pdf` or `Disp1.pptx` vs `Disp.pptx`)
  - `app.engine.scanner`:
    - `scan_all(config: AppConfig, db: Database, now_ts: float | None = None) -> dict` returning:
      - `summary`: `{"total_disorganized": int, "recoverable_bytes": int, "auto_ready_count": int, "c_free_bytes": int}`
      - `folder_cards`: `list[dict]` (`id`, `name`, `path`, `badge`, `status_level` in `{"green", "amber", "red"}`, `score_pct`, `headline`, `detail`)
      - `queue`: `list[dict]` (`id`, `category` in `{"pronto_para_mover", "espaco_recuperavel", "renomear_sugerido", "icone_pendente"}`, `source_path`, `target_path`, `suggested_name`, `reason`, `size_bytes`, `cooldown_ready`, `rule_name`, `folcolor_index`)

- [ ] **Step 1: Write the failing tests in `tests/test_scanner_and_duplicates.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scanner_and_duplicates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.duplicates'`

- [ ] **Step 3: Implement `app/engine/duplicates.py` and `app/engine/scanner.py`**

In `app/engine/duplicates.py`:
- `find_redundant_archives`: strips `.zip`, `.rar`, `.7z`, normalizes whitespace (`re.sub(r"\s+", " ", stem).strip().lower()`), and checks if a directory with that normalized name exists in the same folder.
- `find_installers`: matches `.exe`, `.msi`, `.msix` in `Downloads` (if multiple versions of a portable `.exe` like `MangoDisk*.exe` exist, marks older ones as recoverable).
- `find_duplicates_and_revisions`: groups files by `(size, sha256)` for exact duplicates, and by base stem stripping trailing `[-_ ]?v(\d+)` or `\s*\((\d+)\)` for older revisions.

In `app/engine/scanner.py`:
- Scan `config.downloads_dir` and each category inside `config.vida_root`, skipping protected paths and active downloads.
- Build `folder_cards` (`C:\Downloads`, `F:\Vida\02_Areas`, `F:\Vida\01_Projetos`, `F:\Vida\03_Recursos`, `F:\Vida\00_Jogos`, `F:\Vida\99_Inbox`) with health badges (`ORGANIZADO`, `SOLTOS NA RAIZ`, `FORA DO PADRÃO`, `DESORGANIZADO`) and `score_pct`.
- Build `queue` items with deterministic `id` (hash of `category + source_path`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scanner_and_duplicates.py -v`
Expected: PASS (3 passed)

---

### Task 5: Safe Executor & 1-Click Undo Ledger (`executor.py`)

**Files:**
- Create: `app/engine/executor.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- Consumes: `shutil`, `send2trash.send2trash`, `app.db.Database`, `app.engine.folcolor`, `app.engine.protector`
- Produces:
  - `resolve_collision_path(target_path: Path, source_path: Path) -> Path` (if `target_path` exists and has different content, returns `stem_v2.ext`, `stem_v3.ext`, etc.)
  - `execute_queue_items(items: list[dict], db: Database, config: AppConfig, include_Destructive_trash: bool = False) -> dict` (executes moves, renames, `folcolor` applications, and — only when `include_destructive_trash=True` — `send2trash` or archive moves for `espaco_recuperavel`; records batch in `db`; returns `{"batch_id": int | None, "executed_count": int, "skipped_count": int, "results": list[dict]}`)
  - `undo_batch(batch_id: int, db: Database) -> dict` (reverses moves, renames, and `desktop.ini` changes; returns `{"undone_count": int, "skipped_count": int, "details": list[dict]}`)

- [ ] **Step 1: Write the failing tests in `tests/test_executor.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.executor'`

- [ ] **Step 3: Implement `app/engine/executor.py`**

Implement `resolve_collision_path`, `execute_queue_items`, and `undo_batch`:
- Skip any locked or protected file.
- For `pronto_para_mover` and `renomear_sugerido`: create parent directory, resolve collision path (`_v2`, `_v3`), move with `shutil.move`, apply `Folcolor` icon to target directory if `folcolor_index` is present, and record actual `target_path` in `action_items`.
- For `icone_pendente`: call `apply_folcolor_icon` and store `previous_content` in `meta_json`.
- For `espaco_recuperavel`: only execute if `include_destructive_trash=True`; support `mode="trash"` (`send2trash`) or `mode="archive"` (move to `F:\Vida\04_Arquivo_Morto\Limpeza_Downloads`).
- In `undo_batch`: iterate items in reverse order; if `action_type in {"move", "rename", "archive"}` and `Path(target_path).exists()`, recreate `Path(source_path).parent` and `shutil.move(target_path, source_path)`. If `action_type == "icon"`, call `restore_folcolor_icon`. Mark batch undone.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_executor.py -v`
Expected: PASS (2 passed)

---

### Task 6: FastAPI Backend, Dark-Mode Dashboard UI, and System Tray Entrypoint

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/routes.py`
- Create: `app/static/index.html`
- Create: `app/static/styles.css`
- Create: `app/static/app.js`
- Create: `app/tray/__init__.py`
- Create: `app/tray/tray_agent.py`
- Create: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `app.config.AppConfig`, `app.db.Database`, `app.engine.scanner.scan_all`, `app.engine.executor.execute_queue_items`, `app.engine.executor.undo_batch`
- Produces:
  - `app.api.routes.create_app(config: AppConfig | None = None) -> FastAPI` with endpoints:
    - `GET /` -> serves `app/static/index.html`
    - `GET /api/scan` -> returns `scan_all` report + `last_undoable_batch`
    - `POST /api/execute` -> accepts `{"item_ids": list[str] | None, "categories": list[str] | None, "include_trash": bool, "recoverable_mode": "trash" | "archive"}` and executes matching items
    - `POST /api/undo` -> accepts `{"batch_id": int | None}` and undoes specified or latest batch
    - `GET /api/rules`, `POST /api/rules`, `DELETE /api/rules/{rule_id}` -> CRUD for visual rules
    - `GET /api/history` -> returns recent batches
  - `app.tray.tray_agent.TrayAgent`: Windows System Tray icon (`pystray.Icon`), background daemon thread running periodic auto-organize (only items with `category == "pronto_para_mover"` and `cooldown_ready == True` plus `icone_pendente`), and `open_dashboard()` launching Edge/Chrome with `--app=http://127.0.0.1:<port>` (fallback `webbrowser.open`).
  - `app.main.main()`: CLI flags `--no-tray`, `--open`, `--port` to start server + tray cleanly.

- [ ] **Step 1: Write the failing API & integration tests in `tests/test_api.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: Implement `app/api/routes.py`, `app/static/*`, `app/tray/tray_agent.py`, and `app/main.py`**

- In `app/api/routes.py`: implement `create_app(config)` mounting `/static` and all REST routes (`/api/scan`, `/api/execute`, `/api/undo`, `/api/rules`, `/api/history`, `/api/open-folder`).
- In `app/static/index.html`, `styles.css`, and `app.js`: implement the dark-mode visual interface approved in Option C:
  - Top status header with live disk `C:` free space, recoverable GB count, **Desfazer Última Ação** button, and **Organizar Tudo Agora** button.
  - Folder Health Cards grid (`C:\Downloads`, `F:\Vida\02_Areas`, `F:\Vida\01_Projetos`, `F:\Vida\03_Recursos`, `F:\Vida\00_Jogos`, `F:\Vida\99_Inbox`) with badges (`ORGANIZADO`, `SOLTOS NA RAIZ`, `FORA DO PADRÃO`, `DESORGANIZADO`).
  - Left column: Interactive filterable Disorganized Queue (`Pronto para Mover`, `Espaço Recuperável / Instaladores & Duplicados`, `Renomear`, `Ícones Folcolor`) with per-item and per-category action buttons.
  - Right column: Visual Rules (`Se → Então + Cor Folcolor`) with rule creation/toggle/delete modal and Protected Folders shield card.
- In `app/tray/tray_agent.py` and `app/main.py`: implement the Windows System Tray icon (generated dynamically with `Pillow`), menu items (*Abrir Painel*, *Organizar Agora*, *Desfazer Última Ação*, *Pausar Vigia Automático*, *Sair*), background watcher/scheduler, and a `start_bot.bat` launcher script in project root for 1-click startup.

- [ ] **Step 4: Run entire test suite to verify everything passes**

Run: `python -m pytest -v`
Expected: PASS (all tests across `test_protector_and_db.py`, `test_folcolor.py`, `test_rules.py`, `test_scanner_and_duplicates.py`, `test_executor.py`, and `test_api.py` pass).

