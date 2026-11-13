"""Utilidades comunes: validación y sanitización de entradas.

Este módulo centraliza las funciones de validación y sanitización usadas
tanto por el servidor como por el cliente para prevenir vulnerabilidades de
seguridad como path traversal, inyección de comandos y XSS en el chat.

Las funciones implementadas aquí cubren los Requisitos 12.4, 12.5, 12.6 y 12.8
del documento de requisitos del Sistema de Monitoreo y Administración Remota.

Requisitos: 12.4, 12.5, 12.6, 12.8.
"""

from __future__ import annotations

import html
import os
import platform
import re
import socket
import threading
import time
from datetime import datetime
from typing import Callable

import psutil

# ---------------------------------------------------------------------------
# Constantes de validación
# ---------------------------------------------------------------------------

# Longitud máxima de un mensaje de chat en caracteres (Requisitos 12.6, 3.10).
MAX_CHAT_MESSAGE_LENGTH = 1000

# Longitud máxima permitida para un nombre de archivo (límite habitual de
# sistemas de ficheros tipo ext4).
MAX_FILENAME_LENGTH = 255

# Patrón de validación de dominios (Requisito 12.5):
#   - Cada etiqueta inicia y termina con un carácter alfanumérico y admite
#     guiones en su interior (hasta 63 caracteres por etiqueta).
#   - Debe existir al menos una etiqueta seguida de un punto.
#   - El TLD final debe estar compuesto únicamente por letras (mínimo 2).
# Esto permite solo caracteres alfanuméricos, guiones y puntos, rechazando
# implícitamente cualquier metacaracter de shell (";", "|", "&", "$", "`").
#
# Nota: se usa ``\Z`` en lugar de ``$`` porque ``$`` también coincide antes de
# un salto de línea final, lo que aceptaría erróneamente "example.com\n".
# ``\Z`` ancla estrictamente al final de la cadena (sin salto de línea).
DOMAIN_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\Z"
)

# Caracteres de control (0x00-0x1f) y DEL (0x7f), incluido el byte nulo, que
# deben eliminarse de los nombres de archivo recibidos (Requisito 12.4).
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Validación de dominios (Requisito 12.5)
# ---------------------------------------------------------------------------

def validate_domain(domain: str) -> bool:
    """Valida el formato de un nombre de dominio.

    Permite únicamente caracteres alfanuméricos, guiones y puntos, exigiendo
    un TLD válido de al menos 2 letras (por ejemplo, "example.com" o
    "www.ejemplo.com"). Rechaza cadenas vacías, demasiado largas (>255) o que
    contengan caracteres no permitidos, incluidos metacaracteres de shell.

    Requisito: 12.5.

    Args:
        domain: Cadena con el dominio a validar.

    Returns:
        ``True`` si el dominio tiene un formato válido, ``False`` en caso
        contrario o si el argumento no es una cadena.
    """
    # Se rechazan entradas que no sean cadenas para evitar errores en tiempo
    # de ejecución al recibir datos de la red.
    if not isinstance(domain, str):
        return False
    # Un dominio vacío o que exceda el límite de 255 caracteres es inválido.
    if not domain or len(domain) > 255:
        return False
    return DOMAIN_PATTERN.match(domain) is not None


# ---------------------------------------------------------------------------
# Sanitización de nombres de archivo (Requisito 12.4)
# ---------------------------------------------------------------------------

