"""Paquete del servidor de administración remota.

Contiene los módulos que conforman la aplicación servidora:
- main.py: punto de entrada y coordinación del bucle de eventos asyncio.
- ui.py: interfaz gráfica PyQt6 (ventana principal, panel de clientes, pestañas).
- client_manager.py: gestión de conexiones TLS con hasta 3 clientes simultáneos.
- logger.py: registro de auditoría de acciones (Action_Log) del servidor.
- file_handler.py: lógica de transferencia bidireccional de archivos con verificación SHA-256.

Requisitos: 18.1, 18.3.
"""
