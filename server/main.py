"""Punto de entrada del servidor de administración remota.

Coordina el bucle de eventos asyncio con la interfaz gráfica PyQt6,
integrando ConnectionManager, FileTransferHandler y ActionLogger.
Diseñado para inicio rápido y uso sencillo sin comandos complejos.

Requisitos: 15.1, 17.1, 17.2, 17.3, 18.3.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from functools import partial
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from common.crypto import create_server_tls_context, hash_password
from common.protocol import Protocol
from server.client_manager import ConnectionManager
from server.file_handler import FileTransferHandler
from server.logger import ActionLogger
from server.ui import MainWindow, STYLE_SHEET

__all__ = ["ServerApp"]

# Buscar certificados en directorio local del proyecto o en ~/.config
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CERT_DIR = PROJECT_ROOT / "certs"
DEFAULT_CERT_DIR = LOCAL_CERT_DIR if LOCAL_CERT_DIR.exists() else (Path.home() / ".config" / "remote-monitor" / "certs")

# Directorio de logs
LOCAL_LOG_DIR = PROJECT_ROOT / "logs"


class ServerApp:
    """Aplicación principal del servidor."""

    def __init__(
        self,
        host: str,
        port: int,
        cert_dir: str,
        auth_token: str,
    ) -> None:
        self._host = host
        self._port = port

        cert_path = Path(cert_dir)
        if not cert_path.exists() and LOCAL_CERT_DIR.exists():
            cert_path = LOCAL_CERT_DIR

        self._tls_ctx = create_server_tls_context(
            cert_path=cert_path / "server.crt",
            key_path=cert_path / "server.key",
            ca_path=cert_path / "ca.crt",
        )
        self._token_hash = hash_password(auth_token)

        # Usar directorio de logs accesible
        log_dir = str(LOCAL_LOG_DIR) if not os.access(Path.home() / ".config", os.W_OK) else None
        self._logger = ActionLogger(log_dir)

        self._cm = ConnectionManager(
            tls_context=self._tls_ctx,
            auth_token_hash=self._token_hash,
            logger=self._logger,
        )
        self._file_handler = FileTransferHandler(self._cm)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        self._app: Optional[QApplication] = None
        self._window: Optional[MainWindow] = None

    def _send_command(self, client_id: str, msg_type: str, payload: dict) -> None:
        """Callback invocado por la UI para enviar comandos al cliente."""
        if not self._loop:
            return

        if msg_type == "_export_log":
            filepath = payload.get("filepath", "")
            if filepath:
                self._logger.export_logs(filepath)
            return

        if msg_type == "_send_file":
            filepath = payload.get("filepath", "")
            if filepath and self._loop:
                def _prog(transferred: int, total: int) -> None:
                    pct = (transferred / total * 100) if total > 0 else 0
                    info = f"{transferred // 1024} KB de {total // 1024} KB"
                    if self._window:
                        QTimer.singleShot(0, partial(self._window.files_tab.update_progress, pct, info))

                asyncio.run_coroutine_threadsafe(
                    self._file_handler.send_file(client_id, filepath, progress_callback=_prog),
                    self._loop,
                )
            return

        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._cm.send_message(client_id, msg_type, payload),
                self._loop,
            )

    def _on_message(self, client_id: str, message: dict) -> None:
        """Callback de mensajes recibidos desde los clientes."""
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "file_chunk_ack":
            file_id = payload.get("file_id", "")
            chunk_index = payload.get("chunk_index", 0)
            self._file_handler.handle_chunk_ack(file_id, chunk_index)
            return

        if msg_type in ("file_complete", "file_accept", "file_failed"):
            file_id = payload.get("file_id", "")
            self._file_handler.handle_final_response(file_id, message)
            if msg_type == "file_complete" and self._window:
                name = payload.get("filename", "archivo")
                QTimer.singleShot(0, partial(self._window.files_tab.add_log_transfer, name, "Envio", "Completado"))
            return

        if msg_type == "file_init":
            save_dir = str(Path.home() / "Descargas")
            name = payload.get("filename", "archivo")
            if self._window:
                QTimer.singleShot(0, partial(self._window.files_tab.add_log_transfer, name, "Recepcion", "Recibiendo..."))
            asyncio.run_coroutine_threadsafe(
                self._file_handler.receive_file(client_id, payload, save_dir),
                self._loop,
            )
            return

        if msg_type == "file_chunk":
            save_dir = str(Path.home() / "Descargas")
            def _prog_recv(transferred: int, total: int) -> None:
                pct = (transferred / total * 100) if total > 0 else 0
                info = f"Recibiendo: {transferred // 1024} KB de {total // 1024} KB"
                if self._window:
                    QTimer.singleShot(0, partial(self._window.files_tab.update_progress, pct, info))

            asyncio.run_coroutine_threadsafe(
                self._file_handler.handle_file_chunk(client_id, payload, save_dir, progress_callback=_prog_recv),
                self._loop,
            )
            return

        if self._window:
            QTimer.singleShot(0, partial(self._window.handle_message, client_id, message))

    def _run_asyncio(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _main() -> None:
            self._cm.register_message_callback(self._on_message)
            heartbeat_task = asyncio.create_task(self._cm.heartbeat_monitor())
            try:
                await self._cm.start_server(self._host, self._port)
            except asyncio.CancelledError:
                pass
            finally:
                heartbeat_task.cancel()

        try:
            self._loop.run_until_complete(_main())
        except Exception:
            pass
        finally:
            self._loop.close()

    def run(self) -> int:
        self._app = QApplication(sys.argv)
        self._app.setStyleSheet(STYLE_SHEET)
        self._app.setApplicationName("Monitor Remoto - Servidor")

        self._window = MainWindow(send_command_callback=self._send_command)
        self._window.show()

        self._thread = threading.Thread(target=self._run_asyncio, daemon=True)
        self._thread.start()

        self._logger.log_event(
            "SERVIDOR", "INICIO",
            f"Servidor iniciado en {self._host}:{self._port}",
        )

        self._app.aboutToQuit.connect(self._shutdown)
        return self._app.exec()

    def _shutdown(self) -> None:
        self._logger.log_event("SERVIDOR", "CIERRE", "Servidor detenido")
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._cm.stop(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Servidor de Monitoreo y Administracion Remota",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Direccion de escucha (por defecto: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=5555,
        help="Puerto de escucha (por defecto: 5555)",
    )
    parser.add_argument(
        "--cert-dir", default=str(DEFAULT_CERT_DIR),
        help="Directorio de certificados TLS (por defecto: ./certs)",
    )
    parser.add_argument(
        "--token", default="secreto123",
        help="Token de autenticacion (por defecto: secreto123)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = ServerApp(
        host=args.host,
        port=args.port,
        cert_dir=args.cert_dir,
        auth_token=args.token,
    )
    sys.exit(app.run())
