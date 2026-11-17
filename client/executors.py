"""Ejecutores de comandos recibidos del servidor.

Despacha y ejecuta los comandos enviados por el servidor al cliente.
Utiliza el helper privilegiado si esta disponible, o ejecuta las operaciones
directamente en la sesion del usuario (X11 para entrada, systemctl para energia).

Requisitos: 6.1, 7.1, 8.1, 9.1, 10.1, 13.1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from helper.privileged_helper import DEFAULT_SOCKET_PATH

__all__ = ["CommandExecutor"]

logger = logging.getLogger("client.executors")


class CommandExecutor:
    """Ejecutor de comandos del servidor con soporte de fallback directo."""

    def __init__(self, helper_socket: str = DEFAULT_SOCKET_PATH) -> None:
        self._helper_socket = helper_socket
        self._input_locked = False
        self._locked_device_ids: list[str] = []
        self._icmp_blocked = False
        self._blocked_domains: list[str] = []
        self._shutdown_task: Optional[asyncio.Task] = None

    async def _send_to_helper(self, command: str, params: dict) -> dict:
        """Intenta enviar un comando al helper privilegiado via socket UNIX."""
        try:
            reader, writer = await asyncio.open_unix_connection(self._helper_socket)
            request = json.dumps({"command": command, "params": params})
            writer.write(request.encode("utf-8") + b"\n")
            await writer.drain()

            response_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            writer.close()
            await writer.wait_closed()

            if response_line:
                return json.loads(response_line.decode("utf-8").strip())
            return {"success": False, "error": "Sin respuesta del helper"}

        except Exception as exc:
            return {"success": False, "error": f"Helper no disponible: {exc}"}

    # ------------------------------------------------------------------
    # Control de entrada (Teclado y Mouse / Touchpad)
    # ------------------------------------------------------------------

    def _get_xinput_slave_devices(self) -> list[str]:
        """Obtiene los IDs de dispositivos esclavos (teclado y puntero) con xinput."""
        if not shutil.which("xinput"):
            return []
        try:
            res = subprocess.run(
                ["xinput", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            device_ids = []
            for line in res.stdout.splitlines():
                # Coincidir lineas de slave pointer o slave keyboard
                if "slave" in line.lower() and ("pointer" in line.lower() or "keyboard" in line.lower()):
                    match = re.search(r"id=(\d+)", line)
                    if match:
                        dev_id = match.group(1)
                        # Ignorar dispositivos XTEST si es posible para no corromper el driver
                        if "xtest" not in line.lower():
                            device_ids.append(dev_id)
            # Si no encontro sin xtest, tomar todos los coincidentes
            if not device_ids:
                matches = re.findall(r"id=(\d+).*?\[slave", res.stdout)
                device_ids = matches
            return device_ids
        except Exception as exc:
            logger.error("Error consultando xinput: %s", exc)
            return []

    async def execute_input_lock(self) -> dict:
        """Bloquea teclado y mouse del cliente."""
        # Intentar primero con helper si esta activo
        result = await self._send_to_helper("lock_input", {})
        if result.get("success"):
            self._input_locked = True
            return {"action": "input_lock", "success": True, "message": "Dispositivos bloqueados (via helper)"}

        # Fallback local directo en la sesion X11
        if not shutil.which("xinput"):
            return {
                "action": "input_lock",
                "success": False,
                "message": "xinput no esta instalado en el cliente (ejecutar: sudo apt install xinput)",
            }

        dev_ids = self._get_xinput_slave_devices()
        if not dev_ids:
            return {
                "action": "input_lock",
                "success": False,
                "message": "No se detectaron dispositivos de entrada X11 para bloquear",
            }

        locked = []
        for dev_id in dev_ids:
            try:
                subprocess.run(["xinput", "disable", dev_id], capture_output=True, timeout=5)
                locked.append(dev_id)
            except Exception:
                pass

        self._locked_device_ids = locked
        self._input_locked = len(locked) > 0

        return {
            "action": "input_lock",
            "success": self._input_locked,
            "message": f"Bloqueados {len(locked)} dispositivos de entrada (teclado/mouse)",
        }

    async def execute_input_unlock(self) -> dict:
        """Desbloquea teclado y mouse del cliente."""
        result = await self._send_to_helper("unlock_input", {})
        if result.get("success"):
            self._input_locked = False
            self._locked_device_ids.clear()
            return {"action": "input_unlock", "success": True, "message": "Dispositivos desbloqueados (via helper)"}

        # Fallback local directo
        if not shutil.which("xinput"):
            self._input_locked = False
            return {"action": "input_unlock", "success": True, "message": "xinput no disponible"}

        # Habilitar los que estaban bloqueados o todos los detectados
        target_ids = self._locked_device_ids if self._locked_device_ids else self._get_xinput_slave_devices()
        for dev_id in target_ids:
            try:
                subprocess.run(["xinput", "enable", dev_id], capture_output=True, timeout=5)
            except Exception:
                pass

        self._locked_device_ids.clear()
        self._input_locked = False

        return {
            "action": "input_unlock",
            "success": True,
            "message": "Dispositivos de entrada desbloqueados correctamente",
        }

    # ------------------------------------------------------------------
    # Gestion de Energia (Apagado)
    # ------------------------------------------------------------------

    async def execute_shutdown(self, countdown: int = 30) -> dict:
        """Programa el apagado del sistema con cuenta regresiva."""
        # Cancelar tarea previa si habia una
        if self._shutdown_task and not self._shutdown_task.done():
            self._shutdown_task.cancel()

        # Intentar helper primero
        result = await self._send_to_helper("shutdown", {"countdown": countdown})
        if result.get("success"):
            return {
                "action": "shutdown",
                "success": True,
                "countdown": countdown,
                "message": f"Apagado programado en {countdown} segundos (via helper)",
            }

        # Fallback local: programar tarea asincrona que ejecute el comando de apagado al vencer
        async def _countdown_and_poweroff(delay_seconds: int) -> None:
            try:
                await asyncio.sleep(delay_seconds)
                logger.info("Cuenta regresiva terminada, ejecutando apagado del sistema...")
                for cmd in [
                    ["systemctl", "poweroff"],
                    ["poweroff"],
                    ["shutdown", "-h", "now"],
                ]:
                    try:
                        subprocess.run(cmd, check=True, capture_output=True)
                        break
                    except Exception:
                        continue
            except asyncio.CancelledError:
                logger.info("Apagado cancelado")

        self._shutdown_task = asyncio.create_task(_countdown_and_poweroff(countdown))

        return {
            "action": "shutdown",
            "success": True,
            "countdown": countdown,
            "message": f"Apagado programado en {countdown} segundos",
        }

    # ------------------------------------------------------------------
    # Control de Red (Web e ICMP)
    # ------------------------------------------------------------------

    async def execute_web_block(self, domain: str) -> dict:
        """Bloquea un dominio web."""
        result = await self._send_to_helper("block_domain", {"domain": domain})
        if result.get("success") and domain not in self._blocked_domains:
            self._blocked_domains.append(domain)
        return {
            "action": "web_block",
            "success": result.get("success", False),
            "domain": domain,
            "message": result.get("result", {}).get("message", result.get("error", "Requiere helper privilegiado")),
        }

    async def execute_web_unblock(self, domain: str) -> dict:
        """Desbloquea un dominio web."""
        result = await self._send_to_helper("unblock_domain", {"domain": domain})
        if result.get("success") and domain in self._blocked_domains:
            self._blocked_domains.remove(domain)
        return {
            "action": "web_unblock",
            "success": result.get("success", False),
            "domain": domain,
            "message": result.get("result", {}).get("message", result.get("error", "Requiere helper privilegiado")),
        }

    async def execute_icmp_disable(self) -> dict:
        """Deshabilita la respuesta ICMP (ping)."""
        result = await self._send_to_helper("disable_ping", {})
        if result.get("success"):
            self._icmp_blocked = True
        return {
            "action": "icmp_disable",
            "success": result.get("success", False),
            "message": result.get("result", {}).get("message", result.get("error", "Requiere helper privilegiado")),
        }

    async def execute_icmp_enable(self) -> dict:
        """Habilita la respuesta ICMP (ping)."""
        result = await self._send_to_helper("enable_ping", {})
        if result.get("success"):
            self._icmp_blocked = False
        return {
            "action": "icmp_enable",
            "success": result.get("success", False),
            "message": result.get("result", {}).get("message", result.get("error", "Requiere helper privilegiado")),
        }

    async def emergency_unlock(self) -> None:
        """Desbloqueo de emergencia al desconectarse."""
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
