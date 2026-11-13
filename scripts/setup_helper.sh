#!/usr/bin/env bash
#
# Script de configuración del helper privilegiado.
#
# Instala y configura el helper privilegiado que ejecuta operaciones que
# requieren permisos de root (bloqueo de dominios, control de ICMP,
# bloqueo de entrada, apagado remoto).
#
# El helper se ejecuta como un servicio de systemd con permisos de root,
# comunicándose con el agente cliente a través de un socket UNIX.
#
# Uso:
#   sudo ./setup_helper.sh [--uninstall]
#
# Requisitos cubiertos: 13.1, 13.2, 17.5.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
SERVICE_NAME="remote-monitor-helper"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SOCKET_DIR="${HOME}/.config/remote-monitor"
SOCKET_PATH="${SOCKET_DIR}/helper.sock"
PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"

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

# ── Verificar permisos de root ──────────────────────────────────────────────

if [ "$(id -u)" -ne 0 ]; then
    error "Este script debe ejecutarse como root."
    echo "Uso: sudo ./setup_helper.sh [--uninstall]"
    exit 1
fi

# ── Parsear argumentos ──────────────────────────────────────────────────────

if [ "${1:-}" = "--uninstall" ]; then
    info "Desinstalando el helper privilegiado..."
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    rm -f "${SERVICE_FILE}"
    rm -f "${SOCKET_PATH}"
    systemctl daemon-reload
    success "Helper privilegiado desinstalado."
    exit 0
fi

# ── 1. Verificar dependencias ────────────────────────────────────────────────

if [ ! -f "${PYTHON_BIN}" ]; then
    error "Python del entorno virtual no encontrado: ${PYTHON_BIN}"
    error "Ejecute primero: ./install.sh"
    exit 1
fi

# ── 2. Crear directorio del socket ───────────────────────────────────────────

info "Creando directorio del socket..."
mkdir -p "${SOCKET_DIR}"

# ── 3. Crear archivo de servicio systemd ─────────────────────────────────────

info "Creando servicio systemd: ${SERVICE_NAME}"

cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Remote Monitor Privileged Helper
After=network.target

[Service]
Type=simple
ExecStart=${PYTHON_BIN} -m helper.privileged_helper --socket ${SOCKET_PATH}
WorkingDirectory=${PROJECT_DIR}
Restart=on-failure
RestartSec=5

# Seguridad: limitar las capacidades del proceso.
NoNewPrivileges=no
ProtectSystem=strict
ReadWritePaths=/etc/hosts ${SOCKET_DIR}
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
EOF

# ── 4. Habilitar e iniciar el servicio ───────────────────────────────────────

info "Recargando configuración de systemd..."
systemctl daemon-reload

info "Habilitando e iniciando el servicio..."
systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}"

# ── 5. Verificar estado ─────────────────────────────────────────────────────

sleep 1
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    success "Helper privilegiado activo y ejecutándose."
else
    error "El servicio no se inició correctamente."
    echo "Ejecute: systemctl status ${SERVICE_NAME}"
    exit 1
fi

# ── Resumen ──────────────────────────────────────────────────────────────────

echo ""
success "¡Helper privilegiado configurado!"
echo ""
echo "  Socket UNIX: ${SOCKET_PATH}"
echo "  Servicio:    ${SERVICE_NAME}"
echo ""
echo "  Comandos útiles:"
echo "    sudo systemctl status ${SERVICE_NAME}"
echo "    sudo systemctl restart ${SERVICE_NAME}"
echo "    sudo ./setup_helper.sh --uninstall"
echo ""

