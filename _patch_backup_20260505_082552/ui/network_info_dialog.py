"""
Network Info Dialog — AutoPack VLO-127S
=========================================
Shows LAN URL, QR code, and live diagnostics so users on other devices
in the same WiFi/LAN can connect to the AutoPack monitor.

Usage (from MonitorPage or a menu):

    from app.ui.network_info_dialog import NetworkInfoDialog
    NetworkInfoDialog(self, live_server).exec_()

Requires:
    • PyQt5                  (already used by AutoPack)
    • qrcode[pil]            (optional — dialog falls back to text-only URL
                              if not installed.  `pip install qrcode[pil]`)
    • urllib.request         (stdlib — for health probe)
"""

import io
import json
import socket
import threading
import urllib.request
from urllib.error import URLError

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QGuiApplication
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QSizePolicy,
)

# ── Optional QR code support ──────────────────────────────────────────
try:
    import qrcode
    _QR_OK = True
except ImportError:
    _QR_OK = False


def _make_qr_pixmap(text: str, box_size: int = 8) -> "QPixmap | None":
    """Generate a QR code as a QPixmap, or None if qrcode lib is missing."""
    if not _QR_OK:
        return None
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size,
            border=2,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        return pix
    except Exception:
        return None


def _probe_health(url: str, timeout: float = 1.5) -> dict:
    """Hit /health endpoint and return parsed JSON (or error dict)."""
    try:
        with urllib.request.urlopen(url + "/health", timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return json.loads(body)
    except URLError as e:
        return {"ok": False, "error": f"URLError: {e.reason}"}
    except socket.timeout:
        return {"ok": False, "error": "Request timed out"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class NetworkInfoDialog(QDialog):
    """Modal dialog showing LAN connection info for the live monitor."""

    _probe_result = pyqtSignal(dict)

    def __init__(self, parent, live_server):
        super().__init__(parent)
        self._live_server = live_server
        self.setWindowTitle("LAN Monitor — Network Info")
        self.setModal(True)
        self.setMinimumSize(520, 620)

        # Layout root
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ── Title ──────────────────────────────────────────────
        title = QLabel("🌐  Share this URL with other devices")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel(
            "Open this URL on any phone, tablet, or PC connected to "
            "the same WiFi/LAN as this computer.")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #64748B;")
        root.addWidget(subtitle)

        # ── URL card (big, copyable) ───────────────────────────
        urls = live_server.get_urls() if live_server else {
            "lan": "http://<unknown>:8000",
            "localhost": "http://localhost:8000",
            "ws": "",
            "ip": "unknown",
            "http_port": 8000, "ws_port": 8001,
        }
        self._urls = urls

        url_card = QFrame()
        url_card.setFrameShape(QFrame.StyledPanel)
        url_card.setStyleSheet("""
            QFrame { background: #F1F5F9; border-radius: 10px;
                     padding: 14px; border: 1px solid #CBD5E1; }
        """)
        url_lay = QVBoxLayout(url_card)
        url_lay.setSpacing(6)

        lan_row = QHBoxLayout()
        lan_lbl = QLabel("📱 From phone / tablet / other PC:")
        lan_lbl.setStyleSheet("color: #334155; font-weight: 600;")
        lan_row.addWidget(lan_lbl)
        lan_row.addStretch()
        url_lay.addLayout(lan_row)

        self._lan_url_lbl = QLabel(urls["lan"])
        self._lan_url_lbl.setFont(QFont("Consolas", 13, QFont.Bold))
        self._lan_url_lbl.setStyleSheet(
            "color: #1E40AF; background: white; padding: 8px 12px; "
            "border-radius: 6px; border: 1px solid #CBD5E1;")
        self._lan_url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lan_url_lbl.setAlignment(Qt.AlignCenter)
        url_lay.addWidget(self._lan_url_lbl)

        local_lbl = QLabel(f"💻 On this PC: <code>{urls['localhost']}</code>")
        local_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        local_lbl.setAlignment(Qt.AlignCenter)
        url_lay.addWidget(local_lbl)

        root.addWidget(url_card)

        # ── QR code ────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setMinimumHeight(240)
        pix = _make_qr_pixmap(urls["lan"])
        if pix:
            self._qr_label.setPixmap(pix)
        else:
            self._qr_label.setText(
                "📷  QR code unavailable\n\n"
                "Install  qrcode[pil]  to enable:\n"
                "    pip install qrcode[pil]\n\n"
                "Until then, type the URL above manually.")
            self._qr_label.setStyleSheet(
                "color: #64748B; background: #F8FAFC; "
                "border: 2px dashed #CBD5E1; border-radius: 8px; padding: 20px;")
        root.addWidget(self._qr_label)

        # ── Diagnostics panel ──────────────────────────────────
        diag_title = QLabel("🩺 Server Diagnostics")
        diag_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        diag_title.setStyleSheet("color: #334155; margin-top: 4px;")
        root.addWidget(diag_title)

        self._diag_box = QTextEdit()
        self._diag_box.setReadOnly(True)
        self._diag_box.setMaximumHeight(110)
        self._diag_box.setStyleSheet("""
            QTextEdit { background: #0F172A; color: #A7F3D0;
                        font-family: Consolas, monospace; font-size: 11px;
                        border-radius: 6px; padding: 8px; }
        """)
        self._diag_box.setPlainText("Probing server…")
        root.addWidget(self._diag_box)

        # ── Buttons ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_copy = QPushButton("📋  Copy URL")
        btn_copy.clicked.connect(self._on_copy)
        btn_row.addWidget(btn_copy)

        btn_refresh = QPushButton("🔄  Refresh")
        btn_refresh.clicked.connect(self._probe_server)
        btn_row.addWidget(btn_refresh)

        btn_row.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        # ── Style all buttons ──────────────────────────────────
        self.setStyleSheet(self.styleSheet() + """
            QPushButton { padding: 8px 16px; border-radius: 6px;
                          background: #1E40AF; color: white;
                          font-weight: 600; border: none; min-width: 80px; }
            QPushButton:hover { background: #1E3A8A; }
            QPushButton:pressed { background: #1E3A8A; }
        """)

        # Run probe after UI is shown (non-blocking)
        self._probe_result.connect(self._render_diag)
        QTimer.singleShot(120, self._probe_server)

    # ── Handlers ─────────────────────────────────────────────────

    def _on_copy(self):
        cb = QGuiApplication.clipboard()
        cb.setText(self._urls["lan"])
        # Visual feedback
        orig = self._lan_url_lbl.styleSheet()
        self._lan_url_lbl.setStyleSheet(
            orig + "background: #D1FAE5; border-color: #10B981;")
        QTimer.singleShot(700, lambda: self._lan_url_lbl.setStyleSheet(orig))

    def _probe_server(self):
        self._diag_box.setPlainText("Probing server…")
        url = self._urls["localhost"]

        def worker():
            result = _probe_health(url)
            # Emit signal to update UI on main thread
            try:
                self._probe_result.emit(result)
            except RuntimeError:
                # Dialog was closed mid-probe
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _render_diag(self, result: dict):
        if result.get("ok"):
            lines = [
                "✓ Server is UP and responding",
                f"  HTTP port    : {result.get('http_port', '?')}",
                f"  WS   port    : {result.get('ws_port',   '?')}",
                f"  WS clients   : {result.get('ws_clients', 0)}",
                f"  Has plan     : {result.get('has_plan', False)}",
                f"  Timestamp    : {result.get('timestamp', '—')}",
            ]
            self._diag_box.setStyleSheet(self._diag_box.styleSheet()
                                          .replace("#A7F3D0", "#A7F3D0"))
        else:
            lines = [
                "✗ Server NOT reachable on localhost",
                f"  Reason       : {result.get('error', 'unknown')}",
                "",
                "  Possible causes:",
                "    • LiveServer.start() was not called from main.py",
                "    • websockets package is not installed",
                "    • Port 8000 is blocked by another app",
                "",
                "  Check the activity log for 'LAN Monitor ready'.",
            ]
            self._diag_box.setStyleSheet(
                "QTextEdit { background: #450A0A; color: #FCA5A5;"
                " font-family: Consolas, monospace; font-size: 11px;"
                " border-radius: 6px; padding: 8px; }")
        self._diag_box.setPlainText("\n".join(lines))


# ── Convenience entry point ────────────────────────────────────────
def show_network_info(parent, live_server):
    """Instantiate and show the dialog. Returns QDialog result code."""
    dlg = NetworkInfoDialog(parent, live_server)
    return dlg.exec_()