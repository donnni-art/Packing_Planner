"""
Theme & Scaling — AutoPack VLO-127S
====================================
Blue & White theme, DPI-aware scaling helpers, and global QSS stylesheet.
"""

from PyQt5.QtWidgets import QApplication

# ══════════════════════════════════════════════════════════════
#  SCALE HELPER
# ══════════════════════════════════════════════════════════════

_cached_scale = None

def _screen_scale() -> float:
    """Auto-detect scale from primary screen height (1080p = 1.0)."""
    global _cached_scale
    if _cached_scale is not None:
        return _cached_scale
    app = QApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    h = screen.geometry().height()
    if h <= 800:   _cached_scale = 0.72
    elif h <= 900:   _cached_scale = 0.82
    elif h <= 1080:  _cached_scale = 1.00
    elif h <= 1440:  _cached_scale = 1.20
    else:            _cached_scale = 1.40
    return _cached_scale


def S(px: int) -> int:
    """Scale a pixel value based on screen resolution."""
    return max(1, round(px * _screen_scale()))


def F(pt: int) -> int:
    """Scale a font-point size based on screen resolution (+2 readability boost)."""
    return max(8, round((pt + 2) * _screen_scale()))


# ══════════════════════════════════════════════════════════════
#  THEME  (Blue & White)
# ══════════════════════════════════════════════════════════════

THEME = {
    "bg_app":        "#EEF2F7",
    "bg_sidebar":    "#141C2E",
    "bg_sidebar_sel":"#2563EB",
    "bg_sidebar_hov":"#1E2D45",
    "bg_card":       "#FFFFFF",
    "bg_header":     "#FFFFFF",
    "bg_table_alt":  "#F8FBFF",
    "bg_input":      "#FAFBFD",
    "bg_tag_blue":   "#DBEAFE",
    "bg_tag_green":  "#DCFCE7",
    "bg_tag_amber":  "#FEF3C7",
    "bg_tag_red":    "#FEE2E2",

    "accent":        "#2563EB",
    "accent2":       "#0EA5E9",
    "accent_green":  "#16A34A",
    "accent_amber":  "#D97706",
    "accent_red":    "#DC2626",

    "text_primary":  "#0F172A",
    "text_secondary":"#475569",
    "text_muted":    "#94A3B8",
    "text_sidebar":  "#94A3B8",
    "text_sidebar_sel":"#FFFFFF",
    "text_on_blue":  "#FFFFFF",

    "border":        "#E2E8F0",
    "border_accent": "#BFDBFE",
    "divider":       "#F1F5F9",

    "shadow":        "rgba(15,23,42,0.10)",
}


# ══════════════════════════════════════════════════════════════
#  GLOBAL STYLESHEET
# ══════════════════════════════════════════════════════════════

