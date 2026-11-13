"""Helper privilegiado: proceso separado que ejecuta operaciones de root.

Escucha solicitudes en un socket UNIX con permisos 600 y ejecuta
únicamente los comandos de la lista blanca definida en ``commands.py``.

El agente cliente se comunica con este helper mediante mensajes JSON
delimitados por newline a través del socket UNIX.

Protocolo del socket::

    Solicitud:  {"command": "nombre", "params": {...}}\\n
    Respuesta:  {"success": true/false, "result": {...}, "error": "..."}\\n

Requisitos: 13.1, 13.2, 13.4, 13.7.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from helper.commands import ALLOWED_COMMANDS, CommandError, execute_command

__all__ = ["PrivilegedHelper", "DEFAULT_SOCKET_PATH"]

# Ruta por defecto del socket UNIX.
DEFAULT_SOCKET_PATH: str = str(
    Path.home() / ".config" / "remote-monitor" / "helper.sock"
)

# Configuración del logger del helper.
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [HELPER] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("privileged_helper")


class PrivilegedHelper:
    """Servidor de socket UNIX para comandos privilegiados.

    Acepta conexiones del agente cliente y ejecuta los comandos de la
    lista blanca con separación de privilegios.

    Requisitos: 13.1, 13.2, 13.4.
    """

    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH) -> None:
        self._socket_path = socket_path
        self._server: asyncio.AbstractServer | None = None
        self._running = False

    async def start(self) -> None:
        """Inicia el servidor de socket UNIX.

        Crea el socket con permisos 600 (solo lectura/escritura para el
        propietario) para evitar acceso no autorizado.

        Requisito: 13.2.
        """
        # Eliminar socket anterior si existe.
        sock_path = Path(self._socket_path)
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        if sock_path.exists():
            sock_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._socket_path,
        )
        # Permisos 600 en el socket (Requisito 13.2).
        os.chmod(self._socket_path, 0o600)

        self._running = True
        logger.info("Helper privilegiado escuchando en: %s", self._socket_path)
        logger.info("Comandos disponibles: %s", list(ALLOWED_COMMANDS.keys()))

        async with self._server:
            await self._server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Maneja una conexión entrante del agente cliente.

        Lee solicitudes JSON delimitadas por newline y responde con el
        resultado de la ejecución.
        """
        peer = "cliente local"
        logger.info("Conexión recibida de %s", peer)

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # Conexión cerrada.

                try:
                    request = json.loads(line.decode("utf-8").strip())
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    response = {"success": False, "error": f"JSON inválido: {exc}"}
                    writer.write(json.dumps(response).encode("utf-8") + b"\n")
                    await writer.drain()
                    continue

                command = request.get("command", "")
                params = request.get("params", {})

                logger.info("Comando recibido: %s (params: %s)", command, params)

                try:
                    result = execute_command(command, params)
                    response = {"success": True, "result": result}
                    logger.info("Comando exitoso: %s", command)
                except CommandError as exc:
                    response = {"success": False, "error": str(exc)}
                    logger.warning("Comando fallido: %s — %s", command, exc)

                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()

        except (ConnectionResetError, BrokenPipeError):
            logger.info("Conexión cerrada por el cliente")
        except Exception as exc:
            logger.error("Error en conexión: %s", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

    async def stop(self) -> None:
        """Detiene el servidor del helper."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        # Limpiar el socket.
        sock_path = Path(self._socket_path)
        if sock_path.exists():
            sock_path.unlink()
        logger.info("Helper detenido")


async def _run_helper(socket_path: str) -> None:
    """Ejecuta el helper con manejo de señales."""
    helper = PrivilegedHelper(socket_path)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(helper.stop()))

    await helper.start()


def main() -> None:
    """Punto de entrada del helper privilegiado."""
    # Verificar que se ejecuta como root.
    if os.geteuid() != 0:
        logger.error(
            "El helper privilegiado debe ejecutarse como root.\n"
            "Uso: sudo python -m helper.privileged_helper [--socket PATH]"
        )
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser(
        description="Helper privilegiado del Sistema de Monitoreo Remoto",
    )
    parser.add_argument(
        "--socket", default=DEFAULT_SOCKET_PATH,
        help=f"Ruta del socket UNIX (por defecto: {DEFAULT_SOCKET_PATH})",
    )
    args = parser.parse_args()

    asyncio.run(_run_helper(args.socket))


if __name__ == "__main__":
    main()

