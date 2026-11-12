import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.db import Database
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.folcolor import apply_folcolor_icon, build_vida_tree
from app.engine.scanner import _build_folder_cards, scan_all
from app.engine.storage_monitor import analyze_storage
from app.tray.tray_agent import ensure_app_icon_ico

FOLCOLOR_PALETTE: list[tuple[int, str, str]] = [
    (2, "Vermelho Vibrante (Inbox / Urgente)", "#ef4444"),
    (4, "Laranja Energia (00_Jogos)", "#f97316"),
    (5, "Amarelo Ouro (Destaques)", "#eab308"),
    (6, "Verde Esmeralda (01_Projetos)", "#10b981"),
    (8, "Azul Céu (03_Recursos / Biblioteca)", "#0ea5e9"),
    (9, "Azul Royal (02_Areas / Faculdade)", "#3b82f6"),
    (11, "Roxo Real (Criativo / Design)", "#8b5cf6"),
    (12, "Rosa Magenta (Mídia / Pessoal)", "#ec4899"),
    (13, "Ciano Raiz (Central F:\\Vida)", "#06b6d4"),
    (15, "Cinza Grafite (04_Arquivo_Morto)", "#64748b"),
]


def format_bytes(b: int) -> str:
    if not b or b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    val = float(b)
    while val >= 1024 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    return f"{val:.2f} {units[idx]}" if idx > 1 else f"{int(val)} {units[idx]}"


def folcolor_info(index: int) -> tuple[str, str]:
    for idx, label, hex_col in FOLCOLOR_PALETTE:
        if idx == index:
            return label, hex_col
    return f"Cor Folcolor #{index}", "#3b82f6"


