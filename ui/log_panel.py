"""
Log Panel — AutoPack VLO-127S
===============================
Bottom activity log panel with colored entries.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit
from PyQt5.QtGui import QFont

from ui.theme import THEME, S, F
from ui.widgets import make_btn, make_label


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        T = THEME
        self.setFixedHeight(S(130))
        self.setStyleSheet(
            f"LogPanel {{ background: {T['bg_card']}; border-top: 1px solid {T['border']}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(12), S(6), S(12), S(6))
        lay.setSpacing(S(4))
        hdr_lay = QHBoxLayout()
        ttl = make_label("Activity Log", bold=True, size=10, color=T["text_muted"])
        clear_btn = make_btn("Clear", "ghost")
        clear_btn.setFixedHeight(S(26))
        clear_btn.setFont(QFont("Segoe UI", F(9)))
        clear_btn.clicked.connect(self._clear)
        hdr_lay.addWidget(ttl); hdr_lay.addStretch(); hdr_lay.addWidget(clear_btn)
        lay.addLayout(hdr_lay)
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setFont(QFont("Consolas", F(10)))
        self._log_edit.setStyleSheet(f"""QTextEdit {{
            background: #F8FAFD; border: 1px solid {T['border']};
            border-radius: {S(5)}px; padding: {S(4)}px {S(6)}px;
        }}""")
        lay.addWidget(self._log_edit)

    def append(self, line, level="INFO"):
        T = THEME
        colors = {"INFO": T["text_primary"], "PLAN": T["accent"],
                  "WARN": T["accent_amber"], "ERROR": T["accent_red"]}
        c = colors.get(level, T["text_secondary"])
        self._log_edit.append(
            f'<span style="color:{c};font-family:Consolas;font-size:{F(10)}px;">{line}</span>')
        self._log_edit.verticalScrollBar().setValue(
            self._log_edit.verticalScrollBar().maximum())

    def _clear(self):
        self._log_edit.clear()