def make_stylesheet(sc: float = 1.0) -> str:
    T = THEME
    r = lambda px: max(1, round(px * sc))
    f = lambda pt: max(8, round((pt + 2) * sc))
    return f"""
    QWidget {{
        font-family: "Segoe UI", "Noto Sans Thai", "Sarabun", "Tahoma", sans-serif;
        font-size: {f(13)}px;
        color: {T['text_primary']};
        background: transparent;
    }}
    QMainWindow, QDialog {{
        background: {T['bg_app']};
    }}
    QScrollBar:vertical {{
        background: transparent; width: {r(7)}px; margin: {r(2)}px;
    }}
    QScrollBar::handle:vertical {{
        background: #CBD5E1; border-radius: {r(3)}px; min-height: {r(36)}px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #94A3B8;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent; height: {r(7)}px; margin: {r(2)}px;
    }}
    QScrollBar::handle:horizontal {{
        background: #CBD5E1; border-radius: {r(3)}px; min-width: {r(36)}px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #94A3B8;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {T['bg_input']};
        border: 1.5px solid {T['border']};
        border-radius: {r(7)}px;
        padding: {r(6)}px {r(10)}px;
        font-size: {f(13)}px;
        color: {T['text_primary']};
        selection-background-color: {T['accent']};
        min-height: {r(34)}px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 2px solid {T['accent']}; background: #FFFFFF;
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
        border-color: {T['border_accent']};
    }}
    QComboBox::drop-down {{ border: none; width: {r(24)}px; background: transparent; }}
    QComboBox::down-arrow {{
        image: none;
        border-left: {r(4)}px solid transparent;
        border-right: {r(4)}px solid transparent;
        border-top: {r(5)}px solid {T['text_secondary']};
        width: 0; height: 0;
    }}
    QComboBox QAbstractItemView {{
        background: #FFFFFF; border: 1px solid {T['border_accent']};
        selection-background-color: {T['bg_tag_blue']};
        selection-color: {T['accent']}; border-radius: {r(6)}px; padding: {r(4)}px;
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background: {T['bg_tag_blue']}; border: none; width: {r(22)}px;
        border-radius: {r(4)}px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {T['border_accent']};
    }}
    QPushButton {{
        background: {T['accent']}; color: #FFFFFF; border: none;
        border-radius: {r(8)}px; padding: {r(9)}px {r(20)}px;
        font-size: {f(13)}px; font-weight: 600; min-height: {r(40)}px;
    }}
    QPushButton:hover {{ background: #1D4ED8; }}
    QPushButton:pressed {{ background: #1E40AF; padding-top: {r(10)}px; padding-bottom: {r(8)}px; }}
    QPushButton:disabled {{ background: {T['border']}; color: {T['text_muted']}; }}
    QPushButton[flat="true"] {{
        background: {T['bg_tag_blue']}; color: {T['accent']};
        border: 1.5px solid {T['border_accent']};
    }}
    QPushButton[flat="true"]:hover {{ background: #BFDBFE; }}
    QPushButton[danger="true"] {{ background: {T['accent_red']}; }}
    QPushButton[danger="true"]:hover {{ background: #B91C1C; }}
    QPushButton[success="true"] {{ background: {T['accent_green']}; }}
    QPushButton[success="true"]:hover {{ background: #15803D; }}
    QPushButton[ghost="true"] {{
        background: transparent; color: {T['text_secondary']};
        border: 1.5px solid {T['border']};
    }}
    QPushButton[ghost="true"]:hover {{
        background: {T['bg_tag_blue']}; color: {T['accent']};
        border-color: {T['accent']};
    }}
    QTableWidget {{
        background: {T['bg_card']}; gridline-color: {T['divider']};
        border: none; font-size: {f(13)}px;
        alternate-background-color: {T['bg_table_alt']};
        selection-background-color: {T['bg_tag_blue']};
        selection-color: {T['accent']};
    }}
    QTableWidget::item {{ padding: {r(9)}px {r(10)}px; border: none; }}
    QTableWidget::item:selected {{ background: {T['bg_tag_blue']}; color: {T['accent']}; }}
    QTableWidget::item:hover {{ background: #EFF6FF; }}
    QHeaderView::section {{
        background: #F1F5F9; color: {T['text_secondary']};
        font-weight: 700; font-size: {f(11)}px;
        padding: {r(9)}px {r(10)}px; border: none;
        border-bottom: 2.5px solid {T['accent']};
        text-transform: uppercase;
    }}
    QGroupBox {{
        background: {T['bg_card']};
        border: 1.5px solid {T['border']};
        border-radius: {r(10)}px;
        margin-top: {r(22)}px;
        padding: {r(14)}px {r(14)}px {r(12)}px {r(14)}px;
        font-weight: 700;
        font-size: {f(12)}px;
        color: {T['text_primary']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: {r(10)}px;
        padding: {r(3)}px {r(10)}px;
        background: {T['accent']};
        color: #FFFFFF;
        border-radius: {r(5)}px;
        font-size: {f(11)}px;
        font-weight: 700;
    }}
    QTabWidget::pane {{
        border: 1.5px solid {T['border']}; border-radius: {r(8)}px;
        background: {T['bg_card']}; top: -2px;
    }}
    QTabBar::tab {{
        background: {T['bg_app']}; border: 1.5px solid {T['border']};
        border-bottom: none; padding: {r(9)}px {r(20)}px;
        border-top-left-radius: {r(7)}px; border-top-right-radius: {r(7)}px;
        font-size: {f(13)}px; color: {T['text_secondary']}; margin-right: {r(3)}px;
    }}
    QTabBar::tab:selected {{
        background: {T['bg_card']}; color: {T['accent']};
        font-weight: 700; border-bottom: none;
        border-top: 3px solid {T['accent']};
    }}
    QTextEdit {{
        background: {T['bg_card']}; border: 1.5px solid {T['border']};
        border-radius: {r(7)}px; padding: {r(8)}px;
        font-family: "Consolas", "Courier New", monospace;
        font-size: {f(12)}px;
        color: {T['text_primary']};
    }}
    QProgressBar {{
        background: {T['border']}; border-radius: {r(5)}px;
        height: {r(10)}px; text-align: center;
        font-size: {f(10)}px; color: transparent; border: none;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {T['accent']}, stop:1 {T['accent2']});
        border-radius: {r(5)}px;
    }}
    QCheckBox {{ spacing: {r(8)}px; font-size: {f(13)}px; }}
    QCheckBox::indicator {{
        width: {r(18)}px; height: {r(18)}px;
        border: 2px solid {T['border']}; border-radius: {r(4)}px;
        background: {T['bg_input']};
    }}
    QCheckBox::indicator:hover {{
        border-color: {T['accent']};
    }}
    QCheckBox::indicator:checked {{
        background: {T['accent']}; border-color: {T['accent']};
    }}
    QDateEdit {{
        background: {T['bg_input']}; border: 1.5px solid {T['border']};
        border-radius: {r(7)}px; padding: {r(6)}px {r(10)}px;
        min-height: {r(34)}px; font-size: {f(13)}px;
        color: {T['text_primary']};
    }}
    QDateEdit:focus {{ border: 2px solid {T['accent']}; }}
    QDateEdit::drop-down {{
        subcontrol-origin: padding; subcontrol-position: center right;
        width: {r(22)}px; border: none;
    }}
    QCalendarWidget {{
        background: #FFFFFF;
    }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{
        background: {T['accent']}; min-height: {r(36)}px;
    }}
    QCalendarWidget QToolButton {{
        color: #FFFFFF; font-size: {f(13)}px; font-weight: bold;
        background: transparent; border: none; padding: {r(4)}px;
    }}
    QCalendarWidget QToolButton:hover {{
        background: rgba(255,255,255,0.2); border-radius: {r(4)}px;
    }}
    QCalendarWidget QSpinBox {{
        color: #FFFFFF; background: transparent; border: none;
        font-size: {f(13)}px; font-weight: bold;
        selection-background-color: rgba(255,255,255,0.3);
    }}
    QCalendarWidget QAbstractItemView {{
        background: #FFFFFF; color: #1E293B;
        selection-background-color: {T['accent']};
        selection-color: #FFFFFF;
        font-size: {f(12)}px;
        outline: none;
    }}
    QCalendarWidget QAbstractItemView:enabled {{
        color: #1E293B;
    }}
    QCalendarWidget QAbstractItemView:disabled {{
        color: #94A3B8;
    }}
    QCalendarWidget QWidget {{ alternate-background-color: #F1F5F9; }}
    QSplitter::handle {{ background: {T['border']}; }}
    QToolTip {{
        background: {T['text_primary']}; color: #FFFFFF;
        border: none; border-radius: {r(5)}px;
        padding: {r(5)}px {r(10)}px; font-size: {f(11)}px;
    }}
    """
