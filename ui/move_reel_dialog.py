"""
Move Reel Dialogs — AutoPack VLO-127S
========================================
Professional Material-Light dialogs for safe plan editing.

Public widgets:
  • EditReelMenu        — choose Move / Change Target / Delete
  • MoveReelDialog      — pick destination box with live preview
  • ChangeTargetDialog  — adjust target qty with live validation
"""

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QPixmap, QIcon
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QRadioButton, QButtonGroup,
    QScrollArea, QWidget, QMessageBox, QSpinBox, QSizePolicy,
    QGraphicsDropShadowEffect,
)

from core.plan_editor import (
    PlanEditor, MoveReelOp, ChangeTargetOp, DeleteReelOp, PlanEditError,
)


# ════════════════════════════════════════════════════════════════════
#  DESIGN TOKENS — Material Light
# ════════════════════════════════════════════════════════════════════

COLOR = {
    "bg":           "#F5F7FA",
    "surface":      "#FFFFFF",
    "surface_alt":  "#F8FAFC",
    "border":       "#E2E8F0",
    "border_2":     "#CBD5E1",
    "text":         "#0F172A",
    "text_2":       "#475569",
    "text_3":       "#94A3B8",
    "primary":      "#1E40AF",
    "primary_2":    "#2563EB",
    "primary_soft": "#DBEAFE",
    "success":      "#059669",
    "success_soft": "#D1FAE5",
    "warn":         "#D97706",
    "warn_soft":    "#FEF3C7",
    "danger":       "#DC2626",
    "danger_soft":  "#FEE2E2",
    "violet":       "#7C3AED",
    "violet_soft":  "#EDE9FE",
}


# Stylesheet shared by all dialogs
_QSS = f"""
QDialog {{
    background: {COLOR['bg']};
}}
QLabel {{
    color: {COLOR['text']};
    background: transparent;
}}

/* Section card */
QFrame#card {{
    background: {COLOR['surface']};
    border: 1px solid {COLOR['border']};
    border-radius: 12px;
}}

/* Source banner */
QFrame#source-card {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {COLOR['primary_soft']}, stop:1 {COLOR['surface']});
    border: 1px solid {COLOR['primary_2']};
    border-radius: 12px;
}}

/* Preview card variants */
QFrame#preview-info {{
    background: {COLOR['surface_alt']};
    border: 1px dashed {COLOR['border_2']};
    border-radius: 10px;
}}
QFrame#preview-ok {{
    background: {COLOR['success_soft']};
    border: 1px solid #86EFAC;
    border-radius: 10px;
}}
QFrame#preview-warn {{
    background: {COLOR['warn_soft']};
    border: 1px solid #FCD34D;
    border-radius: 10px;
}}
QFrame#preview-error {{
    background: {COLOR['danger_soft']};
    border: 1px solid #FCA5A5;
    border-radius: 10px;
}}

/* Buttons */
QPushButton {{
    background: {COLOR['surface']};
    color: {COLOR['text_2']};
    border: 1px solid {COLOR['border_2']};
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 600;
    min-height: 18px;
}}
QPushButton:hover {{
    background: {COLOR['surface_alt']};
    border-color: {COLOR['text_3']};
}}
QPushButton:pressed {{
    background: {COLOR['border']};
}}
QPushButton:disabled {{
    color: {COLOR['text_3']};
    background: {COLOR['surface_alt']};
    border-color: {COLOR['border']};
}}

QPushButton#primary {{
    background: {COLOR['primary']};
    color: #FFFFFF;
    border: 1px solid {COLOR['primary']};
}}
QPushButton#primary:hover {{
    background: {COLOR['primary_2']};
    border-color: {COLOR['primary_2']};
}}
QPushButton#primary:pressed {{
    background: #1E3A8A;
}}
QPushButton#primary:disabled {{
    background: {COLOR['border_2']};
    color: {COLOR['text_3']};
    border-color: {COLOR['border_2']};
}}

QPushButton#danger {{
    background: {COLOR['danger']};
    color: #FFFFFF;
    border: 1px solid #B91C1C;
}}
QPushButton#danger:hover {{
    background: #B91C1C;
}}

/* Menu-style choice buttons */
QPushButton#choice {{
    text-align: left;
    padding: 14px 16px;
    font-size: 14px;
    background: {COLOR['surface']};
    color: {COLOR['text']};
    border: 1px solid {COLOR['border']};
}}
QPushButton#choice:hover {{
    background: {COLOR['primary_soft']};
    border-color: {COLOR['primary_2']};
}}
QPushButton#choice-danger {{
    text-align: left;
    padding: 14px 16px;
    font-size: 14px;
    color: {COLOR['danger']};
    background: {COLOR['surface']};
    border: 1px solid {COLOR['border']};
}}
QPushButton#choice-danger:hover {{
    background: {COLOR['danger_soft']};
    border-color: #FCA5A5;
}}

/* Scroll area */
QScrollArea {{
    border: 1px solid {COLOR['border']};
    border-radius: 10px;
    background: {COLOR['surface']};
}}
QScrollBar:vertical {{
    background: {COLOR['surface_alt']};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR['border_2']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLOR['text_3']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* Spin box */
QSpinBox {{
    font-size: 22px;
    font-weight: 700;
    padding: 10px 12px;
    border: 2px solid {COLOR['border_2']};
    border-radius: 8px;
    background: {COLOR['surface']};
    color: {COLOR['text']};
    min-height: 24px;
}}
QSpinBox:focus {{
    border-color: {COLOR['primary_2']};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 28px;
    border: none;
    background: {COLOR['surface_alt']};
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {COLOR['primary_soft']};
}}
"""


