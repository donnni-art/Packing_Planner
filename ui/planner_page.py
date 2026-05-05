"""
Planner Page — AutoPack VLO-127S
==================================
Page 1: Order setup, lot input, and plan calculation (batch & lot-by-lot).
"""

import os
from datetime import datetime
from collections import defaultdict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QSplitter, QFrame, QGroupBox, QLabel, QLineEdit, QSpinBox,
    QComboBox, QDateEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QAbstractSpinBox, QMessageBox, QFileDialog,
    QDialog,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QSize, QDate, QThread, pyqtSignal, QLocale

from ui.theme import THEME, S, F
from ui.widgets import SectionHeader, StatCard, Card, make_btn, make_label

from app.core.config_manager import ConfigManager
from app.core.calculation_engine import (
    calculate_pack_plan, calculate_pack_plan_v6,
    calculate_pack_plan_with_open_box_tracking,
    calculate_single_lot_plan, write_plan_csv,
)
from core.smart_replan import find_smart_split
from core.plan_editor import (
    PlanEditor, MoveReelOp, ChangeTargetOp, DeleteReelOp, PlanEditError,
)
from ui.move_reel_dialog import (
    MoveReelDialog, ChangeTargetDialog, EditReelMenu,
)


# ══════════════════════════════════════════════════════════════
#  PLAN WORKER  (background thread for batch calculation)
# ══════════════════════════════════════════════════════════════

class PlanWorker(QThread):
    finished = pyqtSignal(list, list, str, list)  # Added validation_errors

    def __init__(self, inv, mb, mr, lots, mn, rpb, mode):
        super().__init__()
        self._args = (inv, mb, mr, lots, mn, rpb, mode)

    def run(self):
        inv, mb, mr, lots, mn, rpb, mode = self._args

        def _score(p, s):
            if not p:
                return float('inf')
            packed = sum(r["target"] for r in p)
            return max(0, inv - packed) * 10 + sum(x["qty"] for x in s)

        validation_errors = []
        
        if mode == 1:
            # Use new open-box-tracking version for FIFO mode
            plan, scrap, validation_errors = calculate_pack_plan_with_open_box_tracking(
                inv, mb, mr, lots, mn, rpb)
            used = "FIFO (Open-Box Aware)"
        elif mode == 2:
            plan, scrap = calculate_pack_plan_v6(inv, mb, mr, lots, mn, rpb)
            used = "Optimize"
            # Validate v6 result too
            total_packed = sum(r["target"] for r in plan)
            if total_packed < inv:
                validation_errors.append(f"SHORTFALL: {inv - total_packed:,} pcs")
        else:
            # Try both modes
            p5, s5, err5 = calculate_pack_plan_with_open_box_tracking(inv, mb, mr, lots, mn, rpb)
            p6, s6 = calculate_pack_plan_v6(inv, mb, mr, lots, mn, rpb)
            
            # Validate p6 result
            err6 = []
            total_p6 = sum(r["target"] for r in p6) if p6 else 0
            if total_p6 < inv:
                err6.append(f"SHORTFALL: {inv - total_p6:,} pcs")
            
            if _score(p6, s6) < _score(p5, s5):
                plan, scrap, used, validation_errors = p6, s6, "Optimize", err6
            else:
                plan, scrap, used, validation_errors = p5, s5, "FIFO (Open-Box Aware)", err5

        self.finished.emit(plan or [], scrap or [], used, validation_errors or [])


# ══════════════════════════════════════════════════════════════
#  LOT ROW WIDGET
# ══════════════════════════════════════════════════════════════

