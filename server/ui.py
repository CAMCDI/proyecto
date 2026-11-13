"""Interfaz gráfica del servidor — PyQt6.

Panel principal con sidebar de 3 slots de clientes y pestañas de control:
Pantalla, Chat, Archivos, Control, Red y Log de acciones.

Requisitos: 15.1, 15.2, 15.10, 4.1-4.10, 1.1-1.7, 3.1-3.10, 2.1-2.10,
            6.1-6.2, 7.1-7.2, 8.1-8.3, 9.1-9.3, 10.1-10.2, 5.1-5.5.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap, QPainter
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSlider, QSizePolicy, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget, QComboBox, QHeaderView,
)

# ---------------------------------------------------------------------------
# Paleta de colores (tema oscuro)
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
    padding: 8px 16px;
    border: 1px solid #313244;
    border-bottom: none;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border-bottom: 2px solid #89b4fa;
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
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton#danger {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton#danger:hover {
    background-color: #eb6f92;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 4px 8px;
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
    padding: 4px;
    border: 1px solid #45475a;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #313244;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #89b4fa;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 4px;
}
QScrollBar:vertical {
    background: #181825;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
}
"""

COLOR_CONNECTED = "#a6e3a1"
COLOR_DISCONNECTED = "#6c7086"
COLOR_SELECTED = "#89b4fa"


def _make_status_pixmap(color: str, size: int = 14) -> QPixmap:
    """Crea un pixmap circular del color dado para el indicador de estado."""
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
# ClientSlot
# ---------------------------------------------------------------------------