# ════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════

def _apply_shadow(widget, blur=20, offset_y=4, alpha=40):
    """Drop a soft Material-style shadow on a widget."""
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(blur)
    eff.setOffset(0, offset_y)
    eff.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(eff)


def _hr() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {COLOR['border']}; border: none;")
    return f


def _spacer(h=10) -> QWidget:
    w = QWidget()
    w.setFixedHeight(h)
    return w


def _title(text, size=15) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", size, QFont.Bold)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {COLOR['text']};")
    return lbl


def _eyebrow(text) -> QLabel:
    """Small uppercase label above a card heading."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {COLOR['text_3']}; font-size: 10px; font-weight: 700;"
        " letter-spacing: 1.2px;")
    return lbl


def _box_chip(box_id) -> str:
    """Compact textual icon for a box."""
    if box_id == 0:
        return "📋 Rem"
    return f"📦 Box {box_id}"


# ════════════════════════════════════════════════════════════════════
#  EDIT REEL MENU
# ════════════════════════════════════════════════════════════════════

class EditReelMenu(QDialog):
    """Pop a small dialog asking what action to take on the selected reel."""

    OP_MOVE   = "move"
    OP_TARGET = "target"
    OP_DELETE = "delete"
    OP_CANCEL = "cancel"

    def __init__(self, parent, reel_summary_html: str):
        super().__init__(parent)
        self.choice = self.OP_CANCEL
        self.setWindowTitle("Edit Reel")
        self.setStyleSheet(_QSS)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        # Header
        title = _title("Edit Reel", 16)
        sub = QLabel("Choose what you'd like to do with this reel")
        sub.setStyleSheet(f"color: {COLOR['text_2']}; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(sub)

        # Source summary card
        src = QFrame()
        src.setObjectName("source-card")
        src_lay = QVBoxLayout(src)
        src_lay.setContentsMargins(14, 12, 14, 12)
        src_lay.setSpacing(2)
        eyebrow = _eyebrow("EDITING")
        src_lay.addWidget(eyebrow)
        info = QLabel(reel_summary_html)
        info.setTextFormat(Qt.RichText)
        src_lay.addWidget(info)
        root.addWidget(src)

        root.addWidget(_spacer(4))

        # Choice buttons
        for label, op, obj_name in [
            ("🔀   Move to another box", self.OP_MOVE,   "choice"),
            ("✏    Change target qty",  self.OP_TARGET, "choice"),
            ("🗑   Delete reel",         self.OP_DELETE, "choice-danger"),
        ]:
            b = QPushButton(label)
            b.setObjectName(obj_name)
            b.setMinimumHeight(48)
            b.clicked.connect(lambda _, o=op: self._pick(o))
            root.addWidget(b)

        root.addWidget(_spacer(4))

        # Cancel
        cancel = QPushButton("Cancel")
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.reject)
        root.addWidget(cancel)

    def _pick(self, op):
        self.choice = op
        self.accept()


# ════════════════════════════════════════════════════════════════════
#  MOVE REEL DIALOG
# ════════════════════════════════════════════════════════════════════

class MoveReelDialog(QDialog):
    """Dialog for moving one pending reel to another box."""

    def __init__(self, parent, editor: PlanEditor, reel_id: int):
        super().__init__(parent)
        self._editor = editor
        self._reel_id = reel_id
        self._reel = editor._find_reel(reel_id)
        self._radio_group = QButtonGroup(self)
        self._radio_group.buttonClicked.connect(self._on_target_selected)
        self._selected_box = None

        self.setWindowTitle(f"Move Reel R{reel_id}")
        self.setStyleSheet(_QSS)
        self.setModal(True)
        self.resize(620, 680)

        self._build_ui()
        self._refresh_options()

    # ── UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        # Header
        root.addWidget(_title("Move Reel", 16))
        sub = QLabel("Select a destination box. Invalid options are disabled.")
        sub.setStyleSheet(f"color: {COLOR['text_2']}; font-size: 12px;")
        root.addWidget(sub)

        # Source banner
        if self._reel:
            r = self._reel
            box_lbl = "📋 Remainder" if r["box"] == 0 else f"Box {r['box']}"
            src = QFrame()
            src.setObjectName("source-card")
            src_lay = QHBoxLayout(src)
            src_lay.setContentsMargins(16, 14, 16, 14)
            src_lay.setSpacing(14)

            # Big reel pill
            pill = QLabel(f"R{r['reel']}")
            pill.setAlignment(Qt.AlignCenter)
            pill.setFixedSize(54, 54)
            pill.setStyleSheet(
                f"background: {COLOR['primary']}; color: white; "
                f"border-radius: 27px; font-size: 16px; font-weight: 700;"
                f" border: 3px solid white;")
            src_lay.addWidget(pill)

            # Source info
            info_lay = QVBoxLayout()
            info_lay.setSpacing(2)
            info_lay.addWidget(_eyebrow("MOVING FROM"))
            t = QLabel(f"<b style='font-size:15px;color:{COLOR['text']}'>"
                       f"{box_lbl}</b>")
            t.setTextFormat(Qt.RichText)
            info_lay.addWidget(t)
            d = QLabel(
                f"<span style='color:{COLOR['text_2']};font-size:12px'>"
                f"Lot <b>{r.get('lot', '—')}</b>  ·  "
                f"Target <b>{r.get('target', 0):,}</b> pcs</span>")
            d.setTextFormat(Qt.RichText)
            info_lay.addWidget(d)
            src_lay.addLayout(info_lay, stretch=1)
            root.addWidget(src)

        # Section heading
        root.addWidget(_spacer(2))
        h = _eyebrow("DESTINATION")
        root.addWidget(h)

        # Scrollable list of options
        self._options_wrap = QWidget()
        self._options_wrap.setStyleSheet(f"background: {COLOR['surface']};")
        self._options_lay = QVBoxLayout(self._options_wrap)
        self._options_lay.setContentsMargins(8, 8, 8, 8)
        self._options_lay.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidget(self._options_wrap)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(230)
        root.addWidget(scroll, stretch=1)

        # Preview card
        self._preview_card = QFrame()
        self._preview_card.setObjectName("preview-info")
        self._preview_lay = QVBoxLayout(self._preview_card)
        self._preview_lay.setContentsMargins(14, 12, 14, 12)
        self._preview_lay.setSpacing(6)
        self._preview_lbl = QLabel(
            "👆  Select a destination above to see the impact preview.")
        self._preview_lbl.setWordWrap(True)
        self._preview_lbl.setStyleSheet(
            f"color: {COLOR['text_3']}; font-size: 12px;")
        self._preview_lay.addWidget(self._preview_lbl)
        self._preview_card.setMinimumHeight(110)
        root.addWidget(self._preview_card)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self._confirm_btn = QPushButton("Confirm Move")
        self._confirm_btn.setObjectName("primary")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._confirm_btn)
        root.addLayout(btn_row)

    # ── Option list ──────────────────────────────────────────

    def _refresh_options(self):
        # Clear previous
        while self._options_lay.count():
            item = self._options_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for btn in list(self._radio_group.buttons()):
            self._radio_group.removeButton(btn)

        options = self._editor.list_valid_target_boxes(self._reel_id)
        if not options:
            empty = QLabel("No destinations available")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLOR['text_3']}; padding: 40px; font-size: 13px;")
            self._options_lay.addWidget(empty)
            return

        # Sort: valid first, then disabled
        options.sort(key=lambda o: (not o["ok"], o.get("is_new", False),
                                    o["box"]))
        for opt in options:
            self._options_lay.addWidget(self._make_option_row(opt))
        self._options_lay.addStretch()

    def _make_option_row(self, opt: dict) -> QWidget:
        b_id   = opt["box"]
        ok     = opt["ok"]
        is_new = opt.get("is_new", False)

        # Row container (acts as the radio's clickable area)
        row = QFrame()
        row.setCursor(Qt.PointingHandCursor if ok else Qt.ArrowCursor)
        row.setObjectName("option-row")
        ok_color = COLOR['border'] if ok else COLOR['border']
        bg_color = COLOR['surface'] if ok else COLOR['surface_alt']
        row.setStyleSheet(f"""
            QFrame#option-row {{
                background: {bg_color};
                border: 1px solid {ok_color};
                border-radius: 8px;
            }}
            QFrame#option-row:hover {{
                background: {COLOR['primary_soft'] if ok else COLOR['surface_alt']};
                border-color: {COLOR['primary_2'] if ok else COLOR['border']};
            }}
        """)

        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        # Radio button
        rb = QRadioButton()
        rb.setEnabled(ok)
        rb.setProperty("target_box", b_id)
        self._radio_group.addButton(rb)
        lay.addWidget(rb)

        # Box icon
        if is_new:
            icon_text = "✨"
            icon_bg   = COLOR['violet_soft']
            icon_fg   = COLOR['violet']
        elif b_id == 0:
            icon_text = "📋"
            icon_bg   = COLOR['violet_soft']
            icon_fg   = COLOR['violet']
        elif not ok:
            icon_text = "✕"
            icon_bg   = COLOR['danger_soft']
            icon_fg   = COLOR['danger']
        else:
            icon_text = f"{b_id}"
            icon_bg   = COLOR['primary_soft']
            icon_fg   = COLOR['primary']
        icon = QLabel(icon_text)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(38, 38)
        icon.setStyleSheet(
            f"background: {icon_bg}; color: {icon_fg}; "
            f"border-radius: 19px; font-size: 14px; font-weight: 700;")
        lay.addWidget(icon)

        # Text body
        body_lay = QVBoxLayout()
        body_lay.setSpacing(2)

        # Title
        if b_id == 0:
            title_text = "Remainder Box"
        elif is_new:
            title_text = f"New Box {b_id}"
        else:
            title_text = f"Box {b_id}"
        title_lbl = QLabel(f"<b>{title_text}</b>")
        title_lbl.setStyleSheet(
            f"color: {COLOR['text'] if ok else COLOR['text_3']}; font-size: 13px;")
        body_lay.addWidget(title_lbl)

        # Detail line
        if ok:
            if is_new:
                detail = (f"Empty box  ·  Free: <b>{opt['free']:,}</b> pcs"
                          f"  ·  <b>{opt['slots_free']}</b> slots")
            else:
                lots_txt = ", ".join(opt["lots"]) if opt["lots"] else "—"
                detail = (f"Filled <b>{opt['current_total']:,}</b>  ·  "
                          f"Free <b>{opt['free']:,}</b>  ·  "
                          f"Slots <b>{opt['slots_free']}</b>  ·  "
                          f"Lot <b>{lots_txt}</b>")
        else:
            detail = f"❌ {opt['reason']}"
        det_lbl = QLabel(detail)
        det_lbl.setTextFormat(Qt.RichText)
        det_lbl.setStyleSheet(
            f"color: {COLOR['text_2'] if ok else COLOR['danger']}; "
            f"font-size: 11px;")
        det_lbl.setWordWrap(True)
        body_lay.addWidget(det_lbl)

        lay.addLayout(body_lay, stretch=1)

        # Capacity bar (only for valid existing boxes)
        if ok and not is_new and b_id != 0:
            bar = self._make_cap_bar(
                opt['current_total'], opt['current_total'] + (self._reel['target'] if self._reel else 0),
                opt['current_total'] + opt['free'])
            lay.addWidget(bar)

        return row

    def _make_cap_bar(self, current, after, cap) -> QWidget:
        """Mini visual: current fill + projected fill after move."""
        wrap = QWidget()
        wrap.setFixedSize(120, 28)
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        bar_bg = QFrame()
        bar_bg.setFixedHeight(8)
        bar_bg.setStyleSheet(
            f"background: {COLOR['border']}; border-radius: 4px;")
        bar_lay = QHBoxLayout(bar_bg)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.setSpacing(0)

        cur_pct = (current / cap * 100) if cap else 0
        new_pct = ((after - current) / cap * 100) if cap else 0

        cur_seg = QFrame()
        cur_seg.setStyleSheet(
            f"background: {COLOR['primary_2']}; border-radius: 4px;")
        cur_seg.setMinimumWidth(0)
        cur_seg.setFixedWidth(int(120 * cur_pct / 100))

        new_seg = QFrame()
        new_seg.setStyleSheet(
            f"background: {COLOR['success']}; "
            f"border-top-right-radius: 4px; border-bottom-right-radius: 4px;")
        new_seg.setFixedWidth(int(120 * new_pct / 100))

        bar_lay.addWidget(cur_seg)
        bar_lay.addWidget(new_seg)
        bar_lay.addStretch()
        lay.addWidget(bar_bg)

        # Caption
        cap_lbl = QLabel(f"+{after - current:,}")
        cap_lbl.setAlignment(Qt.AlignRight)
        cap_lbl.setStyleSheet(
            f"color: {COLOR['success']}; font-size: 10px; font-weight: 700;"
            " font-family: Consolas, monospace;")
        lay.addWidget(cap_lbl)
        return wrap

    # ── Selection & preview ──────────────────────────────────

    def _on_target_selected(self, btn: QRadioButton):
        target_box = btn.property("target_box")
        self._selected_box = target_box
        op = MoveReelOp(self._reel_id, target_box)
        v = self._editor.validate(op)
        diff = self._editor.preview(op)
        self._render_preview(diff, v)
        self._confirm_btn.setEnabled(v.ok)

    def _render_preview(self, diff, validation):
        # Clear preview body
        while self._preview_lay.count():
            item = self._preview_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # Pick variant
        if not validation.ok:
            self._preview_card.setObjectName("preview-error")
        elif validation.warnings:
            self._preview_card.setObjectName("preview-warn")
        else:
            self._preview_card.setObjectName("preview-ok")
        self._preview_card.setStyleSheet("")  # re-apply via QSS
        self._preview_card.setStyle(self._preview_card.style())  # refresh

        # Header line
        if not validation.ok:
            head = QLabel(f"❌  {validation.reason}")
            head.setStyleSheet(
                f"color: #991B1B; font-weight: 700; font-size: 13px;")
            head.setWordWrap(True)
            self._preview_lay.addWidget(head)
            return

        head = QLabel(f"📦  {diff.summary}")
        head.setStyleSheet(
            f"color: {COLOR['text']}; font-weight: 700; font-size: 13px;")
        head.setWordWrap(True)
        self._preview_lay.addWidget(head)

        # Box impact rows
        if diff.boxes:
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(4)
            grid.setContentsMargins(0, 4, 0, 0)
            for i, b in enumerate(diff.boxes):
                lbl_box = QLabel(_box_chip(b.box))
                lbl_box.setStyleSheet(
                    f"color: {COLOR['text_2']}; font-size: 12px;"
                    " font-family: Consolas, monospace;")
                lbl_change = QLabel(
                    f"<b>{b.before:,}</b>  →  <b>{b.after:,}</b>"
                )
                lbl_change.setTextFormat(Qt.RichText)
                lbl_change.setStyleSheet(
                    f"color: {COLOR['text']}; font-size: 12px;"
                    " font-family: Consolas, monospace;")
                # Status tag
                if b.after > b.cap:
                    status = "❌ Overflow"
                    status_clr = COLOR['danger']
                elif b.after == b.cap:
                    status = "✓ Full"
                    status_clr = COLOR['success']
                elif b.after == 0:
                    status = "Empty"
                    status_clr = COLOR['text_3']
                else:
                    pct = b.after / b.cap * 100
                    status = f"⚠ {pct:.0f}% filled"
                    status_clr = COLOR['warn']
                lbl_status = QLabel(status)
                lbl_status.setStyleSheet(
                    f"color: {status_clr}; font-size: 11px; font-weight: 700;")
                grid.addWidget(lbl_box,    i, 0)
                grid.addWidget(lbl_change, i, 1)
                grid.addWidget(lbl_status, i, 2)
                grid.setColumnStretch(1, 1)
            wrap = QWidget()
            wrap.setLayout(grid)
            self._preview_lay.addWidget(wrap)

        # Warnings
        if validation.warnings:
            self._preview_lay.addWidget(_spacer(4))
            for w in validation.warnings:
                wl = QLabel(f"⚠  {w}")
                wl.setStyleSheet(
                    f"color: #92400E; font-size: 11px;")
                wl.setWordWrap(True)
                self._preview_lay.addWidget(wl)

    # ── Action ───────────────────────────────────────────────

    def _on_confirm(self):
        if self._selected_box is None:
            return
        op = MoveReelOp(self._reel_id, self._selected_box)
        v = self._editor.validate(op)
        if not v.ok:
            QMessageBox.critical(self, "Cannot Apply",
                                 f"Validation failed:\n\n{v.reason}")
            return
        if v.warnings:
            joined = "\n• ".join(v.warnings)
            reply = QMessageBox.warning(
                self, "Confirm with warnings",
                f"This move will succeed but has warnings:\n\n• {joined}\n\n"
                f"Proceed anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        try:
            self._editor.apply(op)
        except PlanEditError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.accept()


# ════════════════════════════════════════════════════════════════════
#  CHANGE TARGET DIALOG
# ════════════════════════════════════════════════════════════════════

class ChangeTargetDialog(QDialog):
    """Dialog for changing the target qty of a pending reel."""

    def __init__(self, parent, editor: PlanEditor, reel_id: int):
        super().__init__(parent)
        self._editor = editor
        self._reel_id = reel_id
        self._reel = editor._find_reel(reel_id)
        if not self._reel:
            QMessageBox.critical(parent, "Error", f"Reel R{reel_id} not found")
            self.reject()
            return

        self.setWindowTitle(f"Change Target — R{reel_id}")
        self.setStyleSheet(_QSS)
        self.setModal(True)
        self.resize(480, 380)

        c = editor.constraints
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        root.addWidget(_title("Change Target", 16))
        sub = QLabel("Set the desired packing target for this reel.")
        sub.setStyleSheet(f"color: {COLOR['text_2']}; font-size: 12px;")
        root.addWidget(sub)

        # Source banner
        r = self._reel
        box_lbl = "📋 Remainder" if r["box"] == 0 else f"Box {r['box']}"
        src = QFrame()
        src.setObjectName("source-card")
        src_lay = QHBoxLayout(src)
        src_lay.setContentsMargins(16, 14, 16, 14)
        src_lay.setSpacing(14)
        pill = QLabel(f"R{r['reel']}")
        pill.setAlignment(Qt.AlignCenter)
        pill.setFixedSize(50, 50)
        pill.setStyleSheet(
            f"background: {COLOR['primary']}; color: white; "
            f"border-radius: 25px; font-size: 14px; font-weight: 700;"
            f" border: 3px solid white;")
        src_lay.addWidget(pill)
        info_lay = QVBoxLayout()
        info_lay.setSpacing(2)
        info_lay.addWidget(_eyebrow("REEL"))
        info_lay.addWidget(QLabel(
            f"<b style='font-size:14px'>{box_lbl}</b>"
            f"  ·  Lot <b>{r.get('lot', '—')}</b>"))
        info_lay.addWidget(QLabel(
            f"<span style='color:{COLOR['text_2']};font-size:12px'>"
            f"Current: <b>{r['target']:,}</b> pcs  ·  "
            f"Range: <b>{c['min_reel']:,}</b>–<b>{c['max_reel']:,}</b></span>"))
        src_lay.addLayout(info_lay, stretch=1)
        root.addWidget(src)

        # Spin box
        root.addWidget(_eyebrow("NEW TARGET"))
        self._spin = QSpinBox()
        self._spin.setRange(c["min_reel"], c["max_reel"])
        self._spin.setSingleStep(50)
        self._spin.setValue(self._reel["target"])
        self._spin.valueChanged.connect(self._on_change)
        root.addWidget(self._spin)

        # Preview card
        self._preview_card = QFrame()
        self._preview_card.setObjectName("preview-info")
        pcl = QVBoxLayout(self._preview_card)
        pcl.setContentsMargins(14, 12, 14, 12)
        self._preview_lbl = QLabel("")
        self._preview_lbl.setWordWrap(True)
        self._preview_lbl.setStyleSheet("font-size: 12px;")
        pcl.addWidget(self._preview_lbl)
        self._preview_card.setMinimumHeight(70)
        root.addWidget(self._preview_card)

        # Buttons
        root.addStretch()
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self._ok = QPushButton("Apply Change")
        self._ok.setObjectName("primary")
        self._ok.clicked.connect(self._on_ok)
        btn_row.addWidget(self._ok)
        root.addLayout(btn_row)

        self._on_change(self._spin.value())

    def _on_change(self, val):
        v = self._editor.validate(ChangeTargetOp(self._reel_id, val))
        if not v.ok:
            self._preview_card.setObjectName("preview-error")
            self._preview_lbl.setText(f"❌  {v.reason}")
            self._preview_lbl.setStyleSheet(
                f"color: #991B1B; font-weight: 600; font-size: 12px;")
            self._ok.setEnabled(False)
        else:
            delta = val - self._reel["target"]
            sign = "+" if delta > 0 else ""
            msg = f"<b>✓  Valid change ({sign}{delta:,} pcs)</b>"
            if v.warnings:
                msg += "<br>" + "<br>".join(
                    f"<span style='color:#92400E'>⚠  {w}</span>"
                    for w in v.warnings)
                self._preview_card.setObjectName("preview-warn")
            else:
                self._preview_card.setObjectName("preview-ok")
            self._preview_lbl.setTextFormat(Qt.RichText)
            self._preview_lbl.setText(msg)
            self._preview_lbl.setStyleSheet(
                f"color: {COLOR['text']}; font-size: 12px;")
            self._ok.setEnabled(True)
        # Re-apply QSS for objectName change
        self._preview_card.setStyleSheet("")
        self._preview_card.setStyle(self._preview_card.style())

    def _on_ok(self):
        try:
            self._editor.apply(ChangeTargetOp(self._reel_id, self._spin.value()))
        except PlanEditError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.accept()