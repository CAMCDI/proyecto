"""Pruebas unitarias para common/crypto.py.

Cubren la creación de contextos TLS, el hashing y verificación de
contraseñas con argon2id y la generación de tokens de autenticación.

Requisitos: 11.1, 11.2, 11.5, 11.6, 11.9.
"""

from __future__ import annotations

import os
import ssl
import tempfile
import subprocess
from pathlib import Path

import pytest

from common.crypto import (
    CryptoError,
    create_server_tls_context,
    create_client_tls_context,
    hash_password,
    verify_password,
    generate_auth_token,
)


# ---------------------------------------------------------------------------
# Fixtures: generación de certificados temporales para pruebas
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cert_dir():
    """Genera certificados de prueba temporales con OpenSSL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ca_key = os.path.join(tmpdir, "ca.key")
        ca_crt = os.path.join(tmpdir, "ca.crt")
        srv_key = os.path.join(tmpdir, "server.key")
        srv_crt = os.path.join(tmpdir, "server.crt")
        cli_key = os.path.join(tmpdir, "client.key")
        cli_crt = os.path.join(tmpdir, "client.crt")

        # CA autofirmado
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", ca_key, "-out", ca_crt, "-days", "1",
            "-nodes", "-subj", "/CN=TestCA",
        ], check=True, capture_output=True)

        # Certificado del servidor
        srv_csr = os.path.join(tmpdir, "server.csr")
        subprocess.run([
            "openssl", "req", "-newkey", "rsa:2048",
            "-keyout", srv_key, "-out", srv_csr,
            "-nodes", "-subj", "/CN=TestServer",
        ], check=True, capture_output=True)
        subprocess.run([
            "openssl", "x509", "-req", "-in", srv_csr,
            "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
            "-out", srv_crt, "-days", "1",
        ], check=True, capture_output=True)

        # Certificado del cliente
        cli_csr = os.path.join(tmpdir, "client.csr")
        subprocess.run([
            "openssl", "req", "-newkey", "rsa:2048",
            "-keyout", cli_key, "-out", cli_csr,
            "-nodes", "-subj", "/CN=TestClient",
        ], check=True, capture_output=True)
        subprocess.run([
            "openssl", "x509", "-req", "-in", cli_csr,
            "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
            "-out", cli_crt, "-days", "1",
        ], check=True, capture_output=True)

        yield {
            "ca_crt": ca_crt, "ca_key": ca_key,
            "srv_crt": srv_crt, "srv_key": srv_key,
            "cli_crt": cli_crt, "cli_key": cli_key,
            "dir": tmpdir,
        }


# ---------------------------------------------------------------------------
# TLS Contexts
# ---------------------------------------------------------------------------

class TestServerTLSContext:
    """Pruebas de creación de contexto TLS del servidor (Req 11.1, 11.2)."""

    def test_crea_contexto_valido(self, cert_dir):
        ctx = create_server_tls_context(
            cert_dir["srv_crt"], cert_dir["srv_key"], cert_dir["ca_crt"],
        )
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_archivo_inexistente_lanza_crypto_error(self, cert_dir):
        with pytest.raises(CryptoError, match="no existe"):
            create_server_tls_context(
                "/no/existe.crt", cert_dir["srv_key"], cert_dir["ca_crt"],
            )

    def test_clave_inexistente_lanza_crypto_error(self, cert_dir):
        with pytest.raises(CryptoError, match="no existe"):
            create_server_tls_context(
                cert_dir["srv_crt"], "/no/existe.key", cert_dir["ca_crt"],
            )


class TestClientTLSContext:
    """Pruebas de creación de contexto TLS del cliente (Req 11.1, 11.2)."""

    def test_crea_contexto_valido(self, cert_dir):
        ctx = create_client_tls_context(
            cert_dir["cli_crt"], cert_dir["cli_key"], cert_dir["ca_crt"],
        )
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is False

    def test_ca_inexistente_lanza_crypto_error(self, cert_dir):
        with pytest.raises(CryptoError, match="no existe"):
            create_client_tls_context(
                cert_dir["cli_crt"], cert_dir["cli_key"], "/no/ca.crt",
            )


# ---------------------------------------------------------------------------
# Hashing y verificación argon2id
# ---------------------------------------------------------------------------

class TestHashPassword:
    """Pruebas de hash_password (Req 11.5)."""

    def test_produce_hash_argon2id(self):
        h = hash_password("mi_contraseña")
        assert isinstance(h, str)
        assert h.startswith("$argon2id$")

    def test_hashes_diferentes_para_misma_contraseña(self):
        h1 = hash_password("test")
        h2 = hash_password("test")
        assert h1 != h2  # sal distinta cada vez

    def test_tipo_invalido_lanza_crypto_error(self):
        with pytest.raises(CryptoError):
            hash_password(123)  # type: ignore


class TestVerifyPassword:
    """Pruebas de verify_password (Req 11.6)."""

    def test_contraseña_correcta(self):
        h = hash_password("secreto")
        assert verify_password("secreto", h) is True

    def test_contraseña_incorrecta(self):
        h = hash_password("secreto")
        assert verify_password("incorrecto", h) is False

    def test_hash_invalido(self):
        assert verify_password("test", "hash_basura") is False

    def test_tipos_invalidos(self):
        assert verify_password(None, "hash") is False  # type: ignore
        assert verify_password("pw", None) is False  # type: ignore


# ---------------------------------------------------------------------------
# Generación de tokens
# ---------------------------------------------------------------------------

class TestGenerateAuthToken:
    """Pruebas de generate_auth_token (Req 11.9)."""

    def test_longitud_64_caracteres_hex(self):
        token = generate_auth_token()
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_tokens_unicos(self):
        tokens = {generate_auth_token() for _ in range(10)}
        assert len(tokens) == 10

