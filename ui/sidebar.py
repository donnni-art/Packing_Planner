"""
Sidebar Navigation — AutoPack VLO-127S
========================================
Left-hand sidebar with icon buttons for page switching.
"""

from PyQt5.QtWidgets import QWidget, QToolButton, QLabel, QFrame, QVBoxLayout
from PyQt5.QtGui import QFont, QColor, QPixmap, QPainter, QIcon
from PyQt5.QtCore import Qt, QSize, pyqtSignal

from ui.theme import THEME, S, F


class SidebarButton(QToolButton):
    """Single sidebar navigation button with emoji icon and left active indicator."""

    def __init__(self, icon_char, label, page_idx, parent=None):
        super().__init__(parent)
        self.page_idx = page_idx
        self.setCheckable(True)
        self.setFixedSize(QSize(S(84), S(70)))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(label)
        self._icon_char = icon_char
        self._update_style(False)

    def _update_style(self, active):
        T = THEME
        bg  = T["bg_sidebar_sel"] if active else "transparent"
        fg  = "#FFFFFF" if active else T["text_sidebar"]
        hbg = T["bg_sidebar_sel"] if active else T["bg_sidebar_hov"]
        indicator = f"border-left: {S(4)}px solid #FFFFFF;" if active else f"border-left: {S(4)}px solid transparent;"

        self.setStyleSheet(f"""QToolButton {{
            {indicator}
            background: {bg}; color: {fg};
            border-top: none; border-bottom: none; border-right: none;
            border-top-right-radius: {S(8)}px;
            border-bottom-right-radius: {S(8)}px;
            font-size: {F(10)}px; font-weight: {'700' if active else '400'};
            padding: {S(5)}px {S(2)}px;
        }} QToolButton:hover {{ background: {hbg}; border-left: {S(4)}px solid {'#FFFFFF' if active else 'rgba(255,255,255,0.3)'}; }}""")

        icon_size = S(28)
        pix = QPixmap(QSize(icon_size, icon_size))
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(QFont("Segoe UI Emoji", F(16)))
        painter.setPen(QColor(fg))
        painter.drawText(pix.rect(), Qt.AlignCenter, self._icon_char)
        painter.end()
        self.setIcon(QIcon(pix))
        self.setIconSize(QSize(icon_size, icon_size))

    def setActive(self, active):
        self.setChecked(active)
        self._update_style(active)


class Sidebar(QWidget):
    """Left-hand sidebar with page navigation buttons."""

    page_changed = pyqtSignal(int)

    PAGES = [
        ("📊", "Dashboard", 0),
        ("📦", "Planner",   1),
        ("🎯", "Monitor",   2),
        ("📋", "History",   3),
        ("⚙",  "Settings",  4),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        T = THEME
        self.setFixedWidth(S(90))
        self.setStyleSheet(f"background: {T['bg_sidebar']}; border: none;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, S(10), 0, S(14))
        lay.setSpacing(S(3))
        lay.setAlignment(Qt.AlignTop)

        # Brand area
        brand_w = QWidget()
        brand_w.setStyleSheet("background: transparent;")
        brand_lay = QVBoxLayout(brand_w)
        brand_lay.setContentsMargins(S(4), S(8), S(4), S(8))
        brand_lay.setSpacing(S(2))

        logo = QLabel("📐")
        logo.setFont(QFont("Segoe UI Emoji", F(22)))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("color: #60A5FA; background: transparent;")
        brand_lay.addWidget(logo)

        app_name = QLabel("AutoPack")
        app_name.setFont(QFont("Segoe UI", F(8), QFont.Bold))
        app_name.setAlignment(Qt.AlignCenter)
        app_name.setStyleSheet("color: #64748B; background: transparent; letter-spacing: 1px;")
        brand_lay.addWidget(app_name)

        lay.addWidget(brand_w)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"background: #243554; max-height: 1px; margin: {S(2)}px {S(8)}px;")
        lay.addWidget(div)

        lay.addSpacing(S(6))

        self._buttons = []
        for icon, label, idx in self.PAGES:
            if idx == 4:
                lay.addStretch()
            btn = SidebarButton(icon, label, idx, self)
            btn.clicked.connect(lambda checked, i=idx: self._on_click(i))
            lay.addWidget(btn, alignment=Qt.AlignHCenter)
            self._buttons.append(btn)

        # Version label at bottom
        ver = QLabel("v1.0")
        ver.setAlignment(Qt.AlignCenter)
        ver.setFont(QFont("Segoe UI", F(8)))
        ver.setStyleSheet("color: #334155; background: transparent; padding-top: 4px;")
        lay.addWidget(ver)

        self._buttons[0].setActive(True)

    def _on_click(self, idx):
        for btn in self._buttons:
            btn.setActive(btn.page_idx == idx)
        self.page_changed.emit(idx)

    def select(self, idx):
        self._on_click(idx)
