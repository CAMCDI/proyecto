"""Gestor de conexiones del servidor: hasta 3 clientes simultáneos con TLS.

Implementa la aceptación de conexiones, autenticación mutua TLS + argon2id,
bucle de mensajes por cliente y heartbeat para detección de desconexiones.

Requisitos: 4.2, 11.4, 11.5, 11.6, 11.7, 14.6, 14.7.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from common.crypto import verify_password
from common.protocol import Protocol, ProtocolError
from common.utils import RateLimiter, get_system_info
from server.logger import ActionLogger

__all__ = ["ClientState", "ClientSession", "ConnectionManager"]

MAX_CLIENTS: int = 3
HEARTBEAT_INTERVAL: float = 3.0        # segundos entre heartbeats
HEARTBEAT_TIMEOUT: float = 10.0        # segundos sin heartbeat → desconectado
RATE_LIMIT_MAX: int = 100              # mensajes por segundo por cliente
RATE_LIMIT_VIOLATIONS_MAX: int = 3     # violaciones consecutivas antes de desconectar


class ClientState(Enum):
    """Estado de la sesión de un cliente."""
    CONNECTING = "connecting"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"


@dataclass
class ClientSession:
    """Datos de una sesión de cliente activa.

    Requisito: 4.2, 4.3, 11.8.
    """
    client_id: str
    hostname: str
    ip_address: str
    os_info: dict
    reader: Optional[asyncio.StreamReader]
    writer: Optional[asyncio.StreamWriter]
    state: ClientState = ClientState.CONNECTING
    last_heartbeat: datetime = field(default_factory=datetime.now)
    metrics: dict = field(default_factory=lambda: {"cpu_percent": 0.0, "memory_percent": 0.0})
    capabilities: dict = field(default_factory=dict)
    screen_streaming: bool = False
    screen_config: dict = field(default_factory=dict)
    active_transfers: dict = field(default_factory=dict)
    chat_history: list = field(default_factory=list)
    rate_limiter: Optional[RateLimiter] = None
    slot_index: int = -1   # posición 0-2 en el ClientPanel
    connected_at: datetime = field(default_factory=datetime.now)


class ConnectionManager:
    """Gestor de conexiones TLS del servidor.

    Acepta hasta 3 clientes simultáneos, autentica con TLS mutuo + token
    argon2id y mantiene el estado de cada sesión.

    Requisitos: 4.2, 11.4, 11.7, 14.6, 14.7.
    """

    def __init__(
        self,
        tls_context: object,
        auth_token_hash: str,
        logger: ActionLogger,
    ) -> None:
        self._tls_ctx = tls_context
        self._auth_token_hash = auth_token_hash
        self._logger = logger
        self.clients: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()
        self._message_callbacks: list[Callable[[str, dict], None]] = []
        self._server: Optional[asyncio.AbstractServer] = None

    # ------------------------------------------------------------------
    # Inicio del servidor
    # ------------------------------------------------------------------

    async def start_server(self, host: str, port: int) -> None:
        """Inicia el servidor TCP con TLS en host:port.

        Requisito: 4.2, 11.4.
        """
        self._server = await asyncio.start_server(
            self.handle_client,
            host=host,
            port=port,
            ssl=self._tls_ctx,
        )
        async with self._server:
            await self._server.serve_forever()

    # ------------------------------------------------------------------
    # Manejo de nuevas conexiones
    # ------------------------------------------------------------------

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Callback invocado por asyncio para cada nueva conexión.

        Rechaza si ya hay 3 clientes. Autentica y, si es exitoso, inicia
        el bucle de mensajes.

        Requisito: 11.4, 11.7.
        """
        peer = writer.get_extra_info("peername", ("desconocido", 0))
        ip_address = peer[0] if peer else "desconocido"

        async with self._lock:
            if len([c for c in self.clients.values() if c.state != ClientState.DISCONNECTED]) >= MAX_CLIENTS:
                # Rechazar: capacidad máxima alcanzada.
                try:
                    await Protocol.read_message(reader)  # ignorar el mensaje
                    writer.write(Protocol.serialize_message("auth_failed", {
                        "reason": "Servidor lleno (máximo 3 clientes)"
                    }))
                    await writer.drain()
                except Exception:
                    pass
                writer.close()
                return

        session = await self.authenticate_client(reader, writer, ip_address)
        if session is None:
            writer.close()
            return

        # Asignar slot y registrar.
        async with self._lock:
            used_slots = {c.slot_index for c in self.clients.values()}
            session.slot_index = next(i for i in range(3) if i not in used_slots)
            self.clients[session.client_id] = session

        self._logger.log_event(
            session.hostname, "CONEXION",
            f"Cliente conectado desde {ip_address} (slot {session.slot_index})"
        )
        self._notify_callbacks(session.client_id, {
            "type": "_internal_connected",
            "payload": {"session": session},
        })

        try:
            await self.message_loop(session)
        finally:
            await self.disconnect_client(session.client_id)

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------

    async def authenticate_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        ip_address: str,
    ) -> Optional[ClientSession]:
        """Autentica un cliente mediante TLS mutuo + token argon2id.

        Requisito: 11.4, 11.5, 11.6, 11.7.
        """
        try:
            message = await asyncio.wait_for(
                Protocol.read_message(reader), timeout=15.0
            )
        except (asyncio.TimeoutError, ProtocolError, OSError):
            return None

        if message is None or message.get("type") != "client_hello":
            return None

        payload = message.get("payload", {})
        token = payload.get("token", "")
        hostname = payload.get("hostname", ip_address)
        os_info = payload.get("os_info", {})

        # Verificar token argon2id.
        if not verify_password(token, self._auth_token_hash):
            self._logger.log_event(
                hostname, "AUTH_FALLIDA",
                f"Autenticación fallida desde {ip_address}"
            )
            try:
                writer.write(Protocol.serialize_message("auth_failed", {
                    "reason": "Token de autenticación inválido"
                }))
                await writer.drain()
            except OSError:
                pass
            return None

        client_id = str(uuid.uuid4())
        session = ClientSession(
            client_id=client_id,
            hostname=hostname,
            ip_address=ip_address,
            os_info=os_info,
            reader=reader,
            writer=writer,
            state=ClientState.AUTHENTICATED,
            rate_limiter=RateLimiter(RATE_LIMIT_MAX, 1.0),
        )

        try:
            writer.write(Protocol.serialize_message("server_hello", {
                "client_id": client_id,
                "server_info": get_system_info(),
            }))
            await writer.drain()
        except OSError:
            return None

        session.state = ClientState.ACTIVE
        return session

    # ------------------------------------------------------------------
    # Bucle de mensajes
    # ------------------------------------------------------------------

    async def message_loop(self, session: ClientSession) -> None:
        """Lee y despacha mensajes del cliente de forma continua.

        Aplica rate limiting: cierra la conexión tras 3 violaciones
        consecutivas (Requisito 12.10).
        """
        reader = session.reader
        consecutive_violations = 0

        while session.state == ClientState.ACTIVE:
            try:
                message = await asyncio.wait_for(
                    Protocol.read_message(reader), timeout=15.0
                )
            except asyncio.TimeoutError:
                # Sin actividad: comprobar heartbeat externo.
                if (datetime.now() - session.last_heartbeat).total_seconds() > HEARTBEAT_TIMEOUT:
                    break
                continue
            except (ProtocolError, OSError) as exc:
                self._logger.log_event(
                    session.hostname, "PROTOCOLO_ERROR", str(exc)
                )
                continue

            if message is None:
                break  # EOF: cliente desconectado.

            # Rate limiting (Requisito 12.10).
            if session.rate_limiter and not session.rate_limiter.is_allowed():
                consecutive_violations += 1
                self._logger.log_event(
                    session.hostname, "RATE_LIMIT",
                    f"Violación {consecutive_violations}/{RATE_LIMIT_VIOLATIONS_MAX}"
                )
                if consecutive_violations >= RATE_LIMIT_VIOLATIONS_MAX:
                    break
                continue
            else:
                consecutive_violations = 0

            if not Protocol.validate_message(message):
                continue

            # Actualizar heartbeat en mensajes de respuesta.
            if message.get("type") in ("heartbeat_response", "client_metrics"):
                session.last_heartbeat = datetime.now()

            self._notify_callbacks(session.client_id, message)

    # ------------------------------------------------------------------
    # Envío de mensajes
    # ------------------------------------------------------------------

    async def send_message(
        self,
        client_id: str,
        msg_type: str,
        payload: Optional[dict] = None,
    ) -> bool:
        """Envía un mensaje serializado al cliente especificado.

        Returns:
            ``True`` si el mensaje se envió correctamente.
        """
        session = self.clients.get(client_id)
        if not session or session.state == ClientState.DISCONNECTED or not session.writer:
            return False
        try:
            session.writer.write(Protocol.serialize_message(msg_type, payload or {}))
            await session.writer.drain()
            return True
        except (OSError, ProtocolError):
            return False

    async def broadcast_heartbeat(self) -> None:
        """Envía heartbeat a todos los clientes activos.

        Requisito: 14.6.
        """
        for client_id, session in list(self.clients.items()):
            if session.state == ClientState.ACTIVE:
                await self.send_message(client_id, "heartbeat", {})

    async def heartbeat_monitor(self) -> None:
        """Monitorea heartbeats y desconecta clientes inactivos.

        Verifica cada HEARTBEAT_INTERVAL segundos; marca como desconectado
        a los clientes sin heartbeat durante HEARTBEAT_TIMEOUT segundos.

        Requisito: 14.7.
        """
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await self.broadcast_heartbeat()
            now = datetime.now()
            for client_id, session in list(self.clients.items()):
                if session.state != ClientState.ACTIVE:
                    continue
                elapsed = (now - session.last_heartbeat).total_seconds()
                if elapsed > HEARTBEAT_TIMEOUT:
                    self._logger.log_event(
                        session.hostname, "TIMEOUT",
                        f"Sin heartbeat por {elapsed:.1f}s — desconectando"
                    )
                    await self.disconnect_client(client_id)

    async def disconnect_client(self, client_id: str) -> None:
        """Desconecta un cliente de forma ordenada.

        Requisito: 14.7.
        """
        session = self.clients.get(client_id)
        if not session or session.state == ClientState.DISCONNECTED:
            return

        session.state = ClientState.DISCONNECTED
        if session.writer:
            try:
                session.writer.close()
                await session.writer.wait_closed()
            except OSError:
                pass
            session.writer = None
            session.reader = None

        self._logger.log_event(
            session.hostname, "DESCONEXION",
            f"Cliente desconectado (slot {session.slot_index})"
        )
        self._notify_callbacks(client_id, {
            "type": "_internal_disconnected",
            "payload": {"client_id": client_id, "slot_index": session.slot_index},
        })

    # ------------------------------------------------------------------
    # Callbacks y consultas
    # ------------------------------------------------------------------

    def register_message_callback(self, callback: Callable[[str, dict], None]) -> None:
        """Registra una función a invocar con cada mensaje recibido."""
        self._message_callbacks.append(callback)

    def _notify_callbacks(self, client_id: str, message: dict) -> None:
        for cb in self._message_callbacks:
            try:
                cb(client_id, message)
            except Exception:
                pass

    def get_connected_clients(self) -> list[ClientSession]:
        """Devuelve las sesiones de clientes no desconectados."""
        return [c for c in self.clients.values() if c.state != ClientState.DISCONNECTED]

    def get_client(self, client_id: str) -> Optional[ClientSession]:
        return self.clients.get(client_id)

    async def stop(self) -> None:
        """Detiene el servidor y desconecta todos los clientes."""
        for client_id in list(self.clients):
            await self.disconnect_client(client_id)
        if self._server:
            self._server.close()
            await self._server.wait_closed()
