#!/usr/bin/env bash
#
# Script para generar certificados TLS autofirmados para el Sistema de
# Monitoreo y Administración Remota.
#
# Genera:
#   - Certificado de Autoridad Certificadora (CA) autofirmado (4096 bits, 365 días)
#   - Certificado del servidor firmado por la CA
#   - 3 certificados de cliente (client1, client2, client3) firmados por la CA
#
# Los certificados se almacenan en:
#   ~/.config/remote-monitor/certs/
#       ├── ca.crt                  # Certificado CA (público)
#       ├── ca.key                  # Clave CA (privado, permisos 600)
#       ├── server.crt              # Certificado del servidor
#       ├── server.key              # Clave del servidor (privado, permisos 600)
#       └── authorized_clients/
#           ├── client1.crt         # Certificados de clientes autorizados
#           ├── client1.key         # (privado, permisos 600)
#           ├── client2.crt
#           ├── client2.key
#           ├── client3.crt
#           └── client3.key
#
# Uso:
#   ./generate_certs.sh [directorio_base]
#
#       Si no se especifica directorio_base, se usa por defecto:
#       ~/.config/remote-monitor/certs
#
#       Se puede pasar un directorio personalizado como argumento (útil para
#       pruebas) sin afectar el directorio de configuración del usuario.
#
# Requisitos cubiertos: 11.2, 11.3, 17.5
#

set -euo pipefail

# ── Configuración ────────────────────────────────────────────────────────────

# Directorio base de certificados.
# Acepta override por argumento posicional (útil para pruebas); por defecto
# usa el directorio de configuración del usuario según el estándar XDG.
DEFAULT_CERT_DIR="${HOME}/.config/remote-monitor/certs"
CERT_DIR="${1:-${DEFAULT_CERT_DIR}}"
CLIENTS_DIR="${CERT_DIR}/authorized_clients"

# Parámetros de los certificados
RSA_KEY_SIZE=4096      # Tamaño de clave RSA en bits
DAYS=365               # Días de validez de los certificados

# Lista de clientes a generar
CLIENTS=("client1" "client2" "client3")

# ── Funciones de utilidad ────────────────────────────────────────────────────

# Imprime un mensaje informativo en verde
info() {
    echo -e "\033[32m[INFO]\033[0m $*"
}

# Imprime un mensaje de error en rojo
error() {
    echo -e "\033[31m[ERROR]\033[0m $*" >&2
}

# Imprime un mensaje de éxito en azul
success() {
    echo -e "\033[34m[OK]\033[0m $*"
}

# ── Verificación de dependencias ────────────────────────────────────────────

# Verificar que openssl esté instalado antes de continuar
if ! command -v openssl >/dev/null 2>&1; then
    error "openssl no está instalado en el sistema."
    error "Instálelo con uno de los siguientes comandos:"
    error "  sudo apt install openssl   (Debian/Ubuntu)"
    error "  sudo dnf install openssl    (Fedora/RHEL)"
    error "  sudo pacman -S openssl      (Arch Linux)"
    exit 1
fi

info "OpenSSL detectado: $(openssl version)"

# ── 1. Crear estructura de directorios ──────────────────────────────────────

info "Creando estructura de directorios en: ${CERT_DIR}"
mkdir -p "${CLIENTS_DIR}"

# ── 2. Generar certificado CA autofirmado ────────────────────────────────────
# Crea una clave privada RSA de 4096 bits y un certificado autofirmado válido
# por 365 días que actuará como Autoridad Certificadora raíz.

info "Generando certificado CA autofirmado (RSA ${RSA_KEY_SIZE} bits, ${DAYS} días)..."
openssl req -x509 -newkey "rsa:${RSA_KEY_SIZE}" \
    -keyout "${CERT_DIR}/ca.key" \
    -out "${CERT_DIR}/ca.crt" \
    -days "${DAYS}" \
    -nodes \
    -subj "/CN=Remote Monitor Root CA/O=Remote Monitor" \
    2>/dev/null

# ── 3. Generar certificado del servidor firmado por la CA ────────────────────
# El servidor necesita un certificado firmado por la CA para que los clientes
# puedan verificar su identidad durante el handshake TLS.

info "Generando certificado del servidor..."

