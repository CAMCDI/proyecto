"""Interfaz gráfica mínima del cliente de monitoreo remoto.

Incluye un icono en la bandeja del sistema (system tray), ventana de chat
bidireccional, overlay de cuenta regresiva para apagado y ventana de estado.

Requisitos: 15.3, 15.4, 3.1, 3.3-3.8, 8.2.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QAction
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)

__all__ = ["ClientUI"]

# ---------------------------------------------------------------------------
# Paleta de colores (misma que el servidor — Catppuccin Mocha)
# ---------------------------------------------------------------------------
STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #45475a;
}
QLineEdit, QTextEdit {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 4px 8px;
}
QLabel {
    color: #cdd6f4;
}
"""


def _make_tray_icon(color: str = "#a6e3a1") -> QIcon:
    """Crea un icono de bandeja del sistema (círculo de color)."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 24, 24)
    painter.end()
    return QIcon(pix)


# ---------------------------------------------------------------------------
# ChatWindow
# ---------------------------------------------------------------------------

class ChatWindow(QWidget):
    """Ventana de chat bidireccional con el servidor.

    Requisito: 3.1, 3.3-3.8, 3.10.
    """
    message_sent = pyqtSignal(str)

    MAX_HISTORY = 200

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chat — Monitor Remoto")
        self.resize(450, 400)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._chat_area = QTextEdit()
        self._chat_area.setReadOnly(True)
        layout.addWidget(self._chat_area)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Escriba un mensaje... (máx. 1000 caracteres)")
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input)

        send_btn = QPushButton("Enviar")
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)

        layout.addLayout(input_row)

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if len(text) > 1000:
            QMessageBox.warning(self, "Mensaje muy largo", "El mensaje no puede superar 1000 caracteres.")
            return
        self._input.clear()
        self.add_message("Tú", text)
        self.message_sent.emit(text)

    def add_message(self, sender: str, message: str) -> None:
        """Agrega un mensaje al historial."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {sender}: {message}"
        self._chat_area.append(line)
        sb = self._chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())


# ---------------------------------------------------------------------------
# ShutdownOverlay
# ---------------------------------------------------------------------------

