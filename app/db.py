import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_WORKSPACES: list[dict] = [
    {
        "name": "Faculdade",
        "icon": "🎓",
        "color": "#3b82f6",
        "description": "ADS, PDFs, trabalhos, sprints, atas e cursos",
        "favorite_folders": ["02_Areas/01_Faculdade/ADS", "03_Recursos/Cursos"],
        "keywords": ["ads", "faculdade", "sprint", "alumigest", "aula", "ata", "pgc", "wazlawick", "pdf"],
        "shortcuts": [
            {"label": "Pasta ADS", "path": "02_Areas/01_Faculdade/ADS"},
            {"label": "Cursos & Apostilas", "path": "03_Recursos/Cursos"},
        ],
        "is_active": 0,
    },
    {
        "name": "Desenvolvimento",
        "icon": "💻",
        "color": "#10b981",
        "description": "Códigos, projetos, automações e ferramentas tech",
        "favorite_folders": ["01_Projetos", "03_Recursos/Ferramentas_Tech"],
        "keywords": ["projeto", "codigo", "python", "git", "api", "script", "dev", "sdk", "ida", "tools"],
        "shortcuts": [
            {"label": "Projetos (C:\\Projetos)", "path": "C:/Projetos"},
            {"label": "Hub Projetos F:\\Vida", "path": "01_Projetos"},
            {"label": "Ferramentas Tech", "path": "03_Recursos/Ferramentas_Tech"},
        ],
        "is_active": 0,
    },
    {
        "name": "Pessoal",
        "icon": "🏠",
        "color": "#ec4899",
        "description": "Documentos pessoais, financeiro, notas fiscais e comprovantes",
        "favorite_folders": ["02_Areas/02_Financeiro", "02_Areas/03_Saude", "02_Areas/04_Pessoal"],
        "keywords": ["comprovante", "nota", "pix", "boleto", "rg", "cpf", "financeiro", "contrato", "pessoal"],
        "shortcuts": [
            {"label": "Financeiro", "path": "02_Areas/02_Financeiro"},
            {"label": "Saúde & Documentos", "path": "02_Areas/03_Saude"},
        ],
        "is_active": 0,
    },
    {
        "name": "Entretenimento",
        "icon": "🎮",
        "color": "#f97316",
        "description": "Jogos, mods, vídeos, replays, imagens e músicas",
        "favorite_folders": ["00_Jogos", "03_Recursos/Midia"],
        "keywords": ["jogo", "game", "mod", "steam", "epic", "video", "musica", "audio", "wallpaper"],
        "shortcuts": [
            {"label": "Central Jogos", "path": "00_Jogos"},
            {"label": "Mídia & Vídeos", "path": "03_Recursos/Midia"},
        ],
        "is_active": 0,
    },
]


