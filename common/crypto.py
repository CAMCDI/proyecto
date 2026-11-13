"""Módulo de criptografía: contextos TLS y utilidades de autenticación.

Proporciona las funciones necesarias para establecer conexiones TLS seguras
(servidor y cliente) y para gestionar los tokens de autenticación basados
en argon2id.

Requisitos: 11.1, 11.2, 11.5, 11.6, 11.9, 11.10.
"""

from __future__ import annotations

import os
import secrets
import ssl
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

__all__ = [
    "CryptoError",
    "create_server_tls_context",
    "create_client_tls_context",
    "hash_password",
    "verify_password",
    "generate_auth_token",
]


class CryptoError(Exception):
    """Error en operaciones criptográficas (TLS, hashing, verificación).

    Se eleva cuando:
    - Faltan archivos de certificado/clave.
    - El contexto TLS no puede configurarse.
    - La verificación de contraseña falla por motivos de seguridad.
    """


# ---------------------------------------------------------------------------
# Configuración argon2id (Requisito 11.5)
# memory_cost en KiB: 65536 KiB = 64 MB
# ---------------------------------------------------------------------------
_ARGON2_HASHER = PasswordHasher(
    memory_cost=65536,   # 64 MB
    time_cost=3,         # 3 iteraciones
    parallelism=4,       # 4 hilos paralelos
    hash_len=32,
    salt_len=16,
)


# ---------------------------------------------------------------------------
# Contextos TLS (Requisitos 11.1, 11.2, 11.10)
# ---------------------------------------------------------------------------

def create_server_tls_context(
    cert_path: str | Path,
    key_path: str | Path,
    ca_path: str | Path,
) -> ssl.SSLContext:
    """Crea un contexto TLS para el servidor con verificación de cliente.

    Configura TLS 1.3 como versión mínima con suites de cifrado fuertes
    y exige que los clientes presenten un certificado firmado por la CA
    indicada (autenticación mutua).

    Args:
        cert_path: Ruta al certificado del servidor (PEM).
        key_path: Ruta a la clave privada del servidor (PEM).
        ca_path: Ruta al certificado CA para verificar clientes (PEM).

    Returns:
        ``ssl.SSLContext`` configurado para uso en servidor asyncio.

    Raises:
        CryptoError: Si algún archivo no existe o no puede cargarse.

    Requisitos: 11.1, 11.2, 11.10.
    """
    for path, label in [(cert_path, "certificado"), (key_path, "clave privada"), (ca_path, "CA")]:
        if not Path(path).exists():
            raise CryptoError(
                f"El {label} del servidor no existe: {path}"
            )

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # TLS 1.3 como mínimo (Requisito 11.1).
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        # Cargar certificado y clave del servidor.
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        # Requerir y verificar el certificado del cliente (Requisito 11.2).
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=str(ca_path))
    except ssl.SSLError as exc:
        raise CryptoError(f"Error configurando contexto TLS del servidor: {exc}") from exc

    return ctx


def create_client_tls_context(
    cert_path: str | Path,
    key_path: str | Path,
    ca_path: str | Path,
) -> ssl.SSLContext:
    """Crea un contexto TLS para el cliente con verificación del servidor.

    Configura TLS 1.3 como versión mínima. El cliente presenta su propio
    certificado (autenticación mutua) y verifica el certificado del servidor
    contra la CA proporcionada.

    Args:
        cert_path: Ruta al certificado del cliente (PEM).
        key_path: Ruta a la clave privada del cliente (PEM).
        ca_path: Ruta al certificado CA para verificar el servidor (PEM).

    Returns:
        ``ssl.SSLContext`` configurado para uso en cliente asyncio.

    Raises:
        CryptoError: Si algún archivo no existe o no puede cargarse.

    Requisitos: 11.1, 11.2, 11.10.
    """
    for path, label in [(cert_path, "certificado"), (key_path, "clave privada"), (ca_path, "CA")]:
        if not Path(path).exists():
            raise CryptoError(
                f"El {label} del cliente no existe: {path}"
            )

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # TLS 1.3 como mínimo (Requisito 11.1).
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        # Cargar certificado y clave del cliente.
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        # Verificar el certificado del servidor (Requisito 11.2).
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = False  # Usamos IPs en LAN; no hay hostname válido
        ctx.load_verify_locations(cafile=str(ca_path))
    except ssl.SSLError as exc:
        raise CryptoError(f"Error configurando contexto TLS del cliente: {exc}") from exc

    return ctx


# ---------------------------------------------------------------------------
# Hashing y verificación de contraseñas (Requisitos 11.5, 11.6)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Genera un hash argon2id para la contraseña dada.

    Utiliza los parámetros de seguridad definidos por el sistema:
    memory=64 MB, iterations=3, parallelism=4. La sal se genera
    aleatoriamente en cada llamada (incluida en el hash resultante).

    Args:
        password: Contraseña en texto plano a hashear.

    Returns:
        Cadena PHC que contiene el hash argon2id, la sal y los parámetros.

    Raises:
        CryptoError: Si la contraseña no es una cadena válida.

    Requisito: 11.5.
    """
    if not isinstance(password, str):
        raise CryptoError("La contraseña debe ser una cadena de texto.")
    return _ARGON2_HASHER.hash(password)


def verify_password(password: str, hash_str: str) -> bool:
    """Verifica una contraseña contra su hash argon2id.

    Args:
        password: Contraseña en texto plano a verificar.
        hash_str: Hash PHC argon2id previamente generado con ``hash_password``.

    Returns:
        ``True`` si la contraseña coincide, ``False`` en caso contrario.

    Requisito: 11.6.
    """
    if not isinstance(password, str) or not isinstance(hash_str, str):
        return False
    try:
        return _ARGON2_HASHER.verify(hash_str, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ---------------------------------------------------------------------------
# Generación de tokens de autenticación (Requisito 11.9)
# ---------------------------------------------------------------------------

def generate_auth_token() -> str:
    """Genera un token de autenticación aleatorio seguro.

    Genera 32 bytes criptográficamente aleatorios usando ``secrets.token_hex``
    y los devuelve como una cadena hexadecimal de 64 caracteres.

    Returns:
        Cadena hexadecimal de 64 caracteres (32 bytes en hex).

    Requisito: 11.9.
    """
    return secrets.token_hex(32)
