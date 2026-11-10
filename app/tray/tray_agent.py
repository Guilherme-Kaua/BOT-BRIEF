import os
import subprocess
import sys
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


def create_tray_icon_image(size: int = 256) -> Image.Image:
    # Draw at 512x512 and downsample with LANCZOS for crisp anti-aliased edges
    canvas_sz = 512
    img = Image.new("RGBA", (canvas_sz, canvas_sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Outer dark squircle badge
    draw.rounded_rectangle((16, 16, 496, 496), radius=110, fill=(15, 23, 42, 255), outline=(51, 65, 85, 255), width=8)

    # 2. Folder back tab & back cover (Deep Royal Blue)
    draw.rounded_rectangle((68, 96, 240, 180), radius=28, fill=(29, 78, 216, 255))
    draw.rounded_rectangle((68, 132, 444, 412), radius=42, fill=(30, 64, 175, 255))

    # 3. Three Folcolor category cards peeking inside the folder (Orange, Green, Cyan)
    draw.rounded_rectangle((100, 152, 210, 250), radius=16, fill=(249, 115, 22, 255))
    draw.rounded_rectangle((195, 142, 315, 250), radius=16, fill=(16, 185, 129, 255))
    draw.rounded_rectangle((295, 152, 412, 250), radius=16, fill=(14, 165, 233, 255))

    # 4. Folder front pocket (Electric Blue + light top rim)
    draw.rounded_rectangle((68, 196, 444, 416), radius=42, fill=(37, 99, 235, 255), outline=(96, 165, 250, 255), width=6)
    draw.line((104, 226, 408, 226), fill=(147, 197, 253, 190), width=10)

    # 5. Glowing "APP LIGADO" Neon Green Status Badge (Bottom-Right)
    draw.ellipse((308, 308, 484, 484), fill=(11, 15, 25, 255))
    draw.ellipse((322, 322, 470, 470), fill=(34, 197, 94, 255), outline=(134, 239, 172, 255), width=8)
    # Crisp white checkmark inside the green ON badge
    draw.line([(360, 398), (386, 426), (436, 368)], fill=(255, 255, 255, 255), width=20, joint="curve")

    if size != canvas_sz:
        return img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def ensure_app_icon_ico() -> Path:
    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    ico_path = static_dir / "vida_organizer.ico"
    master = create_tray_icon_image(size=256)
    master.save(
        str(ico_path),
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    return ico_path


def open_dashboard_window(url: str) -> None:
    if os.name == "nt":
        try:
            py_exe = Path(sys.executable)
            pythonw = py_exe.with_name("pythonw.exe")
            runner = str(pythonw if pythonw.exists() else py_exe)
            subprocess.Popen(
                [runner, "-m", "app.main", "--desktop-only"],
                cwd=str(Path(__file__).resolve().parent.parent.parent),
            )
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

