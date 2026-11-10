import os
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from PIL import Image, ImageDraw
import pystray
from app.config import AppConfig
from app.db import Database
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.scanner import scan_all


def create_tray_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Folder shape in vibrant blue + green status badge
    draw.rounded_rectangle((6, 16, 58, 52), radius=8, fill=(37, 99, 235, 255))
    draw.rounded_rectangle((6, 10, 28, 22), radius=4, fill=(59, 130, 246, 255))
    draw.ellipse((42, 38, 60, 56), fill=(34, 197, 94, 255))
    return img


def open_dashboard_window(url: str) -> None:
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Google/Chrome/Application/chrome.exe",
        ]
        for browser_exe in candidates:
            if browser_exe.exists():
                try:
                    subprocess.Popen([str(browser_exe), f"--app={url}"])
                    return
                except OSError:
                    pass
    webbrowser.open(url)


class TrayAgent:
    def __init__(self, config: AppConfig, db: Database, dashboard_url: str, fastapi_app=None):
        self.config = config
        self.db = db
        self.dashboard_url = dashboard_url
        self.fastapi_app = fastapi_app
        self.stop_event = threading.Event()
        self.icon: pystray.Icon | None = None

    def _is_watch_enabled(self) -> bool:
        if self.fastapi_app is not None:
            return bool(getattr(self.fastapi_app.state, "auto_watch_enabled", True))
        return True

    def _background_loop(self) -> None:
        while not self.stop_event.wait(timeout=60.0):
            if not self._is_watch_enabled():
                continue
            try:
                report = scan_all(self.config, self.db)
                auto_items = [
                    item
                    for item in report["queue"]
                    if item["category"] in {"pronto_para_mover", "icone_pendente"}
                    and item.get("cooldown_ready", False)
                ]
                if auto_items:
                    execute_queue_items(auto_items, self.db, self.config, include_destructive_trash=False)
            except Exception:
                continue

    def on_open_panel(self, icon=None, item=None) -> None:
        open_dashboard_window(self.dashboard_url)

    def on_organize_now(self, icon=None, item=None) -> None:
        report = scan_all(self.config, self.db)
        safe_items = [
            i
            for i in report["queue"]
            if i["category"] in {"pronto_para_mover", "renomear_sugerido", "icone_pendente"}
        ]
        res = execute_queue_items(safe_items, self.db, self.config, include_destructive_trash=False)
        if self.icon:
            try:
                self.icon.notify(
                    f"{res['executed_count']} item(ns) organizado(s) rumo ao F:\\Vida!",
                    "Vida Organizer",
                )
            except Exception:
                pass

    def on_undo_last(self, icon=None, item=None) -> None:
        last = self.db.get_last_undoable_batch()
        if not last:
            return
        res = undo_batch(int(last["id"]), self.db)
        if self.icon:
            try:
                self.icon.notify(
                    f"{res['undone_count']} item(ns) restaurado(s) ao local original.",
                    "Vida Organizer — Desfazer",
                )
            except Exception:
                pass

    def on_toggle_watch(self, icon=None, item=None) -> None:
        if self.fastapi_app is not None:
            cur = bool(getattr(self.fastapi_app.state, "auto_watch_enabled", True))
            self.fastapi_app.state.auto_watch_enabled = not cur

    def on_quit(self, icon=None, item=None) -> None:
        self.stop_event.set()
        if self.icon:
            self.icon.stop()
        os._exit(0)

    def start(self) -> None:
        bg_thread = threading.Thread(target=self._background_loop, daemon=True)
        bg_thread.start()

        menu = pystray.Menu(
            pystray.MenuItem("Abrir Painel Visual", self.on_open_panel, default=True),
            pystray.MenuItem("Organizar Tudo Agora", self.on_organize_now),
            pystray.MenuItem("Desfazer Última Ação", self.on_undo_last),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Vigia Automático Ativo",
                self.on_toggle_watch,
                checked=lambda item: self._is_watch_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self.on_quit),
        )
        self.icon = pystray.Icon(
            "vida_organizer",
            create_tray_icon_image(),
            "Vida Organizer (F:\\Vida)",
            menu,
        )
        self.icon.run()