DEFAULT_RULES: list[dict] = [
    {
        "name": "Faculdade & ADS",
        "priority": 10,
        "category_folder": "02_Areas",
        "target_subpath": "02_Areas/01_Faculdade/ADS",
        "folcolor_index": 9,
        "keywords": [
            "AlumiGest",
            "Sprint",
            "Ata_de_Reuniao",
            "Ata de Reuniao",
            "Aula",
            "ADS",
            "Usabilidade",
            "Disponibilidade",
            "Teste",
            "Testes Nao Funcionais",
            "Mapa da Empatia",
            "PGC",
            "Wazlawick",
            "Faculdade",
            "SportHub",
        ],
        "extensions": ["pdf", "docx", "pptx", "xlsx", "txt", "zip", "md"],
        "source_scopes": ["Downloads", "Desktop", "Documents", "02_Areas", "03_Recursos", "04_Arquivo_Morto", "99_Inbox"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Concursos & Anki",
        "priority": 20,
        "category_folder": "03_Recursos",
        "target_subpath": "03_Recursos/01.2_Biblioteca_Concursos",
        "folcolor_index": 8,
        "keywords": [
            "PRF",
            "TJPB",
            "ACI",
            "Concurso",
            "Prova Objetiva",
            "Edital",
            "Study-OS",
            "studyn-ciclo",
            "Ciclo",
        ],
        "extensions": ["apkg", "pdf", "zip", "rar", "json", "docx"],
        "source_scopes": ["*"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Documentos Pessoais & Currículos",
        "priority": 30,
        "category_folder": "02_Areas",
        "target_subpath": "02_Areas/04_Docs_Pessoais",
        "folcolor_index": 9,
        "keywords": [
            "Curriculo",
            "RG",
            "CPF",
            "Historico escolar",
            "Comprovante",
            "Contrato",
            "Certidao",
        ],
        "extensions": ["pdf", "docx", "jpg", "jpeg", "png"],
        "source_scopes": ["*"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Ferramentas Tech & Reverse Engineering",
        "priority": 40,
        "category_folder": "03_Recursos",
        "target_subpath": "03_Recursos/01_Biblioteca_Tech/Ferramentas",
        "folcolor_index": 8,
        "keywords": [
            "ghidra",
            "SDIO",
            "scrcpy",
            "QtScrcpy",
            "yt-dlp",
            "yewtube",
            "FiraCode",
            "SegoeUI",
            "segoe-ui",
            "OldNewExplorer",
            "ThemeTool",
            "Spotube",
            "MPF",
            "Folcolor",
            "MangoDisk",
            "Telegram Desktop",
        ],
        "extensions": ["zip", "rar", "7z", "exe", "whl", "dir"],
        "source_scopes": ["Downloads", "99_Inbox"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Prompts, Skills & Docs de Projetos",
        "priority": 45,
        "category_folder": "01_Projetos",
        "target_subpath": "01_Projetos/Prompts_e_Docs",
        "folcolor_index": 6,
        "keywords": ["summary", "review", "subtask", "prompt", "skill", "readme", "spec", "plan"],
        "extensions": ["md", "txt"],
        "source_scopes": ["01_Projetos", "Downloads", "99_Inbox"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Mods, Emuladores & Utilitários de Jogos",
        "priority": 50,
        "category_folder": "00_Jogos",
        "target_subpath": "00_Jogos/Ferramentas",
        "folcolor_index": 4,
        "keywords": [
            "FPSPACK",
            "VALORANT",
            "r2modman",
            "ps2-bios",
            "ISLC",
            "FilterKeysSetter",
            "PokeBonk",
        ],
        "extensions": ["zip", "rar", "7z", "exe", "dir"],
        "source_scopes": ["Downloads", "99_Inbox"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Mídia, Imagens & Memes Salvos",
        "priority": 60,
        "category_folder": "03_Recursos",
        "target_subpath": "03_Recursos/05_Midia_Cultura/Imagens_Salvas",
        "folcolor_index": 8,
        "keywords": [],
        "extensions": ["jpg", "jpeg", "png", "webp", "gif", "mp4"],
        "source_scopes": ["Downloads", "01_Projetos"],
        "min_age_days": 0,
        "enabled": 1,
    },
    {
        "name": "Fallback: Downloads Antigos (> 3 dias)",
        "priority": 90,
        "category_folder": "99_Inbox",
        "target_subpath": "99_Inbox/Downloads",
        "folcolor_index": 2,
        "keywords": [],
        "extensions": ["pdf", "docx", "xlsx", "pptx", "txt", "csv", "json", "zip", "rar"],
        "source_scopes": ["Downloads"],
        "min_age_days": 3,
        "enabled": 1,
    },
]


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 50,
                    category_folder TEXT NOT NULL,
                    target_subpath TEXT NOT NULL,
                    folcolor_index INTEGER NOT NULL DEFAULT 13,
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    extensions_json TEXT NOT NULL DEFAULT '[]',
                    source_scopes_json TEXT NOT NULL DEFAULT '["*"]',
                    min_age_days INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS action_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    description TEXT NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(batch_id) REFERENCES action_batches(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ignored_paths (
                    path TEXT PRIMARY KEY,
                    reason TEXT NOT NULL DEFAULT 'Fixado pelo usuário',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS folder_size_snapshots (
                    folder_path TEXT PRIMARY KEY,
                    folder_name TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    file_count INTEGER NOT NULL,
                    recorded_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS file_tags (
                    path TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (path, tag)
                );

                CREATE TABLE IF NOT EXISTS file_memory (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    current_path TEXT UNIQUE NOT NULL,
                    original_path TEXT NOT NULL,
                    rule_name TEXT NOT NULL DEFAULT '',
                    move_count INTEGER NOT NULL DEFAULT 0,
                    last_reason TEXT NOT NULL DEFAULT '',
                    last_moved_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS file_memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    from_path TEXT NOT NULL,
                    to_path TEXT NOT NULL,
                    rule_name TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES file_memory(file_id)
                );

                CREATE TABLE IF NOT EXISTS decision_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signature_key TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    suggested_target TEXT NOT NULL,
                    suggested_rule TEXT NOT NULL,
                    chosen_target_subpath TEXT NOT NULL,
                    chosen_category TEXT NOT NULL,
                    accepted_rule_id INTEGER,
                    dismissed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inbox_triage_states (
                    item_id TEXT PRIMARY KEY,
                    column_name TEXT NOT NULL,
                    custom_name TEXT,
                    custom_target TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    icon TEXT NOT NULL DEFAULT '📁',
                    color TEXT NOT NULL DEFAULT '#3b82f6',
                    description TEXT NOT NULL DEFAULT '',
                    favorite_folders_json TEXT NOT NULL DEFAULT '[]',
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    shortcuts_json TEXT NOT NULL DEFAULT '[]',
                    is_active INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            # Safe schema migration for action_items.size_bytes
            cols = {r[1] for r in conn.execute("PRAGMA table_info(action_items)").fetchall()}
            if "size_bytes" not in cols:
                conn.execute("ALTER TABLE action_items ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")

            ws_count = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
            if ws_count == 0:
                for ws in DEFAULT_WORKSPACES:
                    conn.execute(
                        """
                        INSERT INTO workspaces (
                            name, icon, color, description,
                            favorite_folders_json, keywords_json, shortcuts_json, is_active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ws["name"],
                            ws["icon"],
                            ws["color"],
                            ws["description"],
                            json.dumps(ws["favorite_folders"], ensure_ascii=False),
                            json.dumps(ws["keywords"], ensure_ascii=False),
                            json.dumps(ws["shortcuts"], ensure_ascii=False),
                            ws["is_active"],
                        ),
                    )
            count = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
            if count == 0:
                for rule in DEFAULT_RULES:
                    conn.execute(
                        """
                        INSERT INTO rules (
                            name, priority, category_folder, target_subpath,
                            folcolor_index, keywords_json, extensions_json,
                            source_scopes_json, min_age_days, enabled
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rule["name"],
                            rule["priority"],
                            rule["category_folder"],
                            rule["target_subpath"],
                            rule["folcolor_index"],
                            json.dumps(rule["keywords"], ensure_ascii=False),
                            json.dumps(rule["extensions"], ensure_ascii=False),
                            json.dumps(rule["source_scopes"], ensure_ascii=False),
                            rule["min_age_days"],
                            rule["enabled"],
                        ),
                    )
            else:
                # Ensure new default rules or updated default scopes/keywords are present
                existing = {
                    r["name"]: r["id"]
                    for r in conn.execute("SELECT id, name FROM rules").fetchall()
                }
                for rule in DEFAULT_RULES:
                    if rule["name"] not in existing:
                        conn.execute(
                            """
                            INSERT INTO rules (
                                name, priority, category_folder, target_subpath,
                                folcolor_index, keywords_json, extensions_json,
                                source_scopes_json, min_age_days, enabled
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                rule["name"],
                                rule["priority"],
                                rule["category_folder"],
                                rule["target_subpath"],
                                rule["folcolor_index"],
                                json.dumps(rule["keywords"], ensure_ascii=False),
                                json.dumps(rule["extensions"], ensure_ascii=False),
                                json.dumps(rule["source_scopes"], ensure_ascii=False),
                                rule["min_age_days"],
                                rule["enabled"],
                            ),
                        )
                    elif rule["name"] in {"Faculdade & ADS", "Ferramentas Tech & Reverse Engineering"}:
                        conn.execute(
                            """
                            UPDATE rules
                            SET keywords_json = ?, extensions_json = ?, source_scopes_json = ?
                            WHERE id = ?
                            """,
                            (
                                json.dumps(rule["keywords"], ensure_ascii=False),
                                json.dumps(rule["extensions"], ensure_ascii=False),
                                json.dumps(rule["source_scopes"], ensure_ascii=False),
                                int(existing[rule["name"]]),
                            ),
                        )
            conn.commit()

    def _row_to_rule(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["keywords"] = json.loads(d["keywords_json"])
        d["extensions"] = json.loads(d["extensions_json"])
        d["source_scopes"] = json.loads(d["source_scopes_json"])
        return d

    def list_rules(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM rules ORDER BY priority ASC, id ASC").fetchall()
            return [self._row_to_rule(r) for r in rows]

    def upsert_rule(self, rule: dict) -> int:
        keywords_json = json.dumps(rule.get("keywords", []), ensure_ascii=False)
        extensions_json = json.dumps(rule.get("extensions", []), ensure_ascii=False)
        source_scopes_json = json.dumps(rule.get("source_scopes", ["*"]), ensure_ascii=False)
        with self._connect() as conn:
            if rule.get("id"):
                conn.execute(
                    """
                    UPDATE rules SET
                        name = ?, priority = ?, category_folder = ?, target_subpath = ?,
                        folcolor_index = ?, keywords_json = ?, extensions_json = ?,
                        source_scopes_json = ?, min_age_days = ?, enabled = ?
                    WHERE id = ?
                    """,
                    (
                        rule["name"],
                        int(rule.get("priority", 50)),
                        rule["category_folder"],
                        rule["target_subpath"],
                        int(rule.get("folcolor_index", 13)),
                        keywords_json,
                        extensions_json,
                        source_scopes_json,
                        int(rule.get("min_age_days", 0)),
                        int(rule.get("enabled", 1)),
                        int(rule["id"]),
                    ),
                )
                conn.commit()
                return int(rule["id"])
            cur = conn.execute(
                """
                INSERT INTO rules (
                    name, priority, category_folder, target_subpath,
                    folcolor_index, keywords_json, extensions_json,
                    source_scopes_json, min_age_days, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["name"],
                    int(rule.get("priority", 50)),
                    rule["category_folder"],
                    rule["target_subpath"],
                    int(rule.get("folcolor_index", 13)),
                    keywords_json,
                    extensions_json,
                    source_scopes_json,
                    int(rule.get("min_age_days", 0)),
                    int(rule.get("enabled", 1)),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def delete_rule(self, rule_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (int(rule_id),))
            conn.commit()

    def add_ignored_path(self, path: str, reason: str = "Fixado pelo usuário") -> None:
        norm = str(Path(path))
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ignored_paths (path, reason, created_at) VALUES (?, ?, ?)",
                (norm, reason, now_iso),
            )
            conn.commit()

    def remove_ignored_path(self, path: str) -> None:
        norm = str(Path(path))
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM ignored_paths WHERE LOWER(path) = LOWER(?)",
                (norm,),
            )
            conn.commit()

    def list_ignored_paths(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM ignored_paths ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def get_ignored_set(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT path FROM ignored_paths").fetchall()
            return {str(Path(r["path"])).lower() for r in rows}

    def get_folder_snapshots(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM folder_size_snapshots").fetchall()
            return {str(Path(r["folder_path"])).lower(): dict(r) for r in rows}

    def upsert_folder_snapshot(
        self,
        folder_path: str,
        folder_name: str,
        size_bytes: int,
        file_count: int,
        recorded_at: float,
    ) -> None:
        norm = str(Path(folder_path))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO folder_size_snapshots
                (folder_path, folder_name, size_bytes, file_count, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (norm, folder_name, int(size_bytes), int(file_count), float(recorded_at)),
            )
            conn.commit()

    def add_file_tag(self, path: str, tag: str) -> None:
        norm_path = str(Path(path))
        clean_tag = tag.strip()
        if not clean_tag:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO file_tags (path, tag, created_at) VALUES (?, ?, ?)",
                (norm_path, clean_tag, now_iso),
            )
            conn.commit()

    def remove_file_tag(self, path: str, tag: str) -> None:
        norm_path = str(Path(path))
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM file_tags WHERE LOWER(path) = LOWER(?) AND LOWER(tag) = LOWER(?)",
                (norm_path, tag.strip()),
            )
            conn.commit()

    def get_tags_for_path(self, path: str) -> list[str]:
        norm_path = str(Path(path))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM file_tags WHERE LOWER(path) = LOWER(?) ORDER BY tag ASC",
                (norm_path,),
            ).fetchall()
            return [str(r["tag"]) for r in rows]

    def get_all_file_tags_map(self) -> dict[str, list[str]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT path, tag FROM file_tags ORDER BY tag ASC").fetchall()
            out: dict[str, list[str]] = {}
            for r in rows:
                key = str(Path(r["path"])).lower()
                out.setdefault(key, []).append(str(r["tag"]))
            return out

    def list_files_by_tag(self, tag: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if tag and tag != "all":
                rows = conn.execute(
                    "SELECT path, tag, created_at FROM file_tags WHERE LOWER(tag) = LOWER(?) ORDER BY created_at DESC",
                    (tag.strip(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT path, tag, created_at FROM file_tags ORDER BY created_at DESC"
                ).fetchall()
            by_path: dict[str, dict] = {}
            for r in rows:
                p_str = str(Path(r["path"]))
                key = p_str.lower()
                if key not in by_path:
                    by_path[key] = {"path": p_str, "tags": [], "created_at": r["created_at"]}
                if r["tag"] not in by_path[key]["tags"]:
                    by_path[key]["tags"].append(r["tag"])
            return list(by_path.values())

    def relocate_file_tags(self, old_path: str, new_path: str) -> None:
        old_norm = str(Path(old_path))
        new_norm = str(Path(new_path))
        if old_norm.lower() == new_norm.lower():
            return
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag, created_at FROM file_tags WHERE LOWER(path) = LOWER(?)",
                (old_norm,),
            ).fetchall()
            if not rows:
                return
            conn.execute("DELETE FROM file_tags WHERE LOWER(path) = LOWER(?)", (old_norm,))
            for r in rows:
                conn.execute(
                    "INSERT OR REPLACE INTO file_tags (path, tag, created_at) VALUES (?, ?, ?)",
                    (new_norm, r["tag"], r["created_at"]),
                )
            conn.commit()

    def record_batch(self, description: str, items: list[dict]) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO action_batches (created_at, description, undone) VALUES (?, ?, 0)",
                (now_iso, description),
            )
            batch_id = int(cur.lastrowid)
            for item in items:
                conn.execute(
                    """
                    INSERT INTO action_items (batch_id, action_type, source_path, target_path, meta_json, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        item["action_type"],
                        str(item["source_path"]),
                        str(item.get("target_path", "")),
                        item.get("meta_json", "{}"),
                        int(item.get("size_bytes", 0)),
                    ),
                )
            conn.commit()
            return batch_id

    def get_batch(self, batch_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM action_batches WHERE id = ?", (int(batch_id),)).fetchone()
            if not row:
                return None
            batch = dict(row)
            items = conn.execute(
                "SELECT * FROM action_items WHERE batch_id = ? ORDER BY id ASC",
                (int(batch_id),),
            ).fetchall()
            batch["items"] = [dict(i) for i in items]
            return batch

    def get_last_undoable_batch(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT b.id FROM action_batches b
                WHERE b.undone = 0
                  AND EXISTS (
                      SELECT 1 FROM action_items i
                      WHERE i.batch_id = b.id
                        AND i.action_type IN ('move', 'rename', 'archive', 'icon')
                  )
                ORDER BY b.id DESC LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            return self.get_batch(int(row["id"]))

    def mark_batch_undone(self, batch_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE action_batches SET undone = 1 WHERE id = ?", (int(batch_id),))
            conn.commit()

    def list_batches(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM action_batches ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
            result = []
            for r in rows:
                b = self.get_batch(int(r["id"]))
                if b:
                    result.append(b)
            return result

    # --- Settings / Preferences ---
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            conn.commit()

    def list_settings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings ORDER BY key ASC").fetchall()
            return {r["key"]: r["value"] for r in rows}

    # --- 13. File Memory (Memória dos arquivos) ---
    def record_file_movement(
        self,
        source_path: str,
        target_path: str,
        rule_name: str = "",
        reason: str = "",
        event_type: str = "move",
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        src_norm = str(Path(source_path))
        dst_norm = str(Path(target_path))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM file_memory WHERE LOWER(current_path) = LOWER(?)",
                (src_norm,),
            ).fetchone()
            if row:
                file_id = int(row["file_id"])
                new_count = int(row["move_count"]) + 1
                conn.execute(
                    """
                    UPDATE file_memory
                    SET current_path = ?, rule_name = ?, move_count = ?, last_reason = ?, last_moved_at = ?
                    WHERE file_id = ?
                    """,
                    (dst_norm, rule_name or row["rule_name"], new_count, reason, now_iso, file_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO file_memory (
                        current_path, original_path, rule_name, move_count,
                        last_reason, last_moved_at, first_seen_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (dst_norm, src_norm, rule_name, reason, now_iso, now_iso),
                )
                file_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO file_memory_events (
                    file_id, event_type, from_path, to_path, rule_name, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, event_type, src_norm, dst_norm, rule_name, reason, now_iso),
            )
            conn.commit()

    def get_file_memory(self, path_str: str) -> dict | None:
        norm = str(Path(path_str))
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM file_memory
                WHERE LOWER(current_path) = LOWER(?) OR LOWER(original_path) = LOWER(?)
                ORDER BY file_id DESC LIMIT 1
                """,
                (norm, norm),
            ).fetchone()
            if not row:
                return None
            mem = dict(row)
            events = conn.execute(
                "SELECT * FROM file_memory_events WHERE file_id = ? ORDER BY id DESC",
                (int(mem["file_id"]),),
            ).fetchall()
            mem["events"] = [dict(e) for e in events]
            return mem

    def list_file_memories(self, limit: int = 200, search: str = "") -> list[dict]:
        q = search.strip().lower()
        with self._connect() as conn:
            if q:
                like = f"%{q}%"
                rows = conn.execute(
                    """
                    SELECT * FROM file_memory
                    WHERE LOWER(current_path) LIKE ? OR LOWER(original_path) LIKE ?
                       OR LOWER(rule_name) LIKE ? OR LOWER(last_reason) LIKE ?
                    ORDER BY last_moved_at DESC LIMIT ?
                    """,
                    (like, like, like, like, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM file_memory ORDER BY last_moved_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            out: list[dict] = []
            for r in rows:
                d = dict(r)
                events = conn.execute(
                    "SELECT * FROM file_memory_events WHERE file_id = ? ORDER BY id DESC",
                    (int(d["file_id"]),),
                ).fetchall()
                d["events"] = [dict(e) for e in events]
                out.append(d)
            return out

    # --- 14. Decision Learning (Aprendizado com decisões do usuário) ---
    @staticmethod
    def _extract_learning_token(file_name: str) -> str:
        import re
        stem = Path(file_name).stem.lower()
        tokens = [t for t in re.split(r"[^a-z0-9à-ÿ]+", stem) if len(t) >= 3 and not t.isdigit()]
        return tokens[0] if tokens else stem[:12]

    def record_user_correction(
        self,
        source_path: str,
        suggested_target: str,
        suggested_rule: str,
        chosen_target_path: str,
        vida_root: Path | None = None,
    ) -> dict:
        src = Path(source_path)
        dst = Path(chosen_target_path)
        dst_dir = dst.parent if dst.suffix else dst
        subpath = str(dst_dir).replace("\\", "/")
        cat = "02_Areas"
        if vida_root is not None:
            try:
                rel = dst_dir.resolve().relative_to(Path(vida_root).resolve())
                subpath = str(rel).replace("\\", "/") or rel.name
                if rel.parts:
                    cat = rel.parts[0]
            except (ValueError, OSError):
                subpath = dst_dir.name
        ext = src.suffix.lower().lstrip(".")
        kw_token = self._extract_learning_token(src.name)
        sig_key = f"{ext}::{kw_token}::{subpath.lower()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decision_feedback (
                    signature_key, source_path, file_name, extension,
                    suggested_target, suggested_rule, chosen_target_subpath,
                    chosen_category, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sig_key,
                    str(src),
                    src.name,
                    ext,
                    str(suggested_target),
                    str(suggested_rule),
                    subpath,
                    cat,
                    now_iso,
                ),
            )
            conn.commit()
        return {
            "signature_key": sig_key,
            "chosen_target_subpath": subpath,
            "chosen_category": cat,
            "keyword": kw_token,
            "extension": ext,
        }

    def list_decision_feedback(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decision_feedback ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
            return [dict(r) for r in rows]

    def list_rule_suggestions(self, min_occurrences: int = 2) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signature_key,
                       extension,
                       chosen_target_subpath,
                       chosen_category,
                       COUNT(*) AS count_hits,
                       MAX(created_at) AS last_seen,
                       GROUP_CONCAT(file_name, ' | ') AS sample_files
                FROM decision_feedback
                WHERE accepted_rule_id IS NULL AND dismissed = 0
                GROUP BY signature_key, chosen_target_subpath, chosen_category
                HAVING COUNT(*) >= ?
                ORDER BY count_hits DESC, last_seen DESC
                """,
                (int(min_occurrences),),
            ).fetchall()
            suggestions: list[dict] = []
            for r in rows:
                d = dict(r)
                parts = d["signature_key"].split("::")
                kw = parts[1] if len(parts) > 1 else ""
                ext = d["extension"]
                target_name = Path(d["chosen_target_subpath"]).name or d["chosen_category"]
                suggestions.append(
                    {
                        "signature_key": d["signature_key"],
                        "count": int(d["count_hits"]),
                        "suggested_rule_name": f"Aprendida: {kw.capitalize() or ext.upper()} → {target_name}",
                        "keyword": kw,
                        "extension": ext,
                        "category_folder": d["chosen_category"],
                        "target_subpath": d["chosen_target_subpath"],
                        "sample_files": [s.strip() for s in (d["sample_files"] or "").split("|") if s.strip()][:5],
                        "last_seen": d["last_seen"],
                        "requires_confirmation": True,
                    }
                )
            return suggestions

    def accept_suggested_rule(self, signature_key: str, folcolor_index: int = 9) -> int | None:
        suggestions = [s for s in self.list_rule_suggestions(min_occurrences=1) if s["signature_key"] == signature_key]
        if not suggestions:
            return None
        s = suggestions[0]
        rule_id = self.upsert_rule(
            {
                "name": s["suggested_rule_name"],
                "priority": 18,
                "category_folder": s["category_folder"],
                "target_subpath": s["target_subpath"],
                "folcolor_index": int(folcolor_index),
                "keywords": [s["keyword"]] if s["keyword"] else [],
                "extensions": [s["extension"]] if s["extension"] else [],
                "source_scopes": ["*"],
                "min_age_days": 0,
                "enabled": 1,
            }
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE decision_feedback SET accepted_rule_id = ? WHERE signature_key = ?",
                (rule_id, signature_key),
            )
            conn.commit()
        return rule_id

    def dismiss_rule_suggestion(self, signature_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE decision_feedback SET dismissed = 1 WHERE signature_key = ?",
                (signature_key,),
            )
            conn.commit()

    # --- 15. Inbox Zero Kanban States ---
    def set_triage_state(
        self,
        item_id: str,
        column_name: str,
        custom_name: str | None = None,
        custom_target: str | None = None,
    ) -> None:
        if column_name not in {"entrada", "em_analise", "organizado"}:
            raise ValueError(f"Coluna Kanban inválida: {column_name}")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT custom_name, custom_target FROM inbox_triage_states WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            final_name = custom_name if custom_name is not None else (existing["custom_name"] if existing else None)
            final_target = custom_target if custom_target is not None else (existing["custom_target"] if existing else None)
            conn.execute(
                """
                INSERT OR REPLACE INTO inbox_triage_states (
                    item_id, column_name, custom_name, custom_target, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (item_id, column_name, final_name, final_target, now_iso),
            )
            conn.commit()

    def get_triage_states_map(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM inbox_triage_states").fetchall()
            return {r["item_id"]: dict(r) for r in rows}

    def clear_triage_state(self, item_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM inbox_triage_states WHERE item_id = ?", (item_id,))
            conn.commit()

    # --- 17. Workspaces (Espaços de trabalho) ---
    def _row_to_workspace(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["favorite_folders"] = json.loads(d.pop("favorite_folders_json", "[]"))
        d["keywords"] = json.loads(d.pop("keywords_json", "[]"))
        d["shortcuts"] = json.loads(d.pop("shortcuts_json", "[]"))
        return d

    def list_workspaces(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY id ASC").fetchall()
            return [self._row_to_workspace(r) for r in rows]

    def set_active_workspace(self, name: str) -> dict | None:
        with self._connect() as conn:
            conn.execute("UPDATE workspaces SET is_active = 0")
            conn.execute("UPDATE workspaces SET is_active = 1 WHERE LOWER(name) = LOWER(?)", (name,))
            conn.commit()
            row = conn.execute("SELECT * FROM workspaces WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
            return self._row_to_workspace(row) if row else None

    def upsert_workspace(self, ws: dict) -> int:
        fav_json = json.dumps(ws.get("favorite_folders", []), ensure_ascii=False)
        kw_json = json.dumps(ws.get("keywords", []), ensure_ascii=False)
        sc_json = json.dumps(ws.get("shortcuts", []), ensure_ascii=False)
        with self._connect() as conn:
            if ws.get("id"):
                conn.execute(
                    """
                    UPDATE workspaces SET
                        name = ?, icon = ?, color = ?, description = ?,
                        favorite_folders_json = ?, keywords_json = ?, shortcuts_json = ?
                    WHERE id = ?
                    """,
                    (
                        ws["name"],
                        ws.get("icon", "📁"),
                        ws.get("color", "#3b82f6"),
                        ws.get("description", ""),
                        fav_json,
                        kw_json,
                        sc_json,
                        int(ws["id"]),
                    ),
                )
                conn.commit()
                return int(ws["id"])
            cur = conn.execute(
                """
                INSERT INTO workspaces (
                    name, icon, color, description,
                    favorite_folders_json, keywords_json, shortcuts_json, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ws["name"],
                    ws.get("icon", "📁"),
                    ws.get("color", "#3b82f6"),
                    ws.get("description", ""),
                    fav_json,
                    kw_json,
                    sc_json,
                    int(ws.get("is_active", 0)),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def delete_workspace(self, workspace_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM workspaces WHERE id = ?", (int(workspace_id),))
            conn.commit()

