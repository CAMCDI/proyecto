"""Punto de entrada del servidor de administración remota.

Coordina el bucle de eventos asyncio con la interfaz gráfica PyQt6,
integrando el ConnectionManager, FileTransferHandler y ActionLogger.

El hilo principal ejecuta la aplicación Qt; un hilo daemon ejecuta el
event loop de asyncio (servidor TLS + heartbeat monitor).

Requisitos: 15.1, 17.1, 17.2, 17.3, 18.3.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
from functools import partial
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QMetaObject, Qt, Q_ARG, QTimer
from PyQt6.QtWidgets import QApplication

from common.crypto import create_server_tls_context, hash_password
from common.protocol import Protocol
from server.client_manager import ConnectionManager
from server.file_handler import FileTransferHandler
from server.logger import ActionLogger
from server.ui import MainWindow, STYLE_SHEET

__all__ = ["ServerApp"]

# Directorio de certificados por defecto.
DEFAULT_CERT_DIR: str = str(Path.home() / ".config" / "remote-monitor" / "certs")


class ServerApp:
    """Aplicación principal del servidor.

    Integra los componentes de red (asyncio) con la interfaz gráfica (PyQt6)
    de forma thread-safe.

    Requisitos: 17.1, 17.2, 17.3.
    """

    def __init__(
        self,
        host: str,
        port: int,
        cert_dir: str,
        auth_token: str,
    ) -> None:
        self._host = host
        self._port = port

        # Componentes de infraestructura.
        cert_path = Path(cert_dir)
        self._tls_ctx = create_server_tls_context(
            cert_path=cert_path / "server.crt",
            key_path=cert_path / "server.key",
            ca_path=cert_path / "ca.crt",
        )
        self._token_hash = hash_password(auth_token)
        self._logger = ActionLogger()
        self._cm = ConnectionManager(
            tls_context=self._tls_ctx,
            auth_token_hash=self._token_hash,
            logger=self._logger,
        )
        self._file_handler = FileTransferHandler(self._cm)

        # Estado del hilo asyncio.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Interfaz gráfica.
        self._app: Optional[QApplication] = None
        self._window: Optional[MainWindow] = None

    # ------------------------------------------------------------------
    # Callback de envío de comandos (Qt → asyncio)
    # ------------------------------------------------------------------

    def _send_command(self, client_id: str, msg_type: str, payload: dict) -> None:
        """Callback invocado por la UI para enviar un comando al cliente.

        Se ejecuta en el hilo de Qt; agenda la coroutine en el hilo asyncio
        mediante ``run_coroutine_threadsafe``.
        """
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
                asyncio.run_coroutine_threadsafe(
                    self._file_handler.send_file(client_id, filepath),
                    self._loop,
                )
            return

        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._cm.send_message(client_id, msg_type, payload),
                self._loop,
            )

    # ------------------------------------------------------------------
    # Callback de mensajes recibidos (asyncio → Qt)
    # ------------------------------------------------------------------

    def _on_message(self, client_id: str, message: dict) -> None:
        """Callback invocado por ConnectionManager al recibir un mensaje.

        Se ejecuta en el hilo de asyncio; despacha a la UI de forma
        thread-safe usando ``QTimer.singleShot``.
        """
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        # Rutas de transferencia de archivos.
        if msg_type == "file_chunk_ack":
            file_id = payload.get("file_id", "")
            chunk_index = payload.get("chunk_index", 0)
            self._file_handler.handle_chunk_ack(file_id, chunk_index)
            return

        if msg_type in ("file_complete", "file_accept", "file_failed"):
            file_id = payload.get("file_id", "")
            self._file_handler.handle_final_response(file_id, message)
            return

        if msg_type == "file_init":
            save_dir = str(Path.home() / "Descargas")
            asyncio.run_coroutine_threadsafe(
                self._file_handler.receive_file(client_id, payload, save_dir),
                self._loop,
            )
            return

        if msg_type == "file_chunk":
            save_dir = str(Path.home() / "Descargas")
            asyncio.run_coroutine_threadsafe(
                self._file_handler.handle_file_chunk(client_id, payload, save_dir),
                self._loop,
            )
            return

        # Despachar al hilo de Qt para actualizar la UI.
        if self._window:
            QTimer.singleShot(0, partial(self._window.handle_message, client_id, message))

    # ------------------------------------------------------------------
    # Hilo asyncio
    # ------------------------------------------------------------------

    def _run_asyncio(self) -> None:
        """Ejecuta el event loop de asyncio en un hilo daemon."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _main() -> None:
            # Registrar callback de mensajes.
            self._cm.register_message_callback(self._on_message)
            # Iniciar heartbeat monitor como tarea concurrente.
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

    # ------------------------------------------------------------------
    # Inicio y cierre
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Ejecuta la aplicación completa (Qt + asyncio).

        Returns:
            Código de salida de la aplicación Qt.
        """
        self._app = QApplication(sys.argv)
        self._app.setStyleSheet(STYLE_SHEET)
        self._app.setApplicationName("Monitor Remoto — Servidor")

        self._window = MainWindow(send_command_callback=self._send_command)
        self._window.show()

        # Iniciar el hilo de asyncio como daemon.
        self._thread = threading.Thread(target=self._run_asyncio, daemon=True)
        self._thread.start()

        self._logger.log_event(
            "SERVIDOR", "INICIO",
            f"Servidor iniciado en {self._host}:{self._port}",
        )

        # Al cerrar la ventana, detener el servidor.
        self._app.aboutToQuit.connect(self._shutdown)

        return self._app.exec()

    def _shutdown(self) -> None:
        """Detiene el servidor y el event loop de asyncio de forma ordenada."""
        self._logger.log_event("SERVIDOR", "CIERRE", "Servidor detenido")
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._cm.stop(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)


def parse_args() -> argparse.Namespace:
    """Parsea los argumentos de línea de comandos del servidor."""
    parser = argparse.ArgumentParser(
        description="Servidor de Monitoreo y Administración Remota",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Dirección de escucha (por defecto: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=5555,
        help="Puerto de escucha (por defecto: 5555)",
    )
    parser.add_argument(
        "--cert-dir", default=DEFAULT_CERT_DIR,
        help="Directorio de certificados TLS",
    )
    parser.add_argument(
        "--token", required=True,
        help="Token de autenticación para los clientes",
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