def sanitize_filename(filename: str) -> str:
    """Sanitiza un nombre de archivo eliminando secuencias de path traversal.

    Realiza las siguientes operaciones de seguridad:

    1. Resuelve el nombre a su *basename*, descartando cualquier componente de
       directorio y los separadores ``/`` (Requisito 12.4: "no contenga '/'").
    2. Elimina bytes nulos y caracteres de control (Requisito 12.4: "caracteres
       nulos").
    3. Rechaza referencias explícitas al directorio actual (``.``) o padre
       (``..``) que ``os.path.basename`` conserva (Requisito 12.4: "no
       contenga '..'").
    4. Limita la longitud a 255 caracteres.

    Requisito: 12.4.

    Args:
        filename: Nombre de archivo potencialmente malicioso recibido por red.

    Returns:
        Nombre de archivo seguro, o cadena vacía si tras la sanitización no
        queda contenido válido.
    """
    if not isinstance(filename, str) or not filename:
        return ""
    # Resuelve a basename: descarta rutas de directorio y separadores "/".
    filename = os.path.basename(filename)
    # Elimina bytes nulos y caracteres de control.
    filename = _CONTROL_CHARS_PATTERN.sub("", filename)
    # Rechaza referencias traversal explícitas que basename conserva.
    if filename in (".", ".."):
        return ""
    # Limita la longitud máxima del nombre de archivo.
    if len(filename) > MAX_FILENAME_LENGTH:
        filename = filename[:MAX_FILENAME_LENGTH]
    return filename


# ---------------------------------------------------------------------------
# Validación de rutas (Requisito 12.8)
# ---------------------------------------------------------------------------

def validate_path(path: str, allowed_dirs: list[str]) -> bool:
    """Valida que una ruta resuelta esté contenida en directorios permitidos.

    Resuelve la ruta a su forma absoluta canonificando enlaces simbólicos y
    secuencias ``..`` mediante :func:`os.path.realpath`, y verifica que el
    resultado se encuentre dentro de alguno de los directorios permitidos.

    La verificación de contención evita el clásico ataque por prefijo donde
    ``"/home/user"`` aceptaría erróneamente ``"/home/userevil"``: se exige que
    la ruta sea igual al directorio permitido o comience con
    ``directorio_permitido + separador``.

    Requisito: 12.8.

    Args:
        path: Ruta de archivo a validar.
        allowed_dirs: Lista de directorios permitidos (relativos o absolutos).

    Returns:
        ``True`` si la ruta resuelta está dentro de un directorio permitido,
        ``False`` en caso contrario o si los argumentos son inválidos.
    """
    if not isinstance(path, str) or not path:
        return False
    if not allowed_dirs:
        return False
    try:
        # realpath resuelve ".." y symlinks, incluso si el archivo no existe,
        # devolviendo la ruta absoluta canonificada.
        abs_path = os.path.realpath(path)
    except (OSError, ValueError):
        # ValueError se produce si la ruta contiene bytes nulos incrustados.
        return False
    for allowed_dir in allowed_dirs:
        if not isinstance(allowed_dir, str) or not allowed_dir:
            continue
        try:
            abs_allowed = os.path.realpath(allowed_dir)
        except (OSError, ValueError):
            continue
        # Contención exacta o como subdirectorio directo. El uso de
        # ``os.sep`` evita el falso positivo de un prefijo parcial.
        if abs_path == abs_allowed:
            return True
        if abs_path.startswith(abs_allowed + os.sep):
            return True
    return False


# ---------------------------------------------------------------------------
# Sanitización de mensajes de chat (Requisito 12.6)
# ---------------------------------------------------------------------------

def sanitize_chat_message(message: str) -> str:
    """Sanitiza un mensaje de chat para su visualización segura.

    Realiza dos operaciones sobre el mensaje recibido:

    1. **Trunca** el mensaje a un máximo de 1000 caracteres (Requisitos 12.6 y
       3.10).
    2. **Escapa** los caracteres especiales de HTML (``<``, ``>``, ``&``,
       ``"`` y ``'``) para prevenir ataques XSS al mostrar el mensaje en la
       interfaz (Requisito 12.6).

    El truncado se aplica primero sobre el texto original, de modo que el
    límite de 1000 caracteres se refiera al contenido del mensaje y no a la
    representación HTML escapada (cuya longitud puede crecer por la expansión
    de entidades).

    Requisito: 12.6.

    Args:
        message: Mensaje de texto recibido por el Remote_Control_Protocol.

    Returns:
        Mensaje truncado y con los caracteres HTML escapados. Cadena vacía
        si la entrada no es una cadena válida.
    """
    if not isinstance(message, str) or not message:
        return ""
    # Trunca la longitud del mensaje original a 1000 caracteres.
    if len(message) > MAX_CHAT_MESSAGE_LENGTH:
        message = message[:MAX_CHAT_MESSAGE_LENGTH]
    # Escapa caracteres especiales de HTML; ``quote=True`` incluye las comillas
    # dobles (") y simples (') además de <, > y &.
    return html.escape(message, quote=True)


