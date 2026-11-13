# Sistema de Monitoreo y Administración Remota

Sistema cliente-servidor para monitorear y controlar hasta **3 clientes Linux**
simultáneamente sobre una red LAN con comunicación segura (TLS). Diseñado para
prácticas universitarias de redes e instrumentación.

## Características principales

- **Streaming de pantalla en tiempo real**: captura a 5-10 FPS con compresión
  JPEG ajustable y resolución configurable.
- **Transferencia bidireccional de archivos**: transferencia por bloques de
  64 KB con verificación de integridad SHA-256.
- **Chat bidireccional en tiempo real**: mensajería entre servidor y cada cliente.
- **Control remoto de dispositivos de entrada**: bloqueo/desbloqueo de teclado
  y mouse mediante `xinput`.
- **Administración de red**: bloqueo de dominios (`/etc/hosts`) y control de
  respuesta ICMP (`sysctl`).
- **Gestión de energía**: apagado remoto con cuenta regresiva.
- **Panel de múltiples clientes**: estado, métricas (CPU/RAM) y miniaturas de
  los 3 clientes conectados.
- **Seguridad**: cifrado TLS, autenticación con tokens argon2id y arquitectura
  de separación de privilegios.
- **Registro de auditoría**: logs de acciones en servidor y cliente.

## Requisitos del sistema

- **Sistema operativo**: Linux con X11 (Ubuntu 22.04, Debian 13 o similar).
  Wayland tiene soporte limitado (el bloqueo de input no está soportado).
- **Python**: 3.11 o superior.
- **OpenSSL**: para la generación de certificados.
- **xinput**: para el bloqueo de dispositivos de entrada (X11).
- **sudo** (en clientes): para la configuración del helper privilegiado.

## Estructura del proyecto

```
proyecto/
├── server/      # Aplicación servidora (UI PyQt6, gestor de clientes, log)
│   ├── main.py
│   ├── ui.py
│   ├── client_manager.py
│   ├── logger.py
│   └── file_handler.py
├── client/      # Agente cliente (UI mínima, ejecutores, captura de pantalla)
│   ├── main.py
│   ├── agent.py
│   ├── ui.py
│   ├── screen_capture.py
│   ├── executors.py
│   └── watchdog.py
├── helper/      # Helper privilegiado mínimo (proceso separado)
│   ├── privileged_helper.py
│   └── commands.py
├── common/      # Módulos comunes (protocolo, cifrado, utilidades)
│   ├── protocol.py
│   ├── crypto.py
│   └── utils.py
├── scripts/     # Scripts de certificados, instalación y systemd
│   ├── generate_certs.sh
│   ├── install.sh
│   └── setup_helper.sh
├── tests/       # Pruebas unitarias, de propiedades e integración
│   ├── test_protocol.py
│   ├── test_crypto.py
│   ├── test_validation.py
│   └── test_integration.py
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Instalación

### 1. Crear y activar el entorno virtual

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Instalar dependencias

```bash
# Dependencias de producción
pip install -r requirements.txt

# Dependencias de desarrollo (incluye las de producción + pruebas)
pip install -r requirements-dev.txt
```

### 3. Generar certificados TLS

```bash
./scripts/generate_certs.sh
```

Esto crea los certificados en `~/.config/remote-monitor/certs/`.

### 4. Generar token de autenticación

```bash
python -m common.crypto generate-token
```

### 5. Configurar e iniciar

Consulte el documento de diseño para la configuración detallada de
`server_config.json` y `client_config.json`.

```bash
# En el servidor
python server/main.py

# En cada cliente
python client/main.py
```

## Arquitectura de seguridad

- **Cifrado TLS**: certificados autofirmados X.509 válidos por 365 días.
- **Autenticación**: tokens derivados de contraseña mediante argon2id con sal
  única; el servidor verifica el certificado del cliente contra una lista de
  certificados autorizados.
- **Separación de privilegios**: el agente cliente se ejecuta como usuario
  normal; las operaciones privilegiadas se delegan a un helper separado con
  lista blanca estricta de comandos.
- **Validación de entradas**: sanitización de path traversal, inyección de
  comandos y XSS, con rate limiting de 100 mensajes/segundo por cliente.

## Limitaciones conocidas

- **Wayland**: el bloqueo de dispositivos de entrada no está soportado; se
  requiere X11.
- **Máximo 3 clientes**: el servidor está diseñado para un máximo de 3
  conexiones simultáneas.
- **Alcance de red**: diseñado para despliegue en LAN.

## Pruebas

```bash
# Ejecutar todas las pruebas
pytest

# Ejecutar con cobertura
pytest --cov
```

Las pruebas basadas en propiedades usan la librería Hypothesis con un mínimo
de 100 iteraciones por propiedad.

## Licencia

Proyecto educativo para prácticas universitarias.
