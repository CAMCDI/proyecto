"""Registro de auditoría de acciones del servidor (Action_Log).

Implementa el registro de todas las acciones ejecutadas por el servidor
sobre los clientes: conexiones, desconexiones, comandos enviados, transferencias
de archivos, cambios de red y energía.

Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["LogEntry", "ActionLogger"]

# Tamaño máximo del caché en memoria (Requisito 5.3).
MAX_CACHE_SIZE: int = 500

# Directorio de logs por defecto.
DEFAULT_LOG_DIR: str = str(Path.home() / ".config" / "remote-monitor" / "logs")


@dataclass
class LogEntry:
    """Entrada individual del Action_Log.

    Attributes:
        timestamp: Momento en que se registró el evento.
        client_hostname: Hostname del cliente involucrado.
        action_type: Tipo de acción (ej. 'CONEXION', 'SCREEN_START', etc.).
        description: Descripción legible del evento.
    """
    timestamp: datetime
    client_hostname: str
    action_type: str
    description: str

    def format(self) -> str:
        """Devuelve la representación textual de la entrada.

        Formato: ``[YYYY-MM-DD HH:MM:SS] [Cliente: hostname] [ACTION] Description``

        Requisito: 5.2.
        """
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"[{ts}] [Cliente: {self.client_hostname}] "
            f"[{self.action_type}] {self.description}"
        )


class ActionLogger:
    """Registrador de auditoría de acciones del servidor.

    Mantiene un caché en memoria de las últimas 500 entradas y escribe
    cada evento en un archivo de log diario con rotación automática.

    Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5.
    """

    def __init__(self, log_dir: Optional[str] = None) -> None:
        self._log_dir = Path(log_dir or DEFAULT_LOG_DIR)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._cache: list[LogEntry] = []
        self._lock = asyncio.Lock()

    def _log_file_path(self, date: datetime) -> Path:
        """Ruta del archivo de log para la fecha dada."""
        return self._log_dir / f"action_log_{date.strftime('%Y%m%d')}.txt"

    def _write_to_file(self, entry: LogEntry) -> None:
        """Escribe una entrada al archivo de log del día actual."""
        path = self._log_file_path(entry.timestamp)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(entry.format() + "\n")
        except OSError:
            # No interrumpir operación si el log no puede escribirse.
            pass

    def log_event(self, client_hostname: str, action: str, description: str) -> LogEntry:
        """Registra un evento en el log.

        Agrega la entrada al caché en memoria (hasta 500 entradas) y la
        persiste en el archivo de log diario.

        Args:
            client_hostname: Hostname del cliente.
            action: Tipo de acción (preferiblemente en MAYÚSCULAS).
            description: Descripción legible del evento.

        Returns:
            La ``LogEntry`` creada.

        Requisitos: 5.1, 5.2, 5.3.
        """
        entry = LogEntry(
            timestamp=datetime.now(),
            client_hostname=client_hostname,
            action_type=action,
            description=description,
        )
        # Mantener caché con límite de 500 entradas.
        if len(self._cache) >= MAX_CACHE_SIZE:
            self._cache.pop(0)
        self._cache.append(entry)
        self._write_to_file(entry)
        return entry

    async def async_log_event(
        self, client_hostname: str, action: str, description: str
    ) -> LogEntry:
        """Versión asíncrona thread-safe de ``log_event``."""
        async with self._lock:
            return self.log_event(client_hostname, action, description)

    def get_recent_logs(self, count: int) -> list[LogEntry]:
        """Devuelve las ``count`` entradas más recientes del caché.

        Requisito: 5.4.
        """
        return list(self._cache[-count:])

    def filter_logs(
        self,
        client: Optional[str] = None,
        action_type: Optional[str] = None,
    ) -> list[LogEntry]:
        """Filtra las entradas del caché.

        Args:
            client: Si se proporciona, filtra por hostname del cliente.
            action_type: Si se proporciona, filtra por tipo de acción.

        Returns:
            Lista de entradas que coinciden con los filtros.

        Requisito: 5.5.
        """
        result = self._cache
        if client:
            result = [e for e in result if e.client_hostname == client]
        if action_type:
            result = [e for e in result if e.action_type == action_type]
        return list(result)

    def export_logs(self, filepath: str) -> None:
        """Exporta todas las entradas del caché a un archivo de texto.

        Args:
            filepath: Ruta del archivo destino.

        Requisito: 5.5.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for entry in self._cache:
                fh.write(entry.format() + "\n")

    def get_all_clients(self) -> list[str]:
        """Devuelve la lista de hostnames únicos en el caché."""
        return list({e.client_hostname for e in self._cache})

    def get_all_action_types(self) -> list[str]:
        """Devuelve la lista de tipos de acción únicos en el caché."""
        return list({e.action_type for e in self._cache})

    def clear_cache(self) -> None:
        """Limpia el caché en memoria (no elimina archivos de log)."""
        self._cache.clear()
