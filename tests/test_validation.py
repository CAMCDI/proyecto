"""Pruebas basadas en propiedades (Hypothesis) para validación y sanitización.

Complementa las pruebas unitarias de test_utils.py con fuzzing basado en
propiedades. Cada propiedad se ejecuta con un mínimo de 100 iteraciones.

Requisitos: 12.4, 12.5, 12.6, 12.8.
"""

from __future__ import annotations

import os
import string

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from common.utils import (
    MAX_CHAT_MESSAGE_LENGTH,
    MAX_FILENAME_LENGTH,
    sanitize_chat_message,
    sanitize_filename,
    validate_domain,
    validate_path,
)

# Mínimo 100 iteraciones por propiedad.
SETTINGS = settings(max_examples=100)


# ---------------------------------------------------------------------------
# validate_domain — Propiedades (Req 12.5)
# ---------------------------------------------------------------------------

class TestValidateDomainProperties:

    @given(st.text(min_size=0, max_size=300))
    @SETTINGS
    def test_nunca_acepta_metacaracteres_shell(self, domain: str):
        """Un dominio con metacaracteres de shell nunca es válido."""
        shell_meta = set(";|&$`(){}\\'\"\n\r")
        if any(c in shell_meta for c in domain):
            assert validate_domain(domain) is False

    @given(st.text(min_size=256, max_size=500))
    @SETTINGS
    def test_rechaza_dominios_largos(self, domain: str):
        """Dominios de más de 255 caracteres son rechazados."""
        assert validate_domain(domain) is False

    @given(st.from_regex(r"[a-z]{1,10}\.[a-z]{2,4}", fullmatch=True))
    @SETTINGS
    def test_acepta_dominios_simples_validos(self, domain: str):
        """Dominios simples generados por regex son válidos."""
        assert validate_domain(domain) is True

    @given(st.integers() | st.floats() | st.none() | st.binary())
    @SETTINGS
    def test_rechaza_tipos_no_string(self, value):
        """Entradas no-string son rechazadas."""
        assert validate_domain(value) is False


# ---------------------------------------------------------------------------
# sanitize_filename — Propiedades (Req 12.4)
# ---------------------------------------------------------------------------

class TestSanitizeFilenameProperties:

    @given(st.text(min_size=0, max_size=500))
    @SETTINGS
    def test_resultado_no_contiene_separador_unix(self, filename: str):
        """El resultado nunca contiene el separador de directorio '/'."""
        result = sanitize_filename(filename)
        assert "/" not in result

    @given(st.text(min_size=0, max_size=500))
    @SETTINGS
    def test_resultado_no_contiene_bytes_nulos(self, filename: str):
        """El resultado nunca contiene bytes nulos."""
        result = sanitize_filename(filename)
        assert "\x00" not in result

    @given(st.text(min_size=0, max_size=500))
    @SETTINGS
    def test_resultado_no_excede_longitud_maxima(self, filename: str):
        """El resultado nunca excede MAX_FILENAME_LENGTH."""
        result = sanitize_filename(filename)
        assert len(result) <= MAX_FILENAME_LENGTH

    @given(st.text(min_size=0, max_size=500))
    @SETTINGS
    def test_resultado_no_es_traversal(self, filename: str):
        """El resultado nunca es '.' o '..'."""
        result = sanitize_filename(filename)
        assert result not in (".", "..")

    @given(st.from_regex(r"[a-zA-Z0-9_\-]{1,50}\.[a-z]{1,5}", fullmatch=True))
    @SETTINGS
    def test_nombres_seguros_se_preservan(self, filename: str):
        """Nombres de archivo seguros se conservan sin cambios."""
        assert sanitize_filename(filename) == filename


# ---------------------------------------------------------------------------
# sanitize_chat_message — Propiedades (Req 12.6)
# ---------------------------------------------------------------------------

class TestSanitizeChatMessageProperties:

    @given(st.text(min_size=0, max_size=2000))
    @SETTINGS
    def test_resultado_no_contiene_html_crudo(self, message: str):
        """El resultado nunca contiene '<' o '>' crudos."""
        result = sanitize_chat_message(message)
        # Los caracteres < y > se convierten en entidades.
        for i, ch in enumerate(result):
            if ch == "<":
                assert False, f"Carácter '<' crudo en posición {i}"
            if ch == ">":
                assert False, f"Carácter '>' crudo en posición {i}"

    @given(st.text(min_size=1001, max_size=1500, alphabet=string.ascii_letters + string.digits + " "))
    @SETTINGS
    def test_truncamiento_a_1000_antes_de_escapar(self, message: str):
        """Mensajes largos sin chars especiales se truncan a exactamente 1000."""
        result = sanitize_chat_message(message)
        assert len(result) == MAX_CHAT_MESSAGE_LENGTH

    @given(st.text(min_size=0, max_size=1000, alphabet=string.ascii_letters + string.digits + " "))
    @SETTINGS
    def test_texto_plano_se_preserva(self, message: str):
        """Texto sin caracteres especiales se preserva tal cual."""
        if message:
            assert sanitize_chat_message(message) == message


# ---------------------------------------------------------------------------
# validate_path — Propiedades (Req 12.8)
# ---------------------------------------------------------------------------

class TestValidatePathProperties:

    @given(st.text(min_size=1, max_size=200))
    @SETTINGS
    def test_path_con_traversal_rechazado(self, subpath: str):
        """Rutas con '..' que escapan del directorio son rechazadas."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            malicious = os.path.join(tmpdir, "..", "..", "etc", "passwd")
            resolved = os.path.realpath(malicious)
            if not resolved.startswith(os.path.realpath(tmpdir)):
                assert validate_path(malicious, [tmpdir]) is False

    @given(st.just(""))
    @SETTINGS
    def test_path_vacio_rechazado(self, path: str):
        """Una ruta vacía siempre es rechazada."""
        assert validate_path(path, ["/tmp"]) is False
