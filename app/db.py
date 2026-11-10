import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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
                """
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
                    INSERT INTO action_items (batch_id, action_type, source_path, target_path, meta_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        item["action_type"],
                        str(item["source_path"]),
                        str(item.get("target_path", "")),
                        item.get("meta_json", "{}"),
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

