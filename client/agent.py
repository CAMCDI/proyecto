"""Agente cliente: lógica de red y despacho de comandos.

Gestiona la conexión TLS con el servidor, la autenticación con token
argon2id, el bucle de mensajes entrantes y el envío de métricas, frames
de pantalla y transferencia de archivos.

Requisitos: 4.3, 11.4, 11.7, 14.6, 14.7, 1.1, 3.1, 2.1-2.10.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import ssl
import uuid
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

METRICS_INTERVAL: float = 3.0
DEFAULT_RECEIVE_DIR: str = str(Path.home() / "Descargas")
CHUNK_SIZE: int = 64 * 1024


def _sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


class ClientAgent:
    """Agente de red del cliente de monitoreo remoto."""

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

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._client_id: Optional[str] = None
        self._server_info: dict = {}
        self._last_error: str = ""

        self._screen_capture = ScreenCapture()
        self._executor = CommandExecutor()
        self._watchdog: Optional[ConnectionWatchdog] = None

        self._on_chat_received: Optional[Callable[[str, str], None]] = None
        self._on_shutdown_countdown: Optional[Callable[[int], None]] = None
        self._on_connected: Optional[Callable[[dict], None]] = None
        self._on_disconnected: Optional[Callable[[str], None]] = None
        self._on_file_received: Optional[Callable[[str], None]] = None
        self._on_input_state_changed: Optional[Callable[[bool], None]] = None

        self._file_buffers: dict[str, dict] = {}
        self._pending_acks: dict[str, asyncio.Event] = {}
        self._pending_responses: dict[str, asyncio.Queue] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def client_id(self) -> Optional[str]:
        return self._client_id

    @property
    def hostname(self) -> str:
        return get_system_info().get("hostname", self._client_name)

    @property
    def executor(self) -> CommandExecutor:
        return self._executor

    def on_chat_received(self, callback: Callable[[str, str], None]) -> None:
        self._on_chat_received = callback

    def on_shutdown_countdown(self, callback: Callable[[int], None]) -> None:
        self._on_shutdown_countdown = callback

    def on_connected(self, callback: Callable[[dict], None]) -> None:
        self._on_connected = callback

    def on_disconnected(self, callback: Callable[[str], None]) -> None:
        self._on_disconnected = callback

    def on_file_received(self, callback: Callable[[str], None]) -> None:
        self._on_file_received = callback

    def on_input_state_changed(self, callback: Callable[[bool], None]) -> None:
        self._on_input_state_changed = callback

    # ------------------------------------------------------------------
    # Conexión y autenticación
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establece la conexión TLS con el servidor y autentica con timeout seguro."""
        logger.info("Intentando conectar al servidor en %s:%s...", self._host, self._port)
        self._last_error = ""

        try:
            # Timeout explícito de 8 segundos para evitar quedarse esperando eternamente
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._host, self._port, ssl=self._ssl_ctx,
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            self._last_error = (
                f"Tiempo de espera agotado al conectar a {self._host}:{self._port}.\n"
                "Verifique que la IP sea correcta y que el firewall del servidor permita el puerto 5555."
            )
            logger.error(self._last_error)
            return False
        except ConnectionRefusedError:
            self._last_error = (
                f"Conexion rechazada en {self._host}:{self._port}.\n"
                "El servidor no parece estar ejecutandose en esa IP o puerto."
            )
            logger.error(self._last_error)
            return False
        except ssl.SSLError as exc:
            self._last_error = f"Error de certificados TLS/SSL: {exc}"
            logger.error(self._last_error)
            return False
        except Exception as exc:
            self._last_error = f"Error de red al conectar a {self._host}:{self._port}: {exc}"
            logger.error(self._last_error)
            return False

        logger.info("Conexion TCP/TLS establecida. Enviando client_hello...")
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
            self._last_error = f"Error enviando datos iniciales: {exc}"
            logger.error(self._last_error)
            return False

        try:
            response = await asyncio.wait_for(
                Protocol.read_message(self._reader), timeout=10.0
            )
        except Exception as exc:
            self._last_error = f"Timeout esperando respuesta de autenticacion: {exc}"
            logger.error(self._last_error)
            return False

        if response is None or response.get("type") != "server_hello":
            reason = "Sin respuesta del servidor"
            if response and response.get("type") == "auth_failed":
                reason = response.get("payload", {}).get("reason", "Autenticacion fallida")
            self._last_error = f"Autenticacion rechazada: {reason}"
            logger.error(self._last_error)
            return False

        payload = response.get("payload", {})
        self._client_id = payload.get("client_id", "")
        self._server_info = payload.get("server_info", {})
        self._connected = True

        logger.info("Autenticado con exito ante el servidor '%s' (id: %s)", self.hostname, self._client_id)

        if self._on_connected:
            self._on_connected(self._server_info)

        return True

    async def run(self) -> None:
        """Ejecuta el ciclo de vida del cliente."""
        if not await self.connect():
            if self._on_disconnected:
                self._on_disconnected(self._last_error)
            return

        self._watchdog = ConnectionWatchdog(
            is_connected=lambda: self._connected,
            is_input_locked=lambda: self._executor.is_input_locked,
            emergency_unlock=self._executor.emergency_unlock,
            on_disconnect=lambda: self._on_disconnected("Conexion perdida con el servidor") if self._on_disconnected else None,
        )
        await self._watchdog.start()

        metrics_task = asyncio.create_task(self._send_metrics_loop())

        try:
            await self._message_loop()
        finally:
            metrics_task.cancel()
            if self._watchdog:
                await self._watchdog.stop()
            await self.disconnect()

    async def _message_loop(self) -> None:
        while self._connected:
            try:
                message = await asyncio.wait_for(
                    Protocol.read_message(self._reader), timeout=15.0,
                )
            except asyncio.TimeoutError:
                continue
            except (ProtocolError, OSError) as exc:
                logger.warning("Error leyendo mensaje: %s", exc)
                continue

            if message is None:
                logger.info("Conexion cerrada por el servidor")
                break

            if not Protocol.validate_message(message):
                continue

            await self._dispatch_message(message)

        self._connected = False

    async def _dispatch_message(self, message: dict) -> None:
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "file_chunk_ack":
            file_id = payload.get("file_id", "")
            chunk_idx = payload.get("chunk_index", 0)
            key = f"{file_id}:{chunk_idx}"
            ev = self._pending_acks.pop(key, None)
            if ev:
                ev.set()
            return

        if msg_type in ("file_accept", "file_complete", "file_failed"):
            file_id = payload.get("file_id", "")
            q = self._pending_responses.get(file_id)
            if q:
                q.put_nowait(message)
            return

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

    async def _handle_heartbeat(self, payload: dict) -> None:
        await self.send_message(MessageType.HEARTBEAT_RESPONSE, {})

    async def _handle_screen_start(self, payload: dict) -> None:
        quality = payload.get("quality", 70)
        fps = payload.get("fps", 8)
        resolution_list = payload.get("resolution")
        resolution = tuple(resolution_list) if resolution_list else None

        loop = asyncio.get_event_loop()

        def on_frame(frame_b64: str) -> None:
            if self._connected:
                asyncio.run_coroutine_threadsafe(
                    self.send_message(MessageType.SCREEN_FRAME, {"data": frame_b64}),
                    loop,
                )

        self._screen_capture.start(on_frame, quality=quality, fps=fps, resolution=resolution)

    async def _handle_screen_stop(self, payload: dict) -> None:
        self._screen_capture.stop()

    async def _handle_screen_resolution(self, payload: dict) -> None:
        quality = payload.get("quality")
        fps = payload.get("fps")
        resolution_list = payload.get("resolution")
        resolution = tuple(resolution_list) if resolution_list else None
        self._screen_capture.update_config(quality=quality, fps=fps, resolution=resolution)

    async def _handle_chat_message(self, payload: dict) -> None:
        message = sanitize_chat_message(payload.get("message", ""))
        sender = payload.get("sender", "Servidor")
        if self._on_chat_received and message:
            self._on_chat_received(sender, message)

    async def _handle_input_lock(self, payload: dict) -> None:
        result = await self._executor.execute_input_lock()
        await self.send_message(MessageType.COMMAND_ACK, result)
        if self._on_input_state_changed:
            self._on_input_state_changed(True)

    async def _handle_input_unlock(self, payload: dict) -> None:
        result = await self._executor.execute_input_unlock()
        await self.send_message(MessageType.COMMAND_ACK, result)
        if self._on_input_state_changed:
            self._on_input_state_changed(False)

    async def _handle_shutdown(self, payload: dict) -> None:
        countdown = payload.get("countdown", 30)
        if self._on_shutdown_countdown:
            self._on_shutdown_countdown(countdown)
        result = await self._executor.execute_shutdown(countdown)
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_web_block(self, payload: dict) -> None:
        domain = payload.get("domain", "")
        result = await self._executor.execute_web_block(domain)
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_web_unblock(self, payload: dict) -> None:
        domain = payload.get("domain", "")
        result = await self._executor.execute_web_unblock(domain)
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_icmp_disable(self, payload: dict) -> None:
        result = await self._executor.execute_icmp_disable()
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_icmp_enable(self, payload: dict) -> None:
        result = await self._executor.execute_icmp_enable()
        await self.send_message(MessageType.COMMAND_ACK, result)

    async def _handle_file_init(self, payload: dict) -> None:
        file_id = payload.get("file_id", "")
        filename = payload.get("filename", "archivo")
        total_size = payload.get("size", 0)
        checksum = payload.get("checksum", "")

        save_dir = Path(self._receive_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / (filename + ".tmp")

        self._file_buffers[file_id] = {
            "filename": filename,
            "total_size": total_size,
            "checksum": checksum,
            "received": 0,
            "path": str(save_path),
        }

        if save_path.exists():
            save_path.unlink()

        await self.send_message("file_accept", {"file_id": file_id})

    async def _handle_file_chunk(self, payload: dict) -> None:
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

        await self.send_message("file_chunk_ack", {
            "file_id": file_id, "chunk_index": chunk_index,
        })

        if is_last:
            actual = _sha256_file(buf["path"])
            final_path = Path(self._receive_dir) / buf["filename"]

            if actual == buf["checksum"]:
                Path(buf["path"]).rename(final_path)
                await self.send_message(MessageType.FILE_COMPLETE, {
                    "file_id": file_id, "filename": buf["filename"],
                })
                logger.info("Archivo recibido con exito: %s", final_path)
                if self._on_file_received:
                    self._on_file_received(str(final_path))
            else:
                Path(buf["path"]).unlink(missing_ok=True)
                await self.send_message("file_failed", {
                    "file_id": file_id, "reason": "Checksum no coincide",
                })

            del self._file_buffers[file_id]

    async def send_file(
        self,
        filepath: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        path = Path(filepath)
        if not path.is_file():
            return False

        checksum = _sha256_file(str(path))
        total_size = path.stat().st_size
        filename = path.name
        file_id = str(uuid.uuid4())

        final_queue: asyncio.Queue = asyncio.Queue()
        self._pending_responses[file_id] = final_queue

        try:
            await self.send_message("file_init", {
                "file_id": file_id,
                "filename": filename,
                "size": total_size,
                "checksum": checksum,
            })

            try:
                resp = await asyncio.wait_for(final_queue.get(), timeout=20.0)
                if resp.get("type") != "file_accept":
                    return False
            except asyncio.TimeoutError:
                return False

            chunk_index = 0
            transferred = 0

            with open(str(path), "rb") as fh:
                while True:
                    chunk_data = fh.read(CHUNK_SIZE)
                    if not chunk_data:
                        break

                    pos = fh.tell()
                    next_peek = fh.read(1)
                    fh.seek(pos)
                    is_last = (len(next_peek) == 0)

                    ack_event = asyncio.Event()
                    self._pending_acks[f"{file_id}:{chunk_index}"] = ack_event

                    encoded = base64.b64encode(chunk_data).decode("ascii")
                    await self.send_message("file_chunk", {
                        "file_id": file_id,
                        "chunk_index": chunk_index,
                        "data": encoded,
                        "is_last": is_last,
                    })

                    try:
                        await asyncio.wait_for(ack_event.wait(), timeout=25.0)
                    except asyncio.TimeoutError:
                        return False

                    transferred += len(chunk_data)
                    if progress_callback:
                        progress_callback(transferred, total_size)

                    chunk_index += 1

            try:
                final = await asyncio.wait_for(final_queue.get(), timeout=30.0)
                return final.get("type") == "file_complete"
            except asyncio.TimeoutError:
                return False

        finally:
            self._pending_responses.pop(file_id, None)

    async def send_message(self, msg_type, payload: dict | None = None) -> bool:
        if not self._connected or not self._writer:
            return False
        try:
            self._writer.write(Protocol.serialize_message(msg_type, payload or {}))
            await self._writer.drain()
            return True
        except (OSError, ProtocolError):
            return False

    async def send_chat_message(self, text: str) -> bool:
        return await self.send_message(
            MessageType.CHAT_MESSAGE,
            {"message": text, "hostname": self.hostname},
        )

    async def _send_metrics_loop(self) -> None:
        while self._connected:
            await self.send_message(MessageType.CLIENT_METRICS, {
                "cpu_percent": get_cpu_percent(),
                "memory_percent": get_memory_percent(),
            })
            await asyncio.sleep(METRICS_INTERVAL)

    async def disconnect(self) -> None:
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
            self._on_disconnected(self._last_error or "Desconectado")
