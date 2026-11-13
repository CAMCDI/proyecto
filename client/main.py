"""Punto de entrada del agente cliente de monitoreo remoto.

Parsea los argumentos de línea de comandos, crea el contexto TLS,
inicializa el agente y la interfaz gráfica, y coordina el event loop
de asyncio con PyQt6.

Requisitos: 17.4, 18.4.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from common.crypto import create_client_tls_context
from client.agent import ClientAgent
from client.ui import ClientUI

__all__: list[str] = []

# Directorio de certificados por defecto.
DEFAULT_CERT_DIR: str = str(Path.home() / ".config" / "remote-monitor" / "certs")


def parse_args() -> argparse.Namespace:
    """Parsea los argumentos de línea de comandos del cliente."""
    parser = argparse.ArgumentParser(
        description="Agente Cliente de Monitoreo y Administración Remota",
    )
    parser.add_argument(
        "--host", required=True,
        help="Dirección IP del servidor",
    )
    parser.add_argument(
        "--port", type=int, default=5555,
        help="Puerto del servidor (por defecto: 5555)",
    )
    parser.add_argument(
        "--cert-dir", default=DEFAULT_CERT_DIR,
        help="Directorio de certificados TLS",
    )
    parser.add_argument(
        "--client-id", required=True, choices=["client1", "client2", "client3"],
        help="Identificador del cliente (client1, client2 o client3)",
    )
    parser.add_argument(
        "--token", required=True,
        help="Token de autenticación (mismo que el servidor)",
    )
    return parser.parse_args()


def main() -> None:
    """Punto de entrada principal del agente cliente."""
    args = parse_args()

    # Crear contexto TLS con los certificados del cliente.
    cert_dir = Path(args.cert_dir)
    clients_dir = cert_dir / "authorized_clients"
    ssl_ctx = create_client_tls_context(
        cert_path=clients_dir / f"{args.client_id}.crt",
        key_path=clients_dir / f"{args.client_id}.key",
        ca_path=cert_dir / "ca.crt",
    )

    # Crear la aplicación Qt.
    app = QApplication(sys.argv)
    ui = ClientUI(app)

    # Crear el agente.
    agent = ClientAgent(
        host=args.host,
        port=args.port,
        ssl_context=ssl_ctx,
        auth_token=args.token,
        client_name=args.client_id,
    )

    # Event loop de asyncio.
    loop: asyncio.AbstractEventLoop | None = None

    # Conectar callbacks UI → agente.
    def on_send_chat(text: str) -> None:
        if loop:
            asyncio.run_coroutine_threadsafe(agent.send_chat_message(text), loop)

    def on_disconnect() -> None:
        if loop:
            asyncio.run_coroutine_threadsafe(agent.disconnect(), loop)

    ui.set_on_send_chat(on_send_chat)
    ui.set_on_disconnect(on_disconnect)

    # Conectar callbacks agente → UI (se ejecutarán en el hilo de asyncio,
    # se despachan al hilo de Qt mediante QTimer.singleShot).
    def on_connected(server_info: dict) -> None:
        QTimer.singleShot(0, partial(
            ui.set_connected, server_info, agent.hostname, agent.client_id or "",
        ))

    def on_disconnected() -> None:
        QTimer.singleShot(0, ui.set_disconnected)

    def on_chat_received(sender: str, message: str) -> None:
        QTimer.singleShot(0, partial(ui.show_chat_message, sender, message))

    def on_shutdown_countdown(seconds: int) -> None:
        QTimer.singleShot(0, partial(ui.show_shutdown_overlay, seconds))

    agent.on_connected(on_connected)
    agent.on_disconnected(on_disconnected)
    agent.on_chat_received(on_chat_received)
    agent.on_shutdown_countdown(on_shutdown_countdown)

    # Ejecutar asyncio en un hilo daemon.
    def run_asyncio() -> None:
        nonlocal loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(agent.run())
        except Exception:
            pass
        finally:
            loop.close()

    asyncio_thread = threading.Thread(target=run_asyncio, daemon=True)
    asyncio_thread.start()

    # Cierre limpio.
    def cleanup() -> None:
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(agent.disconnect(), loop)
            loop.call_soon_threadsafe(loop.stop)

    app.aboutToQuit.connect(cleanup)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