class ClientSlot(QFrame):
    """Slot individual en el panel de clientes (uno por cada máquina).

    Requisito: 4.1-4.8.
    """
    clicked = pyqtSignal(int)   # emite slot_index

    def __init__(self, slot_index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.slot_index = slot_index
        self._selected = False
        self._client_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
                margin: 2px;
            }}
        """)
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

        self._hostname_label = QLabel(f"Slot {self.slot_index + 1} — Libre")
        self._hostname_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(self._hostname_label)
        header.addStretch()
        layout.addLayout(header)

        # Miniatura
        self._thumbnail = QLabel()
        self._thumbnail.setFixedSize(160, 90)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail.setStyleSheet("background-color: #11111b; border-radius: 4px;")
        self._thumbnail.setText("Sin señal")
        layout.addWidget(self._thumbnail, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Info
        self._ip_label = QLabel("IP: —")
        self._os_label = QLabel("OS: —")
        self._cpu_label = QLabel("CPU: —")
        self._ram_label = QLabel("RAM: —")
        for lbl in (self._ip_label, self._os_label, self._cpu_label, self._ram_label):
            lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
            layout.addWidget(lbl)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._client_id:
            self.clicked.emit(self.slot_index)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        border_color = COLOR_SELECTED if selected else "#313244"
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #181825;
                border: 2px solid {border_color};
                border-radius: 8px;
                margin: 2px;
            }}
        """)

    def update_data(self, session_data: dict) -> None:
        """Actualiza los datos mostrados en el slot."""
        connected = session_data.get("connected", False)
        self._client_id = session_data.get("client_id") if connected else None
        hostname = session_data.get("hostname", f"Slot {self.slot_index + 1}")
        ip = session_data.get("ip_address", "—")
        os_info = session_data.get("os_info", {})
        os_name = os_info.get("os_name", "—")
        metrics = session_data.get("metrics", {})
        cpu = metrics.get("cpu_percent", "—")
        ram = metrics.get("memory_percent", "—")

        color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        self._status_icon.setPixmap(_make_status_pixmap(color))
        self._hostname_label.setText(hostname if connected else f"Slot {self.slot_index + 1} — Libre")
        self._ip_label.setText(f"IP: {ip}")
        self._os_label.setText(f"OS: {os_name}")
        self._cpu_label.setText(f"CPU: {cpu}%" if isinstance(cpu, (int, float)) else "CPU: —")
        self._ram_label.setText(f"RAM: {ram}%" if isinstance(ram, (int, float)) else "RAM: —")

        if not connected:
            self._thumbnail.setText("Sin señal")
            self._thumbnail.setPixmap(QPixmap())

    def update_thumbnail(self, jpeg_b64: str) -> None:
        """Actualiza la miniatura con una imagen JPEG en base64."""
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
    """Panel lateral con 3 slots de clientes.

    Requisito: 4.1, 4.2.
    """
    client_selected = pyqtSignal(str)   # emite client_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._slots: list[ClientSlot] = []
        self._selected_client_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFixedWidth(210)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
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
    """Pestaña de streaming de pantalla remota.

    Requisito: 1.1, 1.4, 1.5, 1.6, 1.7.
    """
    screen_start_requested = pyqtSignal(str, int, int)   # resolution, quality, fps
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

        # Área de visualización
        self._screen_label = QLabel("Seleccione un cliente para iniciar el streaming")
        self._screen_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._screen_label.setStyleSheet("background-color: #11111b; border-radius: 6px; color: #6c7086;")
        self._screen_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._screen_label)

        # Controles
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Resolución:"))
        self._resolution_combo = QComboBox()
        self._resolution_combo.addItems(["640x480", "800x600", "1024x768", "Nativa"])
        self._resolution_combo.setCurrentIndex(2)
        controls.addWidget(self._resolution_combo)

        controls.addWidget(QLabel("Calidad:"))
        self._quality_slider = QSlider(Qt.Orientation.Horizontal)
        self._quality_slider.setRange(50, 90)
        self._quality_slider.setValue(70)
        self._quality_slider.setFixedWidth(100)
        controls.addWidget(self._quality_slider)
        self._quality_label = QLabel("70")
        self._quality_slider.valueChanged.connect(lambda v: self._quality_label.setText(str(v)))
        controls.addWidget(self._quality_label)

        self._toggle_btn = QPushButton("▶ Iniciar Streaming")
        self._toggle_btn.clicked.connect(self._toggle_streaming)
        controls.addWidget(self._toggle_btn)

        self._fps_label = QLabel("FPS: —")
        self._fps_label.setStyleSheet("color: #a6e3a1;")
        controls.addWidget(self._fps_label)

        self._bw_label = QLabel("BW: —")
        self._bw_label.setStyleSheet("color: #89b4fa;")
        controls.addWidget(self._bw_label)

        controls.addStretch()
        layout.addLayout(controls)

    def _toggle_streaming(self) -> None:
        self._streaming = not self._streaming
        if self._streaming:
            self._toggle_btn.setText("⬛ Detener Streaming")
            res_str = self._resolution_combo.currentText()
            if res_str == "Nativa":
                resolution = None
            else:
                w, h = res_str.split("x")
                resolution = f"{w}x{h}"
            quality = self._quality_slider.value()
            self.screen_start_requested.emit(resolution or "native", quality, 8)
        else:
            self._toggle_btn.setText("▶ Iniciar Streaming")
            self.screen_stop_requested.emit()
            self._screen_label.setText("Streaming detenido")
            self._fps_label.setText("FPS: —")

    def display_frame(self, jpeg_b64: str) -> None:
        """Decodifica y muestra un frame JPEG en base64."""
        try:
            data = base64.b64decode(jpeg_b64)
            image = QImage.fromData(data)
            pix = QPixmap.fromImage(image).scaled(
                self._screen_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._screen_label.setPixmap(pix)
            self._frame_count += 1

            now = datetime.now()
            elapsed = (now - self._last_fps_time).total_seconds()
            if elapsed >= 1.0:
                fps = self._frame_count / elapsed
                self._fps_label.setText(f"FPS: {fps:.1f}")
                # Aproximación de BW basada en tamaño del frame.
                bw_kbs = len(data) / 1024 * fps
                self._bw_label.setText(f"BW: {bw_kbs:.0f} KB/s")
                self._frame_count = 0
                self._last_fps_time = now
        except Exception:
            pass

    def reset(self) -> None:
        self._streaming = False
        self._toggle_btn.setText("▶ Iniciar Streaming")
        self._screen_label.setText("Seleccione un cliente para iniciar el streaming")
        self._screen_label.setPixmap(QPixmap())
        self._fps_label.setText("FPS: —")
        self._bw_label.setText("BW: —")


# ---------------------------------------------------------------------------
# ChatTab
# ---------------------------------------------------------------------------

class ChatTab(QWidget):
    """Pestaña de chat bidireccional con el cliente.

    Requisito: 3.1, 3.3-3.8, 3.10.
    """
    message_sent = pyqtSignal(str)   # emite el texto del mensaje

    MAX_HISTORY = 200

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
        self.message_sent.emit(text)
        self.add_message("Servidor", text)

    def add_message(self, sender: str, message: str) -> None:
        """Agrega un mensaje al historial con formato [HH:MM:SS] Emisor: msg."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {sender}: {message}"
        self._history.append(line)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)
        self._chat_area.append(line)
        self._chat_area.verticalScrollBar().setValue(
            self._chat_area.verticalScrollBar().maximum()
        )

    def clear_history(self) -> None:
        self._history.clear()
        self._chat_area.clear()


# ---------------------------------------------------------------------------
# FilesTab
# ---------------------------------------------------------------------------

class FilesTab(QWidget):
    """Pestaña de transferencia de archivos.

    Requisito: 2.1, 2.2, 2.6, 2.10.
    """
    send_file_requested = pyqtSignal(str)         # filepath
    receive_file_requested = pyqtSignal(str)      # save_path

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Enviar archivo ---
        send_group = QFrame()
        send_group.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 4px; }")
        sg_layout = QVBoxLayout(send_group)
        sg_layout.addWidget(QLabel("📤  Enviar Archivo al Cliente"))

        row = QHBoxLayout()
        self._send_path = QLineEdit()
        self._send_path.setPlaceholderText("Ruta del archivo a enviar...")
        row.addWidget(self._send_path)
        browse_btn = QPushButton("Examinar")
        browse_btn.clicked.connect(self._browse_send)
        row.addWidget(browse_btn)
        sg_layout.addLayout(row)

        send_btn = QPushButton("Enviar")
        send_btn.clicked.connect(lambda: self.send_file_requested.emit(self._send_path.text()))
        sg_layout.addWidget(send_btn)
        layout.addWidget(send_group)

        # --- Recibir archivo ---
        recv_group = QFrame()
        recv_group.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 4px; }")
        rg_layout = QVBoxLayout(recv_group)
        rg_layout.addWidget(QLabel("📥  Solicitar Archivo del Cliente"))

        row2 = QHBoxLayout()
        self._recv_path = QLineEdit()
        self._recv_path.setPlaceholderText("Directorio de destino...")
        row2.addWidget(self._recv_path)
        browse_recv = QPushButton("Examinar")
        browse_recv.clicked.connect(self._browse_recv)
        row2.addWidget(browse_recv)
        rg_layout.addLayout(row2)

        recv_btn = QPushButton("Solicitar Archivo")
        recv_btn.clicked.connect(lambda: self.receive_file_requested.emit(self._recv_path.text()))
        rg_layout.addWidget(recv_btn)
        layout.addWidget(recv_group)

        # --- Progreso ---
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._speed_label = QLabel("Velocidad: —")
        self._eta_label = QLabel("ETA: —")
        layout.addWidget(self._progress_bar)

        prog_row = QHBoxLayout()
        prog_row.addWidget(self._speed_label)
        prog_row.addStretch()
        prog_row.addWidget(self._eta_label)
        layout.addLayout(prog_row)

        layout.addStretch()

    def _browse_send(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo a enviar")
        if path:
            self._send_path.setText(path)

    def _browse_recv(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleccionar directorio de destino")
        if path:
            self._recv_path.setText(path)

    def update_progress(self, percent: float, speed: str = "—", eta: str = "—") -> None:
        self._progress_bar.setValue(int(percent))
        self._speed_label.setText(f"Velocidad: {speed}")
        self._eta_label.setText(f"ETA: {eta}")


# ---------------------------------------------------------------------------
# ControlTab
# ---------------------------------------------------------------------------

class ControlTab(QWidget):
    """Pestaña de control de entrada y energía.

    Requisito: 6.1-6.2, 7.1-7.2, 8.1-8.3.
    """
    input_lock_requested = pyqtSignal()
    input_unlock_requested = pyqtSignal()
    shutdown_requested = pyqtSignal(int)   # countdown seconds

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # -- Control de entrada --
        input_frame = QFrame()
        input_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 4px; }")
        if_layout = QVBoxLayout(input_frame)
        if_layout.addWidget(QLabel("🖱️  Control de Dispositivos de Entrada"))

        self._lock_state_label = QLabel("Estado: Desbloqueado")
        self._lock_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        if_layout.addWidget(self._lock_state_label)

        btn_row = QHBoxLayout()
        lock_btn = QPushButton("🔒 Bloquear Teclado/Mouse")
        lock_btn.clicked.connect(self.input_lock_requested.emit)
        btn_row.addWidget(lock_btn)

        unlock_btn = QPushButton("🔓 Desbloquear Teclado/Mouse")
        unlock_btn.clicked.connect(self.input_unlock_requested.emit)
        btn_row.addWidget(unlock_btn)
        if_layout.addLayout(btn_row)
        layout.addWidget(input_frame)

        # -- Energía --
        power_frame = QFrame()
        power_frame.setStyleSheet("QFrame { border: 1px solid #f38ba8; border-radius: 6px; padding: 4px; }")
        pf_layout = QVBoxLayout(power_frame)
        pf_layout.addWidget(QLabel("⚡  Gestión de Energía"))

        countdown_row = QHBoxLayout()
        countdown_row.addWidget(QLabel("Cuenta regresiva (seg):"))
        self._countdown_spin = QSpinBox()
        self._countdown_spin.setRange(5, 300)
        self._countdown_spin.setValue(30)
        countdown_row.addWidget(self._countdown_spin)
        countdown_row.addStretch()
        pf_layout.addLayout(countdown_row)

        shutdown_btn = QPushButton("🔴 Apagar Cliente")
        shutdown_btn.setObjectName("danger")
        shutdown_btn.clicked.connect(self._confirm_shutdown)
        pf_layout.addWidget(shutdown_btn)
        layout.addWidget(power_frame)

        layout.addStretch()

    def _confirm_shutdown(self) -> None:
        seconds = self._countdown_spin.value()
        reply = QMessageBox.question(
            self, "Confirmar Apagado",
            f"¿Apagar el cliente con {seconds} segundos de cuenta regresiva?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.shutdown_requested.emit(seconds)

    def update_lock_state(self, locked: bool) -> None:
        if locked:
            self._lock_state_label.setText("Estado: 🔒 Bloqueado")
            self._lock_state_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
        else:
            self._lock_state_label.setText("Estado: 🔓 Desbloqueado")
            self._lock_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")


# ---------------------------------------------------------------------------
# NetworkTab
# ---------------------------------------------------------------------------

class NetworkTab(QWidget):
    """Pestaña de control de red (bloqueo de dominios e ICMP).

    Requisito: 9.1-9.3, 9.7-9.8, 10.1-10.2, 10.6-10.7.
    """
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

        # -- Bloqueo de dominios --
        dom_frame = QFrame()
        dom_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 4px; }")
        df_layout = QVBoxLayout(dom_frame)
        df_layout.addWidget(QLabel("🌐  Bloqueo de Dominios Web"))

        self._domain_list = QListWidget()
        df_layout.addWidget(self._domain_list)

        input_row = QHBoxLayout()
        self._domain_input = QLineEdit()
        self._domain_input.setPlaceholderText("example.com")
        input_row.addWidget(self._domain_input)
        add_btn = QPushButton("Agregar Dominio")
        add_btn.clicked.connect(self._add_domain)
        input_row.addWidget(add_btn)
        remove_btn = QPushButton("Quitar Dominio")
        remove_btn.clicked.connect(self._remove_domain)
        input_row.addWidget(remove_btn)
        df_layout.addLayout(input_row)
        layout.addWidget(dom_frame)

        # -- Control ICMP --
        icmp_frame = QFrame()
        icmp_frame.setStyleSheet("QFrame { border: 1px solid #313244; border-radius: 6px; padding: 4px; }")
        if_layout = QVBoxLayout(icmp_frame)
        if_layout.addWidget(QLabel("📡  Control de Ping (ICMP)"))

        self._icmp_state_label = QLabel("Estado: Ping Permitido")
        self._icmp_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        if_layout.addWidget(self._icmp_state_label)

        icmp_row = QHBoxLayout()
        deny_btn = QPushButton("🚫 Denegar Ping")
        deny_btn.clicked.connect(self.ping_disable_requested.emit)
        icmp_row.addWidget(deny_btn)
        allow_btn = QPushButton("✅ Permitir Ping")
        allow_btn.clicked.connect(self.ping_enable_requested.emit)
        icmp_row.addWidget(allow_btn)
        if_layout.addLayout(icmp_row)
        layout.addWidget(icmp_frame)
        layout.addStretch()

    def _validate_domain(self, domain: str) -> bool:
        pattern = re.compile(
            r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\Z"
        )
        return bool(pattern.match(domain))

    def _add_domain(self) -> None:
        domain = self._domain_input.text().strip()
        if not domain:
            return
        if not self._validate_domain(domain):
            QMessageBox.warning(self, "Dominio Inválido", f"'{domain}' no es un dominio válido.")
            return
        self._domain_input.clear()
        self.domain_block_requested.emit(domain)

    def _remove_domain(self) -> None:
        item = self._domain_list.currentItem()
        if item:
            self.domain_unblock_requested.emit(item.text())
            self._domain_list.takeItem(self._domain_list.row(item))

    def update_blocklist(self, domains: list[str]) -> None:
        self._domain_list.clear()
        self._domain_list.addItems(domains)

    def add_domain_to_list(self, domain: str) -> None:
        self._domain_list.addItem(domain)

    def update_icmp_state(self, blocked: bool) -> None:
        if blocked:
            self._icmp_state_label.setText("Estado: 🚫 Ping Denegado")
            self._icmp_state_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
        else:
            self._icmp_state_label.setText("Estado: ✅ Ping Permitido")
            self._icmp_state_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")


# ---------------------------------------------------------------------------
# LogTab
# ---------------------------------------------------------------------------

class LogTab(QWidget):
    """Pestaña de visualización del Action_Log del servidor.

    Requisito: 5.1, 5.4, 5.5.
    """
    export_requested = pyqtSignal(str)   # filepath

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Filtros
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Cliente:"))
        self._client_filter = QComboBox()
        self._client_filter.addItem("Todos")
        filter_row.addWidget(self._client_filter)

        filter_row.addWidget(QLabel("Acción:"))
        self._action_filter = QComboBox()
        self._action_filter.addItem("Todas")
        filter_row.addWidget(self._action_filter)

        filter_btn = QPushButton("Filtrar")
        filter_btn.clicked.connect(self._apply_filter)
        filter_row.addWidget(filter_btn)

        export_btn = QPushButton("Exportar Log")
        export_btn.clicked.connect(self._export)
        filter_row.addWidget(export_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Tabla
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Timestamp", "Cliente", "Acción", "Descripción"])
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
        path, _ = QFileDialog.getSaveFileName(self, "Exportar Log", "", "Texto (*.txt)")
        if path:
            self.export_requested.emit(path)

    def add_log_entry(self, timestamp: str, client: str, action: str, description: str) -> None:
        """Agrega una fila a la tabla de log."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, text in enumerate([timestamp, client, action, description]):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)
        self._table.scrollToBottom()

        # Actualizar filtros
        if client not in [self._client_filter.itemText(i) for i in range(self._client_filter.count())]:
            self._client_filter.addItem(client)
        if action not in [self._action_filter.itemText(i) for i in range(self._action_filter.count())]:
            self._action_filter.addItem(action)


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Ventana principal del servidor de administración remota.

    Requisito: 15.1, 15.2, 15.10, 17.1, 17.2, 17.3.
    """

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
        self.setWindowTitle("Monitor Remoto — Servidor")
        self.resize(1280, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Panel lateral de clientes
        self.client_panel = ClientPanel()
        self.client_panel.client_selected.connect(self._on_client_selected)
        main_layout.addWidget(self.client_panel)

        # Área de pestañas
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.screen_tab = ScreenTab()
        self.chat_tab = ChatTab()
        self.files_tab = FilesTab()
        self.control_tab = ControlTab()
        self.network_tab = NetworkTab()
        self.log_tab = LogTab()

        self.tabs.addTab(self.screen_tab, "🖥  Pantalla")
        self.tabs.addTab(self.chat_tab, "💬  Chat")
        self.tabs.addTab(self.files_tab, "📁  Archivos")
        self.tabs.addTab(self.control_tab, "🎮  Control")
        self.tabs.addTab(self.network_tab, "🌐  Red")
        self.tabs.addTab(self.log_tab, "📋  Log")

        # Conectar señales de las pestañas
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
        self._send("chat_message", {"message": text})

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

    # ------------------------------------------------------------------
    # Actualizaciones desde el hilo de red (thread-safe via QTimer)
    # ------------------------------------------------------------------

    def handle_message(self, client_id: str, message: dict) -> None:
        """Despacha un mensaje del cliente a la pestaña correspondiente."""
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
                    f"Conectado desde {session.ip_address}"
                )

        elif msg_type == "_internal_disconnected":
            slot_index = payload.get("slot_index", -1)
            if 0 <= slot_index < 3:
                self.client_panel.update_slot(slot_index, {"connected": False})
            if client_id == self._selected_client_id:
                self.screen_tab.reset()

        elif msg_type == "screen_frame":
            if client_id == self._selected_client_id:
                self.screen_tab.display_frame(payload.get("data", ""))

        elif msg_type == "client_metrics":
            # Actualizar métricas en el slot del cliente
            for session in []:  # se llena desde connection_manager
                pass

        elif msg_type == "chat_message":
            if client_id == self._selected_client_id:
                self.chat_tab.add_message(
                    payload.get("hostname", "Cliente"),
                    payload.get("message", "")
                )

        elif msg_type == "command_ack":
            action = payload.get("action", "")
            success = payload.get("success", False)
            if action == "input_lock":
                self.control_tab.update_lock_state(success)
            elif action == "input_unlock":
                self.control_tab.update_lock_state(not success)