class DesktopController:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig()
        self.db = Database(self.config.db_path)
        self.db.init_db()
        self.state: dict[str, Any] = {}
        self.last_scan_ts: float = 0.0

    def refresh(self, force: bool = False) -> dict[str, Any]:
        if force or not self.state or (time.time() - self.last_scan_ts) > 30.0:
            self.state = scan_all(self.config, self.db)
            self.last_scan_ts = time.time()
        self.state["last_undoable_batch"] = self.db.get_last_undoable_batch()
        self.state["rules"] = self.db.list_rules()
        self.state["history"] = self.db.list_batches(limit=25)
        self.state["ignored_paths"] = self.db.list_ignored_paths()
        self.state["vida_tree"] = build_vida_tree(
            self.config.vida_root,
            self.config.folcolor_exe,
            self.state.get("queue", []),
        )
        if "storage_monitor" not in self.state:
            self.state["storage_monitor"] = analyze_storage(self.config, self.db)
        return self.state

    def reset_storage_baseline(self) -> dict[str, Any]:
        self.state["storage_monitor"] = analyze_storage(
            self.config,
            self.db,
            reset_baseline=True,
        )
        return self.state["storage_monitor"]

    def update_item_target(
        self,
        item_id: str,
        new_target_path: str,
        new_category: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.state:
            self.refresh(force=True)
        for item in self.state.get("queue", []):
            if item["id"] == item_id:
                item["target_path"] = str(Path(new_target_path))
                if new_category:
                    item["category"] = new_category
                elif item["category"] == "espaco_recuperavel":
                    item["category"] = "pronto_para_mover"
                item["reason"] = f"Destino personalizado → {Path(new_target_path).name}"
                item["rule_name"] = "Edição Manual"
                self.state["vida_tree"] = build_vida_tree(
                    self.config.vida_root,
                    self.config.folcolor_exe,
                    self.state.get("queue", []),
                )
                return item
        return None

    def ignore_items(self, item_ids: list[str], reason: str = "Fixado pelo usuário no local atual") -> int:
        if not self.state:
            self.refresh(force=True)
        wanted = set(item_ids)
        count = 0
        remaining: list[dict[str, Any]] = []
        for item in self.state.get("queue", []):
            if item["id"] in wanted:
                self.db.add_ignored_path(item["source_path"], reason)
                count += 1
            else:
                remaining.append(item)
        self.state["queue"] = remaining
        self.state["summary"]["total_disorganized"] = len(remaining)
        self.state["summary"]["recoverable_bytes"] = sum(
            i["size_bytes"] for i in remaining if i["category"] == "espaco_recuperavel"
        )
        self.state["folder_cards"] = _build_folder_cards(self.config, remaining, {})
        self.state["ignored_paths"] = self.db.list_ignored_paths()
        self.state["vida_tree"] = build_vida_tree(
            self.config.vida_root,
            self.config.folcolor_exe,
            remaining,
        )
        return count

    def unignore_path(self, path_str: str) -> None:
        self.db.remove_ignored_path(path_str)
        self.refresh(force=True)

    def apply_folder_folcolor(self, folder_path: str, folcolor_index: int) -> dict[str, Any]:
        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        icon_res = (
            f"{self.config.folcolor_exe},{int(folcolor_index)}"
            if self.config.folcolor_exe.exists()
            else "C:\\Windows\\System32\\shell32.dll,3"
        )
        applied = apply_folcolor_icon(folder, icon_res)
        self.state["vida_tree"] = build_vida_tree(
            self.config.vida_root,
            self.config.folcolor_exe,
            self.state.get("queue", []),
        )
        return applied

    def create_colored_subfolder(self, parent_path: str, name: str, folcolor_index: int) -> str:
        clean = name.strip().replace("/", "_").replace("\\", "_")
        target = Path(parent_path) / clean
        target.mkdir(parents=True, exist_ok=True)
        self.apply_folder_folcolor(str(target), folcolor_index)
        return str(target)

    def execute_item(
        self,
        item_id: str,
        include_trash: bool = False,
        recoverable_mode: str = "archive",
    ) -> dict[str, Any]:
        return self.execute_items([item_id], include_trash=include_trash, recoverable_mode=recoverable_mode)

    def execute_items(
        self,
        item_ids: list[str],
        include_trash: bool = False,
        recoverable_mode: str = "archive",
    ) -> dict[str, Any]:
        if not self.state:
            self.refresh(force=True)
        wanted = set(item_ids)
        selected = [i for i in self.state.get("queue", []) if i["id"] in wanted]
        res = execute_queue_items(
            selected,
            self.db,
            self.config,
            include_destructive_trash=include_trash,
            recoverable_mode=recoverable_mode,
        )
        self._remove_executed_from_cache(res)
        return res

    def execute_categories(
        self,
        categories: list[str],
        include_trash: bool = False,
        recoverable_mode: str = "archive",
    ) -> dict[str, Any]:
        if not self.state:
            self.refresh(force=True)
        wanted = set(categories)
        selected = [i for i in self.state.get("queue", []) if i["category"] in wanted]
        res = execute_queue_items(
            selected,
            self.db,
            self.config,
            include_destructive_trash=include_trash,
            recoverable_mode=recoverable_mode,
        )
        self._remove_executed_from_cache(res)
        return res

    def move_items_to_folder(self, item_ids: list[str], target_folder: str) -> dict[str, Any]:
        if not self.state:
            self.refresh(force=True)
        dest_dir = Path(target_folder)
        wanted = set(item_ids)
        custom_items: list[dict[str, Any]] = []
        for item in self.state.get("queue", []):
            if item["id"] in wanted:
                src_name = Path(item["source_path"]).name
                cloned = dict(item)
                cloned["category"] = "pronto_para_mover"
                cloned["target_path"] = str(dest_dir / src_name)
                cloned["rule_name"] = f"Movido em lote p/ {dest_dir.name}"
                custom_items.append(cloned)
        res = execute_queue_items(
            custom_items,
            self.db,
            self.config,
            include_destructive_trash=False,
        )
        self._remove_executed_from_cache(res)
        return res

    def save_rule(self, rule_data: dict[str, Any], apply_icon_now: bool = False) -> int:
        rule_id = self.db.upsert_rule(rule_data)
        if apply_icon_now and rule_data.get("target_subpath"):
            target_dir = self.config.vida_root / str(rule_data["target_subpath"])
            self.apply_folder_folcolor(str(target_dir), int(rule_data.get("folcolor_index", 13)))
        self.state["rules"] = self.db.list_rules()
        return rule_id

    def delete_rule(self, rule_id: int) -> None:
        self.db.delete_rule(rule_id)
        self.state["rules"] = self.db.list_rules()

    def _remove_executed_from_cache(self, res: dict[str, Any]) -> None:
        executed_ids = {r["id"] for r in res.get("results", []) if r.get("status") == "executed"}
        if executed_ids and self.state:
            remaining = [i for i in self.state.get("queue", []) if i["id"] not in executed_ids]
            self.state["queue"] = remaining
            self.state["summary"]["total_disorganized"] = len(remaining)
            self.state["summary"]["recoverable_bytes"] = sum(
                i["size_bytes"] for i in remaining if i["category"] == "espaco_recuperavel"
            )
            self.state["folder_cards"] = _build_folder_cards(self.config, remaining, {})
            self.state["vida_tree"] = build_vida_tree(
                self.config.vida_root,
                self.config.folcolor_exe,
                remaining,
            )
        self.state["last_undoable_batch"] = self.db.get_last_undoable_batch()
        self.state["history"] = self.db.list_batches(limit=25)

    def undo_last(self, batch_id: int | None = None) -> dict[str, Any]:
        target_id = batch_id
        if target_id is None:
            last = self.db.get_last_undoable_batch()
            if not last:
                return {"undone_count": 0, "skipped_count": 0, "details": []}
            target_id = int(last["id"])
        res = undo_batch(target_id, self.db)
        self.refresh(force=True)
        return res

    def open_in_explorer(self, path_str: str) -> None:
        p = Path(path_str)
        target = p if p.is_dir() else p.parent
        if not target.exists():
            return
        if os.name == "nt":
            if p.exists() and p.is_file():
                subprocess.Popen(["explorer", f"/select,{p}"])
            else:
                os.startfile(str(target))


DARK_FLUENT_QSS = """
QMainWindow, QDialog {
    background-color: #0b0f19;
    color: #f8fafc;
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    font-size: 13px;
}
QWidget {
    color: #f8fafc;
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
}
QFrame#HeaderBar, QFrame#SurfaceCard, QFrame#BatchBar {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 10px;
}
QFrame#HealthCard {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
}
QFrame#HealthCard:hover {
    background-color: #1e293b;
}
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #111827;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background-color: #0f172a;
    color: #94a3b8;
    border: 1px solid #1e293b;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 9px 18px;
    margin-right: 4px;
    font-weight: 600;
    font-size: 13px;
}
QTabBar::tab:selected {
    background-color: #1d4ed8;
    color: #ffffff;
    border-color: #2563eb;
}
QTabBar::tab:hover:!selected {
    background-color: #1e293b;
    color: #e2e8f0;
}
QPushButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}
QPushButton:disabled {
    background-color: #0f172a;
    color: #475569;
    border-color: #1e293b;
}
QPushButton#PrimaryBtn {
    background-color: #2563eb;
    border-color: #3b82f6;
    color: #ffffff;
}
QPushButton#PrimaryBtn:hover {
    background-color: #1d4ed8;
}
QPushButton#PurpleBtn {
    background-color: #6d28d9;
    border-color: #7c3aed;
    color: #ffffff;
}
QPushButton#PurpleBtn:hover {
    background-color: #5b21b6;
}
QPushButton#AmberBtn {
    background-color: #b45309;
    border-color: #d97706;
    color: #ffffff;
}
QPushButton#AmberBtn:hover {
    background-color: #92400e;
}
QPushButton#DangerBtn {
    background-color: #991b1b;
    border-color: #dc2626;
    color: #ffffff;
}
QPushButton#DangerBtn:hover {
    background-color: #7f1d1d;
}
QPushButton#FilterPill {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 15px;
    padding: 5px 14px;
    color: #cbd5e1;
}
QPushButton#FilterPill[active="true"] {
    background-color: #2563eb;
    border-color: #60a5fa;
    color: #ffffff;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f8fafc;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #3b82f6;
}
QTableWidget, QTreeWidget {
    background-color: #0f172a;
    alternate-background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
    gridline-color: #1e293b;
    selection-background-color: #1e3a8a;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #151f32;
    color: #94a3b8;
    font-weight: 700;
    font-size: 12px;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #1e293b;
    border-right: 1px solid #1e293b;
}
QScrollBar:vertical {
    background: #0f172a;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 30px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def create_desktop_window(config: AppConfig | None = None, auto_scan_async: bool = True):
    from PySide6 import QtCore, QtGui, QtWidgets

    class SizeSortableItem(QtWidgets.QTableWidgetItem):
        def __lt__(self, other: QtWidgets.QTableWidgetItem) -> bool:
            v1 = self.data(QtCore.Qt.ItemDataRole.UserRole)
            v2 = other.data(QtCore.Qt.ItemDataRole.UserRole)
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                return v1 < v2
            return super().__lt__(other)

    class ScanWorker(QtCore.QThread):
        finished_scan = QtCore.Signal(dict)

        def __init__(self, ctrl: DesktopController):
            super().__init__()
            self.ctrl = ctrl

        def run(self):
            state = self.ctrl.refresh(force=True)
            self.finished_scan.emit(state)

    class EditItemTargetDialog(QtWidgets.QDialog):
        def __init__(self, parent: QtWidgets.QWidget, ctrl: DesktopController, item: dict[str, Any]):
            super().__init__(parent)
            self.ctrl = ctrl
            self.item = item
            self.execute_immediately = False
            self.setWindowTitle("✏️ Editar Nome e Pasta de Destino")
            self.setMinimumWidth(640)
            self.setStyleSheet(DARK_FLUENT_QSS)

            layout = QtWidgets.QVBoxLayout(self)
            layout.setSpacing(12)
            layout.setContentsMargins(20, 20, 20, 20)

            src_path = Path(item["source_path"])
            cur_target = Path(item.get("target_path") or (ctrl.config.vida_root / "99_Inbox" / src_path.name))
            if str(cur_target) == "RecycleBin":
                cur_target = ctrl.config.vida_root / "04_Arquivo_Morto" / "Limpeza_Downloads" / src_path.name

            lbl_info = QtWidgets.QLabel(f"<b>Arquivo atual:</b> {src_path}")
            lbl_info.setWordWrap(True)
            lbl_info.setStyleSheet("color: #94a3b8; font-size: 12px;")
            layout.addWidget(lbl_info)

            layout.addWidget(QtWidgets.QLabel("<b>Novo Nome do Arquivo / Pasta:</b>"))
            self.name_edit = QtWidgets.QLineEdit(cur_target.name)
            layout.addWidget(self.name_edit)

            layout.addWidget(QtWidgets.QLabel("<b>Pasta de Destino (F:\\Vida):</b>"))
            dir_row = QtWidgets.QHBoxLayout()
            self.dir_edit = QtWidgets.QLineEdit(str(cur_target.parent))
            dir_row.addWidget(self.dir_edit, 1)

            btn_browse = QtWidgets.QPushButton("📂 Escolher Pasta...")
            btn_browse.clicked.connect(self._browse_dir)
            dir_row.addWidget(btn_browse)
            layout.addLayout(dir_row)

            preset_lbl = QtWidgets.QLabel("Atalhos rápidos do F:\\Vida:")
            preset_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
            layout.addWidget(preset_lbl)

            preset_row = QtWidgets.QHBoxLayout()
            for sub in ["00_Jogos", "01_Projetos", "02_Areas", "03_Recursos", "04_Arquivo_Morto", "99_Inbox"]:
                b = QtWidgets.QPushButton(sub)
                b.clicked.connect(lambda checked=False, s=sub: self.dir_edit.setText(str(ctrl.config.vida_root / s)))
                preset_row.addWidget(b)
            layout.addLayout(preset_row)

            btn_row = QtWidgets.QHBoxLayout()
            btn_row.addStretch()

            btn_cancel = QtWidgets.QPushButton("Cancelar")
            btn_cancel.clicked.connect(self.reject)
            btn_row.addWidget(btn_cancel)

            btn_save = QtWidgets.QPushButton("💾 Salvar na Fila")
            btn_save.clicked.connect(self.accept)
            btn_row.addWidget(btn_save)

            btn_exec_now = QtWidgets.QPushButton("⚡ Salvar e Mover Agora!")
            btn_exec_now.setObjectName("PrimaryBtn")
            btn_exec_now.clicked.connect(self._accept_and_execute)
            btn_row.addWidget(btn_exec_now)

            layout.addLayout(btn_row)

        def _browse_dir(self):
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Escolher Pasta Destino no F:\\Vida",
                self.dir_edit.text() or str(self.ctrl.config.vida_root),
            )
            if chosen:
                self.dir_edit.setText(str(Path(chosen)))

        def _accept_and_execute(self):
            self.execute_immediately = True
            self.accept()

        def result_target_path(self) -> str:
            folder = Path(self.dir_edit.text().strip() or str(self.ctrl.config.vida_root / "99_Inbox"))
            fname = self.name_edit.text().strip() or Path(self.item["source_path"]).name
            return str(folder / fname)

    class VidaMainWindow(QtWidgets.QMainWindow):
        def __init__(self, ctrl: DesktopController):
            super().__init__()
            self.ctrl = ctrl
            self.current_category_filter = "all"
            self.current_folder_filter: str | None = None
            self.editing_rule_id: int | None = None
            self.selected_tree_folder_path: str = str(self.ctrl.config.vida_root)
            self.scan_worker: ScanWorker | None = None

            self.setWindowTitle(f"Vida Organizer — Central {self.ctrl.config.vida_root} (GPU Desktop)")
            self.resize(1440, 880)
            self.setStyleSheet(DARK_FLUENT_QSS)
            try:
                ico_file = ensure_app_icon_ico()
                app_icon = QtGui.QIcon(str(ico_file))
                self.setWindowIcon(app_icon)
                qapp_inst = QtWidgets.QApplication.instance()
                if qapp_inst is not None:
                    qapp_inst.setWindowIcon(app_icon)
            except Exception:
                pass

            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            root_layout = QtWidgets.QVBoxLayout(central)
            root_layout.setContentsMargins(16, 14, 16, 14)
            root_layout.setSpacing(10)

            # 1. Top Header Bar
            header = QtWidgets.QFrame()
            header.setObjectName("HeaderBar")
            h_layout = QtWidgets.QHBoxLayout(header)
            h_layout.setContentsMargins(16, 12, 16, 12)

            title_col = QtWidgets.QVBoxLayout()
            self.lbl_title = QtWidgets.QLabel(f"🟢 Vida Organizer · Central: {self.ctrl.config.vida_root}")
            self.lbl_title.setStyleSheet("font-size: 17px; font-weight: 700; color: #f8fafc;")
            self.lbl_status = QtWidgets.QLabel("Pronto para organizar seu PC sem travamentos.")
            self.lbl_status.setStyleSheet("font-size: 12px; color: #94a3b8;")
            title_col.addWidget(self.lbl_title)
            title_col.addWidget(self.lbl_status)
            h_layout.addLayout(title_col, 1)

            self.btn_refresh = QtWidgets.QPushButton("🔄 Re-escanear Disco")
            self.btn_refresh.clicked.connect(self.trigger_async_scan)
            h_layout.addWidget(self.btn_refresh)

            self.btn_undo = QtWidgets.QPushButton("↩ Desfazer Última Ação")
            self.btn_undo.clicked.connect(self.on_undo_last)
            h_layout.addWidget(self.btn_undo)

            self.btn_icons = QtWidgets.QPushButton("🎨 Aplicar Ícones Folcolor")
            self.btn_icons.setObjectName("PurpleBtn")
            self.btn_icons.clicked.connect(self.on_apply_all_icons)
            h_layout.addWidget(self.btn_icons)

            self.btn_organize_all = QtWidgets.QPushButton("✨ Organizar Tudo Seguro")
            self.btn_organize_all.setObjectName("PrimaryBtn")
            self.btn_organize_all.clicked.connect(self.on_organize_all_safe)
            h_layout.addWidget(self.btn_organize_all)

            root_layout.addWidget(header)

            # 2. Health Cards Row
            self.cards_container = QtWidgets.QWidget()
            self.cards_layout = QtWidgets.QHBoxLayout(self.cards_container)
            self.cards_layout.setContentsMargins(0, 0, 0, 0)
            self.cards_layout.setSpacing(8)
            root_layout.addWidget(self.cards_container)

            # 3. Main Tabs
            self.tabs = QtWidgets.QTabWidget()
            root_layout.addWidget(self.tabs, 1)

            self._build_queue_tab()
            self._build_storage_tab()
            self._build_vida_tree_tab()
            self._build_rules_tab()
            self._build_history_tab()

        def _build_queue_tab(self):
            tab = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(tab)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            top_bar = QtWidgets.QHBoxLayout()
            self.pill_buttons: dict[str, QtWidgets.QPushButton] = {}
            pill_defs = [
                ("all", "Todos (0)"),
                ("pronto_para_mover", "📁 Mover (0)"),
                ("espaco_recuperavel", "🧹 Espaço Recuperável (0)"),
                ("renomear_sugerido", "✏️ Renomear (0)"),
                ("icone_pendente", "🎨 Ícones Folcolor (0)"),
            ]
            for key, text in pill_defs:
                btn = QtWidgets.QPushButton(text)
                btn.setObjectName("FilterPill")
                btn.setProperty("active", "true" if key == "all" else "false")
                btn.clicked.connect(lambda checked=False, k=key: self.set_category_filter(k))
                top_bar.addWidget(btn)
                self.pill_buttons[key] = btn

            self.btn_clear_folder_filter = QtWidgets.QPushButton("✖ Limpar filtro de pasta")
            self.btn_clear_folder_filter.setVisible(False)
            self.btn_clear_folder_filter.clicked.connect(lambda: self.set_folder_filter(None))
            top_bar.addWidget(self.btn_clear_folder_filter)

            top_bar.addStretch()

            self.search_input = QtWidgets.QLineEdit()
            self.search_input.setPlaceholderText("🔍 Buscar por nome, pasta, regra ou extensão...")
            self.search_input.setMinimumWidth(320)
            self.search_input.textChanged.connect(self.apply_filters)
            top_bar.addWidget(self.search_input)

            layout.addLayout(top_bar)

            # High-performance Table with 7 columns (including sortable Size column)
            self.table = QtWidgets.QTableWidget(0, 7)
            self.table.setAlternatingRowColors(True)
            self.table.setSortingEnabled(True)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.verticalHeader().setVisible(False)
            self.table.verticalHeader().setDefaultSectionSize(44)
            self.table.setHorizontalHeaderLabels(
                [
                    "✓",
                    "Arquivo / Pasta",
                    "Tamanho ⇅",
                    "Origem Atual",
                    "Diagnóstico & Regra",
                    "Destino / Novo Nome (Duplo-clique p/ editar)",
                    "Ações",
                ]
            )
            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(0, 40)
            hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(1, 240)
            hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(2, 95)
            hdr.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(3, 190)
            hdr.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(4, 240)
            hdr.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(6, 285)
            self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
            self.table.itemChanged.connect(lambda _: self._update_selection_counter())
            layout.addWidget(self.table, 1)

            # Bottom Multi-Select Action Bar
            batch_bar = QtWidgets.QFrame()
            batch_bar.setObjectName("BatchBar")
            b_layout = QtWidgets.QHBoxLayout(batch_bar)
            b_layout.setContentsMargins(12, 8, 12, 8)

            btn_sel_all = QtWidgets.QPushButton("☑️ Marcar Visíveis")
            btn_sel_all.clicked.connect(lambda: self.set_all_visible_checked(True))
            b_layout.addWidget(btn_sel_all)

            btn_unsel_all = QtWidgets.QPushButton("⬜ Desmarcar Todos")
            btn_unsel_all.clicked.connect(lambda: self.set_all_visible_checked(False))
            b_layout.addWidget(btn_unsel_all)

            self.lbl_selected_count = QtWidgets.QLabel("0 selecionados")
            self.lbl_selected_count.setStyleSheet("color: #60a5fa; font-weight: 700; margin-left: 8px;")
            b_layout.addWidget(self.lbl_selected_count)

            b_layout.addStretch()

            btn_pin_sel = QtWidgets.QPushButton("📌 Fixar/Ignorar Selecionados")
            btn_pin_sel.setToolTip("Mantém os itens selecionados onde estão e nunca mais sugere movê-los")
            btn_pin_sel.clicked.connect(self.on_ignore_selected)
            b_layout.addWidget(btn_pin_sel)

            btn_move_custom = QtWidgets.QPushButton("📁 Mover Selecionados Para...")
            btn_move_custom.clicked.connect(self.on_move_selected_to_folder)
            b_layout.addWidget(btn_move_custom)

            btn_archive_sel = QtWidgets.QPushButton("📦 Arquivar Selecionados")
            btn_archive_sel.setObjectName("AmberBtn")
            btn_archive_sel.clicked.connect(lambda: self.on_execute_selected(include_trash=True, mode="archive"))
            b_layout.addWidget(btn_archive_sel)

            btn_trash_sel = QtWidgets.QPushButton("🗑️ Lixeira Selecionados")
            btn_trash_sel.setObjectName("DangerBtn")
            btn_trash_sel.clicked.connect(lambda: self.on_execute_selected(include_trash=True, mode="trash"))
            b_layout.addWidget(btn_trash_sel)

            btn_exec_sel = QtWidgets.QPushButton("⚡ Executar Ação dos Selecionados")
            btn_exec_sel.setObjectName("PrimaryBtn")
            btn_exec_sel.clicked.connect(lambda: self.on_execute_selected(include_trash=True, mode="archive"))
            b_layout.addWidget(btn_exec_sel)

            layout.addWidget(batch_bar)
            self.tabs.addTab(tab, "📋 Fila Inteligente & Seleção em Lote")

        def _build_vida_tree_tab(self):
            tab = QtWidgets.QWidget()
            split = QtWidgets.QHBoxLayout(tab)
            split.setContentsMargins(14, 14, 14, 14)
            split.setSpacing(14)

            left_col = QtWidgets.QVBoxLayout()
            left_col.addWidget(
                QtWidgets.QLabel(
                    "<b>🌳 Mapa Visual do F:\\Vida (Simulação Antes → Depois & Cores Folcolor em Tempo Real)</b>"
                )
            )

            self.vida_tree_widget = QtWidgets.QTreeWidget()
            self.vida_tree_widget.setAlternatingRowColors(True)
            self.vida_tree_widget.setHeaderLabels(
                [
                    "Pasta no F:\\Vida",
                    "Cor Folcolor Atual",
                    "Itens Atuais",
                    "Simulação (Entrando da Fila)",
                ]
            )
            th = self.vida_tree_widget.header()
            th.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.vida_tree_widget.setColumnWidth(0, 320)
            th.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.vida_tree_widget.setColumnWidth(1, 230)
            th.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.vida_tree_widget.setColumnWidth(2, 110)
            th.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
            self.vida_tree_widget.itemClicked.connect(self.on_tree_folder_clicked)
            left_col.addWidget(self.vida_tree_widget, 1)
            split.addLayout(left_col, 3)

            # Right panel: Quick Folder Color & Subfolder Creator
            right_card = QtWidgets.QFrame()
            right_card.setObjectName("SurfaceCard")
            r_layout = QtWidgets.QVBoxLayout(right_card)
            r_layout.setContentsMargins(18, 18, 18, 18)
            r_layout.setSpacing(12)

            lbl_panel = QtWidgets.QLabel("🎨 Ações na Pasta Selecionada")
            lbl_panel.setStyleSheet("font-size: 15px; font-weight: 700; color: #60a5fa;")
            r_layout.addWidget(lbl_panel)

            self.lbl_tree_selected_path = QtWidgets.QLabel(f"Pasta: {self.ctrl.config.vida_root}")
            self.lbl_tree_selected_path.setWordWrap(True)
            self.lbl_tree_selected_path.setStyleSheet("color: #cbd5e1; font-size: 12px;")
            r_layout.addWidget(self.lbl_tree_selected_path)

            btn_open_sel_tree = QtWidgets.QPushButton("📂 Abrir Esta Pasta no Windows Explorer")
            btn_open_sel_tree.clicked.connect(
                lambda: self.ctrl.open_in_explorer(self.selected_tree_folder_path)
            )
            r_layout.addWidget(btn_open_sel_tree)

            r_layout.addWidget(QtWidgets.QLabel("<b>1. Trocar Cor Folcolor da Pasta (Instantâneo):</b>"))
            self.tree_color_combo = QtWidgets.QComboBox()
            for idx, label, hex_col in FOLCOLOR_PALETTE:
                pix = QtGui.QPixmap(16, 16)
                pix.fill(QtGui.QColor(hex_col))
                self.tree_color_combo.addItem(QtGui.QIcon(pix), f"#{idx} — {label}", idx)
            r_layout.addWidget(self.tree_color_combo)

            btn_apply_tree_color = QtWidgets.QPushButton("🎨 Aplicar Cor Folcolor Agora (SHChangeNotify)")
            btn_apply_tree_color.setObjectName("PurpleBtn")
            btn_apply_tree_color.clicked.connect(self.on_apply_tree_folder_color)
            r_layout.addWidget(btn_apply_tree_color)

            r_layout.addSpacing(10)
            r_layout.addWidget(QtWidgets.QLabel("<b>2. Criar Nova Subpasta Já Colorida Aqui Dentro:</b>"))
            self.new_subfolder_edit = QtWidgets.QLineEdit()
            self.new_subfolder_edit.setPlaceholderText("Nome da nova subpasta (ex: 06_Investimentos)")
            r_layout.addWidget(self.new_subfolder_edit)

            btn_create_sub = QtWidgets.QPushButton("➕ Criar Subpasta Colorida")
            btn_create_sub.setObjectName("PrimaryBtn")
            btn_create_sub.clicked.connect(self.on_create_colored_subfolder)
            r_layout.addWidget(btn_create_sub)

            r_layout.addStretch()
            split.addWidget(right_card, 2)

            self.tabs.addTab(tab, "🌳 Mapa Visual F:\\Vida (Antes → Depois)")

        def _build_rules_tab(self):
            tab = QtWidgets.QWidget()
            split = QtWidgets.QHBoxLayout(tab)
            split.setContentsMargins(14, 14, 14, 14)
            split.setSpacing(14)

            # Left: Rules table + Ignored/Pinned files table
            left_col = QtWidgets.QVBoxLayout()
            left_col.addWidget(QtWidgets.QLabel("<b>🎨 Regras Ativas (Clique em uma regra para editar)</b>"))

            self.rules_table = QtWidgets.QTableWidget(0, 5)
            self.rules_table.setAlternatingRowColors(True)
            self.rules_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.rules_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.rules_table.verticalHeader().setVisible(False)
            self.rules_table.verticalHeader().setDefaultSectionSize(38)
            self.rules_table.setHorizontalHeaderLabels(
                ["Prioridade", "Nome da Regra", "Palavras-chave", "Destino no F:\\Vida", "Cor Folcolor"]
            )
            rh = self.rules_table.horizontalHeader()
            rh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.rules_table.setColumnWidth(0, 80)
            rh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.rules_table.setColumnWidth(1, 190)
            rh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            rh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.rules_table.setColumnWidth(3, 210)
            rh.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.rules_table.setColumnWidth(4, 170)
            self.rules_table.cellClicked.connect(self.on_rule_row_clicked)
            left_col.addWidget(self.rules_table, 3)

            left_col.addWidget(
                QtWidgets.QLabel("<b>📌 Arquivos e Pastas Fixados / Ignorados (Nunca serão movidos)</b>")
            )
            self.ignored_table = QtWidgets.QTableWidget(0, 3)
            self.ignored_table.setAlternatingRowColors(True)
            self.ignored_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.ignored_table.verticalHeader().setVisible(False)
            self.ignored_table.verticalHeader().setDefaultSectionSize(36)
            self.ignored_table.setHorizontalHeaderLabels(["Caminho Protegido", "Motivo", "Ação"])
            ih = self.ignored_table.horizontalHeader()
            ih.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
            ih.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.ignored_table.setColumnWidth(1, 200)
            ih.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.ignored_table.setColumnWidth(2, 130)
            left_col.addWidget(self.ignored_table, 2)

            shield_lbl = QtWidgets.QLabel(
                "🛡️ <b>Trava Intocável Sempre Ativa:</b> pastas com <code>.git</code>, <code>node_modules</code>, "
                "<code>.venv</code>, <code>SteamLibrary</code>, <code>Riot Games</code> e <code>C:\\Projetos</code> "
                "jamais são movidas."
            )
            shield_lbl.setWordWrap(True)
            shield_lbl.setStyleSheet(
                "background-color: #2e1021; border: 1px solid #9d174d; border-radius: 8px; padding: 10px; color: #fbcfe8;"
            )
            left_col.addWidget(shield_lbl)
            split.addLayout(left_col, 3)

            # Right: Rule Editor Form Card
            form_card = QtWidgets.QFrame()
            form_card.setObjectName("SurfaceCard")
            form_layout = QtWidgets.QVBoxLayout(form_card)
            form_layout.setContentsMargins(18, 18, 18, 18)
            form_layout.setSpacing(10)

            self.lbl_rule_form_title = QtWidgets.QLabel("➕ Criar Nova Regra Automática")
            self.lbl_rule_form_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #60a5fa;")
            form_layout.addWidget(self.lbl_rule_form_title)

            form_layout.addWidget(QtWidgets.QLabel("Nome da Regra:"))
            self.rule_name_edit = QtWidgets.QLineEdit()
            self.rule_name_edit.setPlaceholderText("Ex: Faculdade ADS, Imagens WhatsApp, Notas Fiscais...")
            form_layout.addWidget(self.rule_name_edit)

            row_cat_prio = QtWidgets.QHBoxLayout()
            col_cat = QtWidgets.QVBoxLayout()
            col_cat.addWidget(QtWidgets.QLabel("Categoria Principal:"))
            self.rule_cat_combo = QtWidgets.QComboBox()
            self.rule_cat_combo.addItems(
                ["00_Jogos", "01_Projetos", "02_Areas", "03_Recursos", "04_Arquivo_Morto", "99_Inbox"]
            )
            col_cat.addWidget(self.rule_cat_combo)
            row_cat_prio.addLayout(col_cat, 2)

            col_prio = QtWidgets.QVBoxLayout()
            col_prio.addWidget(QtWidgets.QLabel("Prioridade (1 = mais alta):"))
            self.rule_prio_spin = QtWidgets.QSpinBox()
            self.rule_prio_spin.setRange(1, 200)
            self.rule_prio_spin.setValue(25)
            col_prio.addWidget(self.rule_prio_spin)
            row_cat_prio.addLayout(col_prio, 1)
            form_layout.addLayout(row_cat_prio)

            form_layout.addWidget(QtWidgets.QLabel("Subpasta de Destino dentro do F:\\Vida:"))
            sub_row = QtWidgets.QHBoxLayout()
            self.rule_subpath_edit = QtWidgets.QLineEdit()
            self.rule_subpath_edit.setPlaceholderText("Ex: 02_Areas/01_Faculdade/ADS")
            sub_row.addWidget(self.rule_subpath_edit, 1)
            btn_pick_sub = QtWidgets.QPushButton("📂 Escolher...")
            btn_pick_sub.clicked.connect(self._browse_rule_subpath)
            sub_row.addWidget(btn_pick_sub)
            form_layout.addLayout(sub_row)

            form_layout.addWidget(QtWidgets.QLabel("Palavras-chave no nome (separadas por vírgula):"))
            self.rule_kw_edit = QtWidgets.QLineEdit()
            self.rule_kw_edit.setPlaceholderText("Ex: aula, sprint, trabalho, faculdade")
            form_layout.addWidget(self.rule_kw_edit)

            form_layout.addWidget(QtWidgets.QLabel("Extensões aceitas (separadas por vírgula, vazio = todas):"))
            self.rule_ext_edit = QtWidgets.QLineEdit()
            self.rule_ext_edit.setPlaceholderText("Ex: pdf, docx, pptx, zip")
            form_layout.addWidget(self.rule_ext_edit)

            form_layout.addWidget(QtWidgets.QLabel("Cor do Ícone Folcolor para esta Pasta:"))
            self.rule_color_combo = QtWidgets.QComboBox()
            for idx, label, hex_col in FOLCOLOR_PALETTE:
                pix = QtGui.QPixmap(16, 16)
                pix.fill(QtGui.QColor(hex_col))
                self.rule_color_combo.addItem(QtGui.QIcon(pix), f"#{idx} — {label}", idx)
            form_layout.addWidget(self.rule_color_combo)

            self.chk_apply_icon_now = QtWidgets.QCheckBox("Já criar pasta e aplicar cor Folcolor imediatamente ao salvar")
            self.chk_apply_icon_now.setChecked(True)
            form_layout.addWidget(self.chk_apply_icon_now)

            form_layout.addStretch()

            btn_save_rule = QtWidgets.QPushButton("💾 Salvar Regra e Atualizar Fila")
            btn_save_rule.setObjectName("PrimaryBtn")
            btn_save_rule.clicked.connect(self.on_save_rule)
            form_layout.addWidget(btn_save_rule)

            bottom_rule_btns = QtWidgets.QHBoxLayout()
            btn_new_rule = QtWidgets.QPushButton("➕ Limpar / Nova Regra")
            btn_new_rule.clicked.connect(self.reset_rule_form)
            bottom_rule_btns.addWidget(btn_new_rule)

            self.btn_delete_rule = QtWidgets.QPushButton("🗑️ Excluir Regra")
            self.btn_delete_rule.setObjectName("DangerBtn")
            self.btn_delete_rule.setEnabled(False)
            self.btn_delete_rule.clicked.connect(self.on_delete_rule)
            bottom_rule_btns.addWidget(self.btn_delete_rule)

            form_layout.addLayout(bottom_rule_btns)
            split.addWidget(form_card, 2)

            self.tabs.addTab(tab, "🎨 Editor de Regras & Fixados (📌)")

        def _build_history_tab(self):
            tab = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(tab)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            layout.addWidget(QtWidgets.QLabel("<b>🕒 Histórico de Lotes Executados (Reversão 1-Clique)</b>"))

            self.history_table = QtWidgets.QTableWidget(0, 5)
            self.history_table.setAlternatingRowColors(True)
            self.history_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.history_table.verticalHeader().setVisible(False)
            self.history_table.verticalHeader().setDefaultSectionSize(40)
            self.history_table.setHorizontalHeaderLabels(
                ["Lote #", "Data / Hora", "Descrição", "Itens Movidos / Alterados", "Ação"]
            )
            hh = self.history_table.horizontalHeader()
            hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.history_table.setColumnWidth(0, 80)
            hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.history_table.setColumnWidth(1, 180)
            hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.history_table.setColumnWidth(2, 240)
            hh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.history_table.setColumnWidth(4, 150)

            layout.addWidget(self.history_table, 1)
            self.tabs.addTab(tab, "🕒 Histórico & Desfazer (Undo)")

        def _build_storage_tab(self):
            tab = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(tab)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            banner = QtWidgets.QLabel(
                "🔒 <b>Modo Seguro Não-Destrutivo Ativo:</b> Monitoramento contínuo de espaço em disco, "
                "crescimento anormal de pastas, arquivos temporários e downloads abandonados (&gt;24h) "
                "<b>sem nenhuma limpeza automática destrutiva</b>."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background-color: #064e3b; border: 1px solid #10b981; border-radius: 8px; padding: 10px; color: #d1fae5;"
            )
            layout.addWidget(banner)

            # Drives row
            self.drives_container = QtWidgets.QWidget()
            self.drives_layout = QtWidgets.QHBoxLayout(self.drives_container)
            self.drives_layout.setContentsMargins(0, 0, 0, 0)
            self.drives_layout.setSpacing(10)
            layout.addWidget(self.drives_container)

            # Active Alerts table
            layout.addWidget(QtWidgets.QLabel("<b>🚨 Alertas Ativos de Armazenamento</b>"))
            self.storage_alerts_table = QtWidgets.QTableWidget(0, 4)
            self.storage_alerts_table.setAlternatingRowColors(True)
            self.storage_alerts_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.storage_alerts_table.verticalHeader().setVisible(False)
            self.storage_alerts_table.verticalHeader().setDefaultSectionSize(36)
            self.storage_alerts_table.setMaximumHeight(135)
            self.storage_alerts_table.setHorizontalHeaderLabels(["Nível", "Alerta", "Diagnóstico Detalhado", "Local"])
            ah = self.storage_alerts_table.horizontalHeader()
            ah.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_alerts_table.setColumnWidth(0, 110)
            ah.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.storage_alerts_table.setColumnWidth(1, 260)
            ah.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            ah.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.storage_alerts_table.setColumnWidth(3, 180)
            layout.addWidget(self.storage_alerts_table)

            # Split bottom: Folder Growth (left) vs Temp & Abandoned Downloads (right)
            bottom_split = QtWidgets.QHBoxLayout()
            bottom_split.setSpacing(12)

            # Left: Folder Growth
            growth_col = QtWidgets.QVBoxLayout()
            g_top = QtWidgets.QHBoxLayout()
            g_top.addWidget(QtWidgets.QLabel("<b>📈 Crescimento de Pastas (vs. Linha de Base)</b>"))
            g_top.addStretch()
            btn_reset_base = QtWidgets.QPushButton("🔄 Atualizar Linha de Base (Zerar Δ)")
            btn_reset_base.clicked.connect(self.on_reset_storage_baseline)
            g_top.addWidget(btn_reset_base)
            growth_col.addLayout(g_top)

            self.storage_growth_table = QtWidgets.QTableWidget(0, 5)
            self.storage_growth_table.setAlternatingRowColors(True)
            self.storage_growth_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.storage_growth_table.verticalHeader().setVisible(False)
            self.storage_growth_table.verticalHeader().setDefaultSectionSize(36)
            self.storage_growth_table.setHorizontalHeaderLabels(
                ["Pasta Monitorada", "Tamanho Atual", "Variação (Δ)", "Status", "Abrir"]
            )
            gh = self.storage_growth_table.horizontalHeader()
            gh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
            gh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_growth_table.setColumnWidth(1, 110)
            gh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_growth_table.setColumnWidth(2, 120)
            gh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_growth_table.setColumnWidth(3, 150)
            gh.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_growth_table.setColumnWidth(4, 60)
            growth_col.addWidget(self.storage_growth_table, 1)
            bottom_split.addLayout(growth_col, 1)

            # Right: Temp files & Abandoned Downloads
            temp_col = QtWidgets.QVBoxLayout()
            self.lbl_temp_header = QtWidgets.QLabel(
                "<b>🧪 Arquivos Temporários & Downloads Abandonados (&gt;24h)</b>"
            )
            temp_col.addWidget(self.lbl_temp_header)

            self.storage_temp_table = QtWidgets.QTableWidget(0, 5)
            self.storage_temp_table.setAlternatingRowColors(True)
            self.storage_temp_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.storage_temp_table.verticalHeader().setVisible(False)
            self.storage_temp_table.verticalHeader().setDefaultSectionSize(36)
            self.storage_temp_table.setHorizontalHeaderLabels(
                ["Arquivo", "Tipo", "Tamanho", "Idade", "Explorer"]
            )
            th = self.storage_temp_table.horizontalHeader()
            th.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
            th.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.storage_temp_table.setColumnWidth(1, 175)
            th.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_temp_table.setColumnWidth(2, 95)
            th.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_temp_table.setColumnWidth(3, 80)
            th.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.storage_temp_table.setColumnWidth(4, 70)
            temp_col.addWidget(self.storage_temp_table, 1)
            bottom_split.addLayout(temp_col, 1)

            layout.addLayout(bottom_split, 1)
            self.tabs.addTab(tab, "📊 Monitor de Armazenamento")

        def trigger_async_scan(self):
            if self.scan_worker and self.scan_worker.isRunning():
                return
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("⏳ Escaneando...")
            self.lbl_status.setText("Analisando Downloads, Desktop, Documentos e F:\\Vida em segundo plano...")
            self.scan_worker = ScanWorker(self.ctrl)
            self.scan_worker.finished_scan.connect(self._on_async_scan_done)
            self.scan_worker.start()

        def _on_async_scan_done(self, _state: dict[str, Any]):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("🔄 Re-escanear Disco")
            self.render_all()

        def set_category_filter(self, cat: str):
            self.current_category_filter = cat
            for key, btn in self.pill_buttons.items():
                btn.setProperty("active", "true" if key == cat else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            self.apply_filters()

        def set_folder_filter(self, folder_path: str | None):
            if self.current_folder_filter == folder_path:
                self.current_folder_filter = None
            else:
                self.current_folder_filter = folder_path
            self.btn_clear_folder_filter.setVisible(bool(self.current_folder_filter))
            if self.current_folder_filter:
                self.btn_clear_folder_filter.setText(f"✖ Pasta: {Path(self.current_folder_filter).name}")
            self.apply_filters()

        def render_all(self):
            s = self.ctrl.state.get("summary", {})
            q = self.ctrl.state.get("queue", [])
            self.lbl_status.setText(
                f"Disco C: {format_bytes(s.get('c_free_bytes', 0))} livres  ·  "
                f"{len(q)} itens na fila  ·  {format_bytes(s.get('recoverable_bytes', 0))} recuperáveis"
            )

            last_b = self.ctrl.state.get("last_undoable_batch")
            if last_b:
                self.btn_undo.setEnabled(True)
                self.btn_undo.setText(f"↩ Desfazer #{last_b['id']} ({last_b['description']})")
            else:
                self.btn_undo.setEnabled(False)
                self.btn_undo.setText("↩ Desfazer Última Ação")

            self._render_health_cards()
            self._update_pill_counts()
            self._populate_queue_table()
            self._populate_storage_tab()
            self._populate_vida_tree()
            self._populate_rules_table()
            self._populate_ignored_table()
            self._populate_history_table()
            self.apply_filters()

        def _render_health_cards(self):
            while self.cards_layout.count():
                child = self.cards_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            cards = self.ctrl.state.get("folder_cards", [])
            for card in cards:
                border_col = {"red": "#ef4444", "amber": "#f59e0b", "green": "#10b981"}.get(
                    card["status_level"], "#10b981"
                )
                frame = QtWidgets.QFrame()
                frame.setObjectName("HealthCard")
                frame.setStyleSheet(
                    f"QFrame#HealthCard {{ background-color: #111827; border: 1px solid {border_col}; border-radius: 8px; }}"
                    f"QFrame#HealthCard:hover {{ background-color: #1e293b; }}"
                )
                frame.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
                fl = QtWidgets.QVBoxLayout(frame)
                fl.setContentsMargins(10, 8, 10, 8)
                fl.setSpacing(2)

                top_r = QtWidgets.QHBoxLayout()
                lbl_name = QtWidgets.QLabel(f"<b>{card['name']}</b>")
                lbl_name.setStyleSheet(f"color: {border_col}; font-size: 11px;")
                top_r.addWidget(lbl_name)
                top_r.addStretch()

                btn_open = QtWidgets.QPushButton("📂")
                btn_open.setFixedSize(24, 22)
                btn_open.setToolTip(f"Abrir {card['path']} no Explorer")
                btn_open.setStyleSheet("padding: 0px; font-size: 11px;")
                btn_open.clicked.connect(lambda checked=False, p=card["path"]: self.ctrl.open_in_explorer(p))
                top_r.addWidget(btn_open)
                fl.addLayout(top_r)

                lbl_head = QtWidgets.QLabel(card["headline"])
                lbl_head.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
                fl.addWidget(lbl_head)

                lbl_det = QtWidgets.QLabel(card["detail"])
                lbl_det.setStyleSheet("font-size: 10px; color: #94a3b8;")
                fl.addWidget(lbl_det)

                card_path = card["path"]
                frame.mousePressEvent = lambda event, p=card_path: self.set_folder_filter(p)
                self.cards_layout.addWidget(frame, 1)

        def _update_pill_counts(self):
            q = self.ctrl.state.get("queue", [])
            counts = {
                "all": len(q),
                "pronto_para_mover": sum(1 for i in q if i["category"] == "pronto_para_mover"),
                "espaco_recuperavel": sum(1 for i in q if i["category"] == "espaco_recuperavel"),
                "renomear_sugerido": sum(1 for i in q if i["category"] == "renomear_sugerido"),
                "icone_pendente": sum(1 for i in q if i["category"] == "icone_pendente"),
            }
            labels = {
                "all": f"Todos ({counts['all']})",
                "pronto_para_mover": f"📁 Mover ({counts['pronto_para_mover']})",
                "espaco_recuperavel": f"🧹 Espaço ({counts['espaco_recuperavel']})",
                "renomear_sugerido": f"✏️ Renomear ({counts['renomear_sugerido']})",
                "icone_pendente": f"🎨 Ícones ({counts['icone_pendente']})",
            }
            for k, text in labels.items():
                if k in self.pill_buttons:
                    self.pill_buttons[k].setText(text)

        def _populate_queue_table(self):
            self.table.setSortingEnabled(False)
            self.table.setUpdatesEnabled(False)
            self.table.blockSignals(True)
            try:
                q = self.ctrl.state.get("queue", [])
                self.table.setRowCount(len(q))

                cat_badges = {
                    "pronto_para_mover": ("📁 Mover p/ F:\\Vida", "#3b82f6"),
                    "espaco_recuperavel": ("🧹 Espaço Recuperável", "#f59e0b"),
                    "renomear_sugerido": ("✏️ Padronizar Nome", "#10b981"),
                    "icone_pendente": ("🎨 Ícone Folcolor", "#a855f7"),
                }

                for row_idx, item in enumerate(q):
                    src = Path(item["source_path"])
                    is_dir = item.get("item_type") == "folder" or src.is_dir()
                    icon_char = "📁" if is_dir else "📄"
                    sz_bytes = int(item.get("size_bytes", 0))

                    # Col 0: Checkbox item storing item["id"]
                    chk_item = QtWidgets.QTableWidgetItem()
                    chk_item.setFlags(
                        QtCore.Qt.ItemFlag.ItemIsUserCheckable
                        | QtCore.Qt.ItemFlag.ItemIsEnabled
                        | QtCore.Qt.ItemFlag.ItemIsSelectable
                    )
                    chk_item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                    chk_item.setData(QtCore.Qt.ItemDataRole.UserRole, item["id"])
                    self.table.setItem(row_idx, 0, chk_item)

                    # Col 1: File/Folder name
                    name_item = QtWidgets.QTableWidgetItem(f"{icon_char} {src.name}")
                    name_item.setToolTip(str(src))
                    font_bold = name_item.font()
                    font_bold.setBold(True)
                    name_item.setFont(font_bold)
                    self.table.setItem(row_idx, 1, name_item)

                    # Col 2: Numeric Sortable Size
                    sz_item = SizeSortableItem(format_bytes(sz_bytes) if sz_bytes > 0 else "—")
                    sz_item.setData(QtCore.Qt.ItemDataRole.UserRole, sz_bytes)
                    sz_item.setForeground(QtGui.QColor("#cbd5e1"))
                    self.table.setItem(row_idx, 2, sz_item)

                    # Col 3: Origin folder
                    origin_item = QtWidgets.QTableWidgetItem(str(src.parent))
                    origin_item.setForeground(QtGui.QColor("#94a3b8"))
                    origin_item.setToolTip(str(src))
                    self.table.setItem(row_idx, 3, origin_item)

                    # Col 4: Category badge + Reason
                    badge_text, badge_color = cat_badges.get(item["category"], (item["category"], "#60a5fa"))
                    diag_item = QtWidgets.QTableWidgetItem(f"{badge_text} · {item.get('reason', '')}")
                    diag_item.setForeground(QtGui.QColor(badge_color))
                    diag_item.setToolTip(item.get("reason", ""))
                    self.table.setItem(row_idx, 4, diag_item)

                    # Col 5: Proposed Target / New Name
                    target_str = item.get("target_path", "")
                    if target_str == "RecycleBin":
                        disp_target = "🗑️ Lixeira do Windows (ou Arquivar em 04_Arquivo_Morto)"
                    else:
                        disp_target = f"➜ {target_str}"
                    target_item = QtWidgets.QTableWidgetItem(disp_target)
                    target_item.setForeground(QtGui.QColor("#e2e8f0"))
                    target_item.setToolTip("Duplo-clique para editar o nome ou escolher outra pasta de destino")
                    self.table.setItem(row_idx, 5, target_item)

                    # Col 6: Action buttons widget
                    act_widget = QtWidgets.QWidget()
                    act_layout = QtWidgets.QHBoxLayout(act_widget)
                    act_layout.setContentsMargins(4, 2, 4, 2)
                    act_layout.setSpacing(4)

                    item_id = item["id"]
                    cat = item["category"]

                    if cat == "espaco_recuperavel":
                        btn_exec = QtWidgets.QPushButton("📦 Arquivar")
                        btn_exec.setObjectName("AmberBtn")
                        btn_exec.clicked.connect(
                            lambda checked=False, iid=item_id: self.on_execute_single(iid, True, "archive")
                        )
                        act_layout.addWidget(btn_exec)

                        btn_tr = QtWidgets.QPushButton("🗑️")
                        btn_tr.setObjectName("DangerBtn")
                        btn_tr.setFixedWidth(30)
                        btn_tr.setToolTip("Enviar para a Lixeira do Windows")
                        btn_tr.clicked.connect(
                            lambda checked=False, iid=item_id: self.on_execute_single(iid, True, "trash")
                        )
                        act_layout.addWidget(btn_tr)
                    else:
                        btn_label = "🎨 Cor" if cat == "icone_pendente" else "⚡ Mover"
                        btn_exec = QtWidgets.QPushButton(btn_label)
                        btn_exec.setObjectName("PurpleBtn" if cat == "icone_pendente" else "PrimaryBtn")
                        btn_exec.clicked.connect(
                            lambda checked=False, iid=item_id: self.on_execute_single(iid, False, "archive")
                        )
                        act_layout.addWidget(btn_exec)

                    btn_edit = QtWidgets.QPushButton("✏️")
                    btn_edit.setFixedWidth(30)
                    btn_edit.setToolTip("Editar nome do arquivo ou escolher pasta de destino")
                    btn_edit.clicked.connect(lambda checked=False, iid=item_id: self.open_edit_dialog_by_id(iid))
                    act_layout.addWidget(btn_edit)

                    btn_pin = QtWidgets.QPushButton("📌")
                    btn_pin.setFixedWidth(30)
                    btn_pin.setToolTip("Fixar neste local (Ignorar e nunca mover)")
                    btn_pin.clicked.connect(lambda checked=False, iid=item_id: self.on_ignore_single(iid))
                    act_layout.addWidget(btn_pin)

                    btn_exp = QtWidgets.QPushButton("📂")
                    btn_exp.setFixedWidth(30)
                    btn_exp.setToolTip("Mostrar no Windows Explorer")
                    btn_exp.clicked.connect(
                        lambda checked=False, p=item["source_path"]: self.ctrl.open_in_explorer(p)
                    )
                    act_layout.addWidget(btn_exp)

                    self.table.setCellWidget(row_idx, 6, act_widget)
            finally:
                self.table.blockSignals(False)
                self.table.setUpdatesEnabled(True)
                self.table.setSortingEnabled(True)
            self._update_selection_counter()

        def apply_filters(self):
            by_id = {i["id"]: i for i in self.ctrl.state.get("queue", [])}
            query = self.search_input.text().strip().lower()
            cat_filter = self.current_category_filter
            folder_filter = (
                str(Path(self.current_folder_filter)).lower() if self.current_folder_filter else None
            )

            self.table.setUpdatesEnabled(False)
            try:
                for row_idx in range(self.table.rowCount()):
                    chk = self.table.item(row_idx, 0)
                    if not chk:
                        continue
                    iid = str(chk.data(QtCore.Qt.ItemDataRole.UserRole) or "")
                    item = by_id.get(iid)
                    if not item:
                        self.table.setRowHidden(row_idx, True)
                        continue
                    visible = True
                    if cat_filter != "all" and item["category"] != cat_filter:
                        visible = False
                    if visible and folder_filter:
                        src_norm = str(Path(item["source_path"])).lower()
                        if not src_norm.startswith(folder_filter):
                            visible = False
                    if visible and query:
                        haystack = (
                            f"{item.get('source_path', '')} "
                            f"{item.get('target_path', '')} "
                            f"{item.get('reason', '')} "
                            f"{item.get('rule_name', '')}"
                        ).lower()
                        if query not in haystack:
                            visible = False
                    self.table.setRowHidden(row_idx, not visible)
            finally:
                self.table.setUpdatesEnabled(True)
            self._update_selection_counter()

        def set_all_visible_checked(self, checked: bool):
            state = QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
            self.table.blockSignals(True)
            try:
                for r in range(self.table.rowCount()):
                    if not self.table.isRowHidden(r) or not checked:
                        it = self.table.item(r, 0)
                        if it:
                            it.setCheckState(state)
            finally:
                self.table.blockSignals(False)
            self._update_selection_counter()

        def get_selected_item_ids(self) -> list[str]:
            selected: list[str] = []
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 0)
                if it and it.checkState() == QtCore.Qt.CheckState.Checked:
                    iid = it.data(QtCore.Qt.ItemDataRole.UserRole)
                    if iid:
                        selected.append(str(iid))
            return selected

        def _update_selection_counter(self):
            ids = set(self.get_selected_item_ids())
            total_bytes = sum(
                i.get("size_bytes", 0) for i in self.ctrl.state.get("queue", []) if i["id"] in ids
            )
            self.lbl_selected_count.setText(f"{len(ids)} selecionado(s) ({format_bytes(total_bytes)})")

        def on_table_double_clicked(self, row: int, col: int):
            if col in {1, 5}:
                chk = self.table.item(row, 0)
                if chk:
                    iid = str(chk.data(QtCore.Qt.ItemDataRole.UserRole) or "")
                    self.open_edit_dialog_by_id(iid)

        def open_edit_dialog_by_id(self, item_id: str):
            item = next((i for i in self.ctrl.state.get("queue", []) if i["id"] == item_id), None)
            if not item:
                return
            dlg = EditItemTargetDialog(self, self.ctrl, item)
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                new_dst = dlg.result_target_path()
                self.ctrl.update_item_target(item["id"], new_dst)
                if dlg.execute_immediately:
                    res = self.ctrl.execute_items([item["id"]], include_trash=False)
                    self.lbl_status.setText(f"⚡ Movido para {new_dst} ({res['executed_count']} item)!")
                else:
                    self.lbl_status.setText(f"✏️ Destino atualizado na fila: {new_dst}")
                self.render_all()

        def on_ignore_single(self, item_id: str):
            cnt = self.ctrl.ignore_items([item_id])
            self.lbl_status.setText(f"📌 {cnt} item fixado no local atual (adicionado aos ignorados).")
            self.render_all()

        def on_ignore_selected(self):
            ids = self.get_selected_item_ids()
            if not ids:
                self.lbl_status.setText("⚠️ Marque pelo menos 1 item na coluna [✓] para fixar/ignorar.")
                return
            cnt = self.ctrl.ignore_items(ids)
            self.lbl_status.setText(f"📌 {cnt} item(ns) fixado(s) no local atual.")
            self.render_all()

        def on_execute_single(self, item_id: str, include_trash: bool, mode: str):
            t0 = time.perf_counter()
            res = self.ctrl.execute_item(item_id, include_trash=include_trash, recoverable_mode=mode)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.lbl_status.setText(f"⚡ Executado em {dt_ms:.0f} ms ({res['executed_count']} item processado).")
            self.render_all()

        def on_execute_selected(self, include_trash: bool, mode: str):
            ids = self.get_selected_item_ids()
            if not ids:
                self.lbl_status.setText("⚠️ Marque pelo menos 1 item na coluna [✓] antes de executar em lote.")
                return
            t0 = time.perf_counter()
            res = self.ctrl.execute_items(ids, include_trash=include_trash, recoverable_mode=mode)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.lbl_status.setText(
                f"⚡ Lote concluído em {dt_ms:.0f} ms: {res['executed_count']} item(ns) processado(s)!"
            )
            self.render_all()

        def on_move_selected_to_folder(self):
            ids = self.get_selected_item_ids()
            if not ids:
                self.lbl_status.setText("⚠️ Marque os arquivos desejados na coluna [✓] para mover em lote.")
                return
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                f"Escolher Pasta Destino para {len(ids)} item(ns)",
                str(self.ctrl.config.vida_root),
            )
            if not chosen:
                return
            res = self.ctrl.move_items_to_folder(ids, chosen)
            self.lbl_status.setText(f"📁 {res['executed_count']} item(ns) movido(s) para {chosen}!")
            self.render_all()

        def on_organize_all_safe(self):
            res = self.ctrl.execute_categories(
                ["pronto_para_mover", "renomear_sugerido", "icone_pendente"], include_trash=False
            )
            self.lbl_status.setText(f"✨ Organização segura concluída: {res['executed_count']} item(ns) arrumado(s)!")
            self.render_all()

        def on_apply_all_icons(self):
            res = self.ctrl.execute_categories(["icone_pendente"], include_trash=False)
            self.lbl_status.setText(f"🎨 {res['executed_count']} ícone(s) Folcolor aplicado(s) no F:\\Vida!")
            self.render_all()

        def on_undo_last(self, batch_id: int | None = None):
            res = self.ctrl.undo_last(batch_id)
            self.lbl_status.setText(f"↩ Desfeito: {res['undone_count']} item(ns) restaurado(s) ao local original.")
            self.render_all()

        def on_reset_storage_baseline(self):
            self.ctrl.reset_storage_baseline()
            self.lbl_status.setText("🔄 Linha de base de tamanho das pastas atualizada com sucesso!")
            self.render_all()

        def _populate_storage_tab(self):
            mon = self.ctrl.state.get("storage_monitor", {})

            # 1. Drives cards
            while self.drives_layout.count():
                child = self.drives_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            for drv in mon.get("drives", []):
                col = {"red": "#ef4444", "amber": "#f59e0b", "green": "#10b981"}.get(
                    drv.get("status_level", "green"), "#10b981"
                )
                card = QtWidgets.QFrame()
                card.setObjectName("SurfaceCard")
                card.setStyleSheet(
                    f"QFrame#SurfaceCard {{ background-color: #111827; border: 1px solid {col}; border-radius: 8px; }}"
                )
                cl = QtWidgets.QVBoxLayout(card)
                cl.setContentsMargins(14, 10, 14, 10)
                lbl = QtWidgets.QLabel(
                    f"<b>💾 {drv['label']}</b> — {drv['used_pct']:.1f}% ocupado "
                    f"({format_bytes(drv['free_bytes'])} livres de {format_bytes(drv['total_bytes'])})"
                )
                lbl.setStyleSheet(f"color: {col}; font-size: 13px;")
                cl.addWidget(lbl)

                bar = QtWidgets.QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(int(drv["used_pct"]))
                bar.setFixedHeight(12)
                bar.setTextVisible(False)
                bar.setStyleSheet(
                    f"QProgressBar {{ background-color: #0f172a; border-radius: 6px; border: 1px solid #1e293b; }}"
                    f"QProgressBar::chunk {{ background-color: {col}; border-radius: 5px; }}"
                )
                cl.addWidget(bar)
                self.drives_layout.addWidget(card, 1)

            # 2. Active Alerts
            alerts = mon.get("alerts", [])
            self.storage_alerts_table.setRowCount(len(alerts))
            for idx, a in enumerate(alerts):
                sev = a.get("severity", "info")
                sev_lbl, sev_col = {
                    "critical": ("🔴 CRÍTICO", "#ef4444"),
                    "warning": ("🟠 ATENÇÃO", "#f59e0b"),
                    "info": ("🔵 INFO", "#3b82f6"),
                }.get(sev, ("🔵 INFO", "#3b82f6"))

                s_item = QtWidgets.QTableWidgetItem(sev_lbl)
                s_item.setForeground(QtGui.QColor(sev_col))
                self.storage_alerts_table.setItem(idx, 0, s_item)
                self.storage_alerts_table.setItem(idx, 1, QtWidgets.QTableWidgetItem(a.get("title", "")))
                self.storage_alerts_table.setItem(idx, 2, QtWidgets.QTableWidgetItem(a.get("detail", "")))
                self.storage_alerts_table.setItem(idx, 3, QtWidgets.QTableWidgetItem(a.get("path", "")))

            # 3. Folder Growth Table
            growth_list = mon.get("folder_growth", [])
            self.storage_growth_table.setRowCount(len(growth_list))
            for idx, g in enumerate(growth_list):
                self.storage_growth_table.setItem(idx, 0, QtWidgets.QTableWidgetItem(f"📁 {g['name']}"))
                self.storage_growth_table.setItem(
                    idx, 1, QtWidgets.QTableWidgetItem(format_bytes(g.get("current_bytes", 0)))
                )
                delta = int(g.get("delta_bytes", 0))
                delta_str = f"+{format_bytes(delta)}" if delta > 0 else "0 B (Estável)"
                d_item = QtWidgets.QTableWidgetItem(delta_str)
                abnormal = bool(g.get("abnormal_growth", False))
                d_item.setForeground(QtGui.QColor("#ef4444" if abnormal else "#94a3b8"))
                self.storage_growth_table.setItem(idx, 2, d_item)

                st_txt = "⚠️ Crescimento Anormal" if abnormal else "✓ Normal"
                st_item = QtWidgets.QTableWidgetItem(st_txt)
                st_item.setForeground(QtGui.QColor("#ef4444" if abnormal else "#10b981"))
                self.storage_growth_table.setItem(idx, 3, st_item)

                w_open = QtWidgets.QWidget()
                wl = QtWidgets.QHBoxLayout(w_open)
                wl.setContentsMargins(2, 2, 2, 2)
                b_op = QtWidgets.QPushButton("📂")
                b_op.setFixedWidth(34)
                b_op.clicked.connect(lambda checked=False, p=g["path"]: self.ctrl.open_in_explorer(p))
                wl.addWidget(b_op)
                self.storage_growth_table.setCellWidget(idx, 4, w_open)

            # 4. Temp & Abandoned Downloads Table
            ta = mon.get("temp_and_abandoned", {})
            t_items = ta.get("items", [])
            self.lbl_temp_header.setText(
                f"<b>🧪 Temporários & Downloads Abandonados: {ta.get('total_count', 0)} item(ns) "
                f"({format_bytes(ta.get('total_bytes', 0))})</b>"
            )
            self.storage_temp_table.setRowCount(len(t_items))
            for idx, ti in enumerate(t_items):
                self.storage_temp_table.setItem(idx, 0, QtWidgets.QTableWidgetItem(ti["name"]))
                k_item = QtWidgets.QTableWidgetItem(ti["kind_label"])
                k_col = "#f59e0b" if ti["kind"] == "abandoned_download" else "#60a5fa"
                k_item.setForeground(QtGui.QColor(k_col))
                self.storage_temp_table.setItem(idx, 1, k_item)
                self.storage_temp_table.setItem(
                    idx, 2, QtWidgets.QTableWidgetItem(format_bytes(ti.get("size_bytes", 0)))
                )
                self.storage_temp_table.setItem(idx, 3, QtWidgets.QTableWidgetItem(f"{ti.get('age_hours', 0)}h"))

                w_exp = QtWidgets.QWidget()
                w_el = QtWidgets.QHBoxLayout(w_exp)
                w_el.setContentsMargins(2, 2, 2, 2)
                b_ex = QtWidgets.QPushButton("📂")
                b_ex.setFixedWidth(34)
                b_ex.clicked.connect(lambda checked=False, p=ti["path"]: self.ctrl.open_in_explorer(p))
                w_el.addWidget(b_ex)
                self.storage_temp_table.setCellWidget(idx, 4, w_exp)

        # --- Vida Tree Tab Logic ---
        def _populate_vida_tree(self):
            self.vida_tree_widget.clear()
            nodes = self.ctrl.state.get("vida_tree", [])
            by_path: dict[str, QtWidgets.QTreeWidgetItem] = {}

            for node in nodes:
                folder_p = Path(node["path"])
                c_idx = int(node.get("current_folcolor_index", 13))
                c_label, c_hex = folcolor_info(c_idx)
                status_ini = "✓ Ativo" if node.get("has_desktop_ini") else "⏳ Pendente"

                inc = int(node.get("incoming_count", 0))
                if inc > 0:
                    preview = ", ".join(node.get("incoming_files", [])[:4])
                    sim_txt = f"🟢 +{inc} entrando ({preview})"
                else:
                    sim_txt = "—"

                tree_item = QtWidgets.QTreeWidgetItem(
                    [
                        f"📁 {node['name']}",
                        f"● #{c_idx} {c_label.split('(')[0].strip()} ({status_ini})",
                        f"{node['file_count']} item(ns)",
                        sim_txt,
                    ]
                )
                tree_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, node["path"])
                tree_item.setData(1, QtCore.Qt.ItemDataRole.UserRole, c_idx)
                tree_item.setForeground(1, QtGui.QColor(c_hex))
                if inc > 0:
                    tree_item.setForeground(3, QtGui.QColor("#10b981"))

                parent_key = str(folder_p.parent).lower()
                if node["depth"] == 0 or parent_key not in by_path:
                    self.vida_tree_widget.addTopLevelItem(tree_item)
                else:
                    by_path[parent_key].addChild(tree_item)
                by_path[str(folder_p).lower()] = tree_item

            self.vida_tree_widget.expandAll()

        def on_tree_folder_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int):
            p = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            c_idx = item.data(1, QtCore.Qt.ItemDataRole.UserRole)
            if p:
                self.selected_tree_folder_path = str(p)
                self.lbl_tree_selected_path.setText(f"Pasta selecionada:\n{p}")
            if c_idx is not None:
                combo_i = self.tree_color_combo.findData(int(c_idx))
                if combo_i >= 0:
                    self.tree_color_combo.setCurrentIndex(combo_i)

        def on_apply_tree_folder_color(self):
            idx = int(self.tree_color_combo.currentData() or 13)
            self.ctrl.apply_folder_folcolor(self.selected_tree_folder_path, idx)
            self.lbl_status.setText(
                f"🎨 Cor Folcolor #{idx} aplicada em {self.selected_tree_folder_path} (Explorer atualizado)!"
            )
            self.render_all()

        def on_create_colored_subfolder(self):
            sub_name = self.new_subfolder_edit.text().strip()
            if not sub_name:
                self.lbl_status.setText("⚠️ Digite o nome da nova subpasta antes de criar.")
                return
            idx = int(self.tree_color_combo.currentData() or 13)
            created = self.ctrl.create_colored_subfolder(self.selected_tree_folder_path, sub_name, idx)
            self.new_subfolder_edit.clear()
            self.lbl_status.setText(f"➕ Subpasta criada e colorida (#{idx}): {created}")
            self.render_all()

        # --- Rules & Ignored Tab Logic ---
        def _populate_rules_table(self):
            rules = self.ctrl.state.get("rules", [])
            self.rules_table.setRowCount(len(rules))
            for r_idx, rule in enumerate(rules):
                p_item = QtWidgets.QTableWidgetItem(str(rule.get("priority", 50)))
                p_item.setData(QtCore.Qt.ItemDataRole.UserRole, rule["id"])
                self.rules_table.setItem(r_idx, 0, p_item)

                n_item = QtWidgets.QTableWidgetItem(rule["name"])
                f_bold = n_item.font()
                f_bold.setBold(True)
                n_item.setFont(f_bold)
                self.rules_table.setItem(r_idx, 1, n_item)

                kws = ", ".join(rule.get("keywords", [])) or "(Qualquer nome)"
                exts = ", ".join(rule.get("extensions", []))
                cond_txt = f"{kws}" + (f" [{exts}]" if exts else "")
                self.rules_table.setItem(r_idx, 2, QtWidgets.QTableWidgetItem(cond_txt))

                sub_item = QtWidgets.QTableWidgetItem(f"F:\\Vida\\{rule['target_subpath']}")
                sub_item.setForeground(QtGui.QColor("#60a5fa"))
                self.rules_table.setItem(r_idx, 3, sub_item)

                c_idx = int(rule.get("folcolor_index", 13))
                c_label, c_hex = folcolor_info(c_idx)
                c_item = QtWidgets.QTableWidgetItem(f"● #{c_idx} {c_label.split('(')[0].strip()}")
                c_item.setForeground(QtGui.QColor(c_hex))
                self.rules_table.setItem(r_idx, 4, c_item)

        def _populate_ignored_table(self):
            ignored = self.ctrl.state.get("ignored_paths", [])
            self.ignored_table.setRowCount(len(ignored))
            for idx, entry in enumerate(ignored):
                p_str = entry["path"]
                self.ignored_table.setItem(idx, 0, QtWidgets.QTableWidgetItem(p_str))
                self.ignored_table.setItem(idx, 1, QtWidgets.QTableWidgetItem(entry.get("reason", "")))

                w = QtWidgets.QWidget()
                wl = QtWidgets.QHBoxLayout(w)
                wl.setContentsMargins(4, 2, 4, 2)
                btn_unpin = QtWidgets.QPushButton("🔓 Desafixar")
                btn_unpin.clicked.connect(
                    lambda checked=False, path_val=p_str: (
                        self.ctrl.unignore_path(path_val),
                        self.render_all(),
                    )
                )
                wl.addWidget(btn_unpin)
                self.ignored_table.setCellWidget(idx, 2, w)

        def on_rule_row_clicked(self, row: int, _col: int):
            rules = self.ctrl.state.get("rules", [])
            if row < 0 or row >= len(rules):
                return
            rule = rules[row]
            self.editing_rule_id = int(rule["id"])
            self.lbl_rule_form_title.setText(f"✏️ Editando Regra #{rule['id']}: {rule['name']}")
            self.rule_name_edit.setText(rule["name"])
            self.rule_cat_combo.setCurrentText(rule.get("category_folder", "02_Areas"))
            self.rule_prio_spin.setValue(int(rule.get("priority", 50)))
            self.rule_subpath_edit.setText(rule.get("target_subpath", ""))
            self.rule_kw_edit.setText(", ".join(rule.get("keywords", [])))
            self.rule_ext_edit.setText(", ".join(rule.get("extensions", [])))

            idx_val = int(rule.get("folcolor_index", 13))
            combo_idx = self.rule_color_combo.findData(idx_val)
            if combo_idx >= 0:
                self.rule_color_combo.setCurrentIndex(combo_idx)
            self.btn_delete_rule.setEnabled(True)

        def reset_rule_form(self):
            self.editing_rule_id = None
            self.lbl_rule_form_title.setText("➕ Criar Nova Regra Automática")
            self.rule_name_edit.clear()
            self.rule_subpath_edit.clear()
            self.rule_kw_edit.clear()
            self.rule_ext_edit.clear()
            self.rule_prio_spin.setValue(25)
            self.btn_delete_rule.setEnabled(False)

        def _browse_rule_subpath(self):
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Escolher Pasta dentro do F:\\Vida",
                str(self.ctrl.config.vida_root),
            )
            if chosen:
                p = Path(chosen)
                try:
                    rel = p.relative_to(self.ctrl.config.vida_root)
                    self.rule_subpath_edit.setText(str(rel).replace("\\", "/"))
                    if rel.parts:
                        self.rule_cat_combo.setCurrentText(rel.parts[0])
                except ValueError:
                    self.rule_subpath_edit.setText(str(p).replace("\\", "/"))

        def on_save_rule(self):
            name = self.rule_name_edit.text().strip()
            subpath = self.rule_subpath_edit.text().strip().replace("\\", "/")
            if not name or not subpath:
                self.lbl_status.setText("⚠️ Preencha o Nome da Regra e a Subpasta de Destino.")
                return
            kws = [k.strip() for k in self.rule_kw_edit.text().split(",") if k.strip()]
            exts = [e.strip().lstrip(".") for e in self.rule_ext_edit.text().split(",") if e.strip()]
            folcolor_idx = int(self.rule_color_combo.currentData() or 13)

            payload: dict[str, Any] = {
                "id": self.editing_rule_id,
                "name": name,
                "priority": int(self.rule_prio_spin.value()),
                "category_folder": self.rule_cat_combo.currentText(),
                "target_subpath": subpath,
                "folcolor_index": folcolor_idx,
                "keywords": kws,
                "extensions": exts,
                "source_scopes": ["*"],
                "min_age_days": 0,
                "enabled": 1,
            }
            self.ctrl.save_rule(payload, apply_icon_now=self.chk_apply_icon_now.isChecked())
            self.reset_rule_form()
            self.lbl_status.setText(f"💾 Regra '{name}' salva! Re-escaneando fila com a nova regra...")
            self.trigger_async_scan()

        def on_delete_rule(self):
            if self.editing_rule_id is None:
                return
            rid = self.editing_rule_id
            self.ctrl.delete_rule(rid)
            self.reset_rule_form()
            self.lbl_status.setText(f"🗑️ Regra #{rid} removida.")
            self.trigger_async_scan()

        # --- History Tab Logic ---
        def _populate_history_table(self):
            batches = self.ctrl.state.get("history", [])
            self.history_table.setRowCount(len(batches))
            for idx, b in enumerate(batches):
                self.history_table.setItem(idx, 0, QtWidgets.QTableWidgetItem(f"#{b['id']}"))
                self.history_table.setItem(idx, 1, QtWidgets.QTableWidgetItem(b.get("created_at", "")[:19]))
                self.history_table.setItem(idx, 2, QtWidgets.QTableWidgetItem(b.get("description", "")))

                items_preview = ", ".join(Path(i["source_path"]).name for i in b.get("items", [])[:5])
                if len(b.get("items", [])) > 5:
                    items_preview += f" (+{len(b['items']) - 5} mais)"
                self.history_table.setItem(idx, 3, QtWidgets.QTableWidgetItem(items_preview))

                act_w = QtWidgets.QWidget()
                act_l = QtWidgets.QHBoxLayout(act_w)
                act_l.setContentsMargins(4, 2, 4, 2)
                if not b.get("undone"):
                    btn_u = QtWidgets.QPushButton("↩ Desfazer Lote")
                    btn_u.clicked.connect(lambda checked=False, bid=b["id"]: self.on_undo_last(int(bid)))
                    act_l.addWidget(btn_u)
                else:
                    lbl_u = QtWidgets.QLabel("✓ Já desfeito")
                    lbl_u.setStyleSheet("color: #64748b; font-size: 12px;")
                    act_l.addWidget(lbl_u)
                self.history_table.setCellWidget(idx, 4, act_w)

    ctrl = DesktopController(config)
    win = VidaMainWindow(ctrl)
    if auto_scan_async:
        QtCore.QTimer.singleShot(50, win.trigger_async_scan)
    return win


def launch_desktop_app(config: AppConfig | None = None) -> None:
    import ctypes
    from PySide6 import QtCore, QtGui, QtWidgets

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VidaOrganizer.BotBrief.Desktop.1")
        except Exception:
            pass

    QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    try:
        ico_file = ensure_app_icon_ico()
        app.setWindowIcon(QtGui.QIcon(str(ico_file)))
    except Exception:
        pass
    win = create_desktop_window(config, auto_scan_async=True)
    win.show()
    win.raise_()
    win.activateWindow()
    app.exec()