class LotRow(QWidget):
    """Single lot input row: lot number + qty + remove button."""

    removed = pyqtSignal(object)

    def __init__(self, lot_no="", qty=3000, parent=None):
        super().__init__(parent)
        T = THEME
        row_h = S(48)  # Increased from 44 for better spacing
        control_h = S(40)  # Increased from 36

        lay = QHBoxLayout(self)
        lay.setContentsMargins(S(2), S(2), S(2), S(2))  # Added padding
        lay.setSpacing(S(8))  # Increased from 6

        # Lot number input
        self.lot_edit = QLineEdit(lot_no)
        self.lot_edit.setPlaceholderText("Lot No.")
        self.lot_edit.setFont(QFont("Consolas", F(13)))
        self.lot_edit.setFixedHeight(control_h)
        self.lot_edit.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {T['border']};
                border-radius: {S(6)}px;
                padding: {S(6)}px {S(10)}px;
                background: {T['bg_input']};
                color: {T['text_primary']};
            }}
            QLineEdit:focus {{
                border: 2px solid {T['accent']};
                background: #FFFFFF;
            }}
            QLineEdit::placeholder {{
                color: {T['text_muted']};
            }}
        """)
        lay.addWidget(self.lot_edit, 3)

        # Quantity spinner
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 9_999_999)
        self.qty_spin.setValue(qty)
        self.qty_spin.setSuffix(" pcs.")
        self.qty_spin.setLocale(QLocale(QLocale.C))
        self.qty_spin.setFont(QFont("Consolas", F(13)))
        self.qty_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.qty_spin.setFixedHeight(control_h)
        self.qty_spin.setStyleSheet(f"""
            QSpinBox {{
                border: 1px solid {T['border']};
                border-radius: {S(6)}px;
                padding: {S(6)}px {S(10)}px;
                background: {T['bg_input']};
                color: {T['text_primary']};
            }}
            QSpinBox:focus {{
                border: 2px solid {T['accent']};
                background: #FFFFFF;
            }}
        """)
        lay.addWidget(self.qty_spin, 3)

        # Remove button
        rem_btn = make_btn("✕", "danger")
        rem_btn.setFixedSize(QSize(control_h, control_h))
        rem_btn.setStyleSheet(
            rem_btn.styleSheet() +
            f"QPushButton{{ padding:0; min-height:0; min-width:0; font-size:{F(14)}px; border-radius:{S(6)}px; }}")
        rem_btn.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(rem_btn)
        self.setFixedHeight(row_h)

    def get_data(self):
        return {"lot_no": self.lot_edit.text().strip(), "qty": self.qty_spin.value()}


# ══════════════════════════════════════════════════════════════
#  PLANNER PAGE
# ══════════════════════════════════════════════════════════════

class PlannerPage(QWidget):
    """Page 1: Order entry, lot management, plan calculation."""

    plan_ready = pyqtSignal(list, dict)  # plan, order_info

    def __init__(self, config, app_state, logger, history, parent=None):
        super().__init__(parent)
        self._config  = config
        self._state   = app_state
        self._logger  = logger
        self._history = history
        self._lot_rows   = []
        self._plan       = []
        self._scrap_info = []
        self._used_mode  = ""
        self._plan_state = None
        self._mode_index = config.ui_mode or 0
        self._build()

    # ─── Build UI ─────────────────────────────────────────────

    def _build(self):
        T = THEME
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = SectionHeader("Packing Planner", "สร้างแผนการบรรจุ")
        run_btn = make_btn("▶  Calculate Plan", "primary")
        run_btn.clicked.connect(self._run_plan)
        self._run_btn = run_btn
        hdr.add_widget(run_btn)
        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(S(2))
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {T['border']}; }}")
        root.addWidget(splitter)

        # ── LEFT PANEL ──
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_w = QWidget()
        left_scroll.setWidget(left_w)
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(S(22), S(18), S(12), S(22))
        left_lay.setSpacing(S(16))

        # Order info
        order_grp = QGroupBox("Order Information")
        order_form = QGridLayout(order_grp)
        order_form.setSpacing(S(10))

        self.product_edit = QLineEdit(self._config.product_code)
        self.product_edit.setPlaceholderText("e.g. VLO-127S")

        self.shipment_date = QDateEdit(QDate.currentDate())
        self.shipment_date.setCalendarPopup(True)
        self.shipment_date.setDisplayFormat("dd/MM/yyyy")
        self.shipment_date.setLocale(QLocale(QLocale.C))

        self.dest_combo = QComboBox()
        self.dest_combo.addItems(self._config.destinations or ["IRELAND", "HONG KONG"])

        self.invoice_qty_spin = QSpinBox()
        self.invoice_qty_spin.setRange(1, 9_999_999)
        self.invoice_qty_spin.setValue(19200)
        self.invoice_qty_spin.setSuffix(" pcs.")
        self.invoice_qty_spin.setLocale(QLocale(QLocale.C))
        self.invoice_qty_spin.valueChanged.connect(self._update_avail)

        fields = [
            ("Product", self.product_edit),
            ("Shipment Date", self.shipment_date),
            ("Destination", self.dest_combo),
            ("Order Qty", self.invoice_qty_spin),
        ]
        for i, (lbl_txt, w) in enumerate(fields):
            row, col = divmod(i, 2)
            lbl = make_label(lbl_txt, size=11, color=T["text_muted"])
            lbl.setStyleSheet(
                f"color:{T['text_muted']};background:transparent;font-weight:700;")
            order_form.addWidget(lbl, row * 2, col)
            order_form.addWidget(w, row * 2 + 1, col)
        left_lay.addWidget(order_grp)

        # Constraints (read-only display)
        con_grp = QGroupBox("Packing Constraints")
        con_lay = QHBoxLayout(con_grp)
        self._c_max_box  = self._config.max_per_box
        self._c_max_reel = self._config.max_per_reel
        self._c_min_reel = self._config.min_per_reel
        self._c_reels_per_box = self._config.reels_per_box
        self._constraint_label = QLabel()
        self._constraint_label.setFont(QFont("Consolas", F(12)))
        self._constraint_label.setStyleSheet(
            f"color:{T['text_secondary']}; background:transparent;")
        self._constraint_label.setTextFormat(Qt.RichText)
        self._update_constraint_label()
        con_lay.addWidget(self._constraint_label)
        left_lay.addWidget(con_grp)

        # Lot-by-Lot progress (shown when saved state exists)
        self._progress_grp = QGroupBox("Lot-by-Lot Progress")
        prog_lay_inner = QHBoxLayout(self._progress_grp)
        self._progress_info = QLabel("")
        self._progress_info.setTextFormat(Qt.RichText)
        self._progress_info.setFont(QFont("Segoe UI", F(12)))
        self._progress_info.setStyleSheet(
            f"color:{T['text_primary']}; background:transparent;")
        prog_lay_inner.addWidget(self._progress_info)
        self._queue_info = QLabel("")
        self._queue_info.setTextFormat(Qt.RichText)
        self._queue_info.setFont(QFont("Segoe UI", F(11)))
        self._queue_info.setStyleSheet(
            f"color:{T['text_muted']}; background:transparent;")
        prog_lay_inner.addWidget(self._queue_info)
        self._progress_grp.setVisible(False)
        left_lay.addWidget(self._progress_grp)

        # Lot rows
        lot_grp = QGroupBox("Raw Material Lots")
        lot_lay = QVBoxLayout(lot_grp)
        lot_lay.setSpacing(S(8))  # Increased from 6
        lot_lay.setContentsMargins(0, 0, 0, 0)
        add_lot_btn = make_btn("＋  Add Lot", "flat")
        add_lot_btn.setFixedHeight(S(40))  # Better sizing
        add_lot_btn.setStyleSheet(
            add_lot_btn.styleSheet() + f"""
            QPushButton {{
                padding: {S(4)}px {S(12)}px;
                border-radius: {S(6)}px;
                border: 2px dashed {T['border']};
            }}
            """)
        add_lot_btn.clicked.connect(lambda: self._add_lot_row())
        lot_lay.addWidget(add_lot_btn)
        self._lot_container = QWidget()
        self._lot_vlay = QVBoxLayout(self._lot_container)
        self._lot_vlay.setContentsMargins(0, 0, 0, 0)
        self._lot_vlay.setSpacing(S(6))  # Increased from 4
        lot_lay.addWidget(self._lot_container)

        # Availability label
        self._avail_label = QLabel("")
        self._avail_label.setFont(QFont("Segoe UI", F(11), QFont.Bold))
        self._avail_label.setStyleSheet(
            f"background:{T['bg_tag_blue']};border-radius:{S(8)}px;"
            f"padding:{S(6)}px {S(12)}px;")
        self._avail_label.setTextFormat(Qt.RichText)
        self._avail_label.setWordWrap(False)
        self._avail_label.setFixedHeight(S(38))  # Increased from 34
        lot_lay.addWidget(self._avail_label)

        left_lay.addWidget(lot_grp, stretch=1)
        left_lay.addStretch()
        splitter.addWidget(left_scroll)

        # ── RIGHT PANEL ──
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_w = QWidget()
        right_scroll.setWidget(right_w)
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(S(12), S(18), S(22), S(22))
        right_lay.setSpacing(S(14))

        # Summary cards
        card_row = QHBoxLayout()
        card_row.setSpacing(S(12))
        self._box_card    = StatCard("Total Boxes",  "—", "", T["accent"],       icon="🗃")
        self._reel_card   = StatCard("Total Reels",  "—", "", T["accent2"],      icon="🎯")
        self._packed_card = StatCard("Total Pcs",    "—", "", T["accent_green"], icon="✅")
        self._diff_card   = StatCard("Short / Over", "—", "", T["accent_amber"], icon="⚖")
        for c in [self._box_card, self._reel_card, self._packed_card, self._diff_card]:
            card_row.addWidget(c)
        right_lay.addLayout(card_row)

        # Status label
        self._warn_label = QLabel("")
        self._warn_label.setWordWrap(True)
        self._warn_label.setFont(QFont("Segoe UI", F(12), QFont.Bold))
        self._warn_label.setStyleSheet(
            f"padding:{S(6)}px;border-radius:{S(6)}px;"
            f"background:{T['bg_tag_green']};color:{T['accent_green']};")
        right_lay.addWidget(self._warn_label)

        # Plan table
        plan_grp = QGroupBox("Plan Result")
        plan_grp_lay = QVBoxLayout(plan_grp)

        btn_row = QHBoxLayout()
        self._start_btn = make_btn("▶  Start Monitor", "success")
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start_monitor)
        self._export_btn = make_btn("Export CSV", "ghost")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_csv)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._export_btn)
        self._edit_btn = make_btn("✏  Edit Plan", "ghost")
        self._edit_btn.setEnabled(False)
        self._edit_btn.setCheckable(True)
        self._edit_btn.clicked.connect(self._toggle_edit_mode)
        btn_row.addWidget(self._edit_btn)
        btn_row.addStretch()
        plan_grp_lay.addLayout(btn_row)

        self._plan_table = QTableWidget(0, 6)
        self._plan_table.setHorizontalHeaderLabels(
            ["Box", "Reel", "Lot", "Target", "Box Total", "Note"])
        self._plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._plan_table.setAlternatingRowColors(True)
        self._plan_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._plan_table.verticalHeader().setVisible(False)
        self._plan_table.setMinimumHeight(S(320))
        # Edit mode: double-click any row to open the safe Edit Reel dialog
        self._plan_table.cellDoubleClicked.connect(self._on_plan_table_double_click)
        plan_grp_lay.addWidget(self._plan_table)
        right_lay.addWidget(plan_grp, stretch=1)

        splitter.addWidget(right_scroll)
        splitter.setSizes([S(380), S(520)])

    # ─── Load / restore ──────────────────────────────────────

    def load_state(self, saved_state):
        """Load saved lot-by-lot state into the planner page."""
        self._saved_state = saved_state
        if not saved_state:
            self._progress_grp.setVisible(False)
            return

        st = saved_state

        # Lock order fields
        self.dest_combo.setCurrentText(st.get("destination", "IRELAND"))
        self.dest_combo.setEnabled(False)
        if st.get("shipment_date"):
            self.shipment_date.setDate(
                QDate.fromString(st["shipment_date"], "yyyyMMdd"))
        self.shipment_date.setEnabled(False)
        self.product_edit.setText(st.get("product", self._config.product_code))
        self.product_edit.setReadOnly(True)
        self.invoice_qty_spin.setValue(st.get("order_qty", 19200))
        self.invoice_qty_spin.setReadOnly(True)

        # Load constraints from state
        self._c_max_box  = st.get("max_box", self._config.max_per_box)
        self._c_max_reel = st.get("max_reel", self._config.max_per_reel)
        self._c_min_reel = st.get("min_reel", self._config.min_per_reel)
        self._c_reels_per_box = st.get("reels_per_box", self._config.reels_per_box)
        self._update_constraint_label()

        # Show progress
        packed = st.get("packed", 0)
        order  = st.get("order_qty", 0)
        remain = order - packed
        pct = int(packed / order * 100) if order > 0 else 0
        carry  = st.get("carry_remainder", 0)
        carry_lot = st.get("carry_lot", "")
        carry_txt = (f" | Carry: <b>{carry:,}</b> from {carry_lot}"
                     if carry > 0 else "")

        self._progress_info.setText(
            f"Packed: <b style='color:{THEME['accent_green']}'>{packed:,}</b>"
            f" / {order:,} ({pct}%)"
            f" | Remain: <b style='color:{THEME['accent_amber']}'>{remain:,}</b>"
            f"{carry_txt}")
        self._update_queue_info(st)
        self._progress_grp.setVisible(True)

        # Show lot history as read-only rows
        lot_history = st.get("lot_history", [])
        for h in lot_history:
            lbl = QLabel(
                f"  ✅ <b>{h.get('lot','?')}</b> — "
                f"Packed {h.get('packed',0):,} | Rej {h.get('reject',0):,} | "
                f"Carry {h.get('remainder',0):,}")
            lbl.setTextFormat(Qt.RichText)
            lbl.setFont(QFont("Segoe UI", F(11)))
            lbl.setStyleSheet(
                f"background:{THEME['bg_tag_green']};border-radius:{S(4)}px;"
                f"padding:{S(4)}px;")
            lbl.setFixedHeight(S(30))
            self._lot_vlay.addWidget(lbl)

        pending_lots = st.get("pending_lots", [])
        if pending_lots:
            for pending in pending_lots:
                self._add_lot_row(pending.get("lot_no", ""), pending.get("qty", 3100))
        else:
            # Add empty lot row for next lot
            self._add_lot_row("", 3100)

    def load_defaults(self):
        """Load default lots for batch mode."""
        self._saved_state = None
        for ln, q in [("LotA", 8000), ("LotB", 7000), ("LotC", 6400)]:
            self._add_lot_row(ln, q)

    # ─── Lot row management ──────────────────────────────────

    def _add_lot_row(self, lot_no="", qty=3000):
        row = LotRow(lot_no, qty, self)
        row.removed.connect(self._remove_lot_row)
        row.qty_spin.valueChanged.connect(self._update_avail)
        self._lot_rows.append(row)
        self._lot_vlay.addWidget(row)
        self._update_avail()

    def _remove_lot_row(self, row):
        if len(self._lot_rows) <= 1:
            QMessageBox.warning(self, "Warning", "At least 1 Lot is required")
            return
        if row in self._lot_rows:
            self._lot_rows.remove(row)
            self._lot_vlay.removeWidget(row)
            row.deleteLater()
            self._update_avail()

    def _update_avail(self):
        total = sum(r.qty_spin.value() for r in self._lot_rows)
        T = THEME
        # For continuing orders, compare against remaining qty, not full order
        st = getattr(self, '_saved_state', None)
        if st:
            remaining = st.get("order_qty", 0) - st.get("packed", 0)
        else:
            remaining = self.invoice_qty_spin.value()
        if total >= remaining:
            self._avail_label.setText(
                f"Total Material: <b>{total:,}</b> pcs. ✅ Sufficient")
            self._avail_label.setStyleSheet(
                f"background:{T['bg_tag_green']};border-radius:{S(8)}px;"
                f"padding:{S(6)}px {S(12)}px;color:{T['accent_green']};")
        else:
            self._avail_label.setText(
                f"Total Material: <b>{total:,}</b> pcs. (Short {remaining-total:,})")
            self._avail_label.setStyleSheet(
                f"background:{T['bg_tag_amber']};border-radius:{S(8)}px;"
                f"padding:{S(6)}px {S(12)}px;color:{T['accent_amber']};")

    def _update_constraint_label(self):
        self._constraint_label.setText(
            f"Box: <b>{self._c_max_box:,}</b> | "
            f"Reel: <b>{self._c_min_reel:,}</b>–<b>{self._c_max_reel:,}</b> | "
            f"<b>{self._c_reels_per_box}</b> Reel/Box")

    def _update_queue_info(self, state):
        pending_lots = state.get("pending_lots", []) if state else []
        current_lot = state.get("current_lot", "") if state else ""

        if current_lot:
            if pending_lots:
                self._queue_info.setText(
                    f"Current Lot: <b>{current_lot}</b> | "
                    f"Queued Next: <b>{pending_lots[0].get('lot_no', '?')}</b> | "
                    f"Queue Remaining: <b>{len(pending_lots)}</b> lot(s)")
            else:
                self._queue_info.setText(
                    f"Current Lot: <b>{current_lot}</b> | "
                    f"Queue Remaining: <b>0</b> lot(s)")
        elif pending_lots:
            self._queue_info.setText(
                f"Next Lot: <b>{pending_lots[0].get('lot_no', '?')}</b> | "
                f"Queue Remaining: <b>{len(pending_lots)}</b> lot(s)")
        else:
            self._queue_info.setText("")

    # [FIX-14] Helper: highlight ปุ่ม Start Monitor ให้เด่นเมื่อ plan พร้อมแล้ว
    # ใช้ร่วมกันระหว่าง lot-by-lot mode (_run_plan) และ batch mode (_on_plan_ready)
    # เพื่อให้ user รู้ชัดเจนว่าต้องกดปุ่มไหนต่อ (แก้ UX loop ที่ user กด Calculate ซ้ำ)
    def _highlight_start_button(self):
        T = THEME
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T['accent_green']};
                color: #fff;
                border: 2px solid {T['accent_green']};
                border-radius: {S(6)}px;
                font-size: {F(14)}px;
                font-weight: bold;
                padding: {S(6)}px {S(16)}px;
            }}
            QPushButton:hover {{
                background: #15803D;
            }}
        """)

    # ─── Plan calculation ────────────────────────────────────

    def _run_plan(self):
        # [FIX-BUG-E] Debounce: กัน plan ซ้ำภายใน 2 วินาที (race condition / double-click)
        # จาก log จริงเคยเจอ "Lot-by-Lot plan" fire สองครั้งห่างกัน 21 วินาที
        # (10:35:58 และ 10:36:19) ซึ่งเกิดจาก signal fire ซ้ำ
        import time
        _now = time.monotonic()
        _last = getattr(self, "_last_plan_run_ts", 0.0)
        if _now - _last < 2.0:
            self._logger.warning(
                f"[debounce] _run_plan ถูกเรียกซ้ำภายใน "
                f"{_now - _last:.2f}s → ignored")
            return
        self._last_plan_run_ts = _now

        lots = [r.get_data() for r in self._lot_rows
                if r.get_data()["lot_no"] and r.get_data()["qty"] > 0]
        if not lots:
            QMessageBox.warning(self, "Warning",
                                "กรุณาเพิ่ม Lot อย่างน้อย 1 รายการ")
            return

        # [FIX-13] Guard: เตือนหาก plan เดิมยังไม่ถูก commit (ยังไม่กด Start Monitor)
        # ป้องกัน user กด Calculate ซ้ำ ๆ จนหลง loop (bug ที่เห็นใน log 14:27:33-14:27:56)
        if getattr(self, '_plan', None):
            _existing_count = len(self._plan)
            _reply = QMessageBox.question(
                self, "Plan ยังไม่ได้ Start Monitor",
                f"Plan ปัจจุบัน ({_existing_count} reels) ยังไม่ถูกส่งไป Monitor\n\n"
                f"• Yes → คำนวณ Plan ใหม่ (Plan เดิมจะถูกเขียนทับ)\n"
                f"• No → ยกเลิก แล้วกด Start Monitor เพื่อใช้ Plan เดิม",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)
            if _reply == QMessageBox.No:
                return

        inv = self.invoice_qty_spin.value()
        mb  = self._c_max_box
        mr  = self._c_max_reel
        mn  = self._c_min_reel
        rpb = self._c_reels_per_box
        self._mode_index = self._config.ui_mode

        st = getattr(self, '_saved_state', None)
        forced_lot_by_lot = (self._mode_index == 3)

        # ── Lot-by-Lot mode ──
        first_lot_lbl = (not st and len(lots) == 1 and lots[0]["qty"] < inv)
        if st or forced_lot_by_lot or first_lot_lbl:
            pending_lots = lots[1:] if len(lots) > 1 else []
            lot = lots[0]
            if not st:
                st = {
                    "order_qty": inv, "packed": 0, "next_box": 1,
                    "next_reel": 1, "open_box_slots": 0,
                    "carry_remainder": 0, "carry_lot": "",
                    "current_lot": lot["lot_no"],
                    "pending_lots": pending_lots,
                }
                self._saved_state = st
            else:
                st["current_lot"] = lot["lot_no"]
                st["pending_lots"] = pending_lots

            self._update_queue_info(st)

            remaining = st.get("order_qty", inv) - st.get("packed", 0)
            carry_rem = st.get("carry_remainder", 0)
            carry_lot = st.get("carry_lot", "")
            open_boxes = st.get("open_boxes", [])

            plan, plan_state = calculate_single_lot_plan(
                lot["lot_no"], lot["qty"], remaining,
                mb, mr, mn, rpb,
                start_box=st.get("next_box", 1),
                start_reel=st.get("next_reel", 1),
                open_box_slots=st.get("open_box_slots", 0),
                carry_remainder=carry_rem,
                carry_lot=carry_lot,
                resume_reel=st.get("resume_reel"),
                open_boxes=open_boxes,
                invoice_qty=inv)  # Pass invoice_qty for blueprint

            # ══════════════════════════════════════════════════════════════
            # [DEFER LAST REEL DIALOG]
            # ตรวจสอบ: เป็น Final Lot + มี remainder < min_per_reel
            # ถ้าใช่ → ถามผู้ใช้ว่าต้องการ defer reel สุดท้ายหรือไม่
            # ══════════════════════════════════════════════════════════════
            _rem_total   = plan_state.get("remainder_total", 0)
            _is_final    = (lot["qty"] + carry_rem >= remaining)
            _has_sub_min = (mn > 0 and 0 < _rem_total < mn)

            # ตรวจว่ามี reel จริง (box != 0) ที่สามารถดึงออกได้
            _has_packable_reel = any(
                r.get("note") not in ("Wait next lot", "Carry")
                and r.get("box", 0) != 0
                and r.get("target", 0) > 0
                for r in plan
            )

            if plan and _is_final and _has_sub_min and _has_packable_reel:
                # หา reel สุดท้ายที่จะถูกดึงออก (เพื่อแสดงใน Dialog)
                _last_reel_info = None
                for _ri in range(len(plan) - 1, -1, -1):
                    _r = plan[_ri]
                    if (_r.get("note") not in ("Wait next lot", "Carry")
                            and _r.get("box", 0) != 0
                            and _r.get("target", 0) > 0):
                        _last_reel_info = _r
                        break

                # คำนวณค่าเฉลี่ยต่อ reel ในกล่องสุดท้าย
                _last_box_no  = _last_reel_info["box"] if _last_reel_info else "?"
                _last_box_reels = [
                    r for r in plan
                    if r.get("box") == _last_box_no
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and r.get("target", 0) > 0
                ] if _last_reel_info else []
                _last_box_total = sum(r["target"] for r in _last_box_reels)
                _avg_per_reel   = (
                    _last_box_total // len(_last_box_reels)
                    if _last_box_reels else 0
                )

                _msg = QMessageBox(self)
                _msg.setWindowTitle("แจ้งเตือน: เศษวัสดุน้อยกว่า Min Reel")
                _msg.setIcon(QMessageBox.Question)
                _msg.setText(
                    f"<b>Final Lot</b> มีเศษวัสดุ <b>{_rem_total:,} pcs</b> "
                    f"ซึ่งน้อยกว่า Min/Reel ({mn:,} pcs)<br><br>"
                    f"<b>ข้อมูลกล่องสุดท้าย (Box {_last_box_no}):</b><br>"
                    f"  • Reel ล่าสุด: "
                    f"{_last_reel_info['target']:,} pcs (Reel {_last_reel_info['reel']})<br>"
                    f"  • เฉลี่ย/Reel ในกล่องนี้: {_avg_per_reel:,} pcs<br><br>"
                    f"ต้องการจัดการอย่างไร?"
                ) if _last_reel_info else _msg.setText(
                    f"เศษวัสดุ {_rem_total:,} pcs น้อยกว่า Min/Reel ({mn:,} pcs)<br>"
                    f"ต้องการจัดการอย่างไร?"
                )
                _msg.setTextFormat(Qt.RichText)

                _btn_defer  = _msg.addButton(
                    "เฉลี่ยให้ remainder (รอ Lot ถัดไป)", QMessageBox.AcceptRole)
                _btn_normal = _msg.addButton(
                    "ใช้ Plan ปกติ (ยอมรับเศษ)", QMessageBox.RejectRole)
                _msg.setDefaultButton(_btn_normal)
                _msg.exec_()

                if _msg.clickedButton() == _btn_defer:
                    # เรียก calculate_single_lot_plan ใหม่พร้อม defer_last_reel=True
                    plan, plan_state = calculate_single_lot_plan(
                        lot["lot_no"], lot["qty"], remaining,
                        mb, mr, mn, rpb,
                        start_box=st.get("next_box", 1),
                        start_reel=st.get("next_reel", 1),
                        open_box_slots=st.get("open_box_slots", 0),
                        carry_remainder=carry_rem,
                        carry_lot=carry_lot,
                        resume_reel=st.get("resume_reel"),
                        open_boxes=open_boxes,
                        invoice_qty=inv,
                        defer_last_reel=True)
                    self._logger.info(
                        f"[DeferLastReel] User chose defer — remainder {_rem_total:,} pcs "
                        f"will carry forward. New remainder_total="
                        f"{plan_state.get('remainder_total', 0):,}")
            # ── end DEFER LAST REEL DIALOG ──

            self._used_mode  = "Lot-by-Lot"
            self._plan_state = plan_state
            self._scrap_info = []

            if not plan:
                QMessageBox.critical(self, "Error", "Unable to calculate plan")
                return

            # ── Box overflow check ───────────────────────────
            expected_boxes = -(-inv // mb)  # ceil
            # Collect all box IDs (history + current plan)
            hist_box_ids = set()
            for _h in st.get("lot_history", []):
                for _rd in _h.get("reels", []):
                    if not _rd.get("note", "").startswith("Pulled"):
                        hist_box_ids.add(_rd.get("box", 0))
            plan_box_ids = {r["box"] for r in plan
                           if r.get("note") != "Wait next lot"}
            all_box_ids = hist_box_ids | plan_box_ids
            open_box_ids = {ob["box"] for ob in (open_boxes or [])}

            if len(all_box_ids) > expected_boxes:
                # Find new underfilled boxes
                for _bid in sorted(plan_box_ids - open_box_ids):
                    _bt = sum(r["target"] for r in plan
                             if r["box"] == _bid
                             and r.get("note") != "Wait next lot")
                    if 0 < _bt < mn:
                        reply = QMessageBox.question(
                            self, "Box เกินจำนวน",
                            f"Order {inv:,} ควรได้ {expected_boxes} boxes\n"
                            f"แต่ Plan สร้าง {len(all_box_ids)} boxes\n\n"
                            f"Box {_bid} มี {_bt:,} pcs "
                            f"(น้อยกว่า Min Reel {mn:,})\n\n"
                            f"• Yes → เปิด Box ใหม่ "
                            f"({_bt:,} pcs จะเป็น scrap)\n"
                            f"• No → รอ Lot ถัดไปเพื่อ pack ให้เต็ม",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No)
                        if reply == QMessageBox.No:
                            # Remove extra box, keep material as carry
                            carry_back = sum(
                                r["target"] for r in plan
                                if r["box"] == _bid)
                            plan = [r for r in plan
                                    if r["box"] != _bid]
                            plan_state["lot_remainder"] = \
                                plan_state.get("lot_remainder", 0) \
                                + carry_back
                            plan_state["packed_this_lot"] = \
                                plan_state.get("packed_this_lot", 0) \
                                - carry_back
                            plan_state["next_box"] = _bid
                            plan_state["open_boxes"] = [
                                ob for ob in
                                plan_state.get("open_boxes", [])
                                if ob["box"] != _bid]
                            self._logger.info(
                                f"User deferred Box {_bid} "
                                f"({carry_back:,} pcs) to next lot")
                        break  # Check one box at a time

            # ── Scrap checking & distribution ────────────────
            if plan:
                rem_total = sum(rr["target"] for rr in plan_state.get("remainder_reels", []))
                # Use remainder_total exported by the calculation engine to accurately determine left-over
                # material without accidentally counting carry_remainder_out as scrap.
                scrap_qty = plan_state.get("remainder_total", 0) - rem_total
                
                if 0 < scrap_qty < mn:
                    last_idx = -1
                    for i in range(len(plan)-1, -1, -1):
                        if plan[i].get("note") not in ("Wait next lot", "Carry"):
                            last_idx = i
                            break
                    
                    if last_idx >= 0:
                        lr = plan[last_idx]
                        msg = QMessageBox(self)
                        msg.setWindowTitle("แจ้งเตือน Scrap ปริมาณสูง")
                        msg.setIcon(QMessageBox.Warning)
                        msg.setText(f"พบเศษวัตถุดิบ {scrap_qty:,} pcs\nเนื่องจากน้อยกว่า Min Reel ({mn:,}) จึงต้องถูกปัดเป็น Scrap (ทิ้ง)\n\n"
                                    f"คุณต้องการดึง Reel ล่าสุด (Box {lr['box']} Reel {lr['reel']}: {lr['target']:,} pcs) ออกไปถัว\n"
                                    f"เพื่อให้กลายเป็น Wait Lot และรอ Lot ถัดไปเติมเต็ม (ลด Scrap) หรือไม่?")
                        btn_distribute = msg.addButton("ถัว Reel ล่าสุด (รอ Lot ถัดไป)", QMessageBox.AcceptRole)
                        btn_pack_on = msg.addButton("Pack ต่อ (ยอมรับ Scrap)", QMessageBox.RejectRole)
                        msg.exec_()
                        
                        if msg.clickedButton() == btn_distribute:
                            pulled_target = lr["target"]
                            lr["target"] = 0
                            lr["note"] = "Wait next lot"

                            new_rem_total = scrap_qty + pulled_target

                            pulled_box_no = lr["box"]
                            mb = self._c_max_box
                            mr = self._c_max_reel
                            mn = self._c_min_reel

                            # Search for an open box beyond the pulled box
                            candidate_boxes = [
                                ob for ob in sorted(
                                    plan_state.get("open_boxes", []),
                                    key=lambda x: x["box"])
                                if ob["box"] > pulled_box_no and ob.get("slots", 0) > 0
                            ]

                            place_in_box = 0
                            next_open = None
                            _take_reels = 0
                            if candidate_boxes and mn > 0 and new_rem_total >= mn:
                                _tbox, place_in_box, _take_reels, _rem_after_sp, _ = \
                                    find_smart_split(new_rem_total, candidate_boxes, mn, mr, mb)
                                if _tbox:
                                    next_open = next(
                                        (ob for ob in candidate_boxes if ob["box"] == _tbox),
                                        None)
                                    if next_open:
                                        new_rem_total = _rem_after_sp

                            # Insert reel(s) into the target open box
                            if place_in_box > 0 and next_open:
                                next_r_no = plan_state["next_reel"]
                                from app.core.calculation_engine import _distribute_reels as _dr
                                _split = _dr(place_in_box, _take_reels, mn, mr)
                                insert_pos = len(plan)
                                for idx2, r2 in enumerate(plan):
                                    if (r2["box"] == next_open["box"]
                                            and r2.get("note") == "Wait next lot"):
                                        insert_pos = idx2
                                        break
                                for _si, _sq in enumerate(_split):
                                    plan.insert(insert_pos + _si, {
                                        "box":       next_open["box"],
                                        "reel":      next_r_no + _si,
                                        "lot":       lot["lot_no"],
                                        "target":    _sq,
                                        "box_total": None,
                                        "note":      "",
                                    })
                                plan_state["next_reel"] = next_r_no + len(_split)

                                next_open["current_total"] += place_in_box
                                next_open["slots"] -= _take_reels
                                new_bt = next_open["current_total"]
                                for r2 in plan:
                                    if r2["box"] == next_open["box"]:
                                        r2["box_total"] = new_bt

                                self._logger.info(
                                    f"Smart Re-plan: Placed {place_in_box:,} pcs "
                                    f"into Box {next_open['box']} "
                                    f"(total now {new_bt:,}/{mb:,}). "
                                    f"Remainder reduced to {new_rem_total:,}")

                            # Remainder → Box 0
                            new_rem_list = []
                            next_r_no = plan_state["next_reel"]
                            if new_rem_total >= mn:
                                num_rem = max(1, -(-new_rem_total // mr))
                                while num_rem > 1 and (new_rem_total // num_rem) < mn:
                                    num_rem -= 1
                                base    = new_rem_total // num_rem
                                rem_rem = new_rem_total % num_rem
                                rem_reels_sizes = [base + (1 if i < rem_rem else 0)
                                                   for i in range(num_rem)]
                                for rq in rem_reels_sizes:
                                    new_rem_list.append({
                                        "box": 0, "reel": next_r_no,
                                        "lot": lot["lot_no"], "target": rq,
                                        "box_total": None,
                                        "note": "Remainder reel (next order)",
                                    })
                                    next_r_no += 1
                            elif new_rem_total > 0:
                                self._logger.info(
                                    f"Smart Re-plan: Residual {new_rem_total:,} pcs "
                                    f"< min {mn:,} → treated as scrap")

                            if new_rem_list:
                                plan_state.setdefault("remainder_reels", []).extend(new_rem_list)
                            plan_state["next_reel"] = next_r_no

                            plan_state["packed_this_lot"] = max(
                                0, plan_state.get("packed_this_lot", 0) - pulled_target)
                            if "wait_slots" in plan_state:
                                plan_state["wait_slots"] += 1

                            # อัปเดต open_boxes ของ pulled box
                            box_no   = pulled_box_no
                            ob_exists = False
                            for ob in plan_state.get("open_boxes", []):
                                if ob["box"] == box_no:
                                    ob["slots"] += 1
                                    ob_exists = True
                                    break
                            if not ob_exists:
                                cur_total = sum(
                                    r["target"] for r in plan
                                    if r["box"] == box_no
                                    and r.get("note") not in ("Wait next lot", "Carry")
                                    and r["target"] > 0)
                                for h_lot in st.get("lot_history", []):
                                    for r in h_lot.get("reels", []):
                                        if (r["box"] == box_no
                                                and not r.get("note", "").startswith("Pulled")):
                                            cur_total += r.get("actual", 0)
                                plan_state.setdefault("open_boxes", []).append({
                                    "box": box_no, "slots": 1,
                                    "current_total": cur_total
                                })

                            self._logger.info(
                                f"User distributed scrap ({scrap_qty}). "
                                f"Pulled target={pulled_target}, "
                                f"placed_in_box={place_in_box:,}, "
                                f"remainder_to_box0={new_rem_total:,}.")

            self._plan = plan
            self._plan_state = plan_state
            self._plan_state["current_lot"] = lot["lot_no"]
            self._plan_state["pending_lots"] = pending_lots
            self._populate_table(plan)
            self._update_summary(plan, [])
            self._start_btn.setEnabled(True)
            self._export_btn.setEnabled(True)
            self._edit_btn.setEnabled(True)
            self._edit_btn.setChecked(False)
            # [FIX-14] Highlight ปุ่ม Start Monitor (เด่นเป็นสีเขียว)
            self._highlight_start_button()
            # [FIX-12] Log ขนาดรวมให้ตรงกับที่จะ emit ใน _start_monitor
            # (รวม remainder_reels ด้วย เพื่อป้องกันสับสนกับ "Plan ready: N reels" ใน main.py)
            _rem_count = len(plan_state.get("remainder_reels", []))
            if _rem_count > 0:
                self._logger.plan(
                    f"Lot-by-Lot plan: {len(plan)} reels "
                    f"(+{_rem_count} remainder → {len(plan) + _rem_count} total)")
            else:
                self._logger.plan(f"Lot-by-Lot plan: {len(plan)} reels")
            return

        # ── Batch mode ──
        mode = self._mode_index
        self._run_btn.setEnabled(False)
        self._run_btn.setText("⏳ Calculating...")

        self._worker = PlanWorker(inv, mb, mr, lots, mn, rpb, mode)
        self._worker.finished.connect(self._on_plan_ready)
        self._worker.start()

    def _on_plan_ready(self, plan, scrap_info, used_mode, validation_errors=None):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("▶  Calculate Plan")
        self._used_mode  = used_mode
        self._plan_state = None

        if not plan:
            QMessageBox.critical(self, "Error", "Unable to calculate plan")
            return

        # Show validation errors if any
        if validation_errors:
            error_msg = "⚠️  Validation Issues Found:\n\n" + "\n".join(validation_errors)
            QMessageBox.warning(self, "Plan Validation", error_msg)
            self._logger.warn(f"Plan has validation issues: {validation_errors}")

        self._plan = plan
        self._scrap_info = scrap_info
        self._populate_table(plan, scrap_info)
        self._update_summary(plan, scrap_info)
        self._start_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._edit_btn.setEnabled(True)
        self._edit_btn.setChecked(False)
        # [FIX-14] Highlight ปุ่ม Start Monitor (เด่นเป็นสีเขียว)
        self._highlight_start_button()
        self._logger.plan(f"Batch plan ({used_mode}): {len(plan)} reels")

        # Save to history
        order_info = self._get_order_info()
        self._history.save_order({**order_info, "plan": plan})

    # ─── Table + summary ─────────────────────────────────────

    def _populate_table(self, plan, scrap_info=None):
        T = THEME
        self._plan_table.setRowCount(0)
        self._plan_row_map = {}  # table_row -> plan_index

        # ── History rows (from previous lots) ──
        st = getattr(self, '_saved_state', None) or {}
        lot_history = st.get("lot_history", [])
        history_reels = []
        for h in lot_history:
            for rd in h.get("reels", []):
                if rd.get("note", "").startswith("Pulled"):
                    continue
                history_reels.append(rd)

        for rd in history_reels:
            r = self._plan_table.rowCount()
            self._plan_table.insertRow(r)
            box_val = rd.get('box', '')
            box_text = "📋 Remainder" if box_val == 0 else f"Box {box_val}"
            reject = rd.get("reject", 0)
            note_text = f"✅ Done | Rej {reject:,}" if reject else "✅ Done"
            vals = [
                box_text,
                f"Reel {rd.get('reel','')}",
                rd.get("lot", ""),
                f"{rd.get('actual', rd.get('target', 0)):,}",
                "",
                note_text,
            ]
            for j, v in enumerate(vals):
                itm = QTableWidgetItem(v)
                itm.setTextAlignment(Qt.AlignCenter)
                itm.setForeground(QColor(T["text_muted"]))
                itm.setBackground(QColor("#FAF5FF") if box_val == 0 else QColor("#F1F5F9"))
                self._plan_table.setItem(r, j, itm)

        # ── Lot separator ──
        if history_reels and plan:
            r = self._plan_table.rowCount()
            self._plan_table.insertRow(r)
            sep_itm = QTableWidgetItem("── Current Plan ──")
            sep_itm.setTextAlignment(Qt.AlignCenter)
            sep_itm.setForeground(QColor(T["accent"]))
            fnt = QFont("Segoe UI", F(11), QFont.Bold)
            sep_itm.setFont(fnt)
            self._plan_table.setItem(r, 0, sep_itm)
            self._plan_table.setSpan(r, 0, 1, 6)

        # ── Current plan rows ──
        box_totals = defaultdict(int)
        for rw in plan:
            if rw.get("note") != "Wait next lot":
                box_totals[rw["box"]] += rw["target"]

        # Include history totals in box_totals
        for rd in history_reels:
            box_id = rd.get("box", 0)
            box_totals[box_id] += rd.get("actual", rd.get("target", 0))

        max_box_cfg = self._c_max_box

        prev_box = None
        for pi, row in enumerate(plan):
            # Box separator row
            if prev_box is not None and row["box"] != prev_box:
                sep_r = self._plan_table.rowCount()
                self._plan_table.insertRow(sep_r)
                self._plan_table.setRowHeight(sep_r, S(6))
                for _j in range(6):
                    _sep = QTableWidgetItem("")
                    _sep.setBackground(QColor(T["divider"]))
                    _sep.setFlags(Qt.NoItemFlags)
                    self._plan_table.setItem(sep_r, _j, _sep)
            prev_box = row["box"]

            r = self._plan_table.rowCount()
            self._plan_table.insertRow(r)
            self._plan_row_map[r] = pi  # map table row to plan index
            is_wait = row.get("note") == "Wait next lot"
            bt = box_totals.get(row["box"], 0)
            bt_display = f"{bt:,} / {max_box_cfg:,}"

            vals = [
                f"Box {row['box']}" if row.get('box', 0) != 0 else "—",
                f"Reel {row['reel']}" if row.get('reel', 0) != 0 else "—",
                row["lot"] if not is_wait else "—",
                f"{row['target']:,}" if not is_wait else "—",
                bt_display,
                row.get("note", "") or "",
            ]
            for j, v in enumerate(vals):
                itm = QTableWidgetItem(v)
                itm.setTextAlignment(Qt.AlignCenter)
                if is_wait:
                    itm.setForeground(QColor(T["accent_amber"]))
                elif j == 3:
                    itm.setForeground(QColor(T["accent_green"]))
                elif row.get("note") == "Carry" and j == 5:
                    itm.setForeground(QColor("#9333EA"))
                self._plan_table.setItem(r, j, itm)

        if scrap_info:
            for sc in scrap_info:
                r = self._plan_table.rowCount()
                self._plan_table.insertRow(r)
                vals = ["✕ SCRAP", "—", sc["lot"], f"{sc['qty']:,}", "—",
                        sc.get("reason", "")]
                for j, v in enumerate(vals):
                    itm = QTableWidgetItem(v)
                    itm.setTextAlignment(Qt.AlignCenter)
                    itm.setForeground(QColor(T["accent_red"]))
                    self._plan_table.setItem(r, j, itm)

        # ── Remainder reels (standalone, not in any box) ──
        ps = getattr(self, '_plan_state', None) or {}
        rem_reels = ps.get("remainder_reels", [])
        if rem_reels:
            # Separator
            sep_r = self._plan_table.rowCount()
            self._plan_table.insertRow(sep_r)
            sep_itm = QTableWidgetItem("── Remainder Reels (Next Plan) ──")
            sep_itm.setTextAlignment(Qt.AlignCenter)
            sep_itm.setForeground(QColor("#9333EA"))
            fnt = QFont("Segoe UI", F(11), QFont.Bold)
            sep_itm.setFont(fnt)
            self._plan_table.setItem(sep_r, 0, sep_itm)
            self._plan_table.setSpan(sep_r, 0, 1, 6)
            for rr in rem_reels:
                r = self._plan_table.rowCount()
                self._plan_table.insertRow(r)
                vals = [
                    "—",
                    f"Reel {rr['reel']}",
                    rr.get("lot", ""),
                    f"{rr['target']:,}",
                    "—",
                    "Remainder (Next Plan)",
                ]
                for j, v in enumerate(vals):
                    itm = QTableWidgetItem(v)
                    itm.setTextAlignment(Qt.AlignCenter)
                    itm.setForeground(QColor("#9333EA"))
                    self._plan_table.setItem(r, j, itm)

    def _update_summary(self, plan, scrap_info=None):
        T = THEME
        st = getattr(self, '_saved_state', None) or {}
        prev_packed = st.get("packed", 0)

        current_boxes = {r["box"] for r in plan if r["box"] != 0}
        # Also count history boxes (exclude box=0 = remainder reels)
        lot_history = st.get("lot_history", [])
        hist_boxes = set()
        for h in lot_history:
            for rd in h.get("reels", []):
                if not rd.get("note", "").startswith("Pulled"):
                    b = rd.get("box", 0)
                    if b != 0:
                        hist_boxes.add(b)
        all_boxes = current_boxes | hist_boxes

        reels = len(plan)
        current_packed = sum(r["target"] for r in plan)
        total_packed = prev_packed + current_packed
        invoice = self.invoice_qty_spin.value()
        scrap_total = sum(s["qty"] for s in (scrap_info or []))
        diff = invoice - total_packed

        # Count history reels (non-pulled)
        hist_reel_count = sum(
            1 for h in lot_history
            for rd in h.get("reels", [])
            if not rd.get("note", "").startswith("Pulled"))
        packable_reels = sum(1 for r in plan if r.get("note") != "Wait next lot")
        # Count remainder reels (standalone, not in any box)
        ps = getattr(self, '_plan_state', None) or {}
        remainder_reel_count = len(ps.get("remainder_reels", []))
        total_reels = hist_reel_count + packable_reels + remainder_reel_count

        self._box_card.set_value(str(len(all_boxes)))
        self._reel_card.set_value(str(total_reels))
        self._packed_card.set_value(f"{total_packed:,}")
        
        # Format diff clearly: show as "Remainder (Next Plan)" or "Short"
        if diff > 0:
            diff_s = f"Short: {diff:,} pcs"
        elif diff < 0:
            remainder = abs(diff)
            diff_s = f"Remainder (Next Plan): {remainder:,} pcs"
        else:
            diff_s = "Exact"
        
        self._diff_card.set_value(diff_s)

        scrap_msg = f" | Scrap: {scrap_total:,}" if scrap_total > 0 else ""
        mode_tag  = f" | {self._used_mode}" if self._used_mode else ""
        lot_tag = f" | Lot-by-Lot" if st else ""

        if diff > 0:
            self._warn_label.setText(
                f"⚠ Insufficient: Packed {total_packed:,} pcs (Short {diff:,})"
                f"{scrap_msg}{mode_tag}{lot_tag}")
            self._warn_label.setStyleSheet(
                f"padding:{S(6)}px;border-radius:{S(6)}px;"
                f"background:{T['bg_tag_amber']};color:{T['accent_amber']};")
        elif diff < 0:
            # Excess material = remainder for next plan
            remainder = abs(diff)
            self._warn_label.setText(
                f"✅ Complete + Remainder: {total_packed:,} pcs in {len(all_boxes)} Boxes, "
                f"{reels} Reels | Remainder (Next Plan): {remainder:,} pcs{scrap_msg}{mode_tag}{lot_tag}")
            self._warn_label.setStyleSheet(
                f"padding:{S(6)}px;border-radius:{S(6)}px;"
                f"background:{T['bg_tag_blue']};color:{T['accent']};")
        else:
            # Exact match
            self._warn_label.setText(
                f"✅ Complete: {total_packed:,} pcs in {len(all_boxes)} Boxes, "
                f"{reels} Reels{scrap_msg}{mode_tag}{lot_tag}")
            self._warn_label.setStyleSheet(
                f"padding:{S(6)}px;border-radius:{S(6)}px;"
                f"background:{T['bg_tag_green']};color:{T['accent_green']};")
        self._warn_label.setVisible(True)

    # ─── Edit Plan (Dialog-based, safe) ─────────────────────────

    def _toggle_edit_mode(self, checked):
        """Enable/disable Edit Mode.

        When ON:
          • Button turns orange and reads "🔓  Edit Mode ON"
          • Start Monitor is disabled (prevent committing while editing)
          • Plan rows highlighted with a subtle yellow tint
          • Double-click any pending row → opens Edit Reel dialog
        When OFF:
          • Button reverts to "✏  Edit Plan"
          • Plan saved to history (already mutated in place)
        """
        T = THEME
        if checked:
            self._edit_btn.setText("🔓  Edit Mode ON")
            self._edit_btn.setStyleSheet(
                self._edit_btn.styleSheet()
                + f"QPushButton{{ background:{T['accent_amber']}; color:#fff; "
                  f"font-weight:700; }}")
            self._start_btn.setEnabled(False)
            # Tint pending rows so the user sees what's editable
            self._tint_editable_rows(True)
            self._logger.info("[Edit Plan] Edit Mode ON — double-click any reel")
        else:
            self._edit_btn.setText("✏  Edit Plan")
            self._edit_btn.setStyleSheet("")
            self._start_btn.setEnabled(True)
            self._tint_editable_rows(False)
            # Save the current (possibly edited) plan to history
            try:
                order_info = self._get_order_info()
                self._history.save_order({**order_info, "plan": self._plan})
            except Exception as e:
                self._logger.warn(f"[Edit Plan] Could not save history: {e}")
            self._logger.info("[Edit Plan] Edit Mode OFF — plan saved")

    def _tint_editable_rows(self, on: bool):
        """Apply/remove a soft yellow tint to pending plan rows."""
        if not hasattr(self, "_plan_row_map"):
            return
        tint   = QColor("#FFFBEB")
        clear  = QColor("transparent")
        for tbl_row, pi in self._plan_row_map.items():
            if pi >= len(self._plan):
                continue
            row_data = self._plan[pi]
            if row_data.get("note") == "Wait next lot":
                continue
            for col in range(self._plan_table.columnCount()):
                itm = self._plan_table.item(tbl_row, col)
                if itm:
                    itm.setBackground(tint if on else clear)

    def _on_plan_table_double_click(self, tbl_row, col):
        """Double-click a plan row to open the Edit Reel dialog.

        Only works while Edit Mode is ON.
        """
        if not self._edit_btn.isChecked():
            # Subtle hint: tell user to enable edit mode
            return
        if not self._plan:
            return
        if tbl_row not in self._plan_row_map:
            return
        pi = self._plan_row_map[tbl_row]
        if pi >= len(self._plan):
            return
        row_data = self._plan[pi]
        if row_data.get("note") == "Wait next lot":
            QMessageBox.information(
                self, "Cannot Edit",
                "This row is a wait-marker (waiting for next lot).\n"
                "It cannot be edited directly.")
            return
        if row_data.get("note", "").startswith("Pulled"):
            QMessageBox.information(
                self, "Cannot Edit",
                "This reel was pulled and cannot be edited.")
            return
        self._open_edit_reel_menu(row_data["reel"])

    def _open_edit_reel_menu(self, reel_id):
        """Show the Edit Reel menu and dispatch to the chosen action."""
        r = next((x for x in self._plan if x.get("reel") == reel_id), None)
        if not r:
            return

        box_lbl = "📋 Remainder" if r["box"] == 0 else f"Box {r['box']}"
        summary = (
            f"<b style='font-size:14px;color:#0F172A'>"
            f"{box_lbl} · Reel R{r['reel']}</b>"
            f"<br><span style='color:#475569;font-size:12px'>"
            f"Lot {r.get('lot', '—')} · Target {r.get('target', 0):,} pcs</span>"
        )

        menu = EditReelMenu(self, summary)
        if menu.exec_() != QDialog.Accepted:
            return

        # Build a fresh editor (snapshots current state)
        history_reels = []
        st = getattr(self, '_saved_state', None) or {}
        for h in st.get("lot_history", []):
            for rd in h.get("reels", []):
                if not rd.get("note", "").startswith("Pulled"):
                    history_reels.append(rd)

        editor = PlanEditor(
            plan=self._plan,
            history_reels=history_reels,
            min_reel=self._c_min_reel,
            max_reel=self._c_max_reel,
            box_cap=self._c_max_box,
            slots_per_box=getattr(self._config, "reels_per_box", 4),
        )

        if menu.choice == EditReelMenu.OP_MOVE:
            dlg = MoveReelDialog(self, editor, reel_id)
            if dlg.exec_() == QDialog.Accepted:
                self._after_plan_edit(f"Moved R{reel_id}")

        elif menu.choice == EditReelMenu.OP_TARGET:
            dlg = ChangeTargetDialog(self, editor, reel_id)
            if dlg.exec_() == QDialog.Accepted:
                self._after_plan_edit(f"Changed target of R{reel_id}")

        elif menu.choice == EditReelMenu.OP_DELETE:
            reply = QMessageBox.question(
                self, "Delete Reel",
                f"Delete Reel R{reel_id}?\n\n"
                f"This cannot be undone.\n"
                f"To regenerate, click Calculate Plan again.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    editor.apply(DeleteReelOp(reel_id))
                    self._after_plan_edit(f"Deleted R{reel_id}")
                except PlanEditError as e:
                    QMessageBox.critical(self, "Error", str(e))

    def _after_plan_edit(self, action_msg):
        """Refresh table + summary after a successful dialog edit."""
        self._populate_table(self._plan, self._scrap_info)
        self._update_summary(self._plan, self._scrap_info)
        # Re-apply tint since _populate_table rebuilds the grid
        self._tint_editable_rows(True)
        self._logger.info(f"[Edit Plan] {action_msg}")

    # ─── Helpers ──────────────────────────────────────────────

    def _get_order_info(self):
        return {
            "invoice": self.product_edit.text().strip() or "VLO-127S",
            "dest": self.dest_combo.currentText(),
            "ship_date": self.shipment_date.date().toString("yyyyMMdd"),
            "order_qty": self.invoice_qty_spin.value(),   # [FIX] required by web monitor
            "total_target": sum(r["target"] for r in self._plan),
            "lots": [r.get_data() for r in self._lot_rows if r.get_data()["lot_no"]],
            "timestamp": datetime.now().isoformat(),
        }

    def _start_monitor(self):
        if not self._plan:
            return
        order_info = self._get_order_info()
        # Include remainder reels in the plan so the monitor can pack them
        ps = getattr(self, '_plan_state', None) or {}
        rem_reels = ps.get("remainder_reels", [])
        monitor_plan = list(self._plan)
        if rem_reels:
            monitor_plan.extend(rem_reels)
        self.plan_ready.emit(monitor_plan, order_info)

    def _export_csv(self):
        if not self._plan:
            return
        folder = self._config.output_folder
        fp, _ = QFileDialog.getSaveFileName(
            self, "Export Plan CSV",
            os.path.join(folder, "Planner", "PackPlan.csv"),
            "CSV Files (*.csv)")
        if fp:
            meta = {
                "Product": self.product_edit.text().strip(),
                "Destination": self.dest_combo.currentText(),
                "ShipmentDate": self.shipment_date.date().toString("dd/MM/yyyy"),
                "InvoiceQty": self.invoice_qty_spin.value(),
                "Mode": self._used_mode,
                "Generated": datetime.now().replace(microsecond=0).isoformat(" "),
            }
            write_plan_csv(fp, self._plan, meta)
            self._logger.info(f"Plan exported: {fp}")
            QMessageBox.information(
                self, "Exported", f"CSV saved: {os.path.basename(fp)}")