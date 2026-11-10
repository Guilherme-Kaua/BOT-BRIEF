import argparse
import socket
import threading
import time
import uvicorn
from app.api.routes import create_app
from app.config import AppConfig
from app.db import Database
from app.tray.tray_agent import TrayAgent, open_dashboard_window


def _find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> None:
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
            threading.Timer(1.0, lambda: open_dashboard_window(url)).start()
        uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="info")
        return

    server_thread = threading.Thread(
        target=lambda: uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="warning"),
        daemon=True,
    )
    server_thread.start()

    if args.open:
        threading.Timer(1.0, lambda: open_dashboard_window(url)).start()

    tray = TrayAgent(config=config, db=db, dashboard_url=url, fastapi_app=fastapi_app)
    tray.start()


if __name__ == "__main__":
    main()

