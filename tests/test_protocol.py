"""Tests unitarios para common/protocol.py (Tarea 2.1).

Cubren la serialización con framing de 4 bytes big-endian, la inyección de
timestamp ISO8601, la lectura asíncrona de mensajes con framing y la
aplicación del límite de tamaño de 10 MB.

Las pruebas basadas en propiedades (Hypothesis) se añaden en la Tarea 2.2;
aquí se validan ejemplos concretos y casos límite.

Requisitos: 16.1, 16.2, 16.3, 16.9.
"""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from common.protocol import (
    LENGTH_PREFIX_SIZE,
    MAX_MESSAGE_SIZE,
    MessageType,
    Protocol,
    ProtocolError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feed_reader(data: bytes) -> asyncio.StreamReader:
    """Crea un StreamReader y le alimenta `data` seguido de EOF.

    Permite probar ``Protocol.read_message`` sin abrir sockets reales.
    """
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


# ---------------------------------------------------------------------------
# serialize_message
# ---------------------------------------------------------------------------

class TestSerializeMessage:
    """Pruebas de serialización y framing (Requisitos 16.1, 16.2, 16.9)."""

    def test_produce_prefijo_longitud_big_endian(self):
        """El prefijo son 4 bytes big-endian con la longitud del JSON (16.2)."""
        framed = Protocol.serialize_message("chat_message", {"message": "hola"})

        # El frame debe tener al menos el prefijo + algo de JSON.
        assert len(framed) > LENGTH_PREFIX_SIZE

        length = struct.unpack(">I", framed[:LENGTH_PREFIX_SIZE])[0]
        json_bytes = framed[LENGTH_PREFIX_SIZE:]

        # La longitud declarada coincide con la del contenido JSON.
        assert length == len(json_bytes)

    def test_estructura_json_contiene_type_payload_timestamp(self):
        """El JSON serializado tiene type, payload y timestamp (16.1)."""
        framed = Protocol.serialize_message("chat_message", {"message": "hola"})
        message = json.loads(framed[LENGTH_PREFIX_SIZE:].decode("utf-8"))

        assert message["type"] == "chat_message"
        assert message["payload"] == {"message": "hola"}
        assert "timestamp" in message and isinstance(message["timestamp"], str)

    def test_timestamp_es_iso8601(self):
        """El timestamp inyectado tiene formato ISO8601 (16.1)."""
        framed = Protocol.serialize_message("heartbeat")
        message = json.loads(framed[LENGTH_PREFIX_SIZE:].decode("utf-8"))

        # fromisoformat lanza ValueError si el formato no es ISO8601 válido.
        # Se acepta el sufijo 'Z'/offset de zona horaria.
        ts = message["timestamp"]
        # datetime.fromisoformat soporta offsets desde Python 3.11.
        import datetime as _dt
        _dt.datetime.fromisoformat(ts)

    def test_acepta_enum_como_tipo_de_mensaje(self):
        """Se puede usar un miembro de MessageType como msg_type."""
        framed = Protocol.serialize_message(MessageType.SCREEN_FRAME, {"data": "abc"})
        message = json.loads(framed[LENGTH_PREFIX_SIZE:].decode("utf-8"))
        assert message["type"] == "screen_frame"

    def test_payload_none_se_convierte_en_diccionario_vacio(self):
        """Si payload es None se usa un diccionario vacío."""
        framed = Protocol.serialize_message("heartbeat", None)
        message = json.loads(framed[LENGTH_PREFIX_SIZE:].decode("utf-8"))
        assert message["payload"] == {}

    def test_tipo_invalido_lanza_protocol_error(self):
        """Un tipo que no es str ni MessageType eleva ProtocolError."""
        with pytest.raises(ProtocolError):
            Protocol.serialize_message(123, {})  # type: ignore[arg-type]

    def test_payload_no_serializable_lanza_type_error(self):
        """Un payload con objetos no JSON-serializables lanza TypeError."""
        with pytest.raises(TypeError):
            Protocol.serialize_message("chat_message", {"obj": object()})


# ---------------------------------------------------------------------------
# Límite de tamaño (16.9, 12.7)
# ---------------------------------------------------------------------------

class TestSizeLimit:
    """Pruebas del límite de 10 MB (Requisitos 16.9, 12.7)."""

    def test_constantes_tienen_valores_esperados(self):
        """El límite es 10 MB y el prefijo 4 bytes."""
        assert MAX_MESSAGE_SIZE == 10 * 1024 * 1024
        assert LENGTH_PREFIX_SIZE == 4

    def test_mensaje_cerca_del_limite_se_serializa(self):
        """Un mensaje justo por debajo del límite se serializa correctamente."""
        # JSON {"type": "x", "payload": {"d": "..."}, "timestamp": "..."}
        # Aproximar el tamaño rellenando el payload con una cadena.
        overhead = 200  # margen para type/timestamp/estructura JSON
        target = MAX_MESSAGE_SIZE - overhead
        big_payload = {"d": "a" * target}
        framed = Protocol.serialize_message("screen_frame", big_payload)
        json_len = struct.unpack(">I", framed[:4])[0]
        assert json_len <= MAX_MESSAGE_SIZE

    def test_mensaje_que_excede_el_limite_lanza_protocol_error(self):
        """Un mensaje mayor a 10 MB eleva ProtocolError (16.9, 12.7)."""
        # Payload lo suficientemente grande para superar el límite tras
        # la serialización JSON (la cadena se codifica 1:1 en UTF-8).
        big_payload = {"d": "a" * (MAX_MESSAGE_SIZE + 100)}
        with pytest.raises(ProtocolError):
            Protocol.serialize_message("screen_frame", big_payload)


# ---------------------------------------------------------------------------
# read_message (asíncrono)
# ---------------------------------------------------------------------------

class TestReadMessage:
    """Pruebas de lectura asíncrona con framing (Requisitos 16.2, 16.3, 16.5)."""

    async def test_round_trip_serializar_y_leer(self):
        """Serializar y luego leer reproduce el mensaje original (16.1-16.3)."""
        original = Protocol.serialize_message(
            "chat_message", {"message": "hola mundo"}
        )
        reader = _feed_reader(original)
        message = await Protocol.read_message(reader)

        assert message is not None
        assert message["type"] == "chat_message"
        assert message["payload"] == {"message": "hola mundo"}
        assert "timestamp" in message

    async def test_round_trip_con_enum(self):
        """El round-trip funciona usando MessageType como tipo."""
        original = Protocol.serialize_message(
            MessageType.SCREEN_FRAME, {"width": 1024, "height": 768}
        )
        reader = _feed_reader(original)
        message = await Protocol.read_message(reader)

        assert message is not None
        assert message["type"] == "screen_frame"
        assert message["payload"]["width"] == 1024

    async def test_eof_devuelve_none(self):
        """Una conexión cerrada (EOF inmediato) devuelve None."""
        reader = asyncio.StreamReader()
        reader.feed_eof()
        message = await Protocol.read_message(reader)
        assert message is None

    async def test_eof_durante_lectura_del_cuerpo_devuelve_none(self):
        """Si la conexión se cierra a mitad del cuerpo, devuelve None."""
        # Encabezado que declara 100 bytes pero no se envía el cuerpo completo.
        header = struct.pack(">I", 100)
        reader = asyncio.StreamReader()
        reader.feed_data(header)
        reader.feed_data(b"{no c")  # solo 5 bytes de 100
        reader.feed_eof()
        message = await Protocol.read_message(reader)
        assert message is None

    async def test_longitud_excedida_lanza_protocol_error(self):
        """Una longitud declarada mayor a 10 MB lanza ProtocolError (16.9)."""
        header = struct.pack(">I", MAX_MESSAGE_SIZE + 1)
        reader = _feed_reader(header)
        with pytest.raises(ProtocolError):
            await Protocol.read_message(reader)

    async def test_json_malformado_lanza_protocol_error(self):
        """Un JSON malformado lanza ProtocolError, no None (16.5)."""
        bad_json = b"{no es json valido"
        framed = struct.pack(">I", len(bad_json)) + bad_json
        reader = _feed_reader(framed)
        with pytest.raises(ProtocolError):
            await Protocol.read_message(reader)

    async def test_bytes_invalidos_utf8_lanzan_protocol_error(self):
        """Bytes que no son UTF-8 válido lanza ProtocolError."""
        bad_bytes = b"\xff\xfe\xfd"
        framed = struct.pack(">I", len(bad_bytes)) + bad_bytes
        reader = _feed_reader(framed)
        with pytest.raises(ProtocolError):
            await Protocol.read_message(reader)

    async def test_leer_varios_mensajes_secuenciales(self):
        """Se pueden leer varios mensajes consecutivos del mismo reader."""
        m1 = Protocol.serialize_message("heartbeat")
        m2 = Protocol.serialize_message("chat_message", {"message": "uno"})
        m3 = Protocol.serialize_message("command_ack", {"success": True})

        reader = asyncio.StreamReader()
        reader.feed_data(m1 + m2 + m3)
        reader.feed_eof()

        msg1 = await Protocol.read_message(reader)
        msg2 = await Protocol.read_message(reader)
        msg3 = await Protocol.read_message(reader)
        msg4 = await Protocol.read_message(reader)  # EOF -> None

        assert msg1 is not None and msg1["type"] == "heartbeat"
        assert msg2 is not None and msg2["payload"] == {"message": "uno"}
        assert msg3 is not None and msg3["payload"]["success"] is True
        assert msg4 is None

    async def test_mensaje_vacio_lanza_protocol_error(self):
        """Un frame de longitud 0 (JSON vacío) lanza ProtocolError."""
        framed = struct.pack(">I", 0)
        reader = _feed_reader(framed)
        with pytest.raises(ProtocolError):
            await Protocol.read_message(reader)


# ---------------------------------------------------------------------------
# MessageType Enum
# ---------------------------------------------------------------------------

class TestMessageType:
    """Pruebas del Enum de tipos de mensaje."""

    def test_valores_son_snake_case(self):
        """Los valores del Enum son cadenas snake_case."""
        assert MessageType.SCREEN_START.value == "screen_start"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.WEB_BLOCK.value == "web_block"
        assert MessageType.ICMP_DISABLE.value == "icmp_disable"

    def test_no_hay_valores_duplicados(self):
        """Ningún miembro del Enum comparte el mismo valor."""
        values = [m.value for m in MessageType]
        assert len(values) == len(set(values))

    def test_from_value_devuelve_miembro_correcto(self):
        """from_value resuelve el string al miembro correspondiente."""
        assert MessageType.from_value("screen_frame") is MessageType.SCREEN_FRAME
        assert MessageType.from_value("shutdown") is MessageType.SHUTDOWN

    def test_from_value_desconocido_devuelve_none(self):
        """from_value devuelve None para un valor no registrado."""
        assert MessageType.from_value("comando_inexistente") is None

    def test_todos_los_tipos_esperados_estan_presentes(self):
        """El Enum contiene los tipos listados en la tarea."""
        nombres = {m.name for m in MessageType}
        esperados_cliente = {
            "CLIENT_HELLO", "CLIENT_METRICS", "SCREEN_FRAME", "CHAT_MESSAGE",
            "FILE_CHUNK", "FILE_COMPLETE", "COMMAND_ACK", "HEARTBEAT_RESPONSE",
        }
        esperados_servidor = {
            "SERVER_HELLO", "SCREEN_START", "SCREEN_STOP", "SCREEN_RESOLUTION",
            "INPUT_LOCK", "INPUT_UNLOCK", "SHUTDOWN", "WEB_BLOCK", "WEB_UNBLOCK",
            "ICMP_DISABLE", "ICMP_ENABLE", "FILE_REQUEST", "HEARTBEAT",
        }
        assert esperados_cliente.issubset(nombres)
        assert esperados_servidor.issubset(nombres)


# ---------------------------------------------------------------------------
# Helpers auxiliares (build_message, frame_payload)
# ---------------------------------------------------------------------------

class TestHelpers:
    """Pruebas de los métodos auxiliares build_message y frame_payload."""

    def test_build_message_estructura_correcta(self):
        """build_message devuelve un dict con type, payload y timestamp."""
        msg = Protocol.build_message("chat_message", {"x": 1})
        assert msg["type"] == "chat_message"
        assert msg["payload"] == {"x": 1}
        assert "timestamp" in msg

    def test_frame_payload_aplica_framing(self):
        """frame_payload aplica el prefijo de 4 bytes big-endian."""
        msg = Protocol.build_message("heartbeat")
        framed = Protocol.frame_payload(msg)
        length = struct.unpack(">I", framed[:4])[0]
        assert length == len(framed[4:])
        assert json.loads(framed[4:].decode("utf-8")) == msg

    def test_frame_payload_excede_limite_lanza_error(self):
        """frame_payload lanza ProtocolError si excede el límite."""
        big_msg = {"type": "x", "payload": {"d": "a" * (MAX_MESSAGE_SIZE + 100)}, "timestamp": "t"}
        with pytest.raises(ProtocolError):
            Protocol.frame_payload(big_msg)
