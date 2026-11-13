"""Pruebas unitarias para las funciones de validación y sanitización.

Cubren casos específicos y bordes de las funciones de ``common/utils.py``
(Requisitos 12.4, 12.5, 12.6, 12.8). Las pruebas basadas en propiedades
(hipótesis) corresponden a la tarea 4.2 y viven en este mismo módulo.

Requisitos: 12.4, 12.5, 12.6, 12.8.
"""

from __future__ import annotations

import os
import html

import pytest

from common.utils import (
    MAX_CHAT_MESSAGE_LENGTH,
    MAX_FILENAME_LENGTH,
    sanitize_chat_message,
    sanitize_filename,
    validate_domain,
    validate_path,
)


# ---------------------------------------------------------------------------
# validate_domain (Requisito 12.5)
# ---------------------------------------------------------------------------

class TestValidateDomain:
    """Pruebas de validación de dominios (Requisito 12.5)."""

    @pytest.mark.parametrize(
        "domain",
        [
            "example.com",
            "www.example.com",
            "sub.domain.example.com",
            "a.com",
            "my-site.example.org",
            "x-y-z.example.co.uk",
            "ABCDEF.COM",  # mayúsculas permitidas
        ],
    )
    def test_valid_domains(self, domain):
        assert validate_domain(domain) is True

    @pytest.mark.parametrize(
        "domain",
        [
            "",                          # vacío
            "example",                   # sin TLD ni punto
            "example.c",                 # TLD de un solo carácter
            "example..com",              # etiqueta vacía
            ".example.com",              # inicia con punto
            "example.com.",              # termina con punto
            "-example.com",              # etiqueta inicia con guion
            "example-.com",             # etiqueta termina con guion
            "exa mple.com",              # contiene espacio
            "example.com/path",          # contiene barra (path traversal)
            "example.com;rm -rf",        # metacaracter de shell ';'
            "example.com|cat",           # metacaracter '|'
            "example.com&whoami",        # metacaracter '&'
            "example.com$(id)",          # sustitución de shell
            "192.168.1.1",               # dirección IP (TLD no alfabético)
            "example.com\n",             # salto de línea
            "a" * 256 + ".com",          # excede 255 caracteres
            "exämple.com",              # caractere no ASCII
        ],
    )
    def test_invalid_domains(self, domain):
        assert validate_domain(domain) is False

    @pytest.mark.parametrize("invalid", [None, 123, [], {}, 3.14])
    def test_non_string_inputs_rejected(self, invalid):
        assert validate_domain(invalid) is False


# ---------------------------------------------------------------------------
# sanitize_filename (Requisito 12.4)
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    """Pruebas de sanitización de nombres de archivo (Requisito 12.4)."""

    def test_plain_filename_preserved(self):
        assert sanitize_filename("document.pdf") == "document.pdf"

    def test_strips_directory_components(self):
        # Resuelve a basename: elimina separadores "/" y directorios.
        assert sanitize_filename("/etc/passwd") == "passwd"
        assert sanitize_filename("a/b/c/file.txt") == "file.txt"
        assert sanitize_filename("/var/log/app.log") == "app.log"

    def test_path_traversal_resolved_to_basename(self):
        # "../" se elimina al resolver el basename.
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("../secret.txt") == "secret.txt"

    def test_standalone_parent_dir_rejected(self):
        # basename("..") == "..": debe rechazarse (path traversal explícito).
        assert sanitize_filename("..") == ""
        assert sanitize_filename(".") == ""

    def test_null_bytes_removed(self):
        assert sanitize_filename("file\x00.txt") == "file.txt"
        assert sanitize_filename("file\x00name\x00.txt") == "filename.txt"

    def test_control_characters_removed(self):
        assert sanitize_filename("file\x01\x02.txt") == "file.txt"
        assert sanitize_filename("file\x7f.txt") == "file.txt"

    def test_truncates_long_filename(self):
        largo = "a" * (MAX_FILENAME_LENGTH + 100)
        resultado = sanitize_filename(largo)
        assert len(resultado) == MAX_FILENAME_LENGTH

    def test_empty_input_returns_empty(self):
        assert sanitize_filename("") == ""
        # Una ruta que termina en "/" es un directorio: basename es "".
        assert sanitize_filename("/a/b/") == ""

    def test_internal_dots_preserved(self):
        # "a..b" es un nombre de archivo válido: ".." interno no es traversal.
        assert sanitize_filename("a..b") == "a..b"
        assert sanitize_filename("file..backup.txt") == "file..backup.txt"

    @pytest.mark.parametrize("invalid", [None, 123, [], {}])
    def test_non_string_inputs(self, invalid):
        assert sanitize_filename(invalid) == ""


# ---------------------------------------------------------------------------
# validate_path (Requisito 12.8)
# ---------------------------------------------------------------------------

