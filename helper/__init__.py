"""Paquete del helper privilegiado del cliente.

Proceso separado con privilegios elevados que ejecuta únicamente operaciones
que requieren superusuario, comunicándose con el agente cliente mediante un
socket UNIX con permisos 600:

- privileged_helper.py: proceso principal que escucha solicitudes en el socket.
- commands.py: definición y validación de los comandos de la lista blanca
  (shutdown, block_domain, unblock_domain, disable_ping, enable_ping,
  lock_input, unlock_input).

Principio de menor privilegio: solo se aceptan comandos de la lista blanca con
validación estricta de parámetros y rechazo de metacaracteres de shell.

Requisitos: 18.1, 18.5, 13.1, 13.4, 13.7.
"""
