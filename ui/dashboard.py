"""
Dashboard Page — AutoPack VLO-127S
====================================
Page 0: Real-time overview of order progress and lot history.
Includes per-box reel packing detail with real-time updates.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QProgressBar, QComboBox, QGridLayout, QLabel,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QTimer

from ui.theme import THEME, S, F
from ui.widgets import SectionHeader, StatCard, Card, make_label
from core.live_server import get_live_data


class DashboardPage(QWidget):
    """Live dashboard showing current order progress."""

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self._state = app_state
        self._state.setdefault("completed_orders", [])
        self._build()

    def _build(self):
        T = THEME
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = SectionHeader("Live Dashboard", "Real-time packing status")
        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        vlay = QVBoxLayout(body)
        vlay.setContentsMargins(S(22), S(18), S(22), S(22))
        vlay.setSpacing(S(16))

        # Order selector row
        order_row = QHBoxLayout()
        order_row.setSpacing(S(8))
        order_row.addWidget(make_label("📋 Order:", bold=True, size=12, color=T["accent"]))
        self._order_selector = QComboBox()
        self._order_selector.setFixedWidth(S(320))
        self._order_selector.setFixedHeight(S(32))
        self._order_selector.addItem("Current / Latest Order")
        self._order_selector.currentIndexChanged.connect(self._on_order_selected)
        order_row.addWidget(self._order_selector)
        order_row.addStretch()
        vlay.addLayout(order_row)

        # Stat cards row
        stats = QHBoxLayout()
        stats.setSpacing(S(14))
        self._sc_packed = StatCard("Total Packed", "0", "of 0 target", T["accent"],      icon="📦")
        self._sc_lots   = StatCard("Lots Done",    "0", "",            T["accent2"],     icon="📋")
        self._sc_boxes  = StatCard("Boxes",        "0", "",            "#0891B2",        icon="🗃")
        self._sc_remain = StatCard("Remaining",    "0", "pcs to pack", T["accent_amber"],icon="⏳")
        for sc in [self._sc_packed, self._sc_lots, self._sc_boxes, self._sc_remain]:
            sc.setMinimumWidth(S(150))
            stats.addWidget(sc)
        vlay.addLayout(stats)

        # Progress bar card
        prog_card = Card()
        prog_lay = QVBoxLayout()
        prog_card.set_layout(prog_lay)
        prog_lay.addWidget(make_label("Order Progress", bold=True, size=12,
                                       color=T["text_secondary"]))
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(S(14))
        self._prog_bar.setFormat(" %p%")
        prog_lay.addWidget(self._prog_bar)
        self._prog_lbl = make_label("No active order", size=11, color=T["text_muted"])
        prog_lay.addWidget(self._prog_lbl)
        vlay.addWidget(prog_card)

        # Lot history table
        grp = QGroupBox("Lot History")
        grp_lay = QVBoxLayout(grp)
        self._hist_table = QTableWidget(0, 6)
        self._hist_table.setHorizontalHeaderLabels(
            ["Lot", "Input", "Packed", "Reject", "Scrap", "Carry"])
        self._hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._hist_table.setAlternatingRowColors(True)
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setMinimumHeight(S(220))
        grp_lay.addWidget(self._hist_table)
        vlay.addWidget(grp)

        # ── Box Packing Detail section ──
        box_grp = QGroupBox("📦 Box Packing Detail — Reel Mapping")
        box_grp_lay = QVBoxLayout(box_grp)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(S(8))
        filter_row.addWidget(make_label("Filter Box:", size=11, color=T["text_muted"]))
        self._box_filter = QComboBox()
        self._box_filter.addItem("All Boxes")
        self._box_filter.setFixedWidth(S(160))
        self._box_filter.setFixedHeight(S(30))
        self._box_filter.currentIndexChanged.connect(self._on_box_filter_changed)
        filter_row.addWidget(self._box_filter)

        # Reel search
        filter_row.addWidget(make_label("Search Reel:", size=11, color=T["text_muted"]))
        from PyQt5.QtWidgets import QLineEdit
        self._reel_search = QLineEdit()
        self._reel_search.setPlaceholderText("e.g. 5")
        self._reel_search.setFixedWidth(S(100))
        self._reel_search.setFixedHeight(S(30))
        self._reel_search.textChanged.connect(self._on_reel_search)
        filter_row.addWidget(self._reel_search)

        self._box_status_lbl = make_label("", size=11, color=T["text_secondary"])
        filter_row.addWidget(self._box_status_lbl)
        filter_row.addStretch()

        self._auto_refresh_lbl = QLabel("")
        self._auto_refresh_lbl.setStyleSheet(
            f"color:{T['accent_green']};background:transparent;font-size:{F(10)}px;")
        filter_row.addWidget(self._auto_refresh_lbl)
        box_grp_lay.addLayout(filter_row)

        # Box cards grid
        self._box_detail_area = QWidget()
        self._box_detail_grid = QGridLayout(self._box_detail_area)
        self._box_detail_grid.setContentsMargins(0, S(6), 0, 0)
        self._box_detail_grid.setSpacing(S(10))
        box_grp_lay.addWidget(self._box_detail_area)

        # Box overview summary table
        box_overview_grp = QGroupBox("📊 Box Overview — All Boxes")
        box_overview_lay = QVBoxLayout(box_overview_grp)
        self._box_overview_table = QTableWidget(0, 7)
        self._box_overview_table.setHorizontalHeaderLabels(
            ["Box", "Reels (packed/total)", "Packed Qty", "Max Capacity",
             "Fill %", "Reject", "Status"])
        h_bo = self._box_overview_table.horizontalHeader()
        for ci in range(7):
            h_bo.setSectionResizeMode(ci, QHeaderView.Stretch)
        self._box_overview_table.setAlternatingRowColors(True)
        self._box_overview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._box_overview_table.verticalHeader().setVisible(False)
        self._box_overview_table.setMinimumHeight(S(200))
        box_overview_lay.addWidget(self._box_overview_table)
        box_grp_lay.addWidget(box_overview_grp)

        box_grp_lay.addSpacing(S(10))

        # Reel detail table (per-box) — wrapped in QGroupBox for clear separation
        reel_detail_grp = QGroupBox("🔍 Reel Detail — Per Box")
        reel_detail_lay = QVBoxLayout(reel_detail_grp)
        self._reel_detail_table = QTableWidget(0, 8)
        self._reel_detail_table.setHorizontalHeaderLabels(
            ["Box", "Reel", "Lot", "Target", "Actual", "Reject", "Diff", "Status"])
        h_rdt = self._reel_detail_table.horizontalHeader()
        for ci in range(8):
            h_rdt.setSectionResizeMode(ci, QHeaderView.Stretch)
        self._reel_detail_table.setAlternatingRowColors(True)
        self._reel_detail_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._reel_detail_table.verticalHeader().setVisible(False)
        self._reel_detail_table.setMinimumHeight(S(200))
        reel_detail_lay.addWidget(self._reel_detail_table)
        box_grp_lay.addWidget(reel_detail_grp)

        vlay.addWidget(box_grp)
        vlay.addStretch()

        # Auto-refresh timer for real-time updates
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_live)
        self._refresh_timer.start(2000)  # every 2 seconds
        self._refreshing = False

    def refresh(self):
        """Refresh dashboard cards from app state."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_inner()
        finally:
            self._refreshing = False

    def _refresh_inner(self):
        # Update order selector dropdown
        self._update_order_selector()

        st = self._state.get("saved_state")
        if not st:
            # Show last completed order summary, or reset to defaults
            lc = self._state.get("last_completed")
            if lc:
                order = lc.get("order_qty", 0)
                packed = lc.get("packed", 0)
                self._sc_packed.set_value(f"{packed:,}")
                self._sc_packed.set_sub(f"of {order:,} target")
                self._sc_lots.set_value(str(lc.get("lots", 0)))
                all_boxes = set()
                for h in lc.get("lot_history", []):
                    for rd in h.get("reels", []):
                        all_boxes.add(rd.get("box", 0))
                self._sc_boxes.set_value(str(len(all_boxes)))
                self._sc_remain.set_value("0")
                self._sc_remain.set_sub("Order Complete \u2705")
                self._prog_bar.setValue(100)
                product = lc.get("product", "")
                self._prog_lbl.setText(
                    f"\u2705 {product} \u00b7 {packed:,} / {order:,} — Order Complete")
                lot_history = lc.get("lot_history", [])
                self._hist_table.setRowCount(len(lot_history))
                for i, h in enumerate(lot_history):
                    vals = [
                        h.get("lot", ""), f"{h.get('input', 0):,}",
                        f"{h.get('packed', 0):,}", f"{h.get('reject', 0):,}",
                        f"{h.get('scrap', 0):,}", f"{h.get('remainder', 0):,}",
                    ]
                    for j, v in enumerate(vals):
                        itm = QTableWidgetItem(v)
                        itm.setTextAlignment(Qt.AlignCenter)
                        self._hist_table.setItem(i, j, itm)
                self._refresh_box_detail_from_state(lc)
            else:
                # No active or completed order — clear all displays
                self._sc_packed.set_value("0")
                self._sc_packed.set_sub("No order")
                self._sc_lots.set_value("0")
                self._sc_boxes.set_value("0")
                self._sc_remain.set_value("—")
                self._prog_bar.setValue(0)
                self._prog_lbl.setText("No active order")
                self._hist_table.setRowCount(0)
                self._clear_box_detail()
            return

        packed = st.get("packed", 0)
        order  = st.get("order_qty", 0)
        remain = max(0, order - packed)
        pct = int(packed / order * 100) if order > 0 else 0
        lot_history = st.get("lot_history", [])

        self._sc_packed.set_value(f"{packed:,}")
        self._sc_packed.set_sub(f"of {order:,} target")
        self._sc_lots.set_value(str(len(lot_history)))

        all_boxes = set()
        for h in lot_history:
            for rd in h.get("reels", []):
                all_boxes.add(rd.get("box", 0))
        self._sc_boxes.set_value(str(len(all_boxes)))
        self._sc_remain.set_value(f"{remain:,}")
        self._sc_remain.set_sub("pcs to pack")   # [FIX-A] reset sub after Order Complete

        self._prog_bar.setValue(pct)
        product = st.get("product", "")
        self._prog_lbl.setText(f"{product} · {packed:,} / {order:,} pcs ({pct}%)")

        # Lot history table
        self._hist_table.setRowCount(len(lot_history))
        for i, h in enumerate(lot_history):
            vals = [
                h.get("lot", ""), f"{h.get('input', 0):,}",
                f"{h.get('packed', 0):,}", f"{h.get('reject', 0):,}",
                f"{h.get('scrap', 0):,}", f"{h.get('remainder', 0):,}",
            ]
            for j, v in enumerate(vals):
                itm = QTableWidgetItem(v)
                itm.setTextAlignment(Qt.AlignCenter)
                self._hist_table.setItem(i, j, itm)

        # Update box detail from lot_history reel data
        self._refresh_box_detail_from_state(st)

    # ── Box Packing Detail ───────────────────────────────────

    def _auto_refresh_live(self):
        """Periodically pull live data from the server and refresh box detail.
        [FIX-B] Also update stat cards so they stay current while on Dashboard.
        """
        live = get_live_data()
        reels = live.get("reels", [])
        boxes_data = live.get("boxes", {})

        # [FIX-B] Update stat cards from saved_state (lightweight — no table rebuild)
        st = self._state.get("saved_state")
        if st:
            packed = st.get("packed", 0)
            order  = st.get("order_qty", 0)
            remain = max(0, order - packed)
            pct    = int(packed / order * 100) if order > 0 else 0
            lot_history = st.get("lot_history", [])
            all_boxes = set()
            for h in lot_history:
                for rd in h.get("reels", []):
                    all_boxes.add(rd.get("box", 0))
            self._sc_packed.set_value(f"{packed:,}")
            self._sc_packed.set_sub(f"of {order:,} target")
            self._sc_lots.set_value(str(len(lot_history)))
            self._sc_boxes.set_value(str(len(all_boxes)))
            self._sc_remain.set_value(f"{remain:,}")
            self._sc_remain.set_sub("pcs to pack")
            self._prog_bar.setValue(pct)
            product = st.get("product", "")
            self._prog_lbl.setText(f"{product} · {packed:,} / {order:,} pcs ({pct}%)")

        if not reels and not boxes_data:
            self._auto_refresh_lbl.setText("")
            return
        self._auto_refresh_lbl.setText(
            f"🔄 Live · {live.get('updated_at', '—')}")
        self._refresh_box_detail_live(reels, boxes_data, live.get("max_box", 6400))

    def _refresh_box_detail_from_state(self, state):
        """Build box detail cards from saved state lot_history."""
        if not state:
            self._clear_box_detail()
            return

        lot_history = state.get("lot_history", [])
        if not lot_history:
            self._clear_box_detail()
            return

        # Collect all reels across lots into boxes
        box_reels = {}  # box_id -> [reel_dicts]
        for h in lot_history:
            for rd in h.get("reels", []):
                b = rd.get("box", 0)
                if b not in box_reels:
                    box_reels[b] = []
                box_reels[b].append(rd)

        max_box = state.get("max_box", 6400)
        self._render_box_detail(box_reels, max_box, source="state")

    def _refresh_box_detail_live(self, reels, boxes_data, max_box):
        """Build box detail from live server data."""
        if not reels:
            return

        box_reels = {}
        for r in reels:
            b = r.get("box", 0)
            if b not in box_reels:
                box_reels[b] = []
            box_reels[b].append(r)

        self._render_box_detail(box_reels, max_box or 6400, source="live")

    def _render_box_detail(self, box_reels, max_box, source="state"):
        """Render box cards and reel table from box_reels dict."""
        T = THEME

        # Update filter combo
        current_filter = self._box_filter.currentText()
        self._box_filter.blockSignals(True)
        self._box_filter.clear()
        self._box_filter.addItem("All Boxes")
        for b in sorted(box_reels.keys()):
            self._box_filter.addItem("Remainder" if b == 0 else f"Box {b}")
        # Restore selection
        idx = self._box_filter.findText(current_filter)
        if idx >= 0:
            self._box_filter.setCurrentIndex(idx)
        self._box_filter.blockSignals(False)

        # Apply filter
        filter_box = None
        if self._box_filter.currentIndex() > 0:
            txt = self._box_filter.currentText()
            if txt == "Remainder":
                filter_box = 0
            else:
                txt = txt.replace("Box ", "")
                try:
                    filter_box = int(txt)
                except ValueError:
                    pass

        search_reel = self._reel_search.text().strip()

        # Separate box=0 (remainder reels) from real boxes FIRST
        remainder_reels_b0 = box_reels.pop(0, None)

        # Snapshot ALL boxes (before filter) for use in Box Overview table
        all_box_reels_snapshot = {b: list(rs) for b, rs in box_reels.items()}
        
        # Include remainder in snapshot for overview table
        if remainder_reels_b0:
            all_box_reels_snapshot[0] = remainder_reels_b0

        # Filter boxes
        visible_boxes = {}
        for b in sorted(box_reels.keys()):
            if filter_box is not None and b != filter_box:
                continue
            reels = box_reels[b]
            if search_reel:
                reels = [r for r in reels
                         if search_reel in str(r.get("reel", ""))]
                if not reels:
                    continue
            visible_boxes[b] = reels

        # Status label
        total_boxes = len(box_reels)
        total_reels_all = sum(len(rs) for rs in box_reels.values())
        rem_count = len(remainder_reels_b0) if remainder_reels_b0 else 0
        status_parts = [f"{total_boxes} boxes · {total_reels_all} reels total"]
        if rem_count > 0:
            status_parts.append(f"+ {rem_count} remainder reel(s)")
        self._box_status_lbl.setText("  ".join(status_parts))

        # Clear old cards
        while self._box_detail_grid.count():
            w = self._box_detail_grid.takeAt(0).widget()
            if w:
                w.deleteLater()

        # Render box cards
        BOX_COLORS = ["#2563EB", "#16A34A", "#0891B2", "#7C3AED", "#D97706"]
        cols = min(4, max(1, len(visible_boxes)))
        for idx, b in enumerate(sorted(visible_boxes.keys())):
            reels = visible_boxes[b]
            row_i, col_i = divmod(idx, cols)

            # Calculate box totals
            box_actual = sum(r.get("actual", 0) for r in reels)
            box_target = sum(r.get("target", 0) for r in reels)
            box_reject = sum(r.get("reject", 0) for r in reels)
            done_count = sum(1 for r in reels
                             if r.get("status") == "done" or r.get("actual", 0) > 0)
            wait_count = sum(1 for r in reels
                             if r.get("note", "") == "Wait next lot"
                             or r.get("status") == "wait")
            total_count = len(reels)
            packable = total_count - wait_count

            is_complete = (done_count >= packable > 0)
            pct = int(box_actual / max_box * 100) if max_box > 0 else 0
            accent = BOX_COLORS[(b - 1) % len(BOX_COLORS)]

            if is_complete and box_actual >= max_box:
                border_col = T["accent_green"]
                status_txt = "✅ Sealed"
            elif is_complete:
                border_col = T["accent_amber"]
                status_txt = f"⚠ Done ({box_actual:,}/{max_box:,})"
            elif done_count > 0:
                border_col = accent
                status_txt = f"▶ {done_count}/{packable}"
            else:
                border_col = T["border"]
                status_txt = "⏳ Pending"

            card = QFrame()
            card.setStyleSheet(f"""QFrame {{
                background: {T['bg_card']}; border: 1.5px solid {border_col};
                border-radius: {S(8)}px; border-left: 4px solid {border_col};
            }}""")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(S(10), S(8), S(10), S(8))
            cl.setSpacing(S(4))

            # Header
            hdr = QHBoxLayout()
            box_lbl = QLabel(f"📦 Box {b}")
            box_lbl.setStyleSheet(
                f"font-size:{F(12)}px;font-weight:bold;"
                f"color:{accent};background:transparent;border:none;")
            st_lbl = QLabel(status_txt)
            st_lbl.setStyleSheet(
                f"font-size:{F(10)}px;font-weight:bold;"
                f"color:{border_col};background:transparent;border:none;")
            st_lbl.setAlignment(Qt.AlignRight)
            hdr.addWidget(box_lbl)
            hdr.addStretch()
            hdr.addWidget(st_lbl)
            cl.addLayout(hdr)

            # Progress bar
            prog = QProgressBar()
            prog.setRange(0, 100)
            prog.setValue(pct)
            prog.setFixedHeight(S(8))
            prog.setTextVisible(False)
            prog.setStyleSheet(f"""
                QProgressBar {{
                    background: {T['border']}; border-radius: {S(4)}px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background: {border_col}; border-radius: {S(4)}px;
                }}
            """)
            cl.addWidget(prog)

            # Packed / Max
            val_lbl = QLabel(f"{box_actual:,} / {max_box:,} pcs  ({pct}%)")
            val_lbl.setStyleSheet(
                f"font-size:{F(11)}px;font-weight:bold;"
                f"color:{T['text_primary']};background:transparent;border:none;")
            cl.addWidget(val_lbl)

            # Reel list inside card
            for r in reels:
                reel_no = r.get("reel", "?")
                lot = r.get("lot", "—")
                target = r.get("target", 0)
                actual = r.get("actual", 0)
                reject = r.get("reject", 0)
                note = r.get("note", "")
                status = r.get("status", "")

                if note == "Wait next lot" or status == "wait":
                    reel_txt = f"  R{reel_no}: ⏳ Wait"
                    reel_col = T["accent_amber"]
                elif actual > 0 or status == "done":
                    diff_v = actual - target
                    diff_s = f"+{diff_v:,}" if diff_v > 0 else f"{diff_v:,}" if diff_v < 0 else "0"
                    rej_s = f" Rej:{reject:,}" if reject > 0 else ""
                    reel_txt = (f"  R{reel_no}: {actual:,}/{target:,} "
                                f"({diff_s}){rej_s}  [{lot}]")
                    reel_col = T["accent_green"] if diff_v == 0 else T["accent_amber"]
                else:
                    reel_txt = f"  R{reel_no}: Target {target:,}  [{lot}]"
                    reel_col = T["text_muted"]

                rl = QLabel(reel_txt)
                rl.setStyleSheet(
                    f"font-size:{F(10)}px;color:{reel_col};"
                    f"background:transparent;border:none;padding-left:{S(4)}px;")
                cl.addWidget(rl)

            # Extra info
            detail_parts = []
            if box_reject > 0:
                c_red = T['accent_red']
                detail_parts.append(
                    f"<span style='color:{c_red}'>Reject: {box_reject:,}</span>")
            if wait_count > 0:
                c_amb = T['accent_amber']
                detail_parts.append(
                    f"<span style='color:{c_amb}'>{wait_count} wait slot(s)</span>")
            if detail_parts:
                det = QLabel(" · ".join(detail_parts))
                det.setTextFormat(Qt.RichText)
                det.setStyleSheet(
                    f"font-size:{F(9)}px;background:transparent;border:none;")
                cl.addWidget(det)

            self._box_detail_grid.addWidget(card, row_i, col_i)

        # Render remainder reels (box=0) as distinct purple card
        if remainder_reels_b0:
            rem_col = "#9333EA"  # purple
            rem_reels = remainder_reels_b0
            rem_actual = sum(r.get("actual", 0) for r in rem_reels)
            rem_done = sum(1 for r in rem_reels
                          if r.get("status") == "done" or r.get("actual", 0) > 0)
            card = QFrame()
            card.setStyleSheet(f"""QFrame {{
                background: #FAF5FF; border: 1.5px solid {rem_col};
                border-radius: {S(8)}px; border-left: 4px solid {rem_col};
            }}""")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(S(10), S(8), S(10), S(8))
            cl.setSpacing(S(4))
            hdr = QHBoxLayout()
            box_lbl = QLabel("📋 Remainder (next order)")
            box_lbl.setStyleSheet(
                f"font-size:{F(12)}px;font-weight:bold;"
                f"color:{rem_col};background:transparent;border:none;")
            r_complete = rem_done == len(rem_reels) and len(rem_reels) > 0
            st_txt = "✅ Done" if r_complete else f"▶ {rem_done}/{len(rem_reels)}"
            st_lbl = QLabel(st_txt)
            st_lbl.setStyleSheet(
                f"font-size:{F(10)}px;font-weight:bold;"
                f"color:{rem_col};background:transparent;border:none;")
            st_lbl.setAlignment(Qt.AlignRight)
            hdr.addWidget(box_lbl); hdr.addStretch(); hdr.addWidget(st_lbl)
            cl.addLayout(hdr)
            val_lbl = QLabel(f"{rem_actual:,} pcs · {len(rem_reels)} reel(s)")
            val_lbl.setStyleSheet(
                f"font-size:{F(11)}px;font-weight:bold;"
                f"color:{T['text_primary']};background:transparent;border:none;")
            cl.addWidget(val_lbl)
            for r in rem_reels:
                reel_no = r.get("reel", "?")
                lot = r.get("lot", "—")
                target = r.get("target", 0)
                actual = r.get("actual", 0)
                if actual > 0:
                    reel_txt = f"  R{reel_no}: {actual:,}/{target:,}  [{lot}]"
                    reel_c = T["accent_green"]
                else:
                    reel_txt = f"  R{reel_no}: Target {target:,}  [{lot}]"
                    reel_c = T["text_muted"]
                rl = QLabel(reel_txt)
                rl.setStyleSheet(
                    f"font-size:{F(10)}px;color:{reel_c};"
                    f"background:transparent;border:none;padding-left:{S(4)}px;")
                cl.addWidget(rl)
            row_i, col_i = divmod(len(visible_boxes), max(cols, 1))
            self._box_detail_grid.addWidget(card, row_i, col_i)

        # ── Box Overview Summary Table (always shows ALL boxes) ──
        # Use snapshot taken before filtering so overview is never empty
        all_boxes_sorted = sorted(all_box_reels_snapshot.keys())
        
        if not all_boxes_sorted:
            # No boxes to display
            self._box_overview_table.setRowCount(0)
            return
        
        self._box_overview_table.setRowCount(len(all_boxes_sorted) + 1)  # +1 for total row
        grand_total_reels = 0
        grand_done_reels = 0
        grand_packed = 0
        grand_reject = 0
        for oi, b in enumerate(all_boxes_sorted):
            reels_b = all_box_reels_snapshot[b]
            b_actual = sum(r.get("actual", 0) for r in reels_b)
            b_reject = sum(r.get("reject", 0) for r in reels_b)
            b_done = sum(1 for r in reels_b
                         if r.get("status") == "done" or r.get("actual", 0) > 0)
            b_wait = sum(1 for r in reels_b
                         if r.get("note", "") == "Wait next lot"
                         or r.get("status") == "wait")
            b_total = len(reels_b)
            b_packable = b_total - b_wait
            b_pct = int(b_actual / max_box * 100) if max_box > 0 else 0
            b_complete = (b_done >= b_packable > 0)

            if b == 0:
                # Remainder reels — no "Sealed" status
                if b_complete:
                    st_txt = "✅ Done"
                    st_col = "#9333EA"
                elif b_done > 0:
                    st_txt = f"▶ {b_done}/{b_packable}"
                    st_col = "#9333EA"
                else:
                    st_txt = "⏳ Pending"
                    st_col = T["text_muted"]
            elif b_complete and b_actual >= max_box:
                st_txt = "✅ Sealed"
                st_col = T["accent_green"]
            elif b_complete:
                st_txt = f"⚠ Done ({b_actual:,}/{max_box:,})"
                st_col = T["accent_amber"]
            elif b_done > 0:
                st_txt = f"▶ Packing ({b_done}/{b_packable})"
                st_col = T["accent"]
            else:
                st_txt = "⏳ Pending"
                st_col = T["text_muted"]

            vals_ov = [
                ("Remainder" if b == 0 else f"Box {b}", "#9333EA" if b == 0 else T["accent"], True),
                (f"{b_done} / {b_total}", T["text_primary"], False),
                (f"{b_actual:,}", T["accent_green"] if b_actual > 0 else T["text_muted"], True),
                ("—" if b == 0 else f"{max_box:,}", T["text_muted"] if b == 0 else T["text_primary"], False),
                ("—" if b == 0 else f"{b_pct}%", T["text_muted"] if b == 0 else (T["accent_green"] if b_pct >= 100 else T["accent"] if b_pct > 0 else T["text_muted"]), True),
                (f"{b_reject:,}" if b_reject > 0 else "0",
                 T["accent_red"] if b_reject > 0 else T["text_muted"], False),
                (st_txt, st_col, True),
            ]
            for j, (v, c, bold) in enumerate(vals_ov):
                itm = QTableWidgetItem(v)
                itm.setTextAlignment(Qt.AlignCenter)
                itm.setForeground(QColor(c))
                if bold:
                    fnt = itm.font()
                    fnt.setBold(True)
                    itm.setFont(fnt)
                self._box_overview_table.setItem(oi, j, itm)

            grand_total_reels += b_total
            grand_done_reels += b_done
            grand_packed += b_actual
            grand_reject += b_reject

        # Total row
        trow = len(all_boxes_sorted)
        total_capacity = max_box * max(1, len([b for b in all_boxes_sorted if b != 0]))
        grand_pct = int(grand_packed / total_capacity * 100) if total_capacity > 0 else 0
        total_vals = [
            (f"Total ({len(all_boxes_sorted)} boxes)", T["text_primary"]),
            (f"{grand_done_reels} / {grand_total_reels}", T["text_primary"]),
            (f"{grand_packed:,}", T["accent_green"]),
            (f"{total_capacity:,}", T["text_primary"]),
            (f"{grand_pct}%", T["accent"]),
            (f"{grand_reject:,}" if grand_reject > 0 else "0",
             T["accent_red"] if grand_reject > 0 else T["text_muted"]),
            ("", T["text_muted"]),
        ]
        for j, (v, c) in enumerate(total_vals):
            itm = QTableWidgetItem(v)
            itm.setTextAlignment(Qt.AlignCenter)
            itm.setForeground(QColor(c))
            fnt = itm.font()
            fnt.setBold(True)
            itm.setFont(fnt)
            itm.setBackground(QColor("#F1F5F9"))
            self._box_overview_table.setItem(trow, j, itm)

        # Populate reel detail table
        all_reels = []
        for b in sorted(visible_boxes.keys()):
            for r in visible_boxes[b]:
                all_reels.append((b, r))

        self._reel_detail_table.setRowCount(len(all_reels))
        for i, (b, r) in enumerate(all_reels):
            reel_no = r.get("reel", "?")
            lot = r.get("lot", "—")
            target = r.get("target", 0)
            actual = r.get("actual", 0)
            reject = r.get("reject", 0)
            note = r.get("note", "")
            status = r.get("status", "")

            if note == "Wait next lot" or status == "wait":
                status_txt = "⏳ Wait"
                status_col = T["accent_amber"]
            elif actual > 0 or status == "done":
                diff_v = actual - target
                if diff_v == 0:
                    status_txt = "✔ OK"
                    status_col = T["accent_green"]
                elif (abs(diff_v) <= target * 0.05) if target > 0 else False:
                    status_txt = "⚠ Warn"
                    status_col = T["accent_amber"]
                else:
                    status_txt = "✕ Dev" if diff_v != 0 else "✔ OK"
                    status_col = T["accent_red"] if diff_v < 0 else T["accent_amber"]
            elif status == "current":
                status_txt = "▶ Active"
                status_col = T["accent"]
            else:
                status_txt = "⏳ Pending"
                status_col = T["text_muted"]

            diff_v = actual - target if (actual > 0 or status == "done") else 0
            diff_s = (f"+{diff_v:,}" if diff_v > 0
                      else f"{diff_v:,}" if diff_v < 0 else "—")

            vals = [
                (f"Box {b}", T["accent"]),
                (f"Reel {reel_no}", T["accent2"] if "accent2" in T else T["accent"]),
                (str(lot), T["text_primary"]),
                (f"{target:,}" if target > 0 else "—", T["accent_green"]),
                (f"{actual:,}" if actual > 0 else "—", T["accent"]),
                (f"{reject:,}" if reject > 0 else "0", T["accent_red"] if reject > 0 else T["text_muted"]),
                (diff_s, T["accent_green"] if diff_v == 0 and actual > 0
                 else T["accent_red"] if diff_v < 0 else T["accent_amber"] if diff_v > 0
                 else T["text_muted"]),
                (status_txt, status_col),
            ]
            for j, (v, c) in enumerate(vals):
                itm = QTableWidgetItem(v)
                itm.setTextAlignment(Qt.AlignCenter)
                itm.setForeground(QColor(c))
                if j == 0:
                    fnt = itm.font()
                    fnt.setBold(True)
                    itm.setFont(fnt)
                self._reel_detail_table.setItem(i, j, itm)

    def _clear_box_detail(self):
        """Clear box detail widgets."""
        while self._box_detail_grid.count():
            w = self._box_detail_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._reel_detail_table.setRowCount(0)
        self._box_overview_table.setRowCount(0)
        self._box_status_lbl.setText("")

    def _on_box_filter_changed(self):
        """Re-render box detail with current filter."""
        self._force_refresh_box_detail()

    def _on_reel_search(self):
        """Re-render box detail with reel search."""
        self._force_refresh_box_detail()

    def _force_refresh_box_detail(self):
        """Re-render box detail from whichever source is available."""
        live = get_live_data()
        reels = live.get("reels", [])
        boxes_data = live.get("boxes", {})
        if reels or boxes_data:
            self._refresh_box_detail_live(
                reels, boxes_data, live.get("max_box", 6400))
            return

        st = self._state.get("saved_state")
        if st:
            self._refresh_box_detail_from_state(st)
            return

        lc = self._state.get("last_completed")
        if lc:
            self._refresh_box_detail_from_state(lc)

    # ── Order Selector (multi-order per day) ─────────────────

    def _update_order_selector(self):
        """Populate order selector with completed orders from today."""
        self._order_selector.blockSignals(True)
        current_text = self._order_selector.currentText()
        self._order_selector.clear()
        self._order_selector.addItem("Current / Latest Order")
        completed = self._state.get("completed_orders", [])
        for i, o in enumerate(completed):
            product = o.get("product", "?")
            packed = o.get("packed", 0)
            order_qty = o.get("order_qty", 0)
            ts = o.get("completed_at", "")
            label = f"#{i+1}  {product} — {packed:,}/{order_qty:,} pcs  ({ts})"
            self._order_selector.addItem(label)
        idx = self._order_selector.findText(current_text)
        if idx >= 0:
            self._order_selector.setCurrentIndex(idx)
        self._order_selector.blockSignals(False)

    def _on_order_selected(self, idx):
        """Switch dashboard view to selected order."""
        if idx <= 0:
            # Show current / latest
            self.refresh()
            return
        completed = self._state.get("completed_orders", [])
        order_idx = idx - 1
        if order_idx >= len(completed):
            return
        order_data = completed[order_idx]
        self._show_order_data(order_data)

    def _show_order_data(self, data):
        """Display a specific completed order's data."""
        T = THEME
        order_qty = data.get("order_qty", 0)
        packed = data.get("packed", 0)
        lot_history = data.get("lot_history", [])

        self._sc_packed.set_value(f"{packed:,}")
        self._sc_packed.set_sub(f"of {order_qty:,} target")
        self._sc_lots.set_value(str(len(lot_history)))
        all_boxes = set()
        for h in lot_history:
            for rd in h.get("reels", []):
                all_boxes.add(rd.get("box", 0))
        self._sc_boxes.set_value(str(len(all_boxes)))
        remain = max(0, order_qty - packed)
        self._sc_remain.set_value(f"{remain:,}")
        if remain == 0:
            self._sc_remain.set_sub("Order Complete \u2705")
        pct = int(packed / order_qty * 100) if order_qty > 0 else 0
        self._prog_bar.setValue(pct)
        product = data.get("product", "")
        self._prog_lbl.setText(
            f"\u2705 {product} \u00b7 {packed:,} / {order_qty:,} — Order Complete")
        self._hist_table.setRowCount(len(lot_history))
        for i, h in enumerate(lot_history):
            vals = [
                h.get("lot", ""), f"{h.get('input', 0):,}",
                f"{h.get('packed', 0):,}", f"{h.get('reject', 0):,}",
                f"{h.get('scrap', 0):,}", f"{h.get('remainder', 0):,}",
            ]
            for j, v in enumerate(vals):
                itm = QTableWidgetItem(v)
                itm.setTextAlignment(Qt.AlignCenter)
                self._hist_table.setItem(i, j, itm)
        self._refresh_box_detail_from_state(data)