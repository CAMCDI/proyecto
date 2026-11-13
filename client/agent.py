"""Agente cliente: lógica de red y despacho de comandos.

Gestiona la conexión TLS con el servidor, la autenticación con token
argon2id, el bucle de mensajes entrantes y el envío de métricas y frames
de pantalla.

Requisitos: 4.3, 11.4, 11.7, 14.6, 14.7, 1.1, 3.1.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from common.protocol import Protocol, ProtocolError, MessageType
from common.utils import (
    get_system_info,
    get_cpu_percent,
    get_memory_percent,
    sanitize_chat_message,
)
from client.screen_capture import ScreenCapture
from client.executors import CommandExecutor
from client.watchdog import ConnectionWatchdog

__all__ = ["ClientAgent"]

logger = logging.getLogger("client.agent")

# Intervalo de envío de métricas en segundos.
METRICS_INTERVAL: float = 3.0

# Directorio de recepción de archivos por defecto.
DEFAULT_RECEIVE_DIR: str = str(Path.home() / "Descargas")


class ClientAgent:
    """Agente de red del cliente de monitoreo remoto.

    Gestiona la conexión TLS, autenticación, bucle de mensajes, envío
    de métricas y captura de pantalla.

    Requisitos: 4.3, 11.4, 11.7, 14.6.
    """

    def __init__(
        self,
        host: str,
        port: int,
        ssl_context: object,
        auth_token: str,
        client_name: str = "client1",
        receive_dir: str = DEFAULT_RECEIVE_DIR,
    ) -> None:
        self._host = host
        self._port = port
        self._ssl_ctx = ssl_context
        self._auth_token = auth_token
        self._client_name = client_name
        self._receive_dir = receive_dir

        # Estado de conexión.
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._client_id: Optional[str] = None
        self._server_info: dict = {}

        # Módulos.
        self._screen_capture = ScreenCapture()
        self._executor = CommandExecutor()
        self._watchdog: Optional[ConnectionWatchdog] = None

        # Callbacks para la UI.
        self._on_chat_received: Optional[Callable[[str, str], None]] = None
        self._on_shutdown_countdown: Optional[Callable[[int], None]] = None
        self._on_connected: Optional[Callable[[dict], None]] = None
        self._on_disconnected: Optional[Callable[[], None]] = None

        # Transferencia de archivos.
        self._file_buffers: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def client_id(self) -> Optional[str]:
        return self._client_id

    @property
    def hostname(self) -> str:
        return get_system_info().get("hostname", self._client_name)

    # ------------------------------------------------------------------
    # Registro de callbacks
    # ------------------------------------------------------------------

    def on_chat_received(self, callback: Callable[[str, str], None]) -> None:
        self._on_chat_received = callback

    def on_shutdown_countdown(self, callback: Callable[[int], None]) -> None:
        self._on_shutdown_countdown = callback

    def on_connected(self, callback: Callable[[dict], None]) -> None:
        self._on_connected = callback

    def on_disconnected(self, callback: Callable[[], None]) -> None:
        self._on_disconnected = callback

    # ------------------------------------------------------------------
    # Conexión y autenticación
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establece la conexión TLS con el servidor y autentica.

        Returns:
            ``True`` si la conexión y autenticación fueron exitosas.

        Requisitos: 11.4, 11.7.
        """
        try:
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port, ssl=self._ssl_ctx,
            )
        except (OSError, ConnectionRefusedError) as exc:
            logger.error("Error de conexión: %s", exc)
            return False

        # Enviar client_hello con token y datos del sistema.
        os_info = get_system_info()
        hello_payload = {
            "token": self._auth_token,
            "hostname": os_info.get("hostname", self._client_name),
            "os_info": os_info,
        }

        try:
            self._writer.write(
                Protocol.serialize_message(MessageType.CLIENT_HELLO, hello_payload)
            )
            await self._writer.drain()
        except OSError as exc:
            logger.error("Error enviando client_hello: %s", exc)
            return False

        # Esperar server_hello.
        try:
            response = await asyncio.wait_for(
                Protocol.read_message(self._reader), timeout=15.0
            )
        except (asyncio.TimeoutError, ProtocolError, OSError):
            logger.error("Timeout o error esperando server_hello")
            return False

        if response is None or response.get("type") != "server_hello":
            reason = "Sin respuesta"
            if response and response.get("type") == "auth_failed":
                reason = response.get("payload", {}).get("reason", "Autenticación fallida")
            logger.error("Autenticación fallida: %s", reason)
            return False

        payload = response.get("payload", {})
        self._client_id = payload.get("client_id", "")
        self._server_info = payload.get("server_info", {})
        self._connected = True

        logger.info("Conectado al servidor como '%s' (id: %s)", self.hostname, self._client_id)

        if self._on_connected:
            self._on_connected(self._server_info)

        return True

    # ------------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Ejecuta el agente: conexión, watchdog, métricas y bucle de mensajes.

        Esta es la coroutine principal que debe ejecutarse en el event loop.
        """
        if not await self.connect():
            return

        # Iniciar watchdog.
        self._watchdog = ConnectionWatchdog(
            is_connected=lambda: self._connected,
            is_input_locked=lambda: self._executor.is_input_locked,
            emergency_unlock=self._executor.emergency_unlock,
            on_disconnect=self._on_disconnected,
        )
        await self._watchdog.start()

        # Iniciar envío periódico de métricas.
        metrics_task = asyncio.create_task(self._send_metrics_loop())

        try:
            await self._message_loop()
        finally:
            metrics_task.cancel()
            if self._watchdog:
                await self._watchdog.stop()
            await self.disconnect()

    async def _message_loop(self) -> None:
        """Lee y despacha mensajes del servidor de forma continua.

        Requisito: 16.3, 16.4.
        """
        while self._connected:
            try:
                message = await asyncio.wait_for(
                    Protocol.read_message(self._reader), timeout=15.0,
                )
            except asyncio.TimeoutError:
                continue
            except (ProtocolError, OSError) as exc:
                logger.warning("Error de protocolo: %s", exc)
                continue

            if message is None:
                logger.info("Conexión cerrada por el servidor")
                break

            if not Protocol.validate_message(message):
                continue

            await self._dispatch_message(message)

        self._connected = False

    async def _dispatch_message(self, message: dict) -> None:
        """Despacha un mensaje recibido al handler correspondiente."""
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        handlers = {
            "heartbeat": self._handle_heartbeat,
            "screen_start": self._handle_screen_start,
            "screen_stop": self._handle_screen_stop,
            "screen_resolution": self._handle_screen_resolution,
            "chat_message": self._handle_chat_message,
            "input_lock": self._handle_input_lock,
            "input_unlock": self._handle_input_unlock,
            "shutdown": self._handle_shutdown,
            "web_block": self._handle_web_block,
            "web_unblock": self._handle_web_unblock,
            "icmp_disable": self._handle_icmp_disable,
            "icmp_enable": self._handle_icmp_enable,
            "file_init": self._handle_file_init,
            "file_chunk": self._handle_file_chunk,
        }

        handler = handlers.get(msg_type)
        if handler:
            try:
                await handler(payload)
            except Exception as exc:
                logger.error("Error manejando '%s': %s", msg_type, exc)

    # ------------------------------------------------------------------
    # Handlers de mensajes
    # ------------------------------------------------------------------

    async def _handle_heartbeat(self, payload: dict) -> None:
        """Responde al heartbeat del servidor. Requisito 14.6."""
        await self.send_message(MessageType.HEARTBEAT_RESPONSE, {})

    async def _handle_screen_start(self, payload: dict) -> None:
        """Inicia la captura de pantalla. Requisito 1.1."""
        quality = payload.get("quality", 70)
        fps = payload.get("fps", 8)
        resolution_list = payload.get("resolution")
        resolution = tuple(resolution_list) if resolution_list else None

        loop = asyncio.get_event_loop()

        def on_frame(frame_b64: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self.send_message(MessageType.SCREEN_FRAME, {"data": frame_b64}),
                loop,
            )

        self._screen_capture.start(on_frame, quality=quality, fps=fps, resolution=resolution)
        logger.info("Streaming de pantalla iniciado (Q=%d, FPS=%d)", quality, fps)

    async def _handle_screen_stop(self, payload: dict) -> None:
        """Detiene la captura de pantalla."""
        self._screen_capture.stop()
        logger.info("Streaming de pantalla detenido")

    async def _handle_screen_resolution(self, payload: dict) -> None:
        """Actualiza parámetros de captura. Requisito 1.6."""
        quality = payload.get("quality")
        fps = payload.get("fps")
        resolution_list = payload.get("resolution")
        resolution = tuple(resolution_list) if resolution_list else None
        self._screen_capture.update_config(quality=quality, fps=fps, resolution=resolution)

    async def _handle_chat_message(self, payload: dict) -> None:
        """Procesa un mensaje de chat del servidor. Requisito 3.1."""
        message = sanitize_chat_message(payload.get("message", ""))
        sender = payload.get("sender", "Servidor")
        if self._on_chat_received and message:
            self._on_chat_received(sender, message)

    async def _handle_input_lock(self, payload: dict) -> None:
        """Bloquea dispositivos de entrada. Requisito 6.1."""
        result = await self._executor.execute_input_lock()
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_input_unlock(self, payload: dict) -> None:
        """Desbloquea dispositivos de entrada. Requisito 7.1."""
        result = await self._executor.execute_input_unlock()
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_shutdown(self, payload: dict) -> None:
        """Apaga el sistema con cuenta regresiva. Requisito 8.1."""
        countdown = payload.get("countdown", 30)
        if self._on_shutdown_countdown:
            self._on_shutdown_countdown(countdown)
        result = await self._executor.execute_shutdown(countdown)
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_web_block(self, payload: dict) -> None:
        """Bloquea un dominio web. Requisito 9.1."""
        domain = payload.get("domain", "")
        result = await self._executor.execute_web_block(domain)
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_web_unblock(self, payload: dict) -> None:
        """Desbloquea un dominio web. Requisito 9.7."""
        domain = payload.get("domain", "")
        result = await self._executor.execute_web_unblock(domain)
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_icmp_disable(self, payload: dict) -> None:
        """Deshabilita ping. Requisito 10.1."""
        result = await self._executor.execute_icmp_disable()
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_icmp_enable(self, payload: dict) -> None:
        """Habilita ping. Requisito 10.6."""
        result = await self._executor.execute_icmp_enable()
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_file_init(self, payload: dict) -> None:
        """Inicia recepción de archivo. Requisito 2.4."""
        file_id = payload.get("file_id", "")
        filename = payload.get("filename", "unknown")
        total_size = payload.get("size", 0)
        checksum = payload.get("checksum", "")

        save_path = Path(self._receive_dir) / (filename + ".tmp")
        save_path.parent.mkdir(parents=True, exist_ok=True)

        self._file_buffers[file_id] = {
            "filename": filename,
            "total_size": total_size,
            "checksum": checksum,
            "received": 0,
            "path": str(save_path),
        }

        # Limpiar archivo temporal si existe.
        if save_path.exists():
            save_path.unlink()

        await self.send_message("file_accept", {"file_id": file_id})

    async def _handle_file_chunk(self, payload: dict) -> None:
        """Procesa un bloque de archivo. Requisito 2.4."""
        file_id = payload.get("file_id", "")
        chunk_index = payload.get("chunk_index", 0)
        data_b64 = payload.get("data", "")
        is_last = payload.get("is_last", False)

        buf = self._file_buffers.get(file_id)
        if not buf:
            return

        try:
            chunk_data = base64.b64decode(data_b64)
        except Exception:
            return

        with open(buf["path"], "ab") as fh:
            fh.write(chunk_data)
        buf["received"] += len(chunk_data)

        # ACK del bloque.
        await self.send_message("file_chunk_ack", {
            "file_id": file_id, "chunk_index": chunk_index,
        })

        if is_last:
            # Verificar SHA-256. Requisito 2.7.
            import hashlib
            h = hashlib.sha256()
            with open(buf["path"], "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            actual = h.hexdigest()

            final_path = Path(self._receive_dir) / buf["filename"]
            if actual == buf["checksum"]:
                Path(buf["path"]).rename(final_path)
                await self.send_message(MessageType.FILE_COMPLETE, {
                    "file_id": file_id, "filename": buf["filename"],
                })
                logger.info("Archivo recibido: %s", buf["filename"])
            else:
                Path(buf["path"]).unlink(missing_ok=True)
                await self.send_message("file_failed", {
                    "file_id": file_id, "reason": "Checksum no coincide",
                })
                logger.warning("Archivo corrupto: %s", buf["filename"])

            del self._file_buffers[file_id]

    # ------------------------------------------------------------------
    # Envío de mensajes y métricas
    # ------------------------------------------------------------------

    async def send_message(self, msg_type, payload: dict | None = None) -> bool:
        """Envía un mensaje al servidor.

        Returns:
            ``True`` si el envío fue exitoso.
        """
        if not self._connected or not self._writer:
            return False
        try:
            self._writer.write(Protocol.serialize_message(msg_type, payload or {}))
            await self._writer.drain()
            return True
        except (OSError, ProtocolError):
            return False

    async def send_chat_message(self, text: str) -> bool:
        """Envía un mensaje de chat al servidor. Requisito 3.1."""
        return await self.send_message(
            MessageType.CHAT_MESSAGE,
            {"message": text, "hostname": self.hostname},
        )

    async def _send_metrics_loop(self) -> None:
        """Envía métricas de CPU y RAM periódicamente. Requisito 4.10."""
        while self._connected:
            await self.send_message(MessageType.CLIENT_METRICS, {
                "cpu_percent": get_cpu_percent(),
                "memory_percent": get_memory_percent(),
            })
            await asyncio.sleep(METRICS_INTERVAL)

    # ------------------------------------------------------------------
    # Desconexión
    # ------------------------------------------------------------------

    async def disconnect(self) -> None:
        """Desconecta del servidor de forma ordenada."""
        self._connected = False
        self._screen_capture.stop()

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None
            self._reader = None

        if self._on_disconnected:
            self._on_disconnected()

        logger.info("Desconectado del servidor")

