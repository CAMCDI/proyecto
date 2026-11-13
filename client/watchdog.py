"""Watchdog de seguridad: desbloqueo automático ante desconexión.

Monitorea el estado de la conexión con el servidor. Si se detecta una
desconexión mientras los dispositivos de entrada están bloqueados, ejecuta
un desbloqueo de emergencia para evitar dejar al usuario sin control del
equipo.

Requisitos: 7.2, 14.8.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

__all__ = ["ConnectionWatchdog"]

logger = logging.getLogger("client.watchdog")

# Intervalo de verificación del watchdog en segundos.
WATCHDOG_INTERVAL: float = 5.0

# Tiempo máximo sin heartbeat antes de considerar la conexión perdida.
WATCHDOG_TIMEOUT: float = 15.0


class ConnectionWatchdog:
    """Monitor de conexión con desbloqueo automático de emergencia.

    Verifica periódicamente que la conexión con el servidor esté activa.
    Si se pierde la conexión y los dispositivos de entrada están bloqueados,
    ejecuta un desbloqueo de emergencia.

    Requisitos: 7.2, 14.8.
    """

    def __init__(
        self,
        is_connected: Callable[[], bool],
        is_input_locked: Callable[[], bool],
        emergency_unlock: Callable[[], asyncio.coroutines],
        on_disconnect: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Args:
            is_connected: Función que devuelve ``True`` si la conexión está activa.
            is_input_locked: Función que devuelve ``True`` si la entrada está bloqueada.
            emergency_unlock: Coroutine que ejecuta el desbloqueo de emergencia.
            on_disconnect: Callback opcional invocado al detectar desconexión.
        """
        self._is_connected = is_connected
        self._is_input_locked = is_input_locked
        self._emergency_unlock = emergency_unlock
        self._on_disconnect = on_disconnect
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Inicia el watchdog como tarea asíncrona."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Watchdog de conexión iniciado (intervalo: %.1fs)", WATCHDOG_INTERVAL)

    async def stop(self) -> None:
        """Detiene el watchdog."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Watchdog de conexión detenido")

    async def _monitor_loop(self) -> None:
        """Bucle principal del watchdog.

        Verifica periódicamente el estado de la conexión y ejecuta el
        desbloqueo de emergencia si es necesario.

        Requisito: 14.8.
        """
        while self._running:
            await asyncio.sleep(WATCHDOG_INTERVAL)

            if not self._is_connected():
                logger.warning("Conexión perdida detectada por el watchdog")

                # Desbloqueo de emergencia si la entrada está bloqueada (Req 7.2).
                if self._is_input_locked():
                    logger.warning("Entrada bloqueada — ejecutando desbloqueo de emergencia")
                    try:
                        await self._emergency_unlock()
                        logger.info("Desbloqueo de emergencia completado")
                    except Exception as exc:
                        logger.error("Error en desbloqueo de emergencia: %s", exc)

                # Notificar desconexión.
                if self._on_disconnect:
                    try:
                        self._on_disconnect()
                    except Exception:
                        pass

                # Esperar antes de volver a verificar.
                await asyncio.sleep(WATCHDOG_TIMEOUT)

    @property
    def is_running(self) -> bool:
        return self._running

