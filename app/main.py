import argparse
import os
import socket
import sys
import threading
import time
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


def _find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
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
    parser.add_argument("--port", type=int, default=18420, help="Porta local do painel (padrão: 18420)")
    args = parser.parse_args()

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
    main()
