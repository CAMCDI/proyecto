"""Definición y validación de comandos privilegiados (lista blanca).

Define los comandos que el helper privilegiado acepta ejecutar y las
funciones de validación de parámetros para cada uno. Solo se aceptan
los comandos enumerados en ``ALLOWED_COMMANDS`` con validación estricta
que rechaza metacaracteres de shell.

Principio de menor privilegio: cada comando tiene una función de ejecución
específica que invoca únicamente los binarios necesarios con los argumentos
exactos requeridos, sin pasar por un shell.

Requisitos: 13.1, 13.4, 13.7, 12.5.
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable

__all__ = [
    "CommandError",
    "ALLOWED_COMMANDS",
    "execute_command",
    "cmd_shutdown",
    "cmd_block_domain",
    "cmd_unblock_domain",
    "cmd_disable_ping",
    "cmd_enable_ping",
    "cmd_lock_input",
    "cmd_unlock_input",
]

# Patrón para validar dominios (mismo que en common/utils.py).
_DOMAIN_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\Z"
)

# Patrón para detectar metacaracteres de shell peligrosos.
_SHELL_META_PATTERN = re.compile(r"[;&|`$(){}\\'\"\n\r]")

# Línea que se agrega a /etc/hosts para bloquear un dominio.
_HOSTS_REDIRECT = "127.0.0.1"

# Marcador para identificar entradas gestionadas por el sistema.
_HOSTS_MARKER = "# remote-monitor-block"


class CommandError(Exception):
    """Error al ejecutar o validar un comando privilegiado."""


# ---------------------------------------------------------------------------
# Funciones de validación
# ---------------------------------------------------------------------------

def _validate_domain(domain: str) -> bool:
    """Valida que un dominio tenga formato correcto y no contenga metacaracteres."""
    if not isinstance(domain, str) or not domain:
        return False
    if len(domain) > 255:
        return False
    if _SHELL_META_PATTERN.search(domain):
        return False
    return _DOMAIN_PATTERN.match(domain) is not None


def _validate_countdown(seconds: int) -> bool:
    """Valida que la cuenta regresiva esté en rango razonable (1-600)."""
    return isinstance(seconds, int) and 1 <= seconds <= 600


# ---------------------------------------------------------------------------
# Implementación de comandos
# ---------------------------------------------------------------------------

def cmd_shutdown(params: dict) -> dict:
    """Apaga el sistema con cuenta regresiva.

    Usa ``shutdown`` con el parámetro ``+minutos`` calculado desde los
    segundos proporcionados.

    Requisito: 8.1, 8.2, 8.3.
    """
    seconds = params.get("countdown", 30)
    if not _validate_countdown(seconds):
        raise CommandError(f"Cuenta regresiva inválida: {seconds}")

    minutes = max(1, seconds // 60)
    try:
        subprocess.run(
            ["shutdown", "+{}".format(minutes), "Apagado remoto por administrador"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return {"success": True, "message": f"Apagado programado en {minutes} minuto(s)"}
    except subprocess.CalledProcessError as exc:
        raise CommandError(f"Error ejecutando shutdown: {exc.stderr.decode()}") from exc


def cmd_block_domain(params: dict) -> dict:
    """Bloquea un dominio web agregando una entrada a /etc/hosts.

    Requisito: 9.1, 9.2, 9.3.
    """
    domain = params.get("domain", "")
    if not _validate_domain(domain):
        raise CommandError(f"Dominio inválido: {domain}")

    entry = f"{_HOSTS_REDIRECT} {domain} {_HOSTS_MARKER}\n"
    try:
        with open("/etc/hosts", "r", encoding="utf-8") as fh:
            content = fh.read()
        if f"{_HOSTS_REDIRECT} {domain}" in content:
            return {"success": True, "message": f"Dominio ya bloqueado: {domain}"}
        with open("/etc/hosts", "a", encoding="utf-8") as fh:
            fh.write(entry)
        return {"success": True, "message": f"Dominio bloqueado: {domain}"}
    except OSError as exc:
        raise CommandError(f"Error escribiendo /etc/hosts: {exc}") from exc


def cmd_unblock_domain(params: dict) -> dict:
    """Desbloquea un dominio web eliminando su entrada de /etc/hosts.

    Requisito: 9.7, 9.8.
    """
    domain = params.get("domain", "")
    if not _validate_domain(domain):
        raise CommandError(f"Dominio inválido: {domain}")

    try:
        with open("/etc/hosts", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        new_lines = [
            line for line in lines
            if not (domain in line and _HOSTS_MARKER in line)
        ]
        with open("/etc/hosts", "w", encoding="utf-8") as fh:
            fh.writelines(new_lines)
        return {"success": True, "message": f"Dominio desbloqueado: {domain}"}
    except OSError as exc:
        raise CommandError(f"Error modificando /etc/hosts: {exc}") from exc


def cmd_disable_ping(params: dict) -> dict:
    """Deshabilita la respuesta ICMP (ping) mediante sysctl.

    Requisito: 10.1, 10.2.
    """
    try:
        subprocess.run(
            ["sysctl", "-w", "net.ipv4.icmp_echo_ignore_all=1"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return {"success": True, "message": "Respuesta ICMP deshabilitada"}
    except subprocess.CalledProcessError as exc:
        raise CommandError(f"Error ejecutando sysctl: {exc.stderr.decode()}") from exc


def cmd_enable_ping(params: dict) -> dict:
    """Habilita la respuesta ICMP (ping) mediante sysctl.

    Requisito: 10.6, 10.7.
    """
    try:
        subprocess.run(
            ["sysctl", "-w", "net.ipv4.icmp_echo_ignore_all=0"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return {"success": True, "message": "Respuesta ICMP habilitada"}
    except subprocess.CalledProcessError as exc:
        raise CommandError(f"Error ejecutando sysctl: {exc.stderr.decode()}") from exc


def cmd_lock_input(params: dict) -> dict:
    """Bloquea teclado y mouse mediante xinput.

    Requisito: 6.1, 6.2.
    """
    try:
        result = subprocess.run(
            ["xinput", "list", "--id-only"],
            capture_output=True, text=True, timeout=10,
        )
        device_ids = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        for dev_id in device_ids:
            subprocess.run(
                ["xinput", "disable", dev_id],
                capture_output=True, timeout=10,
            )
        return {"success": True, "message": "Dispositivos de entrada bloqueados",
                "device_ids": device_ids}
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise CommandError(f"Error bloqueando entrada: {exc}") from exc


def cmd_unlock_input(params: dict) -> dict:
    """Desbloquea teclado y mouse mediante xinput.

    Requisito: 7.1, 7.2.
    """
    try:
        result = subprocess.run(
            ["xinput", "list", "--id-only"],
            capture_output=True, text=True, timeout=10,
        )
        device_ids = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        for dev_id in device_ids:
            subprocess.run(
                ["xinput", "enable", dev_id],
                capture_output=True, timeout=10,
            )
        return {"success": True, "message": "Dispositivos de entrada desbloqueados"}
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise CommandError(f"Error desbloqueando entrada: {exc}") from exc


# ---------------------------------------------------------------------------
# Registro de comandos permitidos (lista blanca)
# ---------------------------------------------------------------------------

ALLOWED_COMMANDS: dict[str, Callable[[dict], dict]] = {
    "shutdown": cmd_shutdown,
    "block_domain": cmd_block_domain,
    "unblock_domain": cmd_unblock_domain,
    "disable_ping": cmd_disable_ping,
    "enable_ping": cmd_enable_ping,
    "lock_input": cmd_lock_input,
    "unlock_input": cmd_unlock_input,
}


def execute_command(command: str, params: dict) -> dict:
    """Ejecuta un comando de la lista blanca con los parámetros dados.

    Args:
        command: Nombre del comando (debe estar en ``ALLOWED_COMMANDS``).
        params: Diccionario con los parámetros del comando.

    Returns:
        Diccionario con el resultado de la ejecución.

    Raises:
        CommandError: Si el comando no está en la lista blanca o falla.

    Requisito: 13.1, 13.4, 13.7.
    """
    handler = ALLOWED_COMMANDS.get(command)
    if handler is None:
        raise CommandError(
            f"Comando no permitido: '{command}'. "
            f"Comandos válidos: {list(ALLOWED_COMMANDS.keys())}"
        )
    return handler(params)

