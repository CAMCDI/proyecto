"""Interfaz gráfica del cliente de monitoreo remoto.

Ventana principal visible, limpia e intuitiva con chat bidireccional,
transferencia de archivos, estado de conexión y diálogo de inicio fácil.
Sin emojis y con estilo profesional.

Requisitos: 15.3, 15.4, 3.1, 3.3-3.8, 8.2, 2.1-2.10.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout, QWidget, QComboBox,
)

__all__ = ["ClientMainWindow", "ConnectDialog", "ClientUI", "STYLE_SHEET"]

STYLE_SHEET = """
QMainWindow, QDialog, QWidget {
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
    padding: 7px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton#primary {
    background-color: #89b4fa;
    color: #11111b;
    font-weight: bold;
    border: none;
}
QPushButton#primary:hover {
    background-color: #b4befe;
}
QPushButton#danger {
    background-color: #f38ba8;
    color: #11111b;
    font-weight: bold;
    border: none;
}
QLineEdit, QTextEdit, QComboBox {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 6px 10px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #89b4fa;
}
QProgressBar {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #a6e3a1;
    border-radius: 3px;
}
"""


# ---------------------------------------------------------------------------
# Diálogo de Conexión Fácil (al abrir sin argumentos CLI)
# ---------------------------------------------------------------------------

class ConnectDialog(QDialog):
    """Diálogo gráfico sencillo para conectarse al servidor."""

    def __init__(self, default_host: str = "192.168.1.", default_token: str = "secreto123", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conectar al Servidor de Monitoreo")
        self.resize(380, 260)
        self.setStyleSheet(STYLE_SHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Conexion de Cliente Remoto")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        # Host
        layout.addWidget(QLabel("Direccion IP del Servidor:"))
        self.host_input = QLineEdit(default_host)
        self.host_input.setPlaceholderText("ejemplo: 192.168.1.50")
        layout.addWidget(self.host_input)

        # Token
        layout.addWidget(QLabel("Token de Autenticacion:"))
        self.token_input = QLineEdit(default_token)
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.token_input)

        # Cliente ID
        layout.addWidget(QLabel("Identificador de Cliente:"))
        self.client_id_combo = QComboBox()
        self.client_id_combo.addItems(["client1", "client2", "client3"])
        layout.addWidget(self.client_id_combo)

        # Botones
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_connect = QPushButton("Conectar")
        btn_connect.setObjectName("primary")
        btn_connect.clicked.connect(self._on_connect)
        btn_row.addWidget(btn_connect)

        layout.addLayout(btn_row)

    def _on_connect(self) -> None:
        if not self.host_input.text().strip():
            QMessageBox.warning(self, "Campo requerido", "Ingrese la IP del servidor.")
            return
        if not self.token_input.text().strip():
            QMessageBox.warning(self, "Campo requerido", "Ingrese el token de autenticacion.")
            return
        self.accept()

    def get_values(self) -> tuple[str, str, str]:
        return (
            self.host_input.text().strip(),
            self.token_input.text().strip(),
            self.client_id_combo.currentText(),
        )


# ---------------------------------------------------------------------------
# Overlay de Apagado (Pantalla Completa)
# ---------------------------------------------------------------------------

class ShutdownOverlay(QWidget):
    """Overlay de pantalla completa con cuenta regresiva de apagado."""

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
        self.setStyleSheet("background-color: rgba(15, 15, 25, 230);")

        title = QLabel("APAGADO REMOTO PROGRAMADO")
        title.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #f38ba8; background: transparent;")
        layout.addWidget(title)

        self._countdown_label = QLabel(f"{self._remaining}")
        self._countdown_label.setFont(QFont("Segoe UI", 80, QFont.Weight.Bold))
        self._countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_label.setStyleSheet("color: #cdd6f4; background: transparent;")
        layout.addWidget(self._countdown_label)

        subtitle = QLabel("segundos restantes para apagar el equipo")
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
# Ventana Principal del Cliente
# ---------------------------------------------------------------------------

class ClientMainWindow(QMainWindow):
    """Ventana principal visible del agente cliente."""
    message_sent = pyqtSignal(str)
    send_file_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cliente - Monitor y Administracion Remota")
        self.resize(600, 520)
        self.setStyleSheet(STYLE_SHEET)
        self._download_dir = str(Path.home() / "Descargas")
        self._setup_ui()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Barra de estado superior
        top_frame = QFrame()
        top_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px; padding: 6px;")
        tf_layout = QHBoxLayout(top_frame)

        self._status_indicator = QLabel("[Conectando...]")
        self._status_indicator.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._status_indicator.setStyleSheet("color: #fab387;")
        tf_layout.addWidget(self._status_indicator)

        self._info_label = QLabel("Servidor: -- | Cliente: --")
        self._info_label.setStyleSheet("color: #a6adc8;")
        tf_layout.addWidget(self._info_label)

        tf_layout.addStretch()

        self._disconnect_btn = QPushButton("Desconectar")
        self._disconnect_btn.setObjectName("danger")
        self._disconnect_btn.clicked.connect(self.disconnect_requested.emit)
        tf_layout.addWidget(self._disconnect_btn)

        layout.addWidget(top_frame)

        # Banner de bloqueo (visible solo si el mouse/teclado estan bloqueados)
        self._lock_banner = QLabel("DISPOSITIVOS DE ENTRADA BLOQUEADOS POR EL ADMINISTRADOR")
        self._lock_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lock_banner.setStyleSheet("background-color: #f38ba8; color: #11111b; font-weight: bold; padding: 6px; border-radius: 4px;")
        self._lock_banner.setVisible(False)
        layout.addWidget(self._lock_banner)

        # Seccion de Chat
        layout.addWidget(QLabel("Chat con el Administrador (Servidor):"))
        self._chat_area = QTextEdit()
        self._chat_area.setReadOnly(True)
        layout.addWidget(self._chat_area)

        chat_input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Escriba un mensaje para el servidor...")
        self._input.returnPressed.connect(self._send_chat)
        chat_input_row.addWidget(self._input)

        send_btn = QPushButton("Enviar")
        send_btn.setObjectName("primary")
        send_btn.clicked.connect(self._send_chat)
        chat_input_row.addWidget(send_btn)
        layout.addLayout(chat_input_row)

        # Seccion de Archivos
        files_frame = QFrame()
        files_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px; padding: 8px;")
        ff_layout = QVBoxLayout(files_frame)

        ff_title = QLabel("Transferencia de Archivos:")
        ff_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        ff_layout.addWidget(ff_title)

        files_btn_row = QHBoxLayout()
        send_file_btn = QPushButton("Enviar Archivo al Servidor...")
        send_file_btn.clicked.connect(self._select_file)
        files_btn_row.addWidget(send_file_btn)

        open_down_btn = QPushButton("Abrir Carpeta de Descargas")
        open_down_btn.clicked.connect(self._open_downloads)
        files_btn_row.addWidget(open_down_btn)
        files_btn_row.addStretch()
        ff_layout.addLayout(files_btn_row)

        self._file_status_label = QLabel("Archivos recibidos se guardan en Descargas")
        self._file_status_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        ff_layout.addWidget(self._file_status_label)

        layout.addWidget(files_frame)

    def _send_chat(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if len(text) > 1000:
            QMessageBox.warning(self, "Mensaje largo", "El mensaje no puede superar 1000 caracteres.")
            return
        self._input.clear()
        self.add_chat_message("Yo", text)
        self.message_sent.emit(text)

    def add_chat_message(self, sender: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._chat_area.append(f"[{ts}] {sender}: {message}")
        sb = self._chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _select_file(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo para enviar al servidor")
        if filepath:
            filename = Path(filepath).name
            self._file_status_label.setText(f"Enviando archivo: {filename}...")
            self.send_file_requested.emit(filepath)

    def _open_downloads(self) -> None:
        p = Path(self._download_dir)
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def set_connected(self, server_host: str, client_id: str) -> None:
        self._status_indicator.setText("[CONECTADO]")
        self._status_indicator.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        self._info_label.setText(f"Servidor: {server_host} | ID: {client_id}")

    def set_disconnected(self) -> None:
        self._status_indicator.setText("[DESCONECTADO]")
        self._status_indicator.setStyleSheet("color: #f38ba8; font-weight: bold;")

    def set_input_locked(self, locked: bool) -> None:
        self._lock_banner.setVisible(locked)

    def notify_file_received(self, filepath: str) -> None:
        name = Path(filepath).name
        self._file_status_label.setText(f"Archivo recibido con exito: {name}")
        self.add_chat_message("Sistema", f"Archivo recibido del servidor: {name}")


# ---------------------------------------------------------------------------
# Controlador UI del Cliente
# ---------------------------------------------------------------------------

class ClientUI:
    """Gestiona la ventana del cliente y notificaciones."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._app.setStyleSheet(STYLE_SHEET)
        self.window = ClientMainWindow()
        self._shutdown_overlay: Optional[ShutdownOverlay] = None

        # Mostrar la ventana principal de inmediato
        self.window.show()

    def set_connected(self, server_info: dict, hostname: str, client_id: str) -> None:
        srv_name = server_info.get("hostname", "Servidor")
        self.window.set_connected(srv_name, client_id)

    def set_disconnected(self) -> None:
        self.window.set_disconnected()

    def show_chat_message(self, sender: str, message: str) -> None:
        self.window.add_chat_message(sender, message)
        # Traer al frente si estaba oculta
        self.window.raise_()
        self.window.activateWindow()

    def show_shutdown_overlay(self, seconds: int) -> None:
        if self._shutdown_overlay:
            self._shutdown_overlay.close()
        self._shutdown_overlay = ShutdownOverlay(seconds)

    def notify_file_received(self, filepath: str) -> None:
        self.window.notify_file_received(filepath)

    def set_input_locked(self, locked: bool) -> None:
        self.window.set_input_locked(locked)
