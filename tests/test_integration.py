"""Pruebas de integración del Sistema de Monitoreo y Administración Remota.

Verifican la interacción entre los módulos: protocolo + crypto, transferencia
de archivos con verificación SHA-256, y el flujo completo de autenticación.

Requisitos: 16.1, 11.5, 11.6, 2.3, 2.7.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
import tempfile

import pytest

from common.crypto import hash_password, verify_password, generate_auth_token
from common.protocol import Protocol, ProtocolError, MessageType, COMMAND_WHITELIST
from common.utils import (
    sanitize_filename,
    sanitize_chat_message,
    validate_domain,
    validate_path,
    RateLimiter,
)
from server.logger import ActionLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feed_reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


# ---------------------------------------------------------------------------
# Integración Protocolo + Crypto
# ---------------------------------------------------------------------------

class TestProtocolCryptoIntegration:
    """Pruebas de integración entre el protocolo y la capa criptográfica."""

    def test_token_generado_se_hashea_y_verifica(self):
        """Flujo completo: generar token → hashear → verificar."""
        token = generate_auth_token()
        h = hash_password(token)
        assert verify_password(token, h) is True
        assert verify_password("token_incorrecto", h) is False

    def test_client_hello_con_token_en_payload(self):
        """Un client_hello serializado contiene el token en el payload."""
        token = generate_auth_token()
        framed = Protocol.serialize_message(
            MessageType.CLIENT_HELLO,
            {"token": token, "hostname": "test-host", "os_info": {"os_name": "Linux"}},
        )
        # Deserializar.
        import json
        msg = json.loads(framed[4:].decode("utf-8"))
        assert msg["type"] == "client_hello"
        assert msg["payload"]["token"] == token
        assert msg["payload"]["hostname"] == "test-host"

    async def test_round_trip_hello_completo(self):
        """Serializar y leer un client_hello reproduce los datos originales."""
        token = generate_auth_token()
        payload = {
            "token": token,
            "hostname": "mi-pc",
            "os_info": {"os_name": "Linux", "os_version": "6.1"},
        }
        framed = Protocol.serialize_message(MessageType.CLIENT_HELLO, payload)
        reader = _feed_reader(framed)
        msg = await Protocol.read_message(reader)
        assert msg is not None
        assert msg["type"] == "client_hello"
        assert msg["payload"]["token"] == token
        assert verify_password(msg["payload"]["token"], hash_password(token)) is True


# ---------------------------------------------------------------------------
# Integración Protocolo + Validación
# ---------------------------------------------------------------------------

class TestProtocolValidationIntegration:
    """Pruebas de integración entre protocolo y validación de mensajes."""

    def test_todos_los_message_types_son_validos(self):
        """Cada MessageType genera un mensaje que pasa validate_message."""
        for mt in MessageType:
            msg = Protocol.build_message(mt, {"test": True})
            assert Protocol.validate_message(msg) is True, f"Falló para {mt.name}"

    def test_mensaje_con_tipo_desconocido_no_valida(self):
        """Un mensaje con tipo fuera de la whitelist no pasa validación."""
        msg = {"type": "comando_inventado", "payload": {}, "timestamp": "2024-01-01T00:00:00"}
        assert Protocol.validate_message(msg) is False

    def test_whitelist_sincronizada_con_enum(self):
        """COMMAND_WHITELIST contiene exactamente los valores del Enum."""
        enum_values = {m.value for m in MessageType}
        assert COMMAND_WHITELIST == enum_values

    async def test_multiples_mensajes_en_secuencia(self):
        """Enviar y leer múltiples tipos de mensaje en secuencia."""
        messages = [
            (MessageType.CLIENT_HELLO, {"token": "abc", "hostname": "h"}),
            (MessageType.CLIENT_METRICS, {"cpu_percent": 45.2, "memory_percent": 60.1}),
            (MessageType.CHAT_MESSAGE, {"message": "Hola <b>mundo</b>"}),
            (MessageType.HEARTBEAT_RESPONSE, {}),
        ]
        data = b""
        for mt, payload in messages:
            data += Protocol.serialize_message(mt, payload)

        reader = _feed_reader(data)
        for mt, payload in messages:
            msg = await Protocol.read_message(reader)
            assert msg is not None
            assert msg["type"] == mt.value
            assert Protocol.validate_message(msg) is True


# ---------------------------------------------------------------------------
# Integración SHA-256 + Transferencia de archivos
# ---------------------------------------------------------------------------

class TestFileTransferIntegration:
    """Pruebas de integración de la verificación SHA-256 en transferencias."""

    def test_sha256_archivo_consistente(self):
        """El SHA-256 de un archivo es determinista y consistente."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            content = b"Contenido de prueba para verificacion SHA-256" * 100
            f.write(content)
            f.flush()
            path = f.name

        try:
            expected = hashlib.sha256(content).hexdigest()
            # Calcular como lo hace file_handler (en bloques de 64KB).
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            assert actual == expected
        finally:
            os.unlink(path)

    def test_sanitize_filename_en_transferencia(self):
        """Los nombres de archivo recibidos se sanitizan correctamente."""
        malicious_names = [
            ("../../etc/passwd", "passwd"),
            ("/var/log/syslog", "syslog"),
            ("normal.txt", "normal.txt"),
            ("file\x00name.txt", "filename.txt"),
        ]
        for raw, expected in malicious_names:
            assert sanitize_filename(raw) == expected


# ---------------------------------------------------------------------------
# Integración Logger
# ---------------------------------------------------------------------------

class TestLoggerIntegration:
    """Pruebas de integración del ActionLogger."""

    def test_flujo_completo_de_logging(self):
        """Registra eventos y verifica filtrado y exportación."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ActionLogger(tmpdir)

            logger.log_event("host1", "CONEXION", "Cliente conectado")
            logger.log_event("host1", "SCREEN_START", "Streaming iniciado")
            logger.log_event("host2", "CONEXION", "Cliente 2 conectado")
            logger.log_event("host1", "DESCONEXION", "Cliente desconectado")

            # Filtrar por cliente.
            host1_logs = logger.filter_logs(client="host1")
            assert len(host1_logs) == 3

            # Filtrar por acción.
            conn_logs = logger.filter_logs(action_type="CONEXION")
            assert len(conn_logs) == 2

            # Exportar.
            export_path = os.path.join(tmpdir, "export.txt")
            logger.export_logs(export_path)
            with open(export_path) as f:
                lines = f.readlines()
            assert len(lines) == 4

            # Clientes y acciones únicas.
            assert set(logger.get_all_clients()) == {"host1", "host2"}
            assert "CONEXION" in logger.get_all_action_types()


# ---------------------------------------------------------------------------
# Integración Rate Limiter
# ---------------------------------------------------------------------------

class TestRateLimiterIntegration:
    """Pruebas de integración del rate limiter con el protocolo."""

    def test_rate_limiter_permite_rafaga_inicial(self):
        """El rate limiter permite una ráfaga inicial de max_calls."""
        rl = RateLimiter(max_calls=5, period=1.0)
        results = [rl.is_allowed() for _ in range(5)]
        assert all(results)
        # El sexto debe ser rechazado.
        assert rl.is_allowed() is False

    def test_sanitize_chat_en_flujo_de_mensajes(self):
        """Mensajes de chat se sanitizan correctamente en el flujo completo."""
        raw = '<script>alert("xss")</script>'
        sanitized = sanitize_chat_message(raw)
        msg = Protocol.build_message(MessageType.CHAT_MESSAGE, {"message": sanitized})
        assert "<script>" not in msg["payload"]["message"]
        assert "&lt;script&gt;" in msg["payload"]["message"]

