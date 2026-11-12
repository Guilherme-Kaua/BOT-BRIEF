import argparse
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
import uvicorn
from app.api.routes import create_app
from app.config import AppConfig
from app.db import Database
from app.tray.tray_agent import TrayAgent, open_dashboard_window


def ensure_stdio_streams() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_free_port(preferred: int) -> int:
    if not _is_port_in_use(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_and_open(port: int, url: str, timeout_sec: float = 10.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                open_dashboard_window(url)
                return
        time.sleep(0.15)
    open_dashboard_window(url)


def main() -> None:
    ensure_stdio_streams()

    parser = argparse.ArgumentParser(description="Vida Organizer — BOT-BRIEF")
    parser.add_argument("--no-tray", action="store_true", help="Roda apenas o servidor web sem ícone na bandeja")
    parser.add_argument("--open", action="store_true", help="Abre o painel visual ao iniciar")
    parser.add_argument("--desktop-only", action="store_true", help="Abre diretamente a janela Desktop nativa")
    parser.add_argument("--port", type=int, default=18420, help="Porta local do painel (padrão: 18420)")
    parser.add_argument("--ctx-organize", type=str, default="", help="Menu Explorer: organizar arquivo/pasta")
    parser.add_argument("--ctx-send-vida", type=str, default="", help="Menu Explorer: enviar para F:\\Vida")
    parser.add_argument("--ctx-pin", type=str, default="", help="Menu Explorer: adicionar aos fixados")
    parser.add_argument("--ctx-duplicates", type=str, default="", help="Menu Explorer: analisar duplicados")
    parser.add_argument("--ctx-open-target", type=str, default="", help="Menu Explorer: abrir pasta de destino")
    args = parser.parse_args()

    # Handle Windows Explorer Context Menu actions (no server startup needed)
    ctx_actions = [
        ("organize", args.ctx_organize),
        ("send_vida", args.ctx_send_vida),
        ("pin", args.ctx_pin),
        ("duplicates", args.ctx_duplicates),
        ("open_target", args.ctx_open_target),
    ]
    for act_name, target_p in ctx_actions:
        if target_p:
            from app.engine.explorer_integration import execute_context_menu_action

            cfg_ctx = AppConfig(port=args.port)
            db_ctx = Database(cfg_ctx.db_path)
            db_ctx.init_db()
            res = execute_context_menu_action(act_name, target_p, cfg_ctx, db_ctx)
            if act_name == "duplicates":
                from app.desktop_gui import launch_desktop_app

                launch_desktop_app(cfg_ctx, initial_tab=2)
            print(res)
            return

    if args.desktop_only or (args.open and _is_port_in_use(args.port)):
        from app.desktop_gui import launch_desktop_app

        launch_desktop_app(AppConfig(port=args.port))
        return

    port = _find_free_port(args.port)
    config = AppConfig(port=port)
    db = Database(config.db_path)
    db.init_db()

    fastapi_app = create_app(config)
    url = f"http://127.0.0.1:{port}"

    if args.no_tray:
        if args.open:
            threading.Thread(target=_wait_and_open, args=(port, url), daemon=True).start()
        uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_config=None)
        return

    server_thread = threading.Thread(
        target=lambda: uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_config=None),
        daemon=True,
    )
    server_thread.start()

    if args.open:
        threading.Thread(target=_wait_and_open, args=(port, url), daemon=True).start()

    tray = TrayAgent(config=config, db=db, dashboard_url=url, fastapi_app=fastapi_app)
    tray.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_path = Path(__file__).resolve().parent.parent / "data" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- Crash at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(traceback.format_exc())
        raise
