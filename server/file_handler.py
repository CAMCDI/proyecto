"""Transferencia bidireccional de archivos con verificación SHA-256.

Implementa el protocolo de transferencia de archivos en bloques de 64 KB
con verificación de integridad mediante SHA-256 en ambas direcciones
(servidor -> cliente y cliente -> servidor).

Requisitos: 2.1, 2.3, 2.4, 2.6, 2.7, 2.8, 2.9, 2.10.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

__all__ = ["TransferState", "FileTransfer", "FileTransferHandler"]

# Tamaño de cada bloque de transferencia: 64 KB (Requisito 2.4).
CHUNK_SIZE: int = 64 * 1024


class TransferState(Enum):
    """Estado de una transferencia de archivo."""
    INIT = "init"
    TRANSFERRING = "transferring"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class FileTransfer:
    """Datos de una transferencia de archivo en curso o completada.

    Requisito: 2.4, 2.7.
    """
    file_id: str
    filename: str
    direction: str               # 'send' | 'receive'
    total_size: int
    transferred_bytes: int = 0
    chunk_size: int = CHUNK_SIZE
    checksum: str = ""           # SHA-256 hex del archivo completo
    state: TransferState = TransferState.INIT
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    @property
    def progress(self) -> float:
        """Porcentaje de progreso (0.0 a 100.0)."""
        if self.total_size == 0:
            return 100.0
        return (self.transferred_bytes / self.total_size) * 100.0


def _sha256_file(filepath: str) -> str:
    """Calcula el SHA-256 de un archivo completo.

    Property 1: Para cualquier contenido de archivo, calcular SHA-256 múltiples
    veces produce el mismo hash.

    Requisito: 2.3, 2.7.
    """
    h = hashlib.sha256()
    with open(filepath, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    """Calcula SHA-256 de datos en memoria."""
    return hashlib.sha256(data).hexdigest()


class FileTransferHandler:
    """Gestor de transferencias de archivos bidireccionales.

    Coordina el envío y recepción de archivos entre el servidor y los clientes,
    manteniendo el estado de cada transferencia activa.

    Requisitos: 2.1, 2.3, 2.4, 2.6, 2.7, 2.8, 2.9, 2.10.
    """

    def __init__(self, connection_manager: object) -> None:
        """
        Args:
            connection_manager: Instancia del ``ConnectionManager`` para
                enviar mensajes a los clientes.
        """
        self._cm = connection_manager
        self._transfers: dict[str, FileTransfer] = {}
        self._pending_acks: dict[str, asyncio.Event] = {}
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._temp_files: dict[str, bytes] = {}  # file_id -> accumulated data
        self._lock = asyncio.Lock()

    def _new_transfer(
        self,
        filename: str,
        direction: str,
        total_size: int,
        checksum: str,
    ) -> FileTransfer:
        file_id = str(uuid.uuid4())
        transfer = FileTransfer(
            file_id=file_id,
            filename=filename,
            direction=direction,
            total_size=total_size,
            checksum=checksum,
        )
        self._transfers[file_id] = transfer
        return transfer

    async def send_file(
        self,
        client_id: str,
        filepath: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """Envía un archivo al cliente especificado.

        1. Calcula SHA-256 del archivo completo.
        2. Envía ``file_init`` con metadatos.
        3. Envía bloques de 64 KB esperando ACK por bloque.
        4. Espera respuesta final del cliente.

        Args:
            client_id: ID del cliente destino.
            filepath: Ruta local del archivo a enviar.
            progress_callback: Función ``(bytes_transferred, total)`` opcional.

        Returns:
            ``True`` si la transferencia se completó con éxito.

        Requisitos: 2.1, 2.3, 2.4, 2.7, 2.10.
        """
        path = Path(filepath)
        if not path.exists():
            return False

        checksum = _sha256_file(filepath)
        total_size = path.stat().st_size
        filename = path.name

        transfer = self._new_transfer(filename, "send", total_size, checksum)
        file_id = transfer.file_id

        # Configurar cola para respuesta final.
        final_queue: asyncio.Queue = asyncio.Queue()
        self._pending_responses[file_id] = final_queue

        try:
            # 1. Enviar file_init (Requisito 2.4).
            await self._cm.send_message(client_id, "file_init", {
                "file_id": file_id,
                "filename": filename,
                "size": total_size,
                "checksum": checksum,
            })

            # 2. Esperar file_accept del cliente.
            try:
                resp = await asyncio.wait_for(final_queue.get(), timeout=30.0)
                if resp.get("type") != "file_accept":
                    transfer.state = TransferState.FAILED
                    return False
            except asyncio.TimeoutError:
                transfer.state = TransferState.FAILED
                return False

            # 3. Enviar bloques (Requisito 2.4).
            transfer.state = TransferState.TRANSFERRING
            chunk_index = 0

            with open(filepath, "rb") as fh:
                while True:
                    chunk_data = fh.read(CHUNK_SIZE)
                    if not chunk_data:
                        break
                    is_last = len(chunk_data) < CHUNK_SIZE or fh.peek(1) == b""

                    # Verificar si es el último chunk
                    pos = fh.tell()
                    next_peek = fh.read(1)
                    fh.seek(pos)
                    is_last = len(next_peek) == 0

                    ack_event = asyncio.Event()
                    self._pending_acks[f"{file_id}:{chunk_index}"] = ack_event

                    encoded = base64.b64encode(chunk_data).decode("ascii")
                    await self._cm.send_message(client_id, "file_chunk", {
                        "file_id": file_id,
                        "chunk_index": chunk_index,
                        "data": encoded,
                        "is_last": is_last,
                    })

                    # Esperar ACK del bloque.
                    try:
                        await asyncio.wait_for(ack_event.wait(), timeout=30.0)
                    except asyncio.TimeoutError:
                        transfer.state = TransferState.FAILED
                        return False

                    transfer.transferred_bytes += len(chunk_data)
                    if progress_callback:
                        progress_callback(transfer.transferred_bytes, total_size)

                    chunk_index += 1

            # 4. Esperar verificación final (Requisito 2.7, 2.8, 2.9).
            transfer.state = TransferState.VERIFYING
            try:
                final = await asyncio.wait_for(final_queue.get(), timeout=60.0)
                success = final.get("type") == "file_complete"
                transfer.state = TransferState.COMPLETE if success else TransferState.FAILED
                transfer.completed_at = datetime.now()
                return success
            except asyncio.TimeoutError:
                transfer.state = TransferState.FAILED
                return False

        finally:
            self._pending_responses.pop(file_id, None)

    async def receive_file(
        self,
        client_id: str,
        file_init_payload: dict,
        save_dir: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """Recibe un archivo enviado por el cliente.

        Args:
            client_id: ID del cliente origen.
            file_init_payload: Payload del mensaje ``file_init`` recibido.
            save_dir: Directorio donde guardar el archivo.
            progress_callback: Función ``(bytes_received, total)`` opcional.

        Returns:
            ``True`` si la transferencia y verificación fueron exitosas.

        Requisitos: 2.4, 2.6, 2.7, 2.8, 2.9.
        """
        file_id = file_init_payload.get("file_id", str(uuid.uuid4()))
        filename = file_init_payload.get("filename", "unknown")
        total_size = file_init_payload.get("size", 0)
        expected_checksum = file_init_payload.get("checksum", "")

        transfer = self._new_transfer(filename, "receive", total_size, expected_checksum)
        transfer.file_id = file_id
        self._transfers[file_id] = transfer

        # Acumular datos en memoria para archivos pequeños.
        self._temp_files[file_id] = b""

        # Enviar aceptación.
        await self._cm.send_message(client_id, "file_accept", {"file_id": file_id})
        transfer.state = TransferState.TRANSFERRING

        save_path = Path(save_dir) / filename
        save_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(str(save_path) + ".tmp", "wb") as fh:
                # El progreso de escritura se manejará a través de handle_file_chunk.
                # Aquí esperamos que el caller llame a handle_file_chunk por cada bloque.
                pass
            return True  # Continúa con handle_file_chunk
        except OSError:
            transfer.state = TransferState.FAILED
            return False

    async def handle_file_chunk(
        self,
        client_id: str,
        payload: dict,
        save_dir: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """Procesa un bloque de archivo recibido.

        Requisito: 2.4, 2.5, 2.6, 2.7.
        """
        file_id = payload.get("file_id", "")
        chunk_index = payload.get("chunk_index", 0)
        encoded_data = payload.get("data", "")
        is_last = payload.get("is_last", False)

        transfer = self._transfers.get(file_id)
        if not transfer:
            return False

        try:
            chunk_data = base64.b64decode(encoded_data)
        except Exception:
            await self._cm.send_message(client_id, "file_failed", {
                "file_id": file_id,
                "reason": "Error decodificando chunk",
            })
            transfer.state = TransferState.FAILED
            return False

        # Escribir chunk al archivo temporal.
        save_path = Path(save_dir) / (transfer.filename + ".tmp")
        with open(str(save_path), "ab") as fh:
            fh.write(chunk_data)

        transfer.transferred_bytes += len(chunk_data)
        if progress_callback:
            progress_callback(transfer.transferred_bytes, transfer.total_size)

        # Enviar ACK del bloque (Requisito 2.5).
        await self._cm.send_message(client_id, "file_chunk_ack", {
            "file_id": file_id,
            "chunk_index": chunk_index,
        })

        if is_last:
            # Verificar integridad (Requisito 2.7, 2.8, 2.9).
            transfer.state = TransferState.VERIFYING
            actual_checksum = _sha256_file(str(save_path))
            final_path = Path(save_dir) / transfer.filename

            if actual_checksum == transfer.checksum:
                save_path.rename(final_path)
                transfer.state = TransferState.COMPLETE
                transfer.completed_at = datetime.now()
                await self._cm.send_message(client_id, "file_complete", {
                    "file_id": file_id,
                    "filename": transfer.filename,
                })
                return True
            else:
                # Eliminar archivo corrupto (Requisito 2.9).
                save_path.unlink(missing_ok=True)
                transfer.state = TransferState.FAILED
                transfer.completed_at = datetime.now()
                await self._cm.send_message(client_id, "file_failed", {
                    "file_id": file_id,
                    "reason": "Checksum SHA-256 no coincide",
                })
                return False

        return True

    def handle_chunk_ack(self, file_id: str, chunk_index: int) -> None:
        """Notifica que un ACK de bloque fue recibido."""
        key = f"{file_id}:{chunk_index}"
        event = self._pending_acks.pop(key, None)
        if event:
            event.set()

    def handle_final_response(self, file_id: str, message: dict) -> None:
        """Notifica una respuesta final de transferencia."""
        queue = self._pending_responses.get(file_id)
        if queue:
            queue.put_nowait(message)

    def get_active_transfers(self) -> list[FileTransfer]:
        """Devuelve las transferencias activas (no completadas ni fallidas)."""
        return [
            t for t in self._transfers.values()
            if t.state in (TransferState.INIT, TransferState.TRANSFERRING, TransferState.VERIFYING)
        ]

    def get_all_transfers(self) -> list[FileTransfer]:
        """Devuelve todas las transferencias registradas."""
        return list(self._transfers.values())

    def cancel_transfer(self, file_id: str) -> bool:
        """Cancela una transferencia activa."""
        transfer = self._transfers.get(file_id)
        if transfer and transfer.state not in (TransferState.COMPLETE, TransferState.FAILED):
            transfer.state = TransferState.FAILED
            transfer.completed_at = datetime.now()
            return True
        return False