class TestValidatePath:
    """Pruebas de validación de rutas contenidas (Requisito 12.8)."""

    def test_path_within_allowed_dir(self, tmp_path):
        allowed = str(tmp_path)
        archivo = tmp_path / "doc.txt"
        archivo.write_text("datos")
        assert validate_path(str(archivo), [allowed]) is True

    def test_subdirectory_path_allowed(self, tmp_path):
        allowed = str(tmp_path)
        sub = tmp_path / "subdir"
        sub.mkdir()
        archivo = sub / "anidado.txt"
        archivo.write_text("datos")
        assert validate_path(str(archivo), [allowed]) is True

    def test_path_traversal_rejected(self, tmp_path):
        allowed = str(tmp_path)
        # "/tmp/allowed/../etc/passwd" resuelve fuera del dir permitido.
        traversal = os.path.join(allowed, "..", "..", "etc", "passwd")
        assert validate_path(traversal, [allowed]) is False

    def test_prefix_attack_rejected(self, tmp_path):
        # "/tmp/allowedevil" no debe confundirse con "/tmp/allowed".
        allowed = str(tmp_path) + "x"  # nombre que extiende el prefijo
        base = str(tmp_path)
        evil = base + "evil" + os.sep + "archivo"
        assert validate_path(evil, [base]) is False

    def test_exact_allowed_dir_allowed(self, tmp_path):
        allowed = str(tmp_path)
        assert validate_path(allowed, [allowed]) is True

    def test_path_outside_all_allowed_rejected(self, tmp_path):
        allowed = str(tmp_path)
        outside = os.path.join(os.path.dirname(str(tmp_path)), "otro_lugar")
        assert validate_path(outside, [allowed]) is False

    def test_multiple_allowed_dirs(self, tmp_path):
        d1 = tmp_path / "dir1"
        d2 = tmp_path / "dir2"
        d1.mkdir()
        d2.mkdir()
        f = d2 / "archivo.txt"
        f.write_text("x")
        assert validate_path(str(f), [str(d1), str(d2)]) is True

    def test_empty_or_invalid_inputs(self, tmp_path):
        assert validate_path("", [str(tmp_path)]) is False
        assert validate_path(str(tmp_path), []) is False
        assert validate_path(None, [str(tmp_path)]) is False

    def test_null_bytes_rejected(self, tmp_path):
        allowed = str(tmp_path)
        malicious = os.path.join(allowed, "file\x00.txt")
        # Los bytes nulos provocan ValueError en realpath; debe rechazarse.
        assert validate_path(malicious, [allowed]) is False


# ---------------------------------------------------------------------------
# sanitize_chat_message (Requisito 12.6)
# ---------------------------------------------------------------------------

class TestSanitizeChatMessage:
    """Pruebas de sanitización de mensajes de chat (Requisito 12.6)."""

    def test_plain_message_preserved(self):
        assert sanitize_chat_message("Hola, ¿cómo estás?") == "Hola, ¿cómo estás?"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("<script>", "&lt;script&gt;"),
            ("a & b", "a &amp; b"),
            ('"comillas"', "&quot;comillas&quot;"),
            ("'apostrofos'", "&#x27;apostrofos&#x27;"),
            ("<b>negrita</b>", "&lt;b&gt;negrita&lt;/b&gt;"),
        ],
    )
    def test_html_special_chars_escaped(self, raw, expected):
        assert sanitize_chat_message(raw) == expected

    def test_all_five_special_chars_escaped(self):
        mensaje = '<>&"\''  # <, >, &, ", '
        resultado = sanitize_chat_message(mensaje)
        # Ningún carácter especial crudo debe permanecer en la salida.
        for char in ("<", ">", '"'):
            assert char not in resultado
        # El ampersand se convierte en entidad (&amp;) que sí contiene '&'.
        assert "&lt;" in resultado
        assert "&gt;" in resultado
        assert "&amp;" in resultado
        assert "&quot;" in resultado
        assert "&#x27;" in resultado

    def test_truncates_long_message(self):
        largo = "x" * (MAX_CHAT_MESSAGE_LENGTH + 500)
        resultado = sanitize_chat_message(largo)
        # El contenido original se trunca a 1000 caracteres antes de escapar.
        assert len(resultado) == MAX_CHAT_MESSAGE_LENGTH

    def test_exact_boundary_length_preserved(self):
        exacto = "y" * MAX_CHAT_MESSAGE_LENGTH
        assert sanitize_chat_message(exacto) == exacto

    def test_empty_input(self):
        assert sanitize_chat_message("") == ""

    @pytest.mark.parametrize("invalid", [None, 123, [], {}])
    def test_non_string_inputs(self, invalid):
        assert sanitize_chat_message(invalid) == ""

    def test_truncation_before_escaping(self):
        # Un mensaje de 1000 '&' se trunca y luego se escapa; el resultado
        # contiene solo entidades &amp; y ningún '&' crudo aislado que no sea
        # parte de la entidad.
        mensaje = "&" * (MAX_CHAT_MESSAGE_LENGTH + 10)
        resultado = sanitize_chat_message(mensaje)
        assert resultado == "&amp;" * MAX_CHAT_MESSAGE_LENGTH
