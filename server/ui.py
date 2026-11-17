"""Interfaz gráfica del servidor — PyQt6.

Panel principal con barra lateral de 3 slots de clientes y pestañas de control:
Pantalla, Chat, Archivos, Control, Red y Log de auditoria.
Diseñada sin emojis, con controles directos e intuitivos y visor de pantalla
con relacion de aspecto fija y controlada.

Requisitos: 15.1, 15.2, 15.10, 4.1-4.10, 1.1-1.7, 3.1-3.10, 2.1-2.10,
            6.1-6.2, 7.1-7.2, 8.1-8.3, 9.1-9.3, 10.1-10.2, 5.1-5.5.
"""

from __future__ import annotations

import base64
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap, QPainter, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSizePolicy, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget, QComboBox, QHeaderView,
)

# ---------------------------------------------------------------------------
# Estilo de la interfaz (Tema Oscuro Profesional)
# ---------------------------------------------------------------------------
STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #313244;
    background-color: #1e1e2e;
}
QTabBar::tab {
    background-color: #181825;
    color: #a6adc8;
    padding: 8px 18px;
    border: 1px solid #313244;
    border-bottom: none;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
    border-bottom: 2px solid #89b4fa;
    font-weight: bold;
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
QPushButton:pressed {
    background-color: #585b70;
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
QPushButton#danger:hover {
    background-color: #eb6f92;
}
QPushButton#success {
    background-color: #a6e3a1;
    color: #11111b;
    font-weight: bold;
    border: none;
}
QPushButton#success:hover {
    background-color: #94e2d5;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 5px 9px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #89b4fa;
}
QListWidget, QTableWidget {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    alternate-background-color: #1e1e2e;
    gridline-color: #313244;
}
QHeaderView::section {
    background-color: #313244;
    color: #cdd6f4;
    padding: 6px;
    border: 1px solid #45475a;
    font-weight: bold;
}
QProgressBar {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 3px;
}
"""

COLOR_CONNECTED = "#a6e3a1"
COLOR_DISCONNECTED = "#6c7086"
COLOR_SELECTED = "#89b4fa"


def _make_status_pixmap(color: str, size: int = 14) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return pix


# ---------------------------------------------------------------------------
# Visor de Pantalla Remota (Sin bucles de zoom, centrado y aspect ratio fijo)
# ---------------------------------------------------------------------------

class ScreenViewer(QWidget):
    """Visor de pantalla remota profesional.

    Mantiene la relación de aspecto sin cambiar el tamaño del layout de Qt,
    evitando por completo el efecto de zoom infinito o crecimiento descontrolado.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pixmap: Optional[QPixmap] = None
        self._placeholder: str = "Seleccione un cliente y presione 'Iniciar Streaming'"

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self._pixmap = None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11111b"))

        if self._pixmap and not self._pixmap.isNull():
            # Escala manteniendo la relacion de aspecto dentro de la ventana actual
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Centra la imagen
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(QColor("#6c7086"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)


# ---------------------------------------------------------------------------
# ClientSlot
# ---------------------------------------------------------------------------

class ClientSlot(QFrame):
    """Slot de cliente en la barra lateral."""
    clicked = pyqtSignal(int)

    def __init__(self, slot_index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.slot_index = slot_index
        self._selected = False
        self._client_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._update_border()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        # Fila de estado + nombre
        header = QHBoxLayout()
        self._status_icon = QLabel()
        self._status_icon.setPixmap(_make_status_pixmap(COLOR_DISCONNECTED))
        self._status_icon.setFixedSize(14, 14)
        header.addWidget(self._status_icon)

        self._hostname_label = QLabel(f"Slot {self.slot_index + 1} - Libre")
        self._hostname_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(self._hostname_label)
        header.addStretch()
        layout.addLayout(header)

        # Miniatura
        self._thumbnail = QLabel()
        self._thumbnail.setFixedSize(160, 90)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail.setStyleSheet("background-color: #11111b; border-radius: 4px; color: #6c7086;")
        self._thumbnail.setText("Sin señal")
        layout.addWidget(self._thumbnail, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Info
        self._ip_label = QLabel("IP: --")
        self._os_label = QLabel("SO: --")
        self._cpu_label = QLabel("CPU: --")
        self._ram_label = QLabel("RAM: --")
        for lbl in (self._ip_label, self._os_label, self._cpu_label, self._ram_label):
            lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
            layout.addWidget(lbl)

    def _update_border(self) -> None:
        border_color = COLOR_SELECTED if self._selected else "#313244"
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #181825;
                border: 2px solid {border_color};
                border-radius: 8px;
                margin: 2px;
            }}
        """)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.slot_index)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_border()

    def update_data(self, session_data: dict) -> None:
        connected = session_data.get("connected", False)
        self._client_id = session_data.get("client_id") if connected else None
        hostname = session_data.get("hostname", f"Slot {self.slot_index + 1}")
        ip = session_data.get("ip_address", "--")
        os_info = session_data.get("os_info", {})
        os_name = os_info.get("os_name", "--")
        metrics = session_data.get("metrics", {})
        cpu = metrics.get("cpu_percent", "--")
        ram = metrics.get("memory_percent", "--")

        color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        self._status_icon.setPixmap(_make_status_pixmap(color))
        self._hostname_label.setText(hostname if connected else f"Slot {self.slot_index + 1} - Libre")
        self._ip_label.setText(f"IP: {ip}")
        self._os_label.setText(f"SO: {os_name}")
        self._cpu_label.setText(f"CPU: {cpu}%" if isinstance(cpu, (int, float)) else "CPU: --")
        self._ram_label.setText(f"RAM: {ram}%" if isinstance(ram, (int, float)) else "RAM: --")

        if not connected:
            self._thumbnail.setText("Sin señal")
            self._thumbnail.setPixmap(QPixmap())

    def update_thumbnail(self, jpeg_b64: str) -> None:
        try:
            data = base64.b64decode(jpeg_b64)
            image = QImage.fromData(data)
            pix = QPixmap.fromImage(image).scaled(
                160, 90,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumbnail.setPixmap(pix)
        except Exception:
            pass

    def get_client_id(self) -> Optional[str]:
        return self._client_id


# ---------------------------------------------------------------------------
# ClientPanel
# ---------------------------------------------------------------------------

class ClientPanel(QWidget):
    """Panel lateral con los 3 slots de clientes."""
    client_selected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._slots: list[ClientSlot] = []
        self._selected_client_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        title = QLabel("Clientes Conectados")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #89b4fa; padding: 4px;")
        layout.addWidget(title)

        for i in range(3):
            slot = ClientSlot(i)
            slot.clicked.connect(self._on_slot_clicked)
            self._slots.append(slot)
            layout.addWidget(slot)

        layout.addStretch()

    def _on_slot_clicked(self, slot_index: int) -> None:
        slot = self._slots[slot_index]
        client_id = slot.get_client_id()
        if client_id:
            self.select_slot(slot_index)

    def select_slot(self, slot_index: int) -> None:
        slot = self._slots[slot_index]
        client_id = slot.get_client_id()
        if client_id:
            self._selected_client_id = client_id
            for s in self._slots:
                s.set_selected(s.slot_index == slot_index)
            self.client_selected.emit(client_id)

    def update_slot(self, slot_index: int, session_data: dict) -> None:
        if 0 <= slot_index < 3:
            self._slots[slot_index].update_data(session_data)

    def update_thumbnail(self, slot_index: int, jpeg_b64: str) -> None:
        if 0 <= slot_index < 3:
            self._slots[slot_index].update_thumbnail(jpeg_b64)

    def get_selected_client_id(self) -> Optional[str]:
        return self._selected_client_id


# ---------------------------------------------------------------------------
# ScreenTab
# ---------------------------------------------------------------------------

class ScreenTab(QWidget):
    """Pestaña de visualización de escritorio remoto."""
    screen_start_requested = pyqtSignal(str, int, int)
    screen_stop_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._streaming = False
        self._frame_count = 0
        self._last_fps_time = datetime.now()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Visor de pantalla personalizado
        self._viewer = ScreenViewer()
        layout.addWidget(self._viewer)

        # Controles
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Resolucion:"))
        self._resolution_combo = QComboBox()
        self._resolution_combo.addItems(["640x480", "800x600", "1024x768", "Nativa"])
        self._resolution_combo.setCurrentIndex(2)
        controls.addWidget(self._resolution_combo)

        controls.addWidget(QLabel("Calidad:"))
        self._quality_slider = QSlider(Qt.Orientation.Horizontal)
        self._quality_slider.setRange(40, 90)
        self._quality_slider.setValue(70)
        self._quality_slider.setFixedWidth(100)
        controls.addWidget(self._quality_slider)

        self._quality_label = QLabel("70")
        self._quality_slider.valueChanged.connect(lambda v: self._quality_label.setText(str(v)))
        controls.addWidget(self._quality_label)

        self._toggle_btn = QPushButton("Iniciar Streaming")
        self._toggle_btn.setObjectName("primary")
        self._toggle_btn.clicked.connect(self._toggle_streaming)
        controls.addWidget(self._toggle_btn)

        self._fps_label = QLabel("FPS: --")
        self._fps_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        controls.addWidget(self._fps_label)

        self._bw_label = QLabel("Ancho de banda: --")
        self._bw_label.setStyleSheet("color: #89b4fa;")
        controls.addWidget(self._bw_label)

        controls.addStretch()
        layout.addLayout(controls)

    def _toggle_streaming(self) -> None:
        self._streaming = not self._streaming
        if self._streaming:
            self._toggle_btn.setText("Detener Streaming")
            self._toggle_btn.setObjectName("danger")
            self._toggle_btn.setStyle(self._toggle_btn.style())
            res_str = self._resolution_combo.currentText()
            resolution = None if res_str == "Nativa" else res_str
            quality = self._quality_slider.value()
            self.screen_start_requested.emit(resolution or "native", quality, 8)
        else:
            self._toggle_btn.setText("Iniciar Streaming")
            self._toggle_btn.setObjectName("primary")
            self._toggle_btn.setStyle(self._toggle_btn.style())
            self.screen_stop_requested.emit()
            self._viewer.set_placeholder("Streaming detenido")
            self._fps_label.setText("FPS: --")
            self._bw_label.setText("Ancho de banda: --")

    def display_frame(self, jpeg_b64: str) -> None:
        try:
            data = base64.b64decode(jpeg_b64)
            image = QImage.fromData(data)
            pix = QPixmap.fromImage(image)
            self._viewer.set_pixmap(pix)
            self._frame_count += 1

            now = datetime.now()
            elapsed = (now - self._last_fps_time).total_seconds()
            if elapsed >= 1.0:
                fps = self._frame_count / elapsed
                self._fps_label.setText(f"FPS: {fps:.1f}")
                bw_kbs = (len(data) / 1024) * fps
                self._bw_label.setText(f"Ancho de banda: {bw_kbs:.0f} KB/s")
                self._frame_count = 0
                self._last_fps_time = now
        except Exception:
            pass

    def reset(self) -> None:
        self._streaming = False
        self._toggle_btn.setText("Iniciar Streaming")
        self._toggle_btn.setObjectName("primary")
        self._toggle_btn.setStyle(self._toggle_btn.style())
        self._viewer.set_placeholder("Seleccione un cliente y presione 'Iniciar Streaming'")
        self._fps_label.setText("FPS: --")
        self._bw_label.setText("Ancho de banda: --")


# ---------------------------------------------------------------------------
# ChatTab
# ---------------------------------------------------------------------------

class ChatTab(QWidget):
    """Pestaña de chat bidireccional en tiempo real."""
    message_sent = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._history: list[str] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._chat_area = QTextEdit()
        self._chat_area.setReadOnly(True)
        layout.addWidget(self._chat_area)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Escriba un mensaje para el cliente...")
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input)

        send_btn = QPushButton("Enviar Mensaje")
        send_btn.setObjectName("primary")
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)

        layout.addLayout(input_row)

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if len(text) > 1000:
            QMessageBox.warning(self, "Mensaje largo", "El mensaje no puede superar 1000 caracteres.")
            return
        self._input.clear()
        self.message_sent.emit(text)
        self.add_message("Servidor", text)

    def add_message(self, sender: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {sender}: {message}"
        self._history.append(line)
        self._chat_area.append(line)
        sb = self._chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_history(self) -> None:
        self._history.clear()
        self._chat_area.clear()


# ---------------------------------------------------------------------------
# FilesTab
# ---------------------------------------------------------------------------

class FilesTab(QWidget):
    """Pestaña de transferencia de archivos simplificada y directa."""
    send_file_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._download_dir = str(Path.home() / "Descargas")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Enviar archivo
        send_frame = QFrame()
        send_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 8px; }")
        sf_layout = QVBoxLayout(send_frame)

        sf_layout.addWidget(QLabel("Enviar Archivo al Cliente Seleccionado:"))
        row_send = QHBoxLayout()
        select_btn = QPushButton("Seleccionar y Enviar Archivo...")
        select_btn.setObjectName("primary")
        select_btn.clicked.connect(self._select_and_send)
        row_send.addWidget(select_btn)

        self._selected_file_label = QLabel("Ningun archivo seleccionado")
        self._selected_file_label.setStyleSheet("color: #a6adc8;")
        row_send.addWidget(self._selected_file_label)
        row_send.addStretch()
        sf_layout.addLayout(row_send)
        layout.addWidget(send_frame)

        # Progreso de transferencia
        prog_frame = QFrame()
        prog_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 8px; }")
        pf_layout = QVBoxLayout(prog_frame)
        pf_layout.addWidget(QLabel("Estado de Transferencia:"))

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        pf_layout.addWidget(self._progress_bar)

        row_info = QHBoxLayout()
        self._transfer_status_label = QLabel("Sin transferencias activas")
        self._transfer_status_label.setStyleSheet("color: #a6adc8;")
        row_info.addWidget(self._transfer_status_label)
        row_info.addStretch()

        open_dir_btn = QPushButton("Abrir Carpeta de Descargas")
        open_dir_btn.clicked.connect(self._open_downloads)
        row_info.addWidget(open_dir_btn)
        pf_layout.addLayout(row_info)
        layout.addWidget(prog_frame)

        # Historial de transferencias
        layout.addWidget(QLabel("Historial de Transferencias:"))
        self._transfer_table = QTableWidget(0, 4)
        self._transfer_table.setHorizontalHeaderLabels(["Fecha", "Archivo", "Tipo", "Estado"])
        self._transfer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._transfer_table.setAlternatingRowColors(True)
        self._transfer_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._transfer_table)

    def _select_and_send(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo para enviar al cliente")
        if filepath:
            filename = Path(filepath).name
            self._selected_file_label.setText(f"Enviando: {filename}")
            self.send_file_requested.emit(filepath)
            self.add_log_transfer(filename, "Envio", "Iniciando...")

    def _open_downloads(self) -> None:
        p = Path(self._download_dir)
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def update_progress(self, percent: float, info: str = "", speed: str = "") -> None:
        self._progress_bar.setValue(int(percent))
        text = info if info else f"{percent:.1f}%"
        self._transfer_status_label.setText(text)
        if percent >= 100:
            self._selected_file_label.setText("Transferencia completada")

    def add_log_transfer(self, filename: str, tipo: str, status: str) -> None:
        row = self._transfer_table.rowCount()
        self._transfer_table.insertRow(row)
        ts = datetime.now().strftime("%H:%M:%S")
        for col, text in enumerate([ts, filename, tipo, status]):
            item = QTableWidgetItem(text)
            self._transfer_table.setItem(row, col, item)
        self._transfer_table.scrollToBottom()


# ---------------------------------------------------------------------------
# ControlTab
# ---------------------------------------------------------------------------

class ControlTab(QWidget):
    """Pestaña de control de teclado, mouse y apagado remoto."""
    input_lock_requested = pyqtSignal()
    input_unlock_requested = pyqtSignal()
    shutdown_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Control de entrada
        input_frame = QFrame()
        input_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 10px; }")
        if_layout = QVBoxLayout(input_frame)
        if_layout.addWidget(QLabel("Control de Dispositivos de Entrada (Teclado y Mouse):"))

        self._lock_state_label = QLabel("Estado actual: Desbloqueado")
        self._lock_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 14px;")
        if_layout.addWidget(self._lock_state_label)

        btn_row = QHBoxLayout()
        lock_btn = QPushButton("Bloquear Teclado y Mouse")
        lock_btn.setObjectName("danger")
        lock_btn.clicked.connect(self.input_lock_requested.emit)
        btn_row.addWidget(lock_btn)

        unlock_btn = QPushButton("Desbloquear Teclado y Mouse")
        unlock_btn.setObjectName("success")
        unlock_btn.clicked.connect(self.input_unlock_requested.emit)
        btn_row.addWidget(unlock_btn)
        btn_row.addStretch()
        if_layout.addLayout(btn_row)
        layout.addWidget(input_frame)

        # Gestion de Energia
        power_frame = QFrame()
        power_frame.setStyleSheet("QFrame { border: 1px solid #45475a; border-radius: 6px; padding: 10px; }")
        pf_layout = QVBoxLayout(power_frame)
        pf_layout.addWidget(QLabel("Gestion de Energia:"))

        countdown_row = QHBoxLayout()
        countdown_row.addWidget(QLabel("Cuenta regresiva:"))
        self._countdown_spin = QSpinBox()
        self._countdown_spin.setRange(5, 300)
        self._countdown_spin.setValue(30)
        self._countdown_spin.setSuffix(" segundos")
        countdown_row.addWidget(self._countdown_spin)
        countdown_row.addStretch()
        pf_layout.addLayout(countdown_row)

        shutdown_btn = QPushButton("Apagar Cliente Remoto")
        shutdown_btn.setObjectName("danger")
        shutdown_btn.clicked.connect(self._confirm_shutdown)
        pf_layout.addWidget(shutdown_btn)
        layout.addWidget(power_frame)

        layout.addStretch()

    def _confirm_shutdown(self) -> None:
        seconds = self._countdown_spin.value()
        reply = QMessageBox.question(
            self, "Confirmar Apagado",
            f"¿Desea apagar el cliente remoto con una cuenta regresiva de {seconds} segundos?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.shutdown_requested.emit(seconds)

    def update_lock_state(self, locked: bool) -> None:
        if locked:
            self._lock_state_label.setText("Estado actual: BLOQUEADO")
            self._lock_state_label.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 14px;")
        else:
            self._lock_state_label.setText("Estado actual: DESBLOQUEADO")
            self._lock_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 14px;")


# ---------------------------------------------------------------------------
# NetworkTab
# ---------------------------------------------------------------------------

class NetworkTab(QWidget):
    """Pestaña de control de red (bloqueo de dominios e ICMP)."""
    domain_block_requested = pyqtSignal(str)
    domain_unblock_requested = pyqtSignal(str)
    ping_disable_requested = pyqtSignal()
    ping_enable_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Dominios
        dom_frame = QFrame()
        dom_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 8px; }")
        df_layout = QVBoxLayout(dom_frame)
        df_layout.addWidget(QLabel("Bloqueo de Sitios Web (Dominios):"))

        self._domain_list = QListWidget()
        df_layout.addWidget(self._domain_list)

        input_row = QHBoxLayout()
        self._domain_input = QLineEdit()
        self._domain_input.setPlaceholderText("ejemplo: facebook.com o youtube.com")
        input_row.addWidget(self._domain_input)

        add_btn = QPushButton("Bloquear Dominio")
        add_btn.setObjectName("danger")
        add_btn.clicked.connect(self._add_domain)
        input_row.addWidget(add_btn)

        remove_btn = QPushButton("Desbloquear Seleccionado")
        remove_btn.clicked.connect(self._remove_domain)
        input_row.addWidget(remove_btn)
        df_layout.addLayout(input_row)
        layout.addWidget(dom_frame)

        # ICMP
        icmp_frame = QFrame()
        icmp_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 8px; }")
        if_layout = QVBoxLayout(icmp_frame)
        if_layout.addWidget(QLabel("Control de Respuesta ICMP (Ping):"))

        self._icmp_state_label = QLabel("Estado actual: Ping Permitido")
        self._icmp_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")
        if_layout.addWidget(self._icmp_state_label)

        icmp_row = QHBoxLayout()
        deny_btn = QPushButton("Denegar Ping")
        deny_btn.setObjectName("danger")
        deny_btn.clicked.connect(self.ping_disable_requested.emit)
        icmp_row.addWidget(deny_btn)

        allow_btn = QPushButton("Permitir Ping")
        allow_btn.setObjectName("success")
        allow_btn.clicked.connect(self.ping_enable_requested.emit)
        icmp_row.addWidget(allow_btn)
        icmp_row.addStretch()
        if_layout.addLayout(icmp_row)
        layout.addWidget(icmp_frame)

        layout.addStretch()

    def _add_domain(self) -> None:
        domain = self._domain_input.text().strip()
        if not domain:
            return
        self._domain_input.clear()
        self.domain_block_requested.emit(domain)

    def _remove_domain(self) -> None:
        item = self._domain_list.currentItem()
        if item:
            self.domain_unblock_requested.emit(item.text())
            self._domain_list.takeItem(self._domain_list.row(item))

    def add_domain_to_list(self, domain: str) -> None:
        self._domain_list.addItem(domain)

    def update_icmp_state(self, blocked: bool) -> None:
        if blocked:
            self._icmp_state_label.setText("Estado actual: PING DENEGADO")
            self._icmp_state_label.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 13px;")
        else:
            self._icmp_state_label.setText("Estado actual: PING PERMITIDO")
            self._icmp_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")


# ---------------------------------------------------------------------------
# LogTab
# ---------------------------------------------------------------------------

class LogTab(QWidget):
    """Pestaña de registro de auditoria."""
    export_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Cliente:"))
        self._client_filter = QComboBox()
        self._client_filter.addItem("Todos")
        filter_row.addWidget(self._client_filter)

        filter_row.addWidget(QLabel("Accion:"))
        self._action_filter = QComboBox()
        self._action_filter.addItem("Todas")
        filter_row.addWidget(self._action_filter)

        filter_btn = QPushButton("Filtrar")
        filter_btn.clicked.connect(self._apply_filter)
        filter_row.addWidget(filter_btn)

        export_btn = QPushButton("Exportar Registro...")
        export_btn.clicked.connect(self._export)
        filter_row.addWidget(export_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Timestamp", "Cliente", "Accion", "Descripcion"])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def _apply_filter(self) -> None:
        client = self._client_filter.currentText()
        action = self._action_filter.currentText()
        for row in range(self._table.rowCount()):
            show = True
            if client != "Todos" and self._table.item(row, 1):
                if self._table.item(row, 1).text() != client:
                    show = False
            if action != "Todas" and self._table.item(row, 2):
                if self._table.item(row, 2).text() != action:
                    show = False
            self._table.setRowHidden(row, not show)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar Registro", "", "Texto (*.txt)")
        if path:
            self.export_requested.emit(path)

    def add_log_entry(self, timestamp: str, client: str, action: str, description: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, text in enumerate([timestamp, client, action, description]):
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        self._table.scrollToBottom()

        if client not in [self._client_filter.itemText(i) for i in range(self._client_filter.count())]:
            self._client_filter.addItem(client)
        if action not in [self._action_filter.itemText(i) for i in range(self._action_filter.count())]:
            self._action_filter.addItem(action)


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Ventana principal del servidor de monitoreo y control."""

    def __init__(
        self,
        send_command_callback: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._send_cmd = send_command_callback
        self._selected_client_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Monitor Remoto - Servidor de Administracion")
        self.resize(1280, 800)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Barra superior con la IP del servidor para el usuario
        self._top_bar = QFrame()
        self._top_bar.setStyleSheet("background-color: #181825; border-bottom: 1px solid #313244; padding: 6px 12px;")
        tb_layout = QHBoxLayout(self._top_bar)
        tb_layout.setContentsMargins(12, 6, 12, 6)

        title_lbl = QLabel("MONITOR REMOTO - SERVIDOR")
        title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #89b4fa;")
        tb_layout.addWidget(title_lbl)

        tb_layout.addSpacing(20)

        self._server_ip_label = QLabel("IP del Servidor para Clientes: Consultando...")
        self._server_ip_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")
        tb_layout.addWidget(self._server_ip_label)

        tb_layout.addStretch()

        help_lbl = QLabel("Puerto: 5555 | Token por defecto: secreto123")
        help_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        tb_layout.addWidget(help_lbl)

        root_layout.addWidget(self._top_bar)

        # Contenido principal (Panel lateral + Pestanas)
        content_widget = QWidget()
        main_layout = QHBoxLayout(content_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(content_widget)

        # Panel lateral
        self.client_panel = ClientPanel()
        self.client_panel.client_selected.connect(self._on_client_selected)
        main_layout.addWidget(self.client_panel)

        # Pestanas de control
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.screen_tab = ScreenTab()
        self.chat_tab = ChatTab()
        self.files_tab = FilesTab()
        self.control_tab = ControlTab()
        self.network_tab = NetworkTab()
        self.log_tab = LogTab()

        self.tabs.addTab(self.screen_tab, "Pantalla")
        self.tabs.addTab(self.chat_tab, "Chat")
        self.tabs.addTab(self.files_tab, "Archivos")
        self.tabs.addTab(self.control_tab, "Control")
        self.tabs.addTab(self.network_tab, "Red")
        self.tabs.addTab(self.log_tab, "Registro")

        # Conexiones
        self.screen_tab.screen_start_requested.connect(self._on_screen_start)
        self.screen_tab.screen_stop_requested.connect(self._on_screen_stop)
        self.chat_tab.message_sent.connect(self._on_chat_send)
        self.files_tab.send_file_requested.connect(self._on_send_file)
        self.control_tab.input_lock_requested.connect(self._on_input_lock)
        self.control_tab.input_unlock_requested.connect(self._on_input_unlock)
        self.control_tab.shutdown_requested.connect(self._on_shutdown)
        self.network_tab.domain_block_requested.connect(self._on_domain_block)
        self.network_tab.domain_unblock_requested.connect(self._on_domain_unblock)
        self.network_tab.ping_disable_requested.connect(self._on_ping_disable)
        self.network_tab.ping_enable_requested.connect(self._on_ping_enable)
        self.log_tab.export_requested.connect(self._on_export_log)

    def set_server_info(self, host: str, port: int, token: str) -> None:
        """Actualiza la informacion de conexion en la barra superior."""
        import socket
        display_ip = host
        if host in ("0.0.0.0", ""):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                display_ip = s.getsockname()[0]
                s.close()
            except Exception:
                display_ip = "127.0.0.1"

        self._server_ip_label.setText(f"IP del Servidor para Clientes:  {display_ip}  (Puerto: {port})")

    def _on_client_selected(self, client_id: str) -> None:
        self._selected_client_id = client_id

    def _send(self, msg_type: str, payload: dict) -> None:
        if self._selected_client_id and self._send_cmd:
            self._send_cmd(self._selected_client_id, msg_type, payload)

    def _on_screen_start(self, resolution: str, quality: int, fps: int) -> None:
        payload: dict = {"quality": quality, "fps": fps}
        if resolution != "native":
            w, h = resolution.split("x")
            payload["resolution"] = [int(w), int(h)]
        self._send("screen_start", payload)

    def _on_screen_stop(self) -> None:
        self._send("screen_stop", {})

    def _on_chat_send(self, text: str) -> None:
        self._send("chat_message", {"message": text, "sender": "Servidor"})

    def _on_send_file(self, filepath: str) -> None:
        if self._send_cmd and self._selected_client_id:
            self._send_cmd(self._selected_client_id, "_send_file", {"filepath": filepath})

    def _on_input_lock(self) -> None:
        self._send("input_lock", {})

    def _on_input_unlock(self) -> None:
        self._send("input_unlock", {})

    def _on_shutdown(self, seconds: int) -> None:
        self._send("shutdown", {"countdown": seconds})

    def _on_domain_block(self, domain: str) -> None:
        self._send("web_block", {"domain": domain})
        self.network_tab.add_domain_to_list(domain)

    def _on_domain_unblock(self, domain: str) -> None:
        self._send("web_unblock", {"domain": domain})

    def _on_ping_disable(self) -> None:
        self._send("icmp_disable", {})
        self.network_tab.update_icmp_state(True)

    def _on_ping_enable(self) -> None:
        self._send("icmp_enable", {})
        self.network_tab.update_icmp_state(False)

    def _on_export_log(self, filepath: str) -> None:
        if self._send_cmd:
            self._send_cmd("_server", "_export_log", {"filepath": filepath})

    def handle_message(self, client_id: str, message: dict) -> None:
        """Despacha un mensaje entrante de la red a la interfaz."""
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "_internal_connected":
            session = payload.get("session")
            if session:
                self.client_panel.update_slot(session.slot_index, {
                    "connected": True,
                    "client_id": session.client_id,
                    "hostname": session.hostname,
                    "ip_address": session.ip_address,
                    "os_info": session.os_info,
                    "metrics": session.metrics,
                })
                self.log_tab.add_log_entry(
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    session.hostname, "CONEXION",
                    f"Cliente conectado desde {session.ip_address}",
                )
                # Auto-seleccionar primer cliente si no habia ninguno seleccionado
                if self._selected_client_id is None:
                    self.client_panel.select_slot(session.slot_index)

        elif msg_type == "_internal_disconnected":
            slot_index = payload.get("slot_index", -1)
            if 0 <= slot_index < 3:
                self.client_panel.update_slot(slot_index, {"connected": False})
            if client_id == self._selected_client_id:
                self.screen_tab.reset()

        elif msg_type == "screen_frame":
            # Actualizar miniatura del slot correspondiente
            for s in self.client_panel._slots:
                if s.get_client_id() == client_id:
                    self.client_panel.update_thumbnail(s.slot_index, payload.get("data", ""))
                    break
            # Si esta seleccionado, mostrar en la pestana principal de pantalla
            if client_id == self._selected_client_id:
                self.screen_tab.display_frame(payload.get("data", ""))

        elif msg_type == "client_metrics":
            # Actualizar metricas en el slot
            for s in self.client_panel._slots:
                if s.get_client_id() == client_id:
                    s._cpu_label.setText(f"CPU: {payload.get('cpu_percent', '--')}%")
                    s._ram_label.setText(f"RAM: {payload.get('memory_percent', '--')}%")
                    break

        elif msg_type == "chat_message":
            sender_name = payload.get("hostname", "Cliente")
            msg_text = payload.get("message", "")
            # Mostrar en el chat si es el cliente actual o no hay ninguno seleccionado
            if client_id == self._selected_client_id or self._selected_client_id is None:
                self.chat_tab.add_message(sender_name, msg_text)
            self.log_tab.add_log_entry(
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                sender_name, "CHAT", msg_text,
            )

        elif msg_type == "command_ack":
            action = payload.get("action", "")
            success = payload.get("success", False)
            msg = payload.get("message", "")
            if action == "input_lock":
                self.control_tab.update_lock_state(success)
            elif action == "input_unlock":
                self.control_tab.update_lock_state(not success)
            self.log_tab.add_log_entry(
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Cliente", action.upper(), msg if msg else f"Exito: {success}",
            )
