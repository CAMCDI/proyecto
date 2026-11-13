"""Módulo de protocolo de comunicación (Remote_Control_Protocol).

Define la serialización y el framing de los mensajes intercambiados entre el
servidor y los clientes sobre la conexión TLS. El protocolo es JSON basado en
texto con un prefijo de longitud binario para delimitar los frames.

Formato en el cable (Requisitos 16.1, 16.2)::

    [4 bytes: longitud del mensaje (big-endian)] [payload JSON en UTF-8]

Estructura del mensaje JSON (Requisito 16.1)::

    {"type": "command_name", "payload": {...}, "timestamp": "ISO8601"}

Este módulo cubre la Tarea 2.1: serialización, framing, lectura y límite de
tamaño. La validación contra la lista blanca de comandos se implementa en la
Tarea 2.3 (``Protocol.validate_message``).

Requisitos: 16.1, 16.2, 16.3, 16.9, 12.7.
"""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime, timezone
from enum import Enum

__all__ = [
    "MAX_MESSAGE_SIZE",
    "LENGTH_PREFIX_SIZE",
    "ProtocolError",
    "MessageType",
    "Protocol",
    "COMMAND_WHITELIST",
]

# Tamaño máximo del mensaje JSON en bytes (10 MB).
# Permite transferir frames de pantalla grandes y previene ataques de memoria.
# Requisitos: 12.7, 16.9.
MAX_MESSAGE_SIZE: int = 10 * 1024 * 1024

# Tamaño del prefijo de longitud: 4 bytes en formato big-endian.
# Requisito 16.2.
LENGTH_PREFIX_SIZE: int = 4

# Estructura ``struct`` para empaquetar/desempaquetar el prefijo de longitud.
# ``>I`` = unsigned int de 4 bytes en orden big-endian (red order).
_LENGTH_STRUCT: str = ">I"


class ProtocolError(Exception):
    """Error de protocolo durante la serialización o deserialización.

    Se eleva cuando:
      - El tamaño del mensaje excede ``MAX_MESSAGE_SIZE`` (Requisitos 12.7, 16.9).
      - El JSON recibido está malformado o no es decodificable (Requisito 16.5).
      - El tipo de mensaje proporcionado no es válido.

    Nota (Requisito 16.5): un JSON malformado eleva ``ProtocolError`` en lugar
    de cerrar la conexión. El llamador (bucle de mensajes) debe capturar la
    excepción, registrar el error en el Action_Log y continuar procesando el
    siguiente mensaje sin cerrar la conexión.
    """


class MessageType(Enum):
    """Tipos de mensaje del Remote_Control_Protocol.

    El valor de cada miembro es el nombre del comando (en snake_case) que se
    serializa en el campo ``type`` del mensaje JSON. Definir los comandos como
    un ``Enum`` evita errores tipográficos y centraliza el catálogo de mensajes
    permitidos.

    Direccionalidad (Client -> Server / Server -> Client):
    """

    # ---- Cliente -> Servidor ----
    # Saludo/autenticación inicial del cliente.
    CLIENT_HELLO = "client_hello"
    # Respuesta con métricas de CPU/RAM del cliente.
    CLIENT_METRICS = "client_metrics"
    # Frame de pantalla comprimido (JPEG en base64).
    SCREEN_FRAME = "screen_frame"
    # Mensaje de chat enviado por el cliente.
    CHAT_MESSAGE = "chat_message"
    # Bloque de un archivo en transferencia.
    FILE_CHUNK = "file_chunk"
    # Confirmación de fin de transferencia de archivo.
    FILE_COMPLETE = "file_complete"
    # Acuse de recibo genérico de un comando recibido.
    COMMAND_ACK = "command_ack"
    # Respuesta al heartbeat del servidor.
    HEARTBEAT_RESPONSE = "heartbeat_response"

    # ---- Servidor -> Cliente ----
    # Saludo/aceptación tras autenticación exitosa.
    SERVER_HELLO = "server_hello"
    # Iniciar el streaming de pantalla.
    SCREEN_START = "screen_start"
    # Detener el streaming de pantalla.
    SCREEN_STOP = "screen_stop"
    # Cambiar la resolución/parámetros del streaming.
    SCREEN_RESOLUTION = "screen_resolution"
    # Bloquear teclado y mouse del cliente.
    INPUT_LOCK = "input_lock"
    # Desbloquear teclado y mouse del cliente.
    INPUT_UNLOCK = "input_unlock"
    # Apagado remoto del cliente (con cuenta regresiva).
    SHUTDOWN = "shutdown"
    # Bloquear el acceso a un dominio web (/etc/hosts).
    WEB_BLOCK = "web_block"
    # Desbloquear el acceso a un dominio web.
    WEB_UNBLOCK = "web_unblock"
    # Deshabilitar la respuesta ICMP (denegar ping).
    ICMP_DISABLE = "icmp_disable"
    # Habilitar la respuesta ICMP (permitir ping).
    ICMP_ENABLE = "icmp_enable"
    # Solicitud/inicio de transferencia de archivo.
    FILE_REQUEST = "file_request"
    # Latido del servidor para mantener la conexión activa.
    HEARTBEAT = "heartbeat"

    @classmethod
    def from_value(cls, value: str) -> "MessageType | None":
        """Devuelve el miembro cuyo ``value`` coincide con ``value`` o ``None``.

        Útil para convertir el nombre de comando (string) leído del JSON de
        vuelta a un miembro del ``Enum``.
        """
        for member in cls:
            if member.value == value:
                return member
        return None


