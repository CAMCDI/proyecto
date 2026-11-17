"""Punto de entrada del agente cliente de monitoreo remoto.

Permite inicio tanto por argumentos de linea de comandos como mediante
un dialogo grafico interactivo simple (si no se pasan argumentos).

Requisitos: 17.4, 18.4.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from common.crypto import create_client_tls_context
from client.agent import ClientAgent
from client.ui import ClientUI, ConnectDialog, STYLE_SHEET

# Buscar certificados por defecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CERT_DIR = PROJECT_ROOT / "certs"
DEFAULT_CERT_DIR = LOCAL_CERT_DIR if LOCAL_CERT_DIR.exists() else (Path.home() / ".config" / "remote-monitor" / "certs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agente Cliente de Monitoreo y Administracion Remota",
    )
    parser.add_argument(
        "--host", default=None,
        help="Direccion IP del servidor",
    )
    parser.add_argument(
        "--port", type=int, default=5555,
        help="Puerto del servidor (por defecto: 5555)",
    )
    parser.add_argument(
        "--cert-dir", default=str(DEFAULT_CERT_DIR),
        help="Directorio de certificados TLS",
    )
    parser.add_argument(
        "--client-id", default=None, choices=["client1", "client2", "client3"],
        help="Identificador del cliente (client1, client2 o client3)",
    )
    parser.add_argument(
        "--token", default=None,
        help="Token de autenticacion",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)

    host = args.host
    token = args.token
    client_id = args.client_id
    port = args.port
    cert_dir = Path(args.cert_dir)

    # Si no se pasaron argumentos requeridos por CLI, mostrar el dialogo grafico de conexion
    if not host or not token or not client_id:
        dialog = ConnectDialog(
            default_host="192.168.1." if not host else host,
            default_token="secreto123" if not token else token,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        host, token, client_id = dialog.get_values()

    # Resolver ubicacion de certificados
    if not cert_dir.exists() and LOCAL_CERT_DIR.exists():
        cert_dir = LOCAL_CERT_DIR

    clients_dir = cert_dir / "authorized_clients"
    cert_path = clients_dir / f"{client_id}.crt"
    key_path = clients_dir / f"{client_id}.key"
    ca_path = cert_dir / "ca.crt"

    if not cert_path.exists() or not key_path.exists() or not ca_path.exists():
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None, "Certificados no encontrados",
            f"No se encontraron los certificados en: {cert_dir}\n"
            "Asegurese de copiar la carpeta 'certs' generada en el servidor.",
        )
        sys.exit(1)

    ssl_ctx = create_client_tls_context(
        cert_path=cert_path,
        key_path=key_path,
        ca_path=ca_path,
    )

    # Crear interfaz grafica principal del cliente
    ui = ClientUI(app)

    # Crear agente de red
    agent = ClientAgent(
        host=host,
        port=port,
        ssl_context=ssl_ctx,
        auth_token=token,
        client_name=client_id,
    )

    loop: asyncio.AbstractEventLoop | None = None

    # Callbacks UI -> Agente
    def on_send_chat(text: str) -> None:
        if loop and agent.connected:
            asyncio.run_coroutine_threadsafe(agent.send_chat_message(text), loop)

    def on_send_file(filepath: str) -> None:
        if loop and agent.connected:
            asyncio.run_coroutine_threadsafe(agent.send_file(filepath), loop)

    def on_disconnect_req() -> None:
        if loop:
            asyncio.run_coroutine_threadsafe(agent.disconnect(), loop)

    ui.window.message_sent.connect(on_send_chat)
    ui.window.send_file_requested.connect(on_send_file)
    ui.window.disconnect_requested.connect(on_disconnect_req)

    # Callbacks Agente -> UI
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

    def on_file_received(filepath: str) -> None:
        QTimer.singleShot(0, partial(ui.notify_file_received, filepath))

    def on_input_changed(locked: bool) -> None:
        QTimer.singleShot(0, partial(ui.set_input_locked, locked))

    agent.on_connected(on_connected)
    agent.on_disconnected(on_disconnected)
    agent.on_chat_received(on_chat_received)
    agent.on_shutdown_countdown(on_shutdown_countdown)
    agent.on_file_received(on_file_received)
    agent.on_input_state_changed(on_input_changed)

    # Hilo daemon para asyncio
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

    def cleanup() -> None:
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(agent.disconnect(), loop)
            loop.call_soon_threadsafe(loop.stop)

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
