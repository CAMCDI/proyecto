"""Ejecutores de comandos recibidos del servidor.

Despacha y ejecuta los comandos enviados por el servidor al cliente,
delegando las operaciones privilegiadas al helper mediante un socket UNIX.

Requisitos: 6.1, 7.1, 8.1, 9.1, 10.1, 13.1.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from helper.privileged_helper import DEFAULT_SOCKET_PATH

__all__ = ["CommandExecutor"]

logger = logging.getLogger("client.executors")


class CommandExecutor:
    """Ejecutor de comandos del servidor.

    Se comunica con el helper privilegiado a través de un socket UNIX
    para las operaciones que requieren permisos de root. Las operaciones
    no privilegiadas se ejecutan directamente.

    Requisitos: 13.1, 13.4.
    """

    def __init__(self, helper_socket: str = DEFAULT_SOCKET_PATH) -> None:
        self._helper_socket = helper_socket
        self._input_locked = False
        self._icmp_blocked = False
        self._blocked_domains: list[str] = []

    async def _send_to_helper(self, command: str, params: dict) -> dict:
        """Envía un comando al helper privilegiado vía socket UNIX.

        Args:
            command: Nombre del comando de la lista blanca.
            params: Parámetros del comando.

        Returns:
            Diccionario con la respuesta del helper.

        Requisito: 13.1.
        """
        try:
            reader, writer = await asyncio.open_unix_connection(self._helper_socket)
            request = json.dumps({"command": command, "params": params})
            writer.write(request.encode("utf-8") + b"\n")
            await writer.drain()

            response_line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            writer.close()
            await writer.wait_closed()

            if response_line:
                return json.loads(response_line.decode("utf-8").strip())
            return {"success": False, "error": "Sin respuesta del helper"}

        except FileNotFoundError:
            return {"success": False, "error": "Helper no disponible (socket no encontrado)"}
        except ConnectionRefusedError:
            return {"success": False, "error": "Helper no disponible (conexión rechazada)"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Timeout esperando respuesta del helper"}
        except Exception as exc:
            return {"success": False, "error": f"Error comunicando con helper: {exc}"}

    async def execute_input_lock(self) -> dict:
        """Bloquea teclado y mouse del cliente.

        Requisito: 6.1, 6.2.
        """
        result = await self._send_to_helper("lock_input", {})
        if result.get("success"):
            self._input_locked = True
        return {"action": "input_lock", "success": result.get("success", False),
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def execute_input_unlock(self) -> dict:
        """Desbloquea teclado y mouse del cliente.

        Requisito: 7.1, 7.2.
        """
        result = await self._send_to_helper("unlock_input", {})
        if result.get("success"):
            self._input_locked = False
        return {"action": "input_unlock", "success": result.get("success", False),
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def execute_shutdown(self, countdown: int = 30) -> dict:
        """Apaga el sistema con cuenta regresiva.

        Requisito: 8.1, 8.2, 8.3.
        """
        result = await self._send_to_helper("shutdown", {"countdown": countdown})
        return {"action": "shutdown", "success": result.get("success", False),
                "countdown": countdown,
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def execute_web_block(self, domain: str) -> dict:
        """Bloquea un dominio web.

        Requisito: 9.1, 9.2.
        """
        result = await self._send_to_helper("block_domain", {"domain": domain})
        if result.get("success") and domain not in self._blocked_domains:
            self._blocked_domains.append(domain)
        return {"action": "web_block", "success": result.get("success", False),
                "domain": domain,
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def execute_web_unblock(self, domain: str) -> dict:
        """Desbloquea un dominio web.

        Requisito: 9.7, 9.8.
        """
        result = await self._send_to_helper("unblock_domain", {"domain": domain})
        if result.get("success") and domain in self._blocked_domains:
            self._blocked_domains.remove(domain)
        return {"action": "web_unblock", "success": result.get("success", False),
                "domain": domain,
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def execute_icmp_disable(self) -> dict:
        """Deshabilita la respuesta ICMP.

        Requisito: 10.1, 10.2.
        """
        result = await self._send_to_helper("disable_ping", {})
        if result.get("success"):
            self._icmp_blocked = True
        return {"action": "icmp_disable", "success": result.get("success", False),
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def execute_icmp_enable(self) -> dict:
        """Habilita la respuesta ICMP.

        Requisito: 10.6, 10.7.
        """
        result = await self._send_to_helper("enable_ping", {})
        if result.get("success"):
            self._icmp_blocked = False
        return {"action": "icmp_enable", "success": result.get("success", False),
                "message": result.get("result", {}).get("message", result.get("error", ""))}

    async def emergency_unlock(self) -> None:
        """Desbloquea los dispositivos de entrada de emergencia.

        Llamado por el watchdog cuando se pierde la conexión con el servidor.

        Requisito: 7.2.
        """
        if self._input_locked:
            await self.execute_input_unlock()

    @property
    def is_input_locked(self) -> bool:
        return self._input_locked

    @property
    def is_icmp_blocked(self) -> bool:
        return self._icmp_blocked

    @property
    def blocked_domains(self) -> list[str]:
        return list(self._blocked_domains)

