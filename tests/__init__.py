"""Paquete de pruebas del sistema de monitoreo remoto.

Contiene pruebas unitarias, basadas en propiedades (Hypothesis) y de
integración para los módulos críticos:

- test_protocol.py: pruebas de serialización, framing y validación del protocolo.
- test_crypto.py: pruebas de TLS y utilidades de autenticación.
- test_validation.py: pruebas de validación y sanitización de entradas.
- test_integration.py: pruebas de integración simuladas.

Las pruebas basadas en propiedades usan la librería Hypothesis con un mínimo
de 100 iteraciones y referencian la propiedad del documento de diseño mediante
comentarios con el formato:
    # Feature: remote-monitoring-admin-system, Property N: <descripción>

Requisitos: 18.1, 18.7.
"""