class ShutdownOverlay(QWidget):
    """Overlay de pantalla completa con cuenta regresiva de apagado.

    Requisito: 8.2.
    """

    def __init__(self, seconds: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._remaining = seconds
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.showFullScreen()
        self._setup_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setStyleSheet("background-color: rgba(0, 0, 0, 180);")

        icon_label = QLabel("⚠️")
        icon_label.setFont(QFont("Segoe UI", 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("color: #f38ba8; background: transparent;")
        layout.addWidget(icon_label)

        title = QLabel("APAGADO REMOTO PROGRAMADO")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #f38ba8; background: transparent;")
        layout.addWidget(title)

        self._countdown_label = QLabel(f"{self._remaining}")
        self._countdown_label.setFont(QFont("Segoe UI", 72, QFont.Weight.Bold))
        self._countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_label.setStyleSheet("color: #cdd6f4; background: transparent;")
        layout.addWidget(self._countdown_label)

        subtitle = QLabel("segundos restantes")
        subtitle.setFont(QFont("Segoe UI", 16))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #a6adc8; background: transparent;")
        layout.addWidget(subtitle)

    def _tick(self) -> None:
        self._remaining -= 1
        self._countdown_label.setText(str(max(0, self._remaining)))
        if self._remaining <= 0:
            self._timer.stop()
            self.close()


# ---------------------------------------------------------------------------
# StatusWindow
# ---------------------------------------------------------------------------

class StatusWindow(QWidget):
    """Ventana de estado de conexión del cliente.

    Requisito: 15.4.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Estado — Monitor Remoto")
        self.resize(350, 250)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Estado de Conexión")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        self._status_label = QLabel("Estado: Desconectado")
        self._status_label.setFont(QFont("Segoe UI", 12))
        self._status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
        layout.addWidget(self._status_label)

        self._server_label = QLabel("Servidor: —")
        self._hostname_label = QLabel("Hostname: —")
        self._client_id_label = QLabel("Client ID: —")

        for lbl in (self._server_label, self._hostname_label, self._client_id_label):
            lbl.setStyleSheet("color: #a6adc8;")
            layout.addWidget(lbl)

        layout.addStretch()

    def update_status(
        self,
        connected: bool,
        server_info: dict | None = None,
        hostname: str = "",
        client_id: str = "",
    ) -> None:
        if connected:
            self._status_label.setText("Estado: ✅ Conectado")
            self._status_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        else:
            self._status_label.setText("Estado: ❌ Desconectado")
            self._status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")

        if server_info:
            self._server_label.setText(
                f"Servidor: {server_info.get('hostname', '—')}"
            )
        self._hostname_label.setText(f"Hostname: {hostname or '—'}")
        self._client_id_label.setText(f"Client ID: {client_id or '—'}")


# ---------------------------------------------------------------------------
# ClientUI — Contenedor principal
# ---------------------------------------------------------------------------

class ClientUI:
    """Gestiona todas las ventanas de la UI del cliente.

    Integra la bandeja del sistema, chat, overlay de apagado y estado.

    Requisito: 15.3, 15.4.
    """

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._app.setStyleSheet(STYLE_SHEET)
        self._app.setQuitOnLastWindowClosed(False)

        # Ventanas.
        self._chat_window = ChatWindow()
        self._status_window = StatusWindow()
        self._shutdown_overlay: Optional[ShutdownOverlay] = None

        # Bandeja del sistema.
        self._tray = QSystemTrayIcon(_make_tray_icon("#6c7086"), self._app)
        self._setup_tray_menu()
        self._tray.show()

        # Callbacks.
        self._on_send_chat: Optional[Callable[[str], None]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None

        # Conectar señal de chat.
        self._chat_window.message_sent.connect(self._handle_chat_send)

    def _setup_tray_menu(self) -> None:
        menu = QMenu()

        chat_action = QAction("💬 Chat", self._app)
        chat_action.triggered.connect(self._chat_window.show)
        menu.addAction(chat_action)

        status_action = QAction("📊 Estado", self._app)
        status_action.triggered.connect(self._status_window.show)
        menu.addAction(status_action)

        menu.addSeparator()

        disconnect_action = QAction("🔌 Desconectar", self._app)
        disconnect_action.triggered.connect(self._handle_disconnect)
        menu.addAction(disconnect_action)

        exit_action = QAction("❌ Salir", self._app)
        exit_action.triggered.connect(self._app.quit)
        menu.addAction(exit_action)

        self._tray.setContextMenu(menu)

    def _handle_chat_send(self, text: str) -> None:
        if self._on_send_chat:
            self._on_send_chat(text)

    def _handle_disconnect(self) -> None:
        if self._on_disconnect:
            self._on_disconnect()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def set_on_send_chat(self, callback: Callable[[str], None]) -> None:
        self._on_send_chat = callback

    def set_on_disconnect(self, callback: Callable[[], None]) -> None:
        self._on_disconnect = callback

    def set_connected(self, server_info: dict, hostname: str, client_id: str) -> None:
        """Actualiza la UI al conectarse al servidor."""
        self._tray.setIcon(_make_tray_icon("#a6e3a1"))
        self._tray.setToolTip(f"Monitor Remoto — Conectado ({hostname})")
        self._status_window.update_status(True, server_info, hostname, client_id)
        self._tray.showMessage(
            "Monitor Remoto",
            f"Conectado al servidor como {hostname}",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def set_disconnected(self) -> None:
        """Actualiza la UI al desconectarse."""
        self._tray.setIcon(_make_tray_icon("#f38ba8"))
        self._tray.setToolTip("Monitor Remoto — Desconectado")
        self._status_window.update_status(False)

    def show_chat_message(self, sender: str, message: str) -> None:
        """Muestra un mensaje de chat recibido."""
        self._chat_window.add_message(sender, message)

    def show_shutdown_overlay(self, seconds: int) -> None:
        """Muestra el overlay de cuenta regresiva de apagado. Requisito 8.2."""
        if self._shutdown_overlay:
            self._shutdown_overlay.close()
        self._shutdown_overlay = ShutdownOverlay(seconds)