# ---------------------------------------------------------------------------
# Funciones de información del sistema (Requisitos 4.3, 4.10)
# ---------------------------------------------------------------------------

def get_system_info() -> dict:
    """Devuelve información básica del sistema operativo.

    Returns:
        Diccionario con las claves ``os_name``, ``os_version`` y ``hostname``.

    Requisito: 4.3.
    """
    return {
        "os_name": platform.system(),
        "os_version": platform.version(),
        "hostname": socket.gethostname(),
    }


def get_cpu_percent() -> float:
    """Devuelve el porcentaje de uso de CPU promediado en el último intervalo.

    Usa ``psutil.cpu_percent`` con ``interval=0.1`` para obtener una lectura
    no bloqueante pero representativa.

    Returns:
        Porcentaje de uso de CPU (0.0 a 100.0).

    Requisito: 4.10.
    """
    return psutil.cpu_percent(interval=0.1)


def get_memory_percent() -> float:
    """Devuelve el porcentaje de uso de memoria RAM.

    Returns:
        Porcentaje de uso de RAM (0.0 a 100.0).

    Requisito: 4.10.
    """
    return psutil.virtual_memory().percent


# ---------------------------------------------------------------------------
# Formato de tamaños y timestamps (Requisito 4.3)
# ---------------------------------------------------------------------------

def format_bytes(size: int) -> str:
    """Convierte un tamaño en bytes a una representación legible.

    Args:
        size: Tamaño en bytes (entero no negativo).

    Returns:
        Cadena con la representación legible (ej. ``"1.23 MB"``).
    """
    if not isinstance(size, int) or size < 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}" if unit != "B" else f"{size} {unit}"
        size //= 1024
    return f"{size:.2f} PB"


def format_timestamp(dt: datetime) -> str:
    """Formatea un ``datetime`` como cadena consistente ``HH:MM:SS``.

    Args:
        dt: Objeto ``datetime`` a formatear.

    Returns:
        Cadena con formato ``HH:MM:SS`` (hora local del objeto recibido).
    """
    return dt.strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Rate Limiter - Algoritmo Token Bucket (Requisito 12.10)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Limitador de velocidad basado en el algoritmo Token Bucket.

    Permite hasta ``max_calls`` llamadas dentro de una ventana de ``period``
    segundos. Las llamadas que excedan el límite son rechazadas (devuelven
    ``False`` en lugar de bloquear), permitiendo que el llamador decida cómo
    reaccionar.

    Hilo-seguro: usa un ``threading.Lock`` para proteger el estado interno.

    Requisito: 12.10.

    Args:
        max_calls: Número máximo de llamadas permitidas por ventana.
        period: Duración de la ventana en segundos.
    """

    def __init__(self, max_calls: int, period: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls debe ser positivo")
        if period <= 0:
            raise ValueError("period debe ser positivo")
        self._max_calls = max_calls
        self._period = period
        self._tokens: float = float(max_calls)
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        """Rellena los tokens proporcionalmente al tiempo transcurrido."""
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self._max_calls / self._period)
        self._tokens = min(self._max_calls, self._tokens + new_tokens)
        self._last_refill = now

    def is_allowed(self) -> bool:
        """Intenta consumir un token. Devuelve ``True`` si la llamada está permitida.

        Returns:
            ``True`` si hay tokens disponibles (llamada permitida).
            ``False`` si no hay tokens (límite de velocidad superado).

        Requisito: 12.10.
        """
        with self._lock:
            now = time.monotonic()
            self._refill(now)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def __call__(self) -> bool:
        """Alias de ``is_allowed()`` para uso directo como callable."""
        return self.is_allowed()