def _resolve_msg_type(msg_type: "str | MessageType") -> str:
    """Convierte ``msg_type`` al nombre de comando (string) usado en JSON.

    Acepta tanto un ``str`` como un miembro de ``MessageType`` para mayor
    comodidad del llamador.

    Raises:
        ProtocolError: Si ``msg_type`` no es ``str`` ni ``MessageType``.
    """
    if isinstance(msg_type, MessageType):
        return msg_type.value
    if isinstance(msg_type, str):
        return msg_type
    raise ProtocolError(
        f"Tipo de mensaje inválido: se esperaba str o MessageType, "
        f"se recibió {type(msg_type).__name__}"
    )


# Conjunto de tipos de mensaje permitidos derivado del Enum MessageType.
# Usarlo en ``Protocol.validate_message`` garantiza que la whitelist esté
# siempre sincronizada con los tipos definidos en el Enum.
# Requisitos: 16.6, 16.7, 12.2.
COMMAND_WHITELIST: frozenset[str] = frozenset(m.value for m in MessageType)


class Protocol:
    """Serialización, framing y deserialización de mensajes del protocolo.

    Todos los métodos son estáticos: la clase actúa como un espacio de nombres
    para las operaciones del protocolo y no mantiene estado.

    Atributos de clase:
        MAX_MESSAGE_SIZE: Tamaño máximo del mensaje JSON en bytes (10 MB).
        LENGTH_PREFIX_SIZE: Bytes del prefijo de longitud (4).

    Formato del frame::

        +-------------------+----------------------------------+
        | 4 bytes longitud  |    payload JSON (UTF-8)          |
        |   (big-endian)    |    de 'length' bytes             |
        +-------------------+----------------------------------+
    """

    MAX_MESSAGE_SIZE: int = MAX_MESSAGE_SIZE
    LENGTH_PREFIX_SIZE: int = LENGTH_PREFIX_SIZE

    @staticmethod
    def serialize_message(msg_type: "str | MessageType", payload: "dict | None" = None) -> bytes:
        """Serializa un mensaje a bytes con framing de 4 bytes big-endian.

        Construye el objeto JSON con los campos ``type``, ``payload`` y
        ``timestamp`` (este último se inyecta automáticamente en formato
        ISO8601 con zona horaria UTC), lo serializa a UTF-8 y le antepone un
        prefijo de 4 bytes con la longitud del contenido (big-endian).

        Args:
            msg_type: Nombre del comando (``str``) o miembro de
                ``MessageType``.
            payload: Diccionario con los datos específicos del comando. Si es
                ``None`` se usa un diccionario vacío.

        Returns:
            Los bytes del mensaje con framing: ``[4 bytes longitud][JSON]``.

        Raises:
            ProtocolError: Si el contenido serializado excede
                ``MAX_MESSAGE_SIZE`` (Requisitos 12.7, 16.9) o si ``msg_type``
                no es un tipo válido.
            TypeError: Si ``payload`` contiene objetos no serializables a JSON.

        Requisitos: 16.1, 16.2, 16.9, 12.7.
        """
        command = _resolve_msg_type(msg_type)

        # Estructura del mensaje (Requisito 16.1).
        message: dict = {
            "type": command,
            "payload": payload if payload is not None else {},
            # Inyección de timestamp en formato ISO8601 (Requisito 16.1).
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Serialización a JSON en UTF-8 (Requisito 16.1).
        json_bytes: bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")

        # Verificación del límite de tamaño (Requisitos 12.7, 16.9).
        if len(json_bytes) > Protocol.MAX_MESSAGE_SIZE:
            raise ProtocolError(
                f"El mensaje serializado excede el tamaño máximo de "
                f"{Protocol.MAX_MESSAGE_SIZE} bytes "
                f"(tamaño actual: {len(json_bytes)} bytes)."
            )

        # Prefijo de longitud: 4 bytes big-endian (Requisito 16.2).
        length_prefix: bytes = struct.pack(_LENGTH_STRUCT, len(json_bytes))
        return length_prefix + json_bytes

    @staticmethod
    async def read_message(reader: asyncio.StreamReader) -> "dict | None":
        """Lee y deserializa un mensaje con framing desde un ``StreamReader``.

        Lee primero los 4 bytes del prefijo de longitud (big-endian), luego lee
        exactamente esa cantidad de bytes como el frame JSON y lo parsea.

        Args:
            reader: ``asyncio.StreamReader`` conectado al par remoto.

        Returns:
            El diccionario con el mensaje parseado, o ``None`` si la conexión
            se cerró limpiamente (EOF) antes de completar un mensaje.

        Raises:
            ProtocolError: Si la longitud declarada excede
                ``MAX_MESSAGE_SIZE`` (Requisitos 12.7, 16.9) o si el JSON está
                malformado (Requisito 16.5). En el caso de JSON malformado, el
                llamador debe registrar el error y continuar sin cerrar la
                conexión (Requisito 16.5).

        Requisitos: 16.2, 16.3, 16.4, 16.5, 16.9, 12.7.
        """
        # 1) Leer el prefijo de longitud (4 bytes big-endian) (Requisito 16.2).
        try:
            header: bytes = await reader.readexactly(Protocol.LENGTH_PREFIX_SIZE)
        except asyncio.IncompleteReadError:
            # Conexión cerrada limpiamente antes de leer el encabezado completo.
            return None

        length: int = struct.unpack(_LENGTH_STRUCT, header)[0]

        # 2) Verificar el límite de tamaño antes de leer el cuerpo
        #    (Requisitos 12.7, 16.9).
        if length > Protocol.MAX_MESSAGE_SIZE:
            raise ProtocolError(
                f"La longitud declarada del mensaje ({length} bytes) excede el "
                f"tamaño máximo permitido ({Protocol.MAX_MESSAGE_SIZE} bytes)."
            )

        # 3) Leer exactamente `length` bytes del frame JSON (Requisito 16.3).
        try:
            frame: bytes = await reader.readexactly(length)
        except asyncio.IncompleteReadError:
            # Conexión cerrada mientras se leía el cuerpo del mensaje.
            return None

        # 4) Parsear el JSON (Requisito 16.4).
        try:
            message: dict = json.loads(frame.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # JSON malformado: descartar el mensaje sin cerrar la conexión
            # (Requisito 16.5). Se eleva ProtocolError para que el llamador lo
            # registre en el Action_Log y continúe con el siguiente mensaje.
            raise ProtocolError(f"JSON malformado en el mensaje recibido: {exc}") from exc

        return message

    @staticmethod
    def build_message(msg_type: "str | MessageType", payload: "dict | None" = None) -> dict:
        """Construye un mensaje como diccionario sin serializar a bytes.

        Útil para inspección, logging o pruebas. Inyecta el timestamp actual
        en formato ISO8601 (Requisito 16.1).

        Returns:
            Diccionario ``{"type": ..., "payload": ..., "timestamp": ...}``.

        Raises:
            ProtocolError: Si ``msg_type`` no es un tipo válido.
        """
        command = _resolve_msg_type(msg_type)
        return {
            "type": command,
            "payload": payload if payload is not None else {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def frame_payload(message: dict) -> bytes:
        """Aplica framing (prefijo de 4 bytes big-endian) a un mensaje dict.

        Serializa el diccionario a JSON UTF-8 y le antepone el prefijo de
        longitud. Útil cuando el llamador ya construyó el mensaje (por ejemplo,
        con ``timestamp`` propio) y solo necesita el framing.

        Args:
            message: Diccionario con la estructura del protocolo.

        Returns:
            Bytes ``[4 bytes longitud][JSON]``.

        Raises:
            ProtocolError: Si el contenido excede ``MAX_MESSAGE_SIZE``.
            TypeError: Si ``message`` no es serializable a JSON.

        Requisitos: 16.2, 16.9, 12.7.
        """
        json_bytes: bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(json_bytes) > Protocol.MAX_MESSAGE_SIZE:
            raise ProtocolError(
                f"El mensaje serializado excede el tamaño máximo de "
                f"{Protocol.MAX_MESSAGE_SIZE} bytes "
                f"(tamaño actual: {len(json_bytes)} bytes)."
            )
        length_prefix: bytes = struct.pack(_LENGTH_STRUCT, len(json_bytes))
        return length_prefix + json_bytes

    @staticmethod
    def validate_message(message: dict) -> bool:
        """Valida que un mensaje tenga los campos requeridos y tipo permitido.

        Verifica:
        1. Que ``message`` sea un diccionario.
        2. Que contenga los campos obligatorios ``"type"`` y ``"timestamp"``.
        3. Que el valor de ``"type"`` esté en la lista blanca de comandos
           permitidos (``COMMAND_WHITELIST``).

        Esta función no verifica la semántica del payload; solo valida que el
        mensaje tenga la estructura mínima requerida por el protocolo y que el
        tipo sea uno de los comandos reconocidos.

        Args:
            message: Diccionario a validar (normalmente el resultado de
                ``Protocol.read_message``).

        Returns:
            ``True`` si el mensaje es válido, ``False`` en caso contrario.

        Requisitos: 16.6, 16.7, 12.2.
        """
        if not isinstance(message, dict):
            return False
        # Los campos "type" y "timestamp" son obligatorios (Requisito 16.6).
        if "type" not in message or "timestamp" not in message:
            return False
        msg_type = message["type"]
        if not isinstance(msg_type, str):
            return False
        # Verificación contra la lista blanca de comandos (Requisito 16.7, 12.2).
        return msg_type in COMMAND_WHITELIST
