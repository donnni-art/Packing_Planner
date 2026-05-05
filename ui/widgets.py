"""
Shared Widgets — AutoPack VLO-127S
====================================
Reusable UI components: SectionHeader, StatCard, Badge, Card, buttons, labels.
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame, QVBoxLayout, QHBoxLayout,
    QSizePolicy,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from ui.theme import THEME, S, F


# ─── Section Header ──────────────────────────────────────────

class SectionHeader(QWidget):
    """Page-level header bar with left accent bar, title and optional subtitle."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        T = THEME
        self.setFixedHeight(S(60))
        self.setStyleSheet(
            f"SectionHeader {{ background: {T['bg_header']}; "
            f"border-bottom: 1px solid {T['border']}; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, S(22), 0)
        lay.setSpacing(0)

        # Left accent bar
        accent_bar = QFrame()
        accent_bar.setFixedWidth(S(5))
        accent_bar.setStyleSheet(
            f"QFrame {{ background: {T['accent']}; border: none; "
            f"border-top-right-radius: {S(3)}px; border-bottom-right-radius: {S(3)}px; }}")
        lay.addWidget(accent_bar)

        lay.addSpacing(S(16))

        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", F(17), QFont.Bold))
        lbl.setStyleSheet(f"color: {T['text_primary']}; background: transparent;")
        lay.addWidget(lbl)

        if subtitle:
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setStyleSheet(
                f"color: {T['border']}; max-height: {S(22)}px; margin: 0 {S(10)}px;")
            lay.addWidget(sep)
            sub = QLabel(subtitle)
            sub.setFont(QFont("Segoe UI", F(12)))
            sub.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
            lay.addWidget(sub)

        lay.addStretch()
        self._right_lay = lay

    def add_widget(self, w):
        self._right_lay.addWidget(w)


# ─── Stat Card ────────────────────────────────────────────────

class StatCard(QFrame):
    """Dashboard / summary number card with coloured top border and optional icon."""

    def __init__(self, label, value, sub="", color=None, icon="", parent=None):
        super().__init__(parent)
        T = THEME
        color = color or T["accent"]
        self.setStyleSheet(f"""StatCard {{
            background: #FFFFFF;
            border: 1px solid {T['border']};
            border-radius: {S(10)}px;
            border-top: 4px solid {color};
        }}""")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(16), S(12), S(14), S(12))
        lay.setSpacing(S(4))

        # Top row: label + icon
        top_row = QHBoxLayout()
        top_row.setSpacing(S(4))

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", F(10), QFont.Bold))
        lbl.setStyleSheet(
            f"color: {T['text_muted']}; background: transparent; "
            f"text-transform: uppercase; letter-spacing: 0.5px;")
        top_row.addWidget(lbl)
        top_row.addStretch()

        if icon:
            ico_lbl = QLabel(icon)
            ico_lbl.setFont(QFont("Segoe UI Emoji", F(16)))
            ico_lbl.setStyleSheet(
                f"color: {color}; background: transparent; opacity: 0.7;")
            ico_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            top_row.addWidget(ico_lbl)

        lay.addLayout(top_row)

        self._val_lbl = QLabel(value)
        self._val_lbl.setFont(QFont("Segoe UI", F(28), QFont.Bold))
        self._val_lbl.setStyleSheet(f"color: {color}; background: transparent;")
        lay.addWidget(self._val_lbl)

        self._sub_lbl = None
        if sub:
            self._sub_lbl = QLabel(sub)
            self._sub_lbl.setFont(QFont("Segoe UI", F(11)))
            self._sub_lbl.setStyleSheet(
                f"color: {T['text_muted']}; background: transparent;")
            lay.addWidget(self._sub_lbl)

    def set_value(self, v):
        self._val_lbl.setText(v)

    def set_sub(self, s):
        if self._sub_lbl is None:
            # Card was built without sub text — create the label now
            T = THEME
            self._sub_lbl = QLabel(s)
            self._sub_lbl.setFont(QFont("Segoe UI", F(11)))
            self._sub_lbl.setStyleSheet(
                f"color: {T['text_muted']}; background: transparent;")
            self.layout().addWidget(self._sub_lbl)
        self._sub_lbl.setText(s)


# ─── Badge ────────────────────────────────────────────────────

class Badge(QLabel):
    """Coloured pill label."""
    COLORS = {
        "blue":  ("#DBEAFE", "#2563EB"),
        "green": ("#DCFCE7", "#16A34A"),
        "amber": ("#FEF3C7", "#D97706"),
        "red":   ("#FEE2E2", "#DC2626"),
        "gray":  ("#F1F5F9", "#64748B"),
    }

    def __init__(self, text, color="blue", parent=None):
        super().__init__(text, parent)
        bg, fg = self.COLORS.get(color, self.COLORS["blue"])
        self.setStyleSheet(f"""QLabel {{
            background: {bg}; color: {fg}; border-radius: {S(10)}px;
            padding: {S(3)}px {S(10)}px; font-size: {F(11)}px; font-weight: 700;
        }}""")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


# ─── Card Frame ──────────────────────────────────────────────

class Card(QFrame):
    """White card container with rounded corners and subtle border."""

    def __init__(self, parent=None):
        super().__init__(parent)
        T = THEME
        self.setStyleSheet(
            f"Card {{ background: {T['bg_card']}; "
            f"border: 1px solid {T['border']}; border-radius: {S(10)}px; }}")

    def set_layout(self, lay):
        lay.setContentsMargins(S(16), S(14), S(16), S(14))
        self.setLayout(lay)


# ─── Factory helpers ─────────────────────────────────────────

def make_btn(text, style="primary", parent=None) -> QPushButton:
    """Create a themed QPushButton. Styles: primary, flat, ghost, danger, success."""
    btn = QPushButton(text, parent)
    btn.setFont(QFont("Segoe UI", F(13), QFont.Bold))
    props = {
        "flat":    {"flat": "true"},
        "ghost":   {"ghost": "true"},
        "danger":  {"danger": "true"},
        "success": {"success": "true"},
    }
    for k, v in props.get(style, {}).items():
        btn.setProperty(k, v)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    return btn


def make_label(text, bold=False, size=13, color=None) -> QLabel:
    """Create a themed QLabel."""
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", F(size), QFont.Bold if bold else QFont.Normal))
    lbl.setStyleSheet(f"color: {color or THEME['text_primary']}; background: transparent;")
    return lbl


def make_field_group(label_text, widget):
    """Create a vertical layout with a labelled field."""
    lay = QVBoxLayout()
    lay.setSpacing(S(3))
    lbl = make_label(label_text, size=11, color=THEME["text_muted"])
    lbl.setStyleSheet(
        f"color: {THEME['text_muted']}; background: transparent; font-weight: 700;")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return lay
