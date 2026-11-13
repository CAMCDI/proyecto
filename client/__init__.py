"""Paquete del agente cliente de monitoreo remoto.

Contiene los módulos del agente instalado en las máquinas a monitorear:
- main.py: punto de entrada del cliente.
- agent.py: lógica de red (conexión TLS, autenticación, bucle de mensajes).
- ui.py: interfaz mínima (bandeja del sistema, ventanas de chat y overlays).
- screen_capture.py: captura de pantalla con mss y compresión JPEG.
- executors.py: ejecutores de comandos recibidos del servidor.
- watchdog.py: mecanismo de seguridad para desbloqueo automático ante desconexión.

El agente se ejecuta con privilegios de usuario normal; las operaciones
privilegiadas se delegan al paquete ``helper`` (separación de privilegios).

Requisitos: 18.1, 18.4, 13.1.
"""
