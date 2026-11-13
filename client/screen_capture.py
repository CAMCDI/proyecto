"""Captura de pantalla con mss y compresión JPEG.

Captura el contenido del escritorio usando la librería ``mss`` (compatible
con X11) y lo comprime en formato JPEG con calidad y resolución ajustables.
La imagen resultante se codifica en base64 para su envío por el protocolo.

Requisitos: 1.1, 1.2, 1.4, 1.5, 1.6.
"""

from __future__ import annotations

import asyncio
import base64
import io
import threading
from typing import Callable, Optional

import mss
from PIL import Image

__all__ = ["ScreenCapture"]

# Valores por defecto.
DEFAULT_QUALITY: int = 70
DEFAULT_FPS: int = 8
DEFAULT_RESOLUTION: tuple[int, int] | None = None  # None = resolución nativa


class ScreenCapture:
    """Captura de pantalla continua con compresión JPEG.

    Ejecuta la captura en un hilo separado para no bloquear el event loop
    de asyncio. Los frames capturados se entregan al callback proporcionado
    como cadenas base64.

    Requisitos: 1.1, 1.2, 1.4, 1.5.
    """

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._quality: int = DEFAULT_QUALITY
        self._fps: int = DEFAULT_FPS
        self._resolution: Optional[tuple[int, int]] = DEFAULT_RESOLUTION
        self._frame_callback: Optional[Callable[[str], None]] = None
        self._lock = threading.Lock()

    def start(
        self,
        callback: Callable[[str], None],
        quality: int = DEFAULT_QUALITY,
        fps: int = DEFAULT_FPS,
        resolution: Optional[tuple[int, int]] = None,
    ) -> None:
        """Inicia la captura de pantalla en un hilo separado.

        Args:
            callback: Función invocada con cada frame como cadena base64.
            quality: Calidad JPEG (1-95). Requisito 1.4.
            fps: Frames por segundo objetivo (1-30). Requisito 1.5.
            resolution: Tupla ``(ancho, alto)`` o ``None`` para nativa.

        Requisito: 1.1, 1.4, 1.5.
        """
        if self._running:
            self.stop()

        self._quality = max(1, min(95, quality))
        self._fps = max(1, min(30, fps))
        self._resolution = resolution
        self._frame_callback = callback
        self._running = True

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Detiene la captura de pantalla."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def update_config(
        self,
        quality: Optional[int] = None,
        fps: Optional[int] = None,
        resolution: Optional[tuple[int, int]] = None,
    ) -> None:
        """Actualiza los parámetros de captura en caliente.

        Requisito: 1.6.
        """
        with self._lock:
            if quality is not None:
                self._quality = max(1, min(95, quality))
            if fps is not None:
                self._fps = max(1, min(30, fps))
            if resolution is not None:
                self._resolution = resolution

    @property
    def is_running(self) -> bool:
        return self._running

    def _capture_loop(self) -> None:
        """Bucle principal de captura ejecutado en un hilo separado.

        Captura el monitor principal con ``mss``, escala si es necesario,
        comprime en JPEG y entrega al callback como base64.

        Requisito: 1.1, 1.2, 1.4.
        """
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Monitor principal.
                while self._running:
                    with self._lock:
                        quality = self._quality
                        fps = self._fps
                        resolution = self._resolution

                    interval = 1.0 / fps

                    # Capturar pantalla.
                    screenshot = sct.grab(monitor)

                    # Convertir a imagen PIL.
                    image = Image.frombytes(
                        "RGB",
                        (screenshot.width, screenshot.height),
                        screenshot.rgb,
                    )

                    # Escalar si se especificó una resolución (Requisito 1.6).
                    if resolution:
                        image = image.resize(
                            resolution, Image.Resampling.LANCZOS
                        )

                    # Comprimir a JPEG (Requisito 1.4).
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG", quality=quality)
                    jpeg_bytes = buffer.getvalue()

                    # Codificar en base64 y entregar al callback.
                    frame_b64 = base64.b64encode(jpeg_bytes).decode("ascii")
                    if self._frame_callback:
                        try:
                            self._frame_callback(frame_b64)
                        except Exception:
                            pass

                    # Esperar para mantener el FPS objetivo.
                    import time
                    time.sleep(interval)

        except Exception:
            self._running = False

