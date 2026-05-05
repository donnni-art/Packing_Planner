"""
History Page — AutoPack VLO-127S
=================================
Page 3: Past order records with detail view and CSV export.
"""

import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFrame,
    QScrollArea, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QFileDialog,
)
from PyQt5.QtCore import Qt

from ui.theme import THEME, S
from ui.widgets import SectionHeader, StatCard, Badge, make_btn, make_label


class HistoryPage(QWidget):
    def __init__(self, history, logger, parent=None):
        super().__init__(parent)
        self._history = history
        self._logger = logger
        self._orders = []
        self._build()

    def _build(self):
        T = THEME
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        hdr = SectionHeader("Plan History", "ประวัติการ Plan แต่ละ Order")
        refresh_btn = make_btn("↻  Refresh", "flat")
        refresh_btn.clicked.connect(self.reload)
        hdr.add_widget(refresh_btn)
        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(S(2))
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {T['border']}; }}")
        root.addWidget(splitter)

        # LEFT: list
        left_w = QWidget()
        left_w.setStyleSheet(f"background: {T['bg_card']};")
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(S(12), S(12), S(12), S(12))
        left_lay.setSpacing(S(8))
        search = QLineEdit(); search.setPlaceholderText("ค้นหา Invoice...")
        search.textChanged.connect(self._filter)
        left_lay.addWidget(search)
        self._order_list = QTableWidget(0, 4)
        self._order_list.setHorizontalHeaderLabels(["Invoice", "Dest", "Ship Date", "Packed Time"])
        self._order_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._order_list.setAlternatingRowColors(True)
        self._order_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._order_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._order_list.verticalHeader().setVisible(False)
        self._order_list.itemSelectionChanged.connect(self._on_select)
        left_lay.addWidget(self._order_list)
        splitter.addWidget(left_w)

        # RIGHT: detail
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_w = QWidget(); right_scroll.setWidget(right_w)
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(S(16), S(14), S(20), S(20))
        right_lay.setSpacing(S(12))
        self._det_header = make_label("เลือก Order เพื่อดูรายละเอียด", bold=True, size=14)
        right_lay.addWidget(self._det_header)
        det_meta = QHBoxLayout()
        self._det_inv = Badge("—", "blue")
        self._det_dest = Badge("—", "green")
        self._det_date = Badge("—", "gray")
        det_meta.addWidget(self._det_inv); det_meta.addWidget(self._det_dest)
        det_meta.addWidget(self._det_date); det_meta.addStretch()
        right_lay.addLayout(det_meta)
        det_stats = QHBoxLayout(); det_stats.setSpacing(S(10))
        self._det_boxes = StatCard("Boxes", "—", "", THEME["accent"])
        self._det_reels = StatCard("Reels", "—", "", THEME["accent2"])
        self._det_target = StatCard("Target", "—", "", "#0891B2")
        self._det_packed = StatCard("Packed", "—", "", THEME["accent_green"])
        self._det_reject = StatCard("Reject", "—", "", THEME["accent_amber"])
        for c in [self._det_boxes, self._det_reels, self._det_target,
                  self._det_packed, self._det_reject]:
            det_stats.addWidget(c)
        self._det_packed.setVisible(False)
        self._det_reject.setVisible(False)
        right_lay.addLayout(det_stats)
        self._det_table = QTableWidget(0, 5)
        self._det_table.setHorizontalHeaderLabels(["Box", "Reel", "Lot", "Target", "Note"])
        self._det_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._det_table.setAlternatingRowColors(True)
        self._det_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._det_table.verticalHeader().setVisible(False)
        self._det_table.setMinimumHeight(S(260))
        right_lay.addWidget(self._det_table)
        export_btn = make_btn("Export Plan CSV", "flat")
        export_btn.clicked.connect(self._export_selected)
        right_lay.addWidget(export_btn)
        right_lay.addStretch()
        splitter.addWidget(right_scroll)
        splitter.setSizes([S(320), S(580)])
        self.reload()

    def reload(self):
        self._orders = self._history.list_orders()
        self._filtered = self._orders
        self._populate_list(self._orders)

    def _populate_list(self, orders):
        self._order_list.setRowCount(len(orders))
        for i, (fn, data) in enumerate(orders):
            for j, val in enumerate([
                data.get("invoice", "—"),
                data.get("dest", "—"),
                data.get("ship_date", "—"),
                self._display_packed_time(fn, data),
            ]):
                itm = QTableWidgetItem(val)
                itm.setTextAlignment(Qt.AlignCenter)
                self._order_list.setItem(i, j, itm)

    def _display_packed_time(self, filename, data):
        completed_at = data.get("completed_at", "")
        if completed_at:
            try:
                return datetime.fromisoformat(completed_at).strftime("%H:%M:%S")
            except ValueError:
                return str(completed_at)

        # Fallback for legacy files using invoice_YYYYMMDD_HHMMSS(.json) format.
        stem = os.path.splitext(filename)[0]
        parts = stem.rsplit("_", 2)
        if len(parts) >= 2 and len(parts[-1]) >= 6:
            hhmmss = parts[-1][:6]
            if hhmmss.isdigit():
                return f"{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"
        return "—"

    def _filter(self, text):
        self._filtered = [(fn, d) for fn, d in self._orders
                          if text.lower() in d.get("invoice", "").lower()
                          or text.lower() in d.get("dest", "").lower()]
        self._populate_list(self._filtered)

    def _on_select(self):
        row_idx = self._order_list.currentRow()
        src = getattr(self, "_filtered", self._orders)
        if row_idx < 0 or row_idx >= len(src):
            return
        _, data = src[row_idx]
        self._show_detail(data)

    def _show_detail(self, data):
        plan = data.get("plan", [])
        inv = data.get("invoice", "—")
        dest = data.get("dest", "—")
        date = data.get("ship_date", "—")
        is_completed = data.get("completed", False)
        total_boxes = len(set(r.get("box", 1) for r in plan))
        total_target = sum(r.get("target", 0) for r in plan)
        self._det_header.setText(f"Invoice: {inv}")
        self._det_inv.setText(f"Invoice: {inv}")
        self._det_dest.setText(dest)
        self._det_date.setText(date)
        self._det_boxes.set_value(str(total_boxes))
        self._det_reels.set_value(str(len(plan)))
        self._det_target.set_value(f"{total_target:,}")

        if is_completed:
            total_packed = data.get("total_packed", sum(r.get("actual", 0) for r in plan))
            total_reject = data.get("total_reject", sum(r.get("reject", 0) for r in plan))
            self._det_packed.set_value(f"{total_packed:,}")
            self._det_reject.set_value(f"{total_reject:,}")
            self._det_packed.setVisible(True)
            self._det_reject.setVisible(True)
        else:
            self._det_packed.setVisible(False)
            self._det_reject.setVisible(False)

        if is_completed:
            cols = ["Box", "Reel", "Lot", "Target", "Actual", "Reject", "Diff", "Note"]
        else:
            cols = ["Box", "Reel", "Lot", "Target", "Note"]
        self._det_table.setColumnCount(len(cols))
        self._det_table.setHorizontalHeaderLabels(cols)
        self._det_table.setRowCount(len(plan))
        for i, row in enumerate(plan):
            box_val = row.get('box', '')
            box_text = "📋 Remainder" if box_val == 0 else f"Box {box_val}"
            if is_completed:
                vals = [
                    box_text, f"R{row.get('reel','')}",
                    row.get("lot", ""), f"{row.get('target',0):,}",
                    f"{row.get('actual',0):,}", f"{row.get('reject',0):,}",
                    f"{row.get('diff',0):+,}", row.get("note", ""),
                ]
            else:
                vals = [
                    box_text, f"R{row.get('reel','')}",
                    row.get("lot", ""), f"{row.get('target',0):,}",
                    row.get("note", ""),
                ]
            for j, val in enumerate(vals):
                itm = QTableWidgetItem(val)
                itm.setTextAlignment(Qt.AlignCenter)
                self._det_table.setItem(i, j, itm)
        self._current_detail = data

    def _export_selected(self):
        data = getattr(self, "_current_detail", None)
        if not data:
            QMessageBox.warning(self, "Warning", "เลือก Order ก่อน"); return
        fp, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", f"Plan_{data.get('invoice','ORDER')}.csv", "CSV Files (*.csv)")
        if fp:
            self._history.export_csv(data, fp)
            self._logger.info(f"History export: {fp}")
            QMessageBox.information(self, "Exported", f"CSV saved: {os.path.basename(fp)}")