"""Paquete de módulos comunes reutilizables por servidor y cliente.

Contiene la lógica compartida por ambos extremos de la comunicación:

- protocol.py: definición del Remote_Control_Protocol (serialización JSON con
  framing de 4 bytes big-endian, validación y lista blanca de comandos).
- crypto.py: funciones de TLS (creación de contextos) y autenticación
  (hashing argon2id, generación de tokens).
- utils.py: utilidades comunes (validación de dominios y rutas, sanitización,
  métricas del sistema, formateo y rate limiting).

Requisitos: 18.1, 18.2.
"""
