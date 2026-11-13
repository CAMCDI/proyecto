#!/usr/bin/env bash
#
# Script de instalación del Sistema de Monitoreo y Administración Remota.
#
# Instala las dependencias del sistema, crea el entorno virtual de Python,
# instala las dependencias del proyecto y genera los certificados TLS.
#
# Uso:
#   ./install.sh [--dev]
#
#   --dev  Instala también las dependencias de desarrollo (pytest, hypothesis).
#
# Requisitos cubiertos: 17.1, 18.7, 18.8.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
VENV_DIR="${PROJECT_DIR}/venv"
DEV_MODE=false

# ── Funciones de utilidad ────────────────────────────────────────────────────

info() {
    echo -e "\033[32m[INFO]\033[0m $*"
}

error() {
    echo -e "\033[31m[ERROR]\033[0m $*" >&2
}

success() {
    echo -e "\033[34m[OK]\033[0m $*"
}

# ── Parsear argumentos ──────────────────────────────────────────────────────

for arg in "$@"; do
    case "${arg}" in
        --dev)
            DEV_MODE=true
            ;;
        *)
            error "Argumento desconocido: ${arg}"
            echo "Uso: ./install.sh [--dev]"
            exit 1
            ;;
    esac
done

# ── 1. Verificar dependencias del sistema ────────────────────────────────────

info "Verificando dependencias del sistema..."

deps_missing=false
for cmd in python3 openssl pip3; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        error "${cmd} no está instalado."
        deps_missing=true
    fi
done

# Verificar xinput (opcional, solo para X11).
if ! command -v xinput >/dev/null 2>&1; then
    info "xinput no detectado. El bloqueo de entrada no estará disponible."
    info "Instalar con: sudo apt install xinput"
fi

if [ "${deps_missing}" = true ]; then
    error "Instale las dependencias faltantes y vuelva a ejecutar este script."
    exit 1
fi

info "Python detectado: $(python3 --version)"
info "OpenSSL detectado: $(openssl version)"

# ── 2. Crear entorno virtual ────────────────────────────────────────────────

if [ ! -d "${VENV_DIR}" ]; then
    info "Creando entorno virtual en: ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
else
    info "Entorno virtual existente: ${VENV_DIR}"
fi

# Activar entorno virtual.
source "${VENV_DIR}/bin/activate"

# ── 3. Instalar dependencias de Python ───────────────────────────────────────

info "Instalando dependencias de producción..."
pip install --quiet --upgrade pip
pip install --quiet -r "${PROJECT_DIR}/requirements.txt"

if [ "${DEV_MODE}" = true ]; then
    info "Instalando dependencias de desarrollo..."
    pip install --quiet -r "${PROJECT_DIR}/requirements-dev.txt"
fi

# ── 4. Generar certificados TLS ──────────────────────────────────────────────

CERTS_SCRIPT="${SCRIPT_DIR}/generate_certs.sh"
if [ -f "${CERTS_SCRIPT}" ]; then
    info "Generando certificados TLS..."
    chmod +x "${CERTS_SCRIPT}"
    bash "${CERTS_SCRIPT}"
else
    error "Script de generación de certificados no encontrado: ${CERTS_SCRIPT}"
fi

# ── 5. Crear directorios de trabajo ─────────────────────────────────────────

info "Creando directorios de trabajo..."
mkdir -p "${HOME}/.config/remote-monitor/logs"
mkdir -p "${HOME}/Descargas"

# ── Resumen ──────────────────────────────────────────────────────────────────

echo ""
success "¡Instalación completada!"
echo ""
echo "  Para iniciar el servidor:"
echo "    source venv/bin/activate"
echo "    python server/main.py --token MI_TOKEN_SECRETO"
echo ""
echo "  Para iniciar un cliente:"
echo "    source venv/bin/activate"
echo "    python client/main.py --host IP_SERVIDOR --client-id client1 --token MI_TOKEN_SECRETO"
echo ""
if [ "${DEV_MODE}" = true ]; then
    echo "  Para ejecutar las pruebas:"
    echo "    pytest"
    echo ""
fi