# 3a. Crear solicitud de firma (CSR) y clave privada del servidor
openssl req -newkey "rsa:${RSA_KEY_SIZE}" \
    -keyout "${CERT_DIR}/server.key" \
    -out "${CERT_DIR}/server.csr" \
    -nodes \
    -subj "/CN=remote-monitor-server/O=Remote Monitor" \
    2>/dev/null

# 3b. Firmar el CSR con la CA para obtener el certificado del servidor
openssl x509 -req \
    -in "${CERT_DIR}/server.csr" \
    -CA "${CERT_DIR}/ca.crt" \
    -CAkey "${CERT_DIR}/ca.key" \
    -CAcreateserial \
    -out "${CERT_DIR}/server.crt" \
    -days "${DAYS}" \
    2>/dev/null

# ── 4. Generar certificados de cliente firmados por la CA ────────────────────
# Cada cliente necesita su propio certificado firmado por la CA. El servidor
# verificará los certificados de cliente presentados durante el handshake TLS
# contra la lista de certificados autorizados en el directorio authorized_clients/.

# Función para generar un certificado de cliente firmado por la CA
generar_cliente() {
    local nombre="$1"
    info "Generando certificado de cliente '${nombre}'..."

    # 4a. Crear solicitud de firma (CSR) y clave privada del cliente
    openssl req -newkey "rsa:${RSA_KEY_SIZE}" \
        -keyout "${CLIENTS_DIR}/${nombre}.key" \
        -out "${CLIENTS_DIR}/${nombre}.csr" \
        -nodes \
        -subj "/CN=${nombre}/O=Remote Monitor Client" \
        2>/dev/null

    # 4b. Firmar el CSR del cliente con la CA
    openssl x509 -req \
        -in "${CLIENTS_DIR}/${nombre}.csr" \
        -CA "${CERT_DIR}/ca.crt" \
        -CAkey "${CERT_DIR}/ca.key" \
        -CAcreateserial \
        -out "${CLIENTS_DIR}/${nombre}.crt" \
        -days "${DAYS}" \
        2>/dev/null
}

# Generar los 3 certificados de cliente
for cliente in "${CLIENTS[@]}"; do
    generar_cliente "${cliente}"
done

# ── 5. Configurar permisos 600 en todas las claves privadas ──────────────────
# Las claves privadas deben tener permisos 600 (lectura/escritura solo para el
# propietario) para proteger el material criptográfico sensible.

info "Configurando permisos 600 en claves privadas..."
chmod 600 "${CERT_DIR}/ca.key"
chmod 600 "${CERT_DIR}/server.key"
for cliente in "${CLIENTS[@]}"; do
    chmod 600 "${CLIENTS_DIR}/${cliente}.key"
done

# Los certificados públicos (.crt) pueden tener permisos 644 para ser legibles
# y distribuibles, ya que no contienen material secreto.
chmod 644 "${CERT_DIR}/ca.crt"
chmod 644 "${CERT_DIR}/server.crt"
for cliente in "${CLIENTS[@]}"; do
    chmod 644 "${CLIENTS_DIR}/${cliente}.crt"
done

# ── 6. Limpiar archivos temporales (CSR y serial) ───────────────────────────
# Las solicitudes de firma (CSR) y el archivo de número de serial (.srl) ya no
# son necesarios después de firmar los certificados.

info "Limpiando archivos temporales (CSR y serial)..."
rm -f "${CERT_DIR}/server.csr"
rm -f "${CERTS_DIR:-}" 2>/dev/null || true
rm -f "${CLIENTS_DIR}/"*.csr
rm -f "${CERT_DIR}/ca.srl"

# ── Resumen final ────────────────────────────────────────────────────────────

echo ""
success "¡Certificados generados correctamente en: ${CERT_DIR}"
echo ""
echo "  Estructura creada:"
echo "    ${CERT_DIR}/"
echo "    ├── ca.crt              (Certificado CA, público)"
echo "    ├── ca.key              (Clave CA, permisos 600)"
echo "    ├── server.crt          (Certificado del servidor)"
echo "    ├── server.key          (Clave del servidor, permisos 600)"
echo "    └── authorized_clients/"
for cliente in "${CLIENTS[@]}"; do
    echo "        ├── ${cliente}.crt          (Certificado de cliente)"
    echo "        ├── ${cliente}.key          (Clave de cliente, permisos 600)"
done
echo ""
info "Los certificados son válidos por ${DAYS} días."
info "Distribuya ca.crt y cada clientN.crt/key a las máquinas correspondientes."
