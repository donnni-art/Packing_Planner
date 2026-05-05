"""
Monitor Page — AutoPack VLO-127S
=================================
Page 2: Full inline monitor with reel-by-reel actual entry.
Includes 5 themed dialog classes for deviation warnings, replan, and scrap.
"""

import os, csv, json, queue, threading, platform
from datetime import datetime
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler


def _beep(freq: int, ms: int):
    """Audible beep on Windows; silent no-op on other platforms."""
    if platform.system() != "Windows":
        return
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass

from core.live_server import get_submit_queue

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QGridLayout,
    QLabel, QLineEdit, QSpinBox, QComboBox, QTableWidget,
    QTableWidgetItem, QScrollArea, QMessageBox, QFileDialog,
    QDialog, QPushButton, QHeaderView,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal, QLocale

from ui.theme import THEME, S, F
from ui.widgets import SectionHeader, Card, make_btn, make_label
from core.live_server import update_live_data


# ══════════════════════════════════════════════════════════════
#  DIALOGS
# ══════════════════════════════════════════════════════════════

class _MonitorDeviationDialog(QDialog):
    """Large deviation (>10%) confirmation."""

    def __init__(self, actual, target, diff, pct, parent=None):
        super().__init__(parent)
        T = THEME
        self.setWindowTitle("⚠ Large Deviation")
        self.setFixedWidth(S(420))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(f"""
            QDialog {{ background: {T['bg_card']}; border: 2px solid {T['accent_red']};
                       border-radius: {S(10)}px; }}
            QLabel {{ color: {T['text_primary']}; background: transparent; }}
            QPushButton {{ min-height: {S(38)}px; min-width: {S(100)}px;
                           border-radius: {S(7)}px; font-size: {F(12)}px; font-weight: bold; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(20), S(16), S(20), S(16))
        lay.setSpacing(S(10))
        tr = QHBoxLayout()
        ico = QLabel("⚠"); ico.setStyleSheet(f"font-size:{F(26)}px;color:{T['accent_red']};")
        ttl = QLabel("Large Deviation Detected")
        ttl.setStyleSheet(f"font-size:{F(15)}px;font-weight:bold;color:{T['accent_red']};")
        tr.addWidget(ico); tr.addWidget(ttl); tr.addStretch()
        lay.addLayout(tr)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{T['border']};max-height:1px;")
        lay.addWidget(sep)
        info = QFormLayout(); info.setSpacing(S(6)); info.setContentsMargins(S(8), 0, 0, 0)
        ls = f"font-size:{F(12)}px;color:{T['text_muted']};"
        vs = f"font-size:{F(13)}px;font-weight:bold;"
        for lbl, val, col in [("Target:", f"{target:,} pcs", T["accent"]),
                               ("Actual:", f"{actual:,} pcs", T["accent_amber"]),
                               ("Diff:", f"{diff:+,} pcs ({pct:.1f}%)", T["accent_red"])]:
            l = QLabel(lbl); l.setStyleSheet(ls)
            v = QLabel(val); v.setStyleSheet(vs + f"color:{col};")
            info.addRow(l, v)
        lay.addLayout(info)
        q = QLabel("Confirm this value?"); q.setAlignment(Qt.AlignCenter)
        q.setStyleSheet(f"font-size:{F(12)}px;color:{T['text_muted']};")
        lay.addWidget(q)
        br = QHBoxLayout(); br.setSpacing(S(10)); br.addStretch()
        yes_btn = QPushButton("✔  Yes")
        yes_btn.setStyleSheet(f"QPushButton{{background:{T['accent_green']};color:#fff;}}"
                              f"QPushButton:hover{{background:#15803D;}}")
        yes_btn.clicked.connect(self.accept)
        no_btn = QPushButton("✖  No")
        no_btn.setStyleSheet(f"QPushButton{{background:{T['accent_red']};color:#fff;}}"
                             f"QPushButton:hover{{background:#B91C1C;}}")
        no_btn.clicked.connect(self.reject); no_btn.setDefault(True); no_btn.setFocus()
        br.addWidget(yes_btn); br.addWidget(no_btn)
        lay.addLayout(br)


class _MonitorOverflowDialog(QDialog):
    """Actual + Reject exceeds Target (overflow) warning."""

    def __init__(self, actual, reject, target, parent=None):
        super().__init__(parent)
        T = THEME
        overflow = (actual + reject) - target
        self.setWindowTitle("⚠ Overflow Detected")
        self.setFixedWidth(S(460))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(f"""
            QDialog {{ background: {T['bg_card']}; border: 2px solid {T['accent_red']};
                       border-radius: {S(10)}px; }}
            QLabel {{ color: {T['text_primary']}; background: transparent; }}
            QPushButton {{ min-height: {S(38)}px; min-width: {S(100)}px;
                           border-radius: {S(7)}px; font-size: {F(12)}px; font-weight: bold; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(20), S(16), S(20), S(16))
        lay.setSpacing(S(12))
        
        # Title
        tr = QHBoxLayout()
        ico = QLabel("⛔"); ico.setStyleSheet(f"font-size:{F(26)}px;")
        ttl = QLabel("Actual + Reject Exceeds Input")
        ttl.setStyleSheet(f"font-size:{F(15)}px;font-weight:bold;color:{T['accent_red']};")
        tr.addWidget(ico); tr.addWidget(ttl); tr.addStretch()
        lay.addLayout(tr)
        
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{T['border']};max-height:1px;")
        lay.addWidget(sep)
        
        # Info details
        info = QFormLayout(); info.setSpacing(S(6)); info.setContentsMargins(S(8), 0, 0, 0)
        ls = f"font-size:{F(12)}px;color:{T['text_muted']};"
        vs = f"font-size:{F(13)}px;font-weight:bold;"
        for lbl, val, col in [
            ("Target (Input):", f"{target:,} pcs", T["accent"]),
            ("Actual:", f"{actual:,} pcs", T["accent_amber"]),
            ("Reject:", f"{reject:,} pcs", T["accent_red"]),
            ("Total (A+R):", f"{actual + reject:,} pcs", T["accent_red"]),
            ("Overflow:", f"+{overflow:,} pcs EXCEEDS INPUT", T["accent_red"]),
        ]:
            l = QLabel(lbl); l.setStyleSheet(ls)
            v = QLabel(val); v.setStyleSheet(vs + f"color:{col};")
            info.addRow(l, v)
        lay.addLayout(info)
        
        # Warning message
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"background:{T['border']};max-height:1px;")
        lay.addWidget(sep2)
        
        warn_msg = QLabel(
            "⚠️  This indicates:\n"
            "  • User data entry error (actual or reject is wrong), OR\n"
            "  • Reel 4 cannot borrow (it's a MIN reel)\n\n"
            "Please verify your entries and correct them.\n"
            "Click 'Edit' to correct the values."
        )
        warn_msg.setStyleSheet(f"font-size:{F(11)}px;color:{T['text_secondary']};line-height:1.5;")
        warn_msg.setWordWrap(True)
        lay.addWidget(warn_msg)
        
        # Buttons
        br = QHBoxLayout(); br.setSpacing(S(10)); br.addStretch()
        edit_btn = QPushButton("✏️  Edit")
        edit_btn.setStyleSheet(f"QPushButton{{background:{T['accent_amber']};color:#fff;}}"
                              f"QPushButton:hover{{background:#F59E0B;}}")
        edit_btn.clicked.connect(self.reject)  # Close dialog, go back to editing
        br.addWidget(edit_btn)
        
        force_btn = QPushButton("⚠️  Force Accept")
        force_btn.setStyleSheet(f"QPushButton{{background:{T['accent_red']};color:#fff;}}"
                               f"QPushButton:hover{{background:#B91C1C;}}")
        force_btn.clicked.connect(self.accept)  # Force proceed despite overflow
        br.addWidget(force_btn)
        
        lay.addLayout(br)


class _MonitorSummaryDialog(QDialog):
    CANCEL_CODE = 2

    def __init__(self, confirmed, total_target, total_actual, diff_text,
                 incomplete=False, incomplete_boxes=None, max_per_box=6400,
                 parent=None):
        super().__init__(parent)
        T = THEME
        self.setWindowTitle("Packing Complete")
        self.setFixedWidth(S(440))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        border_col = T["accent_green"] if not incomplete else T["accent_amber"]
        icon_char  = "✅" if not incomplete else "⚠"
        title_text = "Packing Complete" if not incomplete else "Incomplete Packing"
        self.setStyleSheet(f"""
            QDialog {{ background: {T['bg_card']}; border: 2px solid {border_col};
                       border-radius: {S(10)}px; }}
            QLabel {{ color: {T['text_primary']}; background: transparent; }}
            QPushButton {{ min-height: {S(38)}px; min-width: {S(90)}px;
                           border-radius: {S(7)}px; font-size: {F(12)}px; font-weight: bold; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(20), S(16), S(20), S(16))
        lay.setSpacing(S(10))
        tr = QHBoxLayout()
        ico = QLabel(icon_char); ico.setStyleSheet(f"font-size:{F(24)}px;color:{border_col};")
        ttl = QLabel(title_text); ttl.setStyleSheet(f"font-size:{F(15)}px;font-weight:bold;color:{border_col};")
        tr.addWidget(ico); tr.addWidget(ttl); tr.addStretch()
        lay.addLayout(tr)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{T['border']};max-height:1px;")
        lay.addWidget(sep)
        info = QFormLayout(); info.setSpacing(S(6)); info.setContentsMargins(S(8), 0, 0, 0)
        ls = f"font-size:{F(12)}px;color:{T['text_muted']};"
        vs = f"font-size:{F(13)}px;font-weight:bold;"
        for lbl, val, col in [("Reels:", f"{confirmed} confirmed", T["accent"]),
                               ("Target:", f"{total_target:,} pcs", T["accent"]),
                               ("Actual:", f"{total_actual:,} pcs",
                                T["accent_green"] if total_actual == total_target else T["accent_amber"]),
                               ("Result:", diff_text,
                                T["accent_green"] if total_actual == total_target else T["accent_red"])]:
            l = QLabel(lbl); l.setStyleSheet(ls)
            v = QLabel(val); v.setStyleSheet(vs + f"color:{col};")
            info.addRow(l, v)
        lay.addLayout(info)
        # ── Incomplete boxes section (merged from separate popup) ──
        if incomplete_boxes:
            sep_ib = QFrame(); sep_ib.setFrameShape(QFrame.HLine)
            sep_ib.setStyleSheet(f"background:{T['border']};max-height:1px;")
            lay.addWidget(sep_ib)
            ib_title = QLabel("📦 Boxes รอวัตถุดิบจาก Lot ถัดไป:")
            ib_title.setStyleSheet(f"font-size:{F(11)}px;font-weight:bold;color:{T['accent_amber']};")
            lay.addWidget(ib_title)
            for b, binfo in sorted(incomplete_boxes.items()):
                need = max(0, max_per_box - binfo['packed'])
                line = QLabel(
                    f"  Box {b}:  Packed {binfo['packed']:,}  |  "
                    f"{binfo['wait_slots']} reel(s) waiting  |  Need ~{need:,}")
                line.setStyleSheet(f"font-size:{F(11)}px;color:{T['text_secondary']};")
                lay.addWidget(line)
        q = QLabel("Auto saving CSV and closing..."); q.setAlignment(Qt.AlignCenter)
        q.setStyleSheet(f"font-size:{F(12)}px;color:{T['accent_green']};font-weight:bold;")
        lay.addWidget(q)
        
        # Start timer to auto close
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.accept)
        self.auto_timer.start(2500)


class _MonitorReplanDialog(QDialog):
    """Re-plan dialog — handles flowchart cases."""

    def __init__(self, reject_sum, replan_case, details,
                 ask_user=False, parent=None):
        """
        replan_case:
          'retarget'       — pull reject from next reel (same/next box)
          'move_next_box'  — reel moves to next box + retarget
          'combined'       — reels merged into one ≤ max_reel
          'divided'        — split across 2 reels in next box
          'warning'        — insufficient input, next reel can't be packed
        details: dict with case-specific display info
        """
        super().__init__(parent)
        T = THEME
        is_warn = ask_user
        border = T["accent_red"] if is_warn else T["accent_amber"]
        title = "⚠ Reject High — Action Required" if is_warn else "⚡ Auto Re-plan"
        self.setWindowTitle(title)
        self.setFixedWidth(S(520))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(f"""
            QDialog {{ background: {T['bg_card']}; border: 2px solid {border};
                       border-radius: {S(10)}px; }}
            QLabel {{ color: {T['text_primary']}; background: transparent; }}
            QPushButton {{ min-height: {S(38)}px; min-width: {S(110)}px;
                           border-radius: {S(7)}px; font-size: {F(12)}px; font-weight: bold; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(20), S(16), S(20), S(16))
        lay.setSpacing(S(10))

        hr = QHBoxLayout()
        ico = QLabel("⚠" if is_warn else "⚡")
        ico.setStyleSheet(f"font-size:{F(24)}px;color:{border};")
        ttl = QLabel("Reject สูงมาก — กรุณาเลือก" if is_warn else "Auto Re-plan")
        ttl.setStyleSheet(f"font-size:{F(14)}px;font-weight:bold;color:{border};")
        hr.addWidget(ico); hr.addWidget(ttl); hr.addStretch()
        lay.addLayout(hr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{T['border']};max-height:1px;")
        lay.addWidget(sep)

        ls = f"font-size:{F(11)}px;color:{T['text_muted']};"
        vs = f"font-size:{F(12)}px;font-weight:bold;"
        def _mk(t, s):
            lb = QLabel(t); lb.setStyleSheet(s); return lb

        info = QFormLayout(); info.setSpacing(S(5)); info.setContentsMargins(S(8), 0, 0, 0)
        info.addRow(_mk("Reject สะสม:", ls), _mk(f"{reject_sum:,} pcs", vs + f"color:{T['accent_red']};"))
        lay.addLayout(info)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"background:{T['border']};max-height:1px;")
        lay.addWidget(sep2)

        plan_lbl = QLabel("แผน Re-plan:")
        plan_lbl.setStyleSheet(f"font-size:{F(11)}px;color:{T['text_muted']};font-weight:bold;")
        lay.addWidget(plan_lbl)

        d = details
        dl = QFormLayout(); dl.setSpacing(S(4)); dl.setContentsMargins(S(16), 0, 0, 0)

        if replan_case == "retarget":
            dl.addRow(_mk(f"Box {d['next_box']} R{d['next_reel']}:", ls),
                      _mk(f"{d['next_orig']:,} → {d['next_new']:,} ({d['next_new']-d['next_orig']:+,})",
                          vs + f"color:{T['accent_amber']};"))
            note = QLabel("✔ ดึง reject จาก reel ถัดไป — ทุก reel ≥ min")
            note.setStyleSheet(f"font-size:{F(12)}px;color:{T['accent_green']};")

        elif replan_case == "move_next_box":
            dl.addRow(_mk(f"R{d['curr_reel']}:", ls),
                      _mk(f"ย้ายไป Box {d['target_box']}",
                          vs + f"color:{T['accent']};"))
            dl.addRow(_mk(f"Box {d['next_box']} R{d['next_reel']}:", ls),
                      _mk(f"{d['next_orig']:,} → {d['next_new']:,} ({d['next_new']-d['next_orig']:+,})",
                          vs + f"color:{T['accent_amber']};"))
            note = QLabel("✔ ย้าย reel ไป box ถัดไป + retarget")
            note.setStyleSheet(f"font-size:{F(12)}px;color:{T['accent_green']};")

        elif replan_case == "combined":
            dl.addRow(_mk(f"Box {d['merged_box']} R{d['merged_reel']}:", ls),
                      _mk(f"รวม → {d['merged_target']:,}",
                          vs + f"color:{T['accent']};"))
            dl.addRow(_mk(f"Box {d['wait_box']} R{d['wait_reel']}:", ls),
                      _mk("→ Wait Slot (รอ lot ถัดไป)",
                          vs + f"color:{T['accent_amber']};"))
            note = QLabel("⚠ รวม reel เพื่อลด scrap — slot ว่างรอ lot ถัดไป")
            note.setStyleSheet(f"font-size:{F(12)}px;color:{T['accent_amber']};")

        elif replan_case == "divided":
            dl.addRow(_mk(f"Box {d['reel1_box']} R{d['reel1_reel']}:", ls),
                      _mk(f"{d['reel1_target']:,}",
                          vs + f"color:{T['accent']};"))
            dl.addRow(_mk(f"Box {d['reel2_box']} R{d['reel2_reel']}:", ls),
                      _mk(f"{d['reel2_target']:,}",
                          vs + f"color:{T['accent']};"))
            note = QLabel("⚠ แบ่ง 2 reel เพื่อลด scrap")
            note.setStyleSheet(f"font-size:{F(12)}px;color:{T['accent_amber']};")

        else:  # warning
            dl.addRow(_mk("สถานะ:", ls),
                      _mk("วัตถุดิบไม่เพียงพอสำหรับ reel ถัดไป",
                          vs + f"color:{T['accent_red']};"))
            if 'wait_reel' in d:
                dl.addRow(_mk(f"Box {d['wait_box']} R{d['wait_reel']}:", ls),
                          _mk("→ Wait Slot", vs + f"color:{T['accent_amber']};"))
            note = QLabel("⚠ reject สูงเกิน — reel ถัดไป pack ไม่ได้ → replan")
            note.setStyleSheet(f"font-size:{F(12)}px;color:{T['accent_red']};")

        lay.addLayout(dl)
        lay.addWidget(note)

        br = QHBoxLayout(); br.setSpacing(S(10)); br.addStretch()
        if is_warn and replan_case not in ("retarget",):
            replan_btn = QPushButton("⚡ Re-plan ทันที")
            replan_btn.setStyleSheet(f"QPushButton{{background:{T['accent_amber']};color:#FFFFFF;}}"
                                     f"QPushButton:hover{{background:#F59E0B;}}")
            replan_btn.clicked.connect(self.accept); replan_btn.setDefault(True)
            continue_btn = QPushButton("▶ Pack ต่อ")
            continue_btn.setStyleSheet(
                f"QPushButton{{background:{T['border']};color:{T['text_secondary']};"
                f"border:1px solid {T['border']};}}"
                f"QPushButton:hover{{background:{T['bg_tag_blue']};}}")
            continue_btn.clicked.connect(self.reject)
            br.addWidget(replan_btn); br.addWidget(continue_btn)
        else:
            ok = QPushButton("✔ รับทราบ")
            ok.setStyleSheet(f"QPushButton{{background:{border};color:#fff;}}"
                             f"QPushButton:hover{{background:{T['accent']};}}")
            ok.clicked.connect(self.accept); ok.setDefault(True)
            br.addWidget(ok)
        lay.addLayout(br)


# ══════════════════════════════════════════════════════════════
#  MONITOR PAGE
# ══════════════════════════════════════════════════════════════

class MonitorPage(QWidget):
    """
    Full inline monitor page with reel-by-reel actual entry.
    All logic from the original PackingMonitorDialog is preserved:
    re-plan triggers, adjusted targets, undo, box transitions,
    below-min scrap, deviation warnings, CSV export, real-time backup.
    """
    monitor_finished = pyqtSignal()

    _BOX_COLORS = ["#F0F7FF", "#FFFCF0", "#F0FFF4", "#FFF0F6", "#F0FDFF"]

    def __init__(self, config, app_state, logger, parent=None):
        super().__init__(parent)
        self._config = config
        self._state  = app_state
        self._logger = logger

        self.plan          = []
        self.actuals       = []
        self.current_idx   = 0
        self._orig_targets = []
        self._undo_stack   = []  # [L3] Stack for undo: (confirmed_idx, target_snapshot, affected_indices)
        self._replan_triggered    = False
        self._user_chose_continue = False
        self._replan_trigger_pct  = float(getattr(config, 'replan_trigger_pct', 0.70))
        self._replan_warn_pct     = float(getattr(config, 'replan_warn_pct', 0.85))
        self._order_info   = {}
        self._has_plan     = False

        # Web sync
        self._live_server      = None   # set via set_live_server()
        self._web_submit_mode  = False  # True → skip confirmation dialogs
        self._web_queue        = get_submit_queue()
        self._web_poll_timer   = QTimer(self)
        self._web_poll_timer.timeout.connect(self._poll_web_queue)
        self._web_poll_timer.start(100)

        self._build()

    def _build(self):
        T = THEME
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        hdr = SectionHeader("Packing Monitor", "บันทึกจำนวนจริงแต่ละ Reel")
        root.addWidget(hdr)

        # ── Top bar ──
        top = QFrame()
        top.setStyleSheet(f"background:{T['bg_card']};border-bottom:1px solid {T['border']};")
        top.setFixedHeight(S(48))
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(S(16), S(4), S(16), S(4)); top_lay.setSpacing(S(14))
        self._inv_lbl = QLabel("📦 Invoice: —")
        self._inv_lbl.setFont(QFont("Segoe UI", F(12), QFont.Bold))
        self._inv_lbl.setStyleSheet(f"color:{T['text_primary']};background:transparent;")
        top_lay.addWidget(self._inv_lbl)
        top_lay.addStretch()
        top_lay.addWidget(make_label("Operator:", size=10, color=T["text_muted"]))
        self._operator_edit = QLineEdit()
        self._operator_edit.setPlaceholderText("e.g. OP-01")
        self._operator_edit.setFixedWidth(S(120)); self._operator_edit.setFixedHeight(S(30))
        top_lay.addWidget(self._operator_edit)
        top_lay.addWidget(make_label("Shift:", size=10, color=T["text_muted"]))
        self._shift_combo = QComboBox()
        self._shift_combo.addItems(["Day", "Night"])
        self._shift_combo.setFixedWidth(S(80)); self._shift_combo.setFixedHeight(S(30))
        top_lay.addWidget(self._shift_combo)
        self._progress_lbl = QLabel("0 / 0 Reels")
        self._progress_lbl.setFont(QFont("Consolas", F(12), QFont.Bold))
        self._progress_lbl.setStyleSheet(f"color:{T['accent']};background:transparent;")
        top_lay.addWidget(self._progress_lbl)
        root.addWidget(top)

        # ── Middle ──
        mid = QHBoxLayout(); mid.setSpacing(0)

        # LEFT: current reel card + input
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True); left_scroll.setFrameShape(QFrame.NoFrame)
        left_w = QWidget(); left_scroll.setWidget(left_w)
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(S(16), S(12), S(8), S(12)); left_lay.setSpacing(S(10))

        # Active reel card
        reel_card = Card()
        rc_lay = QVBoxLayout(); reel_card.set_layout(rc_lay)
        rc_hdr = QHBoxLayout(); rc_hdr.setSpacing(S(10))
        self._reel_circle = QLabel("R—")
        self._reel_circle.setFixedSize(QSize(S(48), S(48)))
        self._reel_circle.setAlignment(Qt.AlignCenter)
        self._reel_circle.setFont(QFont("Segoe UI", F(16), QFont.Bold))
        self._reel_circle.setStyleSheet(f"""QLabel {{
            background: {T['bg_tag_blue']}; color: {T['accent']};
            border-radius: {S(24)}px; border: 2px solid {T['accent']};
        }}""")
        rc_hdr.addWidget(self._reel_circle)
        info_col = QVBoxLayout(); info_col.setSpacing(S(2))
        self._reel_title = make_label("No plan loaded", bold=True, size=14)
        self._reel_meta  = make_label("กรุณา Run Plan ในหน้า Planner ก่อน", size=10, color=T["text_muted"])
        info_col.addWidget(self._reel_title); info_col.addWidget(self._reel_meta)
        rc_hdr.addLayout(info_col); rc_hdr.addStretch()
        rc_lay.addLayout(rc_hdr)

        sep_t = QFrame(); sep_t.setFrameShape(QFrame.HLine)
        sep_t.setStyleSheet(f"background:{T['border']};max-height:1px;")
        rc_lay.addWidget(sep_t)
        self._target_lbl = QLabel("Target: —")
        self._target_lbl.setFont(QFont("Consolas", F(22), QFont.Bold))
        self._target_lbl.setStyleSheet(f"color:{T['accent_green']};background:transparent;")
        self._target_lbl.setAlignment(Qt.AlignCenter)
        rc_lay.addWidget(self._target_lbl)

        self._box_prog_lbl = QLabel("")
        self._box_prog_lbl.setFont(QFont("Segoe UI", F(11), QFont.Bold))
        self._box_prog_lbl.setAlignment(Qt.AlignCenter)
        self._box_prog_lbl.setMinimumHeight(S(28))
        self._box_prog_lbl.setStyleSheet(
            f"background:{T['bg_tag_blue']};border:1px solid {T['border_accent']};"
            f"border-radius:{S(6)}px;padding:{S(4)}px;color:{T['accent']};")
        rc_lay.addWidget(self._box_prog_lbl)
        left_lay.addWidget(reel_card)

        # Actual input card
        input_card = Card()
        ig_lay = QVBoxLayout(); input_card.set_layout(ig_lay)
        ig_lay.setSpacing(S(8))
        ig_lay.addWidget(make_label("✏ Enter Actual Qty", bold=True, size=12, color=T["text_secondary"]))

        self._actual_spin = QSpinBox()
        self._actual_spin.setRange(0, 9_999_999)
        self._actual_spin.setSuffix(" pcs.")
        self._actual_spin.setLocale(QLocale(QLocale.C))
        self._actual_spin.setFont(QFont("Consolas", F(18), QFont.Bold))
        self._actual_spin.setMinimumHeight(S(50))
        self._actual_spin.setAlignment(Qt.AlignCenter)
        self._actual_spin.setStyleSheet(f"""QSpinBox {{
            font-size:{F(18)}px; padding:{S(6)}px;
            border: 2px solid {T['accent']}; border-radius:{S(8)}px;
            background: {T['bg_input']};
        }} QSpinBox:focus {{ border: 2px solid {T['accent_green']}; }}""")
        ig_lay.addWidget(self._actual_spin)

        rej_row = QHBoxLayout(); rej_row.setSpacing(S(8))
        rej_row.addWidget(make_label("Reject:", size=11, color=T["text_secondary"]))
        self._reject_spin = QSpinBox()
        self._reject_spin.setRange(0, 9_999_999); self._reject_spin.setValue(0)
        self._reject_spin.setSuffix(" pcs.")
        self._reject_spin.setLocale(QLocale(QLocale.C))
        self._reject_spin.setFont(QFont("Consolas", F(13), QFont.Bold))
        self._reject_spin.setMinimumHeight(S(36))
        self._reject_spin.setAlignment(Qt.AlignCenter)
        self._reject_spin.setStyleSheet(f"""QSpinBox {{
            font-size:{F(13)}px; padding:{S(4)}px;
            border: 2px solid {T['accent_red']}; border-radius:{S(6)}px;
        }} QSpinBox:focus {{ border: 2px solid {T['accent_amber']}; }}""")
        rej_row.addWidget(self._reject_spin)
        ig_lay.addLayout(rej_row)

        self._diff_preview = QLabel("")
        self._diff_preview.setFont(QFont("Consolas", F(12)))
        self._diff_preview.setAlignment(Qt.AlignCenter)
        self._diff_preview.setStyleSheet(f"background:transparent;color:{T['text_secondary']};")
        self._diff_preview.setTextFormat(Qt.RichText)
        self._actual_spin.valueChanged.connect(self._update_diff_preview)
        self._reject_spin.valueChanged.connect(self._update_diff_preview)
        ig_lay.addWidget(self._diff_preview)

        note_row = QHBoxLayout()
        note_row.addWidget(make_label("Note:", size=10, color=T["text_muted"]))
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("Optional note")
        self._note_edit.setFixedHeight(S(30))
        note_row.addWidget(self._note_edit)
        ig_lay.addLayout(note_row)

        self._confirm_btn = make_btn("✔  Confirm Reel", "success")
        self._confirm_btn.setMinimumHeight(S(44))
        self._confirm_btn.setFont(QFont("Segoe UI", F(13), QFont.Bold))
        self._confirm_btn.clicked.connect(self._confirm_reel)
        self._confirm_btn.setEnabled(False)
        ig_lay.addWidget(self._confirm_btn)

        self._undo_btn = make_btn("↩ Undo Last", "ghost")
        self._undo_btn.setMinimumHeight(S(32))
        self._undo_btn.clicked.connect(self._undo_last)
        self._undo_btn.setEnabled(False)
        ig_lay.addWidget(self._undo_btn)

        # Enter key moves focus from spinbox → confirm button (2nd Enter clicks it)
        self._actual_spin.editingFinished.connect(self._on_actual_editing_done)

        left_lay.addWidget(input_card)
        left_lay.addStretch()
        mid.addWidget(left_scroll, 4)

        # RIGHT: progress table
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(S(8), S(12), S(16), S(4)); right_lay.setSpacing(S(6))
        right_lay.addWidget(make_label("📊 Packing Progress", bold=True, size=12, color=T["text_secondary"]))

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["Box", "Reel", "Lot", "Target", "Actual", "Reject", "Diff", "Status"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        right_lay.addWidget(self._table, 1)

        # Box summary cards area
        self._box_card_area = QWidget()
        self._box_card_layout = QGridLayout(self._box_card_area)
        self._box_card_layout.setContentsMargins(0, S(4), 0, 0)
        self._box_card_layout.setSpacing(S(6))
        right_lay.addWidget(self._box_card_area)
        self._box_cards = {}
        mid.addWidget(right_w, 6)
        root.addLayout(mid, 1)

        # ── Bottom bar ──
        bot = QFrame()
        bot.setFixedHeight(S(48))
        bot.setStyleSheet(f"background:{T['bg_card']};border-top:1px solid {T['border']};")
        bot_lay = QHBoxLayout(bot)
        bot_lay.setContentsMargins(S(16), S(4), S(16), S(4)); bot_lay.setSpacing(S(16))
        self._sum_target = QLabel("Target: —")
        self._sum_target.setFont(QFont("Consolas", F(11), QFont.Bold))
        self._sum_target.setStyleSheet(f"color:{T['accent_green']};background:transparent;")
        self._sum_actual = QLabel("Actual: —")
        self._sum_actual.setFont(QFont("Consolas", F(11), QFont.Bold))
        self._sum_actual.setStyleSheet(f"color:{T['accent']};background:transparent;")
        self._sum_reject = QLabel("Reject: 0")
        self._sum_reject.setFont(QFont("Consolas", F(11), QFont.Bold))
        self._sum_reject.setStyleSheet(f"color:{T['text_muted']};background:transparent;")
        self._sum_diff = QLabel("Diff: —")
        self._sum_diff.setFont(QFont("Consolas", F(11), QFont.Bold))
        self._sum_diff.setStyleSheet(f"color:{T['text_muted']};background:transparent;")
        for w in [self._sum_target, self._sum_actual, self._sum_reject, self._sum_diff]:
            bot_lay.addWidget(w)
        bot_lay.addStretch()
        self._lan_btn = make_btn("🌐 LAN URL", "flat")
        self._lan_btn.setFixedHeight(S(40))
        self._lan_btn.setToolTip("แสดง URL / QR Code สำหรับเชื่อมต่อจาก Phone / PC อื่นใน LAN")
        self._lan_btn.clicked.connect(self._show_lan_info)
        bot_lay.addWidget(self._lan_btn)
        self._export_btn = make_btn("📥 Export CSV", "flat")
        self._export_btn.setFixedHeight(S(40))
        self._export_btn.clicked.connect(self._export_csv)
        bot_lay.addWidget(self._export_btn)
        self._finish_btn = make_btn("✔ Finish", "success")
        self._finish_btn.setFixedHeight(S(40))
        self._finish_btn.setStyleSheet(f"""
            QPushButton {{ background:{T['accent_green']};color:#fff;
                border:none;border-radius:{S(7)}px;padding:{S(8)}px {S(18)}px;
                font-size:{F(13)}px;font-weight:600;min-height:{S(38)}px; }}
            QPushButton:hover {{ background:#15803D; }}
            QPushButton:disabled {{ background:{T['border']};color:{T['text_muted']}; }}
        """)
        self._finish_btn.clicked.connect(self._finish)
        self._finish_btn.setEnabled(False)
        bot_lay.addWidget(self._finish_btn)
        root.addWidget(bot)

    # ─── Set plan ────────────────────────────────────────────

    def set_plan(self, plan, order_info):
        self.plan        = plan
        self._order_info = order_info
        self.actuals     = [None] * len(plan)
        self.current_idx = 0
        self._orig_targets = [r["target"] for r in plan]
        self._undo_stack = []  # [L3] Clear undo stack when loading new plan
        self._replan_triggered    = False
        self._user_chose_continue = False
        self._has_plan   = True

        inv = order_info.get("invoice", "")
        self._inv_lbl.setText(f"📦 Invoice: <b>{inv}</b>")
        self._confirm_btn.setEnabled(True)
        self._finish_btn.setEnabled(False)
        self._undo_btn.setEnabled(False)
        self._populate_table()
        self._highlight_current()
        self._broadcast_web_state()

    # ─── Table population ────────────────────────────────────

    def _populate_table(self):
        T = THEME
        # Count rows: plan rows + separator rows between boxes
        box_list = [row["box"] for row in self.plan]
        sep_count = sum(1 for i in range(1, len(box_list)) if box_list[i] != box_list[i-1])
        self._table.setRowCount(len(self.plan) + sep_count)
        row_h = S(32)
        tbl_row = 0
        prev_box = None
        self._row_map = {}
        for r, row in enumerate(self.plan):
            # Box separator
            if prev_box is not None and row["box"] != prev_box:
                self._table.setRowHeight(tbl_row, S(6))
                for _j in range(8):
                    _sep = QTableWidgetItem("")
                    _sep.setBackground(QColor(T["divider"]))
                    _sep.setFlags(Qt.NoItemFlags)
                    self._table.setItem(tbl_row, _j, _sep)
                tbl_row += 1
            prev_box = row["box"]
            self._row_map[r] = tbl_row

            bg = QColor(self._BOX_COLORS[(max(row["box"], 1) - 1) % len(self._BOX_COLORS)])
            is_wait = (row.get("note") == "Wait next lot")
            is_remainder = (row.get("box", 0) == 0)
            box_label = "📋 Remainder" if is_remainder else f"Box {row['box']}"
            box_color = "#9333EA" if is_remainder else T["accent"]
            if is_remainder:
                bg = QColor("#FAF5FF")
            self._table.setItem(tbl_row, 0, self._cell(box_label, box_color, bold=True, bg=bg))
            
            if is_wait:
                for c, txt in [(1, f"Reel {row['reel']}"), (2, "—"), (3, "—"),
                                (4, "—"), (5, "—"), (6, "—")]:
                    self._table.setItem(tbl_row, c, self._cell(txt, T["text_muted"], bg=bg))
                self._table.setItem(tbl_row, 7, self._cell("⏳ Wait", T["accent_amber"], bold=True, bg=bg))
            else:
                self._table.setItem(tbl_row, 1, self._cell(f"Reel {row['reel']}", T["accent2"], bg=bg))
                self._table.setItem(tbl_row, 2, self._cell(row["lot"], T["accent"], bold=True, bg=bg))
                self._table.setItem(tbl_row, 3, self._cell(f"{row['target']:,}", T["accent_green"], bg=bg))
                
                # --- [FIX] ดึงข้อมูล Actual กลับมาแสดงผลบนตารางแทนการปล่อยว่าง ---
                act = self.actuals[r]
                if act is not None:
                    actual = act.get("actual", 0)
                    reject = act.get("reject", 0)
                    diff = act.get("diff", 0)
                    
                    self._table.setItem(tbl_row, 4, self._cell(f"{actual:,}", T["accent"], bold=True, bg=bg))
                    
                    if reject > 0:
                        self._table.setItem(tbl_row, 5, self._cell(f"{reject:,}", T["accent_red"], bold=True, bg=bg))
                    else:
                        self._table.setItem(tbl_row, 5, self._cell("0", T["text_muted"], bg=bg))
                        
                    if diff == 0:
                        dt, dc = "0", T["accent_green"]
                    elif diff > 0:
                        dt, dc = f"+{diff:,}", T["accent_amber"]
                    else:
                        dt, dc = f"{diff:,}", T["accent_red"]
                    self._table.setItem(tbl_row, 6, self._cell(dt, dc, bold=True, bg=bg))
                    
                    if diff == 0 or abs(diff) <= row["target"] * 0.05:
                        st, sc = "✔ OK", T["accent_green"]
                    elif abs(diff) <= row["target"] * 0.10:
                        st, sc = "⚠ Warn", T["accent_amber"]
                    else:
                        st, sc = "✕ Dev", T["accent_red"]

                    self._table.setItem(tbl_row, 7, self._cell(st, sc, bold=True, bg=bg))
                else:
                    self._table.setItem(tbl_row, 4, self._cell("—", T["text_muted"], bg=bg))
                    self._table.setItem(tbl_row, 5, self._cell("—", T["text_muted"], bg=bg))
                    self._table.setItem(tbl_row, 6, self._cell("—", T["text_muted"], bg=bg))
                    
                    if r == self.current_idx:
                        self._table.setItem(tbl_row, 7, self._cell("▶ Active", T["accent_amber"], bold=True, bg=bg))
                    else:
                        self._table.setItem(tbl_row, 7, self._cell("⏳ Pending", T["text_muted"], bg=bg))
                        
            self._table.setRowHeight(tbl_row, row_h)
            tbl_row += 1

    def _trow(self, plan_idx):
        """Map plan index to actual table row (accounting for separator rows)."""
        return self._row_map.get(plan_idx, plan_idx)

    def _cell(self, text, color, bold=False, bg=None):
        item = QTableWidgetItem(str(text))
        item.setForeground(QColor(color))
        if bold:
            fnt = item.font(); fnt.setBold(True); item.setFont(fnt)
        if bg:
            item.setBackground(bg)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    # ─── Highlight current reel ──────────────────────────────

    def _highlight_current(self):
        T = THEME
        while (self.current_idx < len(self.plan) and
               self.plan[self.current_idx].get("note") == "Wait next lot"):
            self.current_idx += 1

        if self.current_idx >= len(self.plan):
            self._reel_title.setText("✅ ALL REELS COMPLETE")
            self._reel_meta.setText("")
            self._target_lbl.setText("")
            self._box_prog_lbl.setVisible(False)
            self._actual_spin.setEnabled(False)
            self._confirm_btn.setEnabled(False)
            self._note_edit.setEnabled(False)
            self._finish_btn.setEnabled(True)
            self._update_summary()
            self._broadcast_web_state()
            return

        row = self.plan[self.current_idx]
        is_remainder = (row.get("box", 0) == 0)
        box_label = "Remainder" if is_remainder else f"Box {row['box']}"
        self._reel_circle.setText(f"R{row['reel']}")
        self._reel_title.setText(f"{box_label} · Reel {row['reel']}")
        self._reel_meta.setText(f"Lot: {row['lot']}")
        adj_target = self._get_adjusted_target(self.current_idx)
        if adj_target < self._orig_targets[self.current_idx]:
            self._target_lbl.setText(f"Target: {adj_target:,}")
            self._target_lbl.setStyleSheet(f"color:{T['accent_amber']};background:transparent;")
        else:
            self._target_lbl.setText(f"Target: {adj_target:,}")
            self._target_lbl.setStyleSheet(f"color:{T['accent_green']};background:transparent;")

        box_no = row["box"]
        reels_in_box = [i for i, r in enumerate(self.plan)
                        if r["box"] == box_no and r.get("note") != "Wait next lot"]
        done_in_box = sum(1 for i in reels_in_box if self.actuals[i] is not None)
        total_in_box = len(reels_in_box)
        wait_in_box = sum(1 for r in self.plan
                          if r["box"] == box_no and r.get("note") == "Wait next lot")
        wait_txt = f" + {wait_in_box} wait" if wait_in_box > 0 else ""
        if box_no == 0:
            self._box_prog_lbl.setText(f"📋 Remainder: Reel {done_in_box + 1} / {total_in_box}")
        else:
            self._box_prog_lbl.setText(f"📦 Box {box_no}: Reel {done_in_box + 1} / {total_in_box}{wait_txt}")
        self._box_prog_lbl.setVisible(True)

        self._actual_spin.setEnabled(True)
        self._actual_spin.setValue(adj_target)
        self._reject_spin.setValue(0)
        self._note_edit.clear()

        self._table.selectRow(self._trow(self.current_idx))
        self._table.scrollTo(self._table.model().index(self._trow(self.current_idx), 0))

        bg = self._table.item(self._trow(self.current_idx), 0).background()
        self._table.setItem(self._trow(self.current_idx), 7,
                            self._cell("▶ Active", T["accent_amber"], bold=True, bg=bg.color()))
        self._update_diff_preview()
        self._update_summary()
        QTimer.singleShot(100, lambda: (
            self._actual_spin.setFocus(),
            self._actual_spin.selectAll()))

    # ─── Adjusted target ────────────────────────────────────

    def _get_adjusted_target(self, idx):
        row = self.plan[idx]
        lot = row.get("lot", "")
        orig = self._orig_targets[idx]
        if not lot or row.get("note") in ("Wait next lot", "Carry"):
            return orig
        lot_total = sum(
            self._orig_targets[i] for i, r in enumerate(self.plan)
            if r.get("lot") == lot
            and r.get("note") not in ("Wait next lot", "Carry"))
        consumed = 0
        for i, r in enumerate(self.plan):
            if (r.get("lot") == lot
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and self.actuals[i] is not None):
                consumed += self.actuals[i].get("actual", 0)
        remaining = lot_total - consumed
        future_target = sum(
            self._orig_targets[i] for i, r in enumerate(self.plan)
            if i > idx
            and r.get("lot") == lot
            and r.get("note") not in ("Wait next lot", "Carry")
            and self.actuals[i] is None)
        max_packable = remaining - future_target
        return min(orig, max(0, max_packable))

    def _refresh_future_targets(self):
        """Refresh the 'Target' column in the UI to show *adjusted* targets.

        [FIX-16] NOTE: This function is UI-preview only — it does NOT persist
        adjusted values back to plan[i]["target"] or _orig_targets.
        
        The actual persistence happens in _confirm_reel when the user confirms
        each reel (see [FIX-10]). Keeping them separate allows the user to see
        the effect of lot-budget capping (_get_adjusted_target) without
        mutating canonical state prematurely.

        If future refactor wants to persist here, ensure BOTH:
          - self.plan[i]["target"] = adj
          - self._orig_targets[i] = adj
        are updated together to avoid STATE-DESYNC (see _check_reject_replan).
        """
        T = THEME
        for i, r in enumerate(self.plan):
            if (self.actuals[i] is None
                    and r.get("note") not in ("Wait next lot", "Carry")):
                adj = self._get_adjusted_target(i)
                bg = self._table.item(self._trow(i), 0).background().color()
                col = T["accent_green"] if adj == self._orig_targets[i] else T["accent_amber"]
                self._table.setItem(self._trow(i), 3, self._cell(f"{adj:,}", col, bg=bg))

    # ─── Diff preview ───────────────────────────────────────

    def _update_diff_preview(self):
        T = THEME
        if not self._has_plan or self.current_idx >= len(self.plan):
            self._diff_preview.setText(""); return
        target = self._get_adjusted_target(self.current_idx)
        actual = self._actual_spin.value()
        reject = self._reject_spin.value()
        diff = actual - target
        
        # Check for overflow (actual + reject > target)
        total_pieces = actual + reject
        if total_pieces > target:
            overflow = total_pieces - target
            self._diff_preview.setText(
                f"<span style='color:{T['accent_red']};font-weight:bold;'>"
                f"⛔ OVERFLOW: +{overflow:,} pcs exceeds input</span>"
            )
        elif diff == 0:
            self._diff_preview.setText(f"<span style='color:{T['accent_green']}'>✔ Exact match</span>")
        elif diff > 0:
            self._diff_preview.setText(f"<span style='color:{T['accent_amber']}'>▲ Over by {diff:,}</span>")
        else:
            self._diff_preview.setText(f"<span style='color:{T['accent_red']}'>▼ Under by {abs(diff):,}</span>")

    # ─── Confirm reel ────────────────────────────────────────

    def _confirm_reel(self):
        if self.current_idx >= len(self.plan):
            return
        T = THEME
        actual = self._actual_spin.value()
        adjusted = self._get_adjusted_target(self.current_idx)
        self.plan[self.current_idx]["target"] = adjusted
        # [FIX-10] sync _orig_targets พร้อมกัน ป้องกัน STATE-DESYNC
        # ที่จะถูก force reset ใน _check_reject_replan (บรรทัด ~1119)
        self._orig_targets[self.current_idx] = adjusted
        target = adjusted
        diff = actual - target
        reject = self._reject_spin.value()
        note = self._note_edit.text().strip()

        # Check for overflow (actual + reject > target) FIRST
        total_pieces = actual + reject
        if total_pieces > target and not self._web_submit_mode:
            overflow = total_pieces - target
            dlg = _MonitorOverflowDialog(actual, reject, target, parent=self)
            if dlg.exec_() != QDialog.Accepted:
                return

        if target > 0 and abs(diff) > target * 0.10 and not self._web_submit_mode:
            pct = abs(diff) / target * 100
            dlg = _MonitorDeviationDialog(actual, target, diff, pct, parent=self)
            if dlg.exec_() != QDialog.Accepted:
                return

        # [FIX-BUG-C] Accumulate reject ถ้า reel นี้เคยถูก confirm แล้ว (retarget flow)
        # เดิม: self.actuals[idx] = {...} → เซ็ตทับ reject ก่อนหน้าทั้งหมด
        # ปัญหา: retarget ครั้งที่ 2 บน reel เดียวกัน reject ค่าเก่าหายไป
        # ผลคือ Total Reject ใน CSV < ค่าจริง
        _prev = self.actuals[self.current_idx]
        _accum_reject = reject + (_prev.get("reject", 0) if _prev else 0)
        # [FIX-BUG-C2] preserve _reject_processed ข้าม confirm (ใช้ใน _check_reject_replan)
        _processed = _prev.get("_reject_processed", 0) if _prev else 0
        self.actuals[self.current_idx] = {
            "actual": actual, "reject": _accum_reject, "diff": diff,
            "note": note, "time": datetime.now().replace(microsecond=0).isoformat(" "),
            "_reject_processed": _processed,
        }
        # Display the accumulated reject (not just this session's input)
        reject = _accum_reject

        bg = self._table.item(self._trow(self.current_idx), 0).background().color()
        self._table.setItem(self._trow(self.current_idx), 4,
                            self._cell(f"{actual:,}", T["accent"], bold=True, bg=bg))
        if reject > 0:
            self._table.setItem(self._trow(self.current_idx), 5,
                                self._cell(f"{reject:,}", T["accent_red"], bold=True, bg=bg))
        else:
            self._table.setItem(self._trow(self.current_idx), 5,
                                self._cell("0", T["text_muted"], bg=bg))
        if diff == 0:
            dt, dc = "0", T["accent_green"]
        elif diff > 0:
            dt, dc = f"+{diff:,}", T["accent_amber"]
        else:
            dt, dc = f"{diff:,}", T["accent_red"]
        self._table.setItem(self._trow(self.current_idx), 6,
                            self._cell(dt, dc, bold=True, bg=bg))
        if diff == 0 or abs(diff) <= target * 0.05:
            st, sc = "✔ OK", T["accent_green"]
        elif abs(diff) <= target * 0.10:
            st, sc = "⚠ Warn", T["accent_amber"]
        else:
            st, sc = "✕ Dev", T["accent_red"]
        self._table.setItem(self._trow(self.current_idx), 7,
                            self._cell(st, sc, bold=True, bg=bg))

        prev_box = self.plan[self.current_idx]["box"]
        self.current_idx += 1
        self._undo_btn.setEnabled(True)

        peek = self.current_idx
        while peek < len(self.plan) and self.plan[peek].get("note") == "Wait next lot":
            peek += 1
        if peek < len(self.plan) and self.plan[peek]["box"] != prev_box:
            self._show_box_complete(prev_box, self.plan[peek]["box"])

        self._refresh_future_targets()
        
        # [L3] Capture targets before replan to track affected indices
        targets_before = list(self._orig_targets)
        
        self._check_reject_replan()
        
        # [L3] Find affected indices and push to undo stack
        affected = [i for i, (before, after) in enumerate(zip(targets_before, self._orig_targets)) if before != after]
        undo_entry = {
            "confirmed_idx": self.current_idx - 1,
            "target_snapshot": targets_before,
            "affected_indices": affected
        }
        self._undo_stack.append(undo_entry)
        
        self._check_below_min_after_confirm(self.current_idx - 1)
        self._highlight_current()
        self._backup_txt()

        # [FIX-BUG-F] Fallback เมื่อ reel# ยังเป็น 0 (plan พึ่งสร้าง/monitor log ไม่ sync)
        # เดิม: log โชว์ R0 แทนเลข reel จริง ทำให้ traceability สับสน
        _confirmed_row = self.plan[self.current_idx - 1]
        _log_reel = _confirmed_row.get("reel", 0)
        if not _log_reel:
            _log_reel = self.current_idx  # fallback: 1-based index
        self._logger.info(
            f"Reel confirmed: Box {_confirmed_row.get('box')} "
            f"R{_log_reel} "
            f"target={target} actual={actual} diff={diff:+d}")
        self._broadcast_web_state()

        # Audio feedback — beep tone varies by deviation level
        if target > 0:
            dev = abs(diff) / target
            if diff == 0:
                _beep(1200, 100)          # perfect
            elif dev <= 0.05:
                _beep(1000, 120)          # within 5% — OK
            elif dev <= 0.10:
                _beep(700,  220)          # 5–10% — warn
            else:
                _beep(400,  350)          # >10% — large deviation

        # Return focus to actual spinbox so operator can type the next value
        self._actual_spin.setFocus()
        self._actual_spin.selectAll()

    # ─── Box transition ──────────────────────────────────────

    def _show_box_complete(self, prev_box, next_box):
        pass  # removed popup — box transition is visible in table

    def _on_actual_editing_done(self):
        """Enter pressed in actual spinbox → move focus to Confirm button.
        Second Enter press clicks the button (standard Qt button behaviour)."""
        if self._confirm_btn.isEnabled():
            self._confirm_btn.setFocus()

    # ─── Reel4 viability check ───────────────────────────────
    # (removed — superseded by _check_reject_replan)

    # ─── Reject Re-plan (flowchart) ──────────────────────────

    def _find_next_reel_same_box(self, confirmed_idx):
        """Find the next unconfirmed reel in the SAME box & SAME lot."""
        row = self.plan[confirmed_idx]
        box, lot = row["box"], row.get("lot", "")
        for i, r in enumerate(self.plan):
            if (i > confirmed_idx
                    and r["box"] == box
                    and r.get("lot") == lot
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and self.actuals[i] is None):
                return i
        return None

    def _find_next_reel_next_box(self, confirmed_idx):
        """Find the next unconfirmed reel in the NEXT box, SAME lot."""
        row = self.plan[confirmed_idx]
        box, lot = row["box"], row.get("lot", "")
        for i, r in enumerate(self.plan):
            if (r.get("lot") == lot
                    and r["box"] != box
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and self.actuals[i] is None):
                return i
        return None

    def _is_last_reel_in_box(self, idx):
        """True if idx is the last packable reel in its box."""
        box = self.plan[idx]["box"]
        for i, r in enumerate(self.plan):
            if (i > idx and r["box"] == box
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and self.actuals[i] is None):
                return False
        return True

    # ─── Helper: Box fill analysis ───────────────────────────

    def _get_box_planned_total(self, box_id):
        """Sum actuals (confirmed) + pending targets (unconfirmed) for a box."""
        total = 0
        for i, r in enumerate(self.plan):
            if r["box"] != box_id:
                continue
            if r.get("note") in ("Wait next lot", "Carry"):
                continue
            if self.actuals[i] is not None:
                total += self.actuals[i].get("actual", 0)
            else:
                total += r["target"]
        return total

    def _get_wait_slots_in_box(self, box_id):
        """Count number of wait slots (unconfirmed reels with 'Wait next lot' note) in a box."""
        count = 0
        for r in self.plan:
            if r["box"] == box_id and r.get("note") == "Wait next lot":
                count += 1
        return count

    def _is_box_fillable(self, box_id):
        """
        Check if box can still be filled to capacity.
        Returns True if deficit ∈ [slots×min_reel, slots×max_reel].
        """
        max_box = int(getattr(self._config, 'max_per_box', 6400))
        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))

        planned_total = self._get_box_planned_total(box_id)
        deficit = max_box - planned_total
        wait_slots = self._get_wait_slots_in_box(box_id)

        if wait_slots == 0:
            return deficit <= 0  # No wait slots available, can't fill further

        min_needed = wait_slots * min_reel
        max_possible = wait_slots * max_reel

        return min_needed <= deficit <= max_possible

    def _check_reject_replan(self):
        """
        Reject handling — ตาม Repack.png flowchart ทุก node

        Flowchart summary:
          Actual=Target? → Reject=0? → Pack next
          → Check last reel in box?
            [NOT last] → next reel (same box, same lot) > min+reject?
                           Yes → Extract/Retarget next reel
                                 → Check next box reel > min+reject?
                                     Yes → Extract/Retarget → Pack next plan
                                     No  → Move this reel to next box
                           No  → (warning) replan → combined or divided
            [Last]     → next reel (next box, same lot) > min+reject?
                           Yes → Extract/Retarget → Pack next plan
                           No  → (warning) replan → combined or divided
        """
        if self.current_idx <= 0:
            return
        confirmed_idx = self.current_idx - 1
        row = self.plan[confirmed_idx]
        if row.get("note") in ("Wait next lot", "Carry"):
            return

        act = self.actuals[confirmed_idx]
        if act is None:
            return
        reject = act.get("reject", 0)
        if reject == 0:
            return  # Reject=0 → Pack next plan (no replan needed)

        # [FIX-BUG-C2] reject_sum ต้องเป็น "delta ใหม่" เท่านั้น
        # (ไม่ใช่ accumulated total) เพื่อคำนวณ retarget delta ให้ถูก
        # act["reject"] = accumulated (จาก FIX-BUG-C)
        # act["_reject_processed"] = ส่วนที่ retarget ประมวลผลแล้ว
        # → delta = accumulated - processed
        _processed = act.get("_reject_processed", 0)
        _delta = reject - _processed
        if _delta <= 0:
            return  # ประมวลผลแล้ว (ป้องกันเรียกซ้ำหลัง undo)

        current_lot = row.get("lot", "")
        if not current_lot:
            return

        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))
        reject_sum = _delta  # ใช้ delta สำหรับ retarget calc

        is_last = self._is_last_reel_in_box(confirmed_idx)

        # ⚠️ CRITICAL: State synchronization check before processing
        # [FIX-15] เปลี่ยนจาก force-sync เป็น warning-only
        # หลัง [FIX-10] (sync _orig_targets ใน _confirm_reel) ถ้ายังเจอ desync
        # แสดงว่ามี callsite อื่นที่ write plan["target"] โดยไม่ sync → ต้อง audit
        # การ force reset เดิมจะปกปิด bug ทำให้ดีบักยาก
        for i, (p, orig) in enumerate(zip(self.plan, self._orig_targets)):
            if p.get("note") in ("Wait next lot", "Carry"):
                continue  # Skip special rows
            
            if p["target"] > orig:
                # ⚠️ WARNING: plan ahead of orig (อาจมี callsite ที่ไม่ sync _orig_targets)
                self._logger.error(
                    f"[STATE-DESYNC] idx={i}: plan['target']={p['target']} > "
                    f"_orig_targets={orig} (Box {p['box']}, Reel {p['reel']}) "
                    f"— audit callsite ที่เขียน plan['target'] โดยไม่ sync _orig_targets"
                )
                # [FIX-15] ไม่ force reset แล้ว — ให้ desync แสดงออกมาเพื่อดีบัก
                # หากต้องการ emergency reset กลับมาได้โดย uncomment บรรทัดล่าง:
                # p["target"] = orig

        def _can_absorb(idx):
            """
            Check if a reel can absorb rejection by being retargeted down.
            
            Rules:
            1. new_target >= min_per_reel (reel minimum)
            2. After retarget, box must maintain fillability
               (wait slots' deficit must be in [min*slots, max*slots])
            3. Box total must not exceed max_per_box
            """
            r = self.plan[idx]
            new_target = r["target"] - reject_sum
            
            _min = int(getattr(self._config, 'min_per_reel', 1500))
            _max = int(getattr(self._config, 'max_per_reel', 3100))
            _box_cap = int(getattr(self._config, 'max_per_box', 6400))
            
            # Rule 1: Reel minimum
            if new_target < _min:
                return False
            
            # Rule 2 & 3: Box fillability after retarget
            box_id = r["box"]
            box_reels_indices = [
                i for i, pr in enumerate(self.plan)
                if pr["box"] == box_id and pr.get("note") != "Wait next lot"
            ]
            
            if not box_reels_indices:
                return True  # Empty box (shouldn't happen)
            
            # Simulate retarget and recalculate box total
            simulated_box_total = 0
            for i in box_reels_indices:
                if i == idx:
                    simulated_box_total += new_target
                else:
                    simulated_box_total += self.plan[i]["target"]
            
            if simulated_box_total > _box_cap:
                return False  # ❌ Box would overflow
            
            # Check fillability of any wait slots
            wait_slots = sum(
                1 for pr in self.plan
                if pr["box"] == box_id and pr.get("note") == "Wait next lot"
            )
            
            if wait_slots > 0:
                deficit = _box_cap - simulated_box_total
                min_fillable = wait_slots * _min
                max_fillable = wait_slots * _max
                
                if not (min_fillable <= deficit <= max_fillable):
                    return False  # ❌ Wait slots can't be filled by future lots
            
            # ✅ All checks passed
            return True

        def _retarget(idx):
            """Extract reject from reel → Retarget"""
            new_t = self._orig_targets[idx] - reject_sum
            self.plan[idx]["target"]    = new_t
            self._orig_targets[idx]     = new_t
            self._refresh_future_targets()
            # [FIX-BUG-C2] Mark ว่า reject delta นี้ถูกประมวลผลแล้ว
            # ป้องกัน double-subtract เมื่อ user confirm reel เดิมซ้ำ
            _a = self.actuals[confirmed_idx]
            if _a is not None:
                _a["_reject_processed"] = _a.get("reject", 0)
            self._logger.info(
                f"[retarget] idx={idx} Box={self.plan[idx]['box']} "
                f"Reel={self.plan[idx].get('reel',0)} "
                f"→ {new_t:,} (reject={reject_sum})"
            )

        # ════════════════════════════════════════════════════════
        #  PATH A — NOT last reel in box
        # ════════════════════════════════════════════════════════
        if not is_last:
            same_idx = self._find_next_reel_same_box(confirmed_idx)

            if same_idx is not None:
                # 1. ลองดึงยอด Reject จากกล่องถัดไปก่อน เพื่อรักษายอดกล่องปัจจุบันให้เต็ม Max เสมอ
                next_box_idx = self._find_next_reel_next_box(confirmed_idx)
                if next_box_idx is not None and _can_absorb(next_box_idx):
                    _retarget(next_box_idx)
                    return
                
                # 2. ถ้ากล่องถัดไปรับไม่ได้ หรือไม่มี ค่อยดึงจาก Reel ถัดไปในกล่องเดียวกัน
                if _can_absorb(same_idx):
                    _retarget(same_idx)
                    return

            # 3. ถ้ารับไม่ได้ทั้งคู่ → เข้าสู่กระบวนการหา Remainder / Replan
            # [L1] Add _try_absorb_reject_via_remainder shortcut to PATH A
            if self._try_absorb_reject_via_remainder(confirmed_idx, reject_sum):
                return
            if self._try_use_remainder(confirmed_idx, reject_sum):
                return
            self._do_replan_bottom(confirmed_idx, reject_sum)
            return

        # ════════════════════════════════════════════════════════
        #  PATH B — Last reel in box
        # ════════════════════════════════════════════════════════
        # หา next reel ใน next box (same lot) ที่ผ่าน smart-borrow check
        # ขั้น 1: [NEW] Remainder absorb reject ก่อน → ไม่กระทบ box ใดเลย
        if self._try_absorb_reject_via_remainder(confirmed_idx, reject_sum):
            return
        chosen_idx = self._find_best_borrow_candidate(confirmed_idx, reject_sum)

        if chosen_idx is not None:
            # Yes → Extract/Retarget → Pack next plan
            _retarget(chosen_idx)
            self._logger.info(
                f"[last-reel borrow] chosen={chosen_idx} "
                f"Box={self.plan[chosen_idx]['box']}"
            )
        else:
            # No → ลอง Remainder ก่อน replan (combined / divided)
            if not self._try_use_remainder(confirmed_idx, reject_sum):
                self._do_replan_bottom(confirmed_idx, reject_sum)
                
    def _try_absorb_reject_via_remainder(self, confirmed_idx, reject_sum):
        """
        PATH B shortcut — ก่อนทำ retarget หรือ replan ใดๆ
        ถ้ามี Remainder (box=0, same lot) ที่รับ reject ได้
        โดยเพียงแค่ลด target ลง reject_sum → ไม่กระทบ Box ใดเลย

        เงื่อนไข: Remainder_target - reject_sum >= min_per_reel
        Returns: True ถ้าสำเร็จ
        """
        min_reel    = int(getattr(self._config, 'min_per_reel', 1500))
        current_lot = self.plan[confirmed_idx].get("lot", "")

        remainder_candidates = sorted(
            [
                i for i, r in enumerate(self.plan)
                if r["box"] == 0
                and r.get("lot") == current_lot
                and r.get("note") not in ("Wait next lot", "Carry")
                and self.actuals[i] is None
                and self._orig_targets[i] > 0
            ],
            key=lambda i: self._orig_targets[i],
            reverse=True,  # ลองตัวใหญ่สุดก่อน
        )

        for rem_idx in remainder_candidates:
            orig_t = self._orig_targets[rem_idx]
            new_t  = orig_t - reject_sum
            if new_t < min_reel:
                continue

            self.plan[rem_idx]["target"]  = new_t
            self._orig_targets[rem_idx]   = new_t
            self._refresh_future_targets()
            self._logger.info(
                f"[remainder absorb reject] rem_idx={rem_idx} lot={current_lot} "
                f"orig={orig_t:,} → {new_t:,} (reject={reject_sum} absorbed)"
            )
            return True

        return False
    # ──────────────────────────────────────────────────────────────
    def _try_use_remainder(self, confirmed_idx, reject_sum):
        """
        ก่อน replan — ดึง Remainder (box=0, same lot) มาใส่ box ที่มี wait slot

        มี 2 โหมด ลองตามลำดับ:

        โหมด 1 — Remainder เข้า box ด้วย target เต็ม (ไม่หัก reject)
        ─────────────────────────────────────────────────────────────
        • ค้นหา box ที่มี wait slot รับ Remainder (target เต็ม) ได้
        • ถ้า reel ถัดไปในแผนรับ reject ได้ (> min+reject) → retarget reel นั้น
        • ถ้า reel ถัดไปรับ reject ไม่ได้ → Remainder รับ reject แทน (target - reject)
          และวาง Remainder ด้วย target ที่หักแล้ว
        เหมาะกับ: Reel8 reject50 → Remainder(1800) เข้า Box ที่มี wait slot
                  Reel9 retarget −50  ถ้าทำได้ / Remainder รับ reject เองถ้าไม่ได้

        โหมด 2 — Remainder รับ reject เอง (orig_t - reject) เสมอ
        ──────────────────────────────────────────────────────────
        ใช้เมื่อโหมด 1 ไม่สำเร็จ

        เงื่อนไขร่วมทั้ง 2 โหมด:
          • box ปลายทางมี wait slot ว่าง
          • real reels ใน box + 1 ≤ rpb
          • box_total + place_t ≤ max_per_box
          • shortfall ที่เหลือ (ถ้ายังมี wait) อยู่ใน [min×wait, max×wait]

        Returns: True ถ้าสำเร็จ, False ถ้าไม่มี remainder ที่ใช้ได้
        """
        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))
        max_box  = int(getattr(self._config, 'max_per_box',  6400))
        rpb      = int(getattr(self._config, 'reels_per_box', 3))
        current_lot = self.plan[confirmed_idx].get("lot", "")

        # ── หา Remainder reels (box=0, same lot, unconfirmed, target>0) ──
        remainder_candidates = [
            i for i, r in enumerate(self.plan)
            if r["box"] == 0
            and r.get("lot") == current_lot
            and r.get("note") not in ("Wait next lot", "Carry")
            and self.actuals[i] is None
            and self._orig_targets[i] > 0
        ]
        if not remainder_candidates:
            return False

        # เรียง Remainder มากสุดก่อน
        remainder_candidates.sort(
            key=lambda i: self._orig_targets[i], reverse=True
        )

        # ── helper: ตรวจว่า box รับ reel ที่มี target=check_t ได้ไหม ──
        def _box_can_accept(box_id, check_t):
            if check_t < min_reel or check_t > max_reel:
                return False
            real_reels = sum(
                1 for r2 in self.plan
                if r2["box"] == box_id
                and r2.get("note") not in ("Wait next lot", "Carry")
                and r2.get("target", 0) > 0
            )
            wait_slots = sum(
                1 for r2 in self.plan
                if r2["box"] == box_id and r2.get("note") == "Wait next lot"
            )
            total_slots = real_reels + wait_slots

            # รับได้ถ้า:
            #   (A) มี wait slot ว่าง (explicit slot สำหรับ next lot), หรือ
            #   (B) real reels < rpb (ยังมี slot ว่างจริงๆ โดยไม่ต้องมี wait slot)
            # ทั้ง 2 กรณีต้อง total slots หลังรับ ≤ rpb
            if real_reels >= rpb:
                return False  # box เต็ม real reels แล้ว
            if total_slots >= rpb and wait_slots == 0:
                return False  # เต็มแล้ว ไม่มี slot ใดว่าง

            box_total = sum(
                (self.actuals[j].get("actual", 0)
                 if self.actuals[j] is not None else r2["target"])
                for j, r2 in enumerate(self.plan)
                if r2["box"] == box_id
                and r2.get("note") not in ("Wait next lot", "Carry")
            )
            new_box_total = box_total + check_t
            if new_box_total > max_box:
                return False

            # ตรวจ shortfall ที่เหลือหลังรับ reel นี้
            remaining_shortfall = max_box - new_box_total
            # wait slots ที่เหลือหลังใช้ 1 (ถ้ามี wait slot) หรือ 0
            remaining_wait = max(0, wait_slots - 1) if wait_slots > 0 else 0
            # real slot ว่างที่เหลือ (ไม่นับ wait)
            remaining_real_slots = rpb - real_reels - 1  # -1 เพราะเพิ่ม reel นี้แล้ว

            if remaining_shortfall > 0:
                # slot รับเพิ่มได้รวม = remaining wait + remaining real slots
                total_remaining_slots = remaining_wait + remaining_real_slots
                if total_remaining_slots <= 0:
                    return False
                if not (min_reel * total_remaining_slots
                        <= remaining_shortfall
                        <= max_reel * total_remaining_slots):
                    return False
            return True

        # ── helper: ย้าย rem_idx เข้า box_id ──
        def _place_remainder(rem_idx, box_id, use_t):
            self.plan[rem_idx]["box"]    = box_id
            self.plan[rem_idx]["target"] = use_t
            self._orig_targets[rem_idx]  = use_t
            # ลบ wait slot 1 ช่อง (ถ้ามี — กรณีไม่มี wait slot ให้ข้ามได้)
            for wi, wr in enumerate(self.plan):
                if wr["box"] == box_id and wr.get("note") == "Wait next lot":
                    self.plan.pop(wi)
                    self.actuals.pop(wi)
                    self._orig_targets.pop(wi)
                    break
            
            # ⚠️ NEW: Validate box isn't now stuck with dead scrap
            _min = int(getattr(self._config, 'min_per_reel', 1500))
            _box_cap = int(getattr(self._config, 'max_per_box', 6400))
            remaining_wait = sum(
                1 for wr in self.plan
                if wr["box"] == box_id and wr.get("note") == "Wait next lot"
            )
            box_total = sum(
                wr["target"] for wr in self.plan
                if wr["box"] == box_id and wr.get("note") != "Wait next lot"
            )
            deficit = _box_cap - box_total
            if remaining_wait == 0 and 0 < deficit < _min:
                # ⚠️ WARNING: Box now has dead scrap
                self._logger.warning(
                    f"[WARN] Box {box_id} has {deficit:,} pcs dead scrap after remainder placement "
                    f"(< {_min:,} min). Box will need manual adjustment."
                )
            
            self._populate_table()
            self._refresh_future_targets()

        # ── helper: หา reel ถัดไปในแผนที่รับ reject ได้ ──
        def _find_next_absorbable():
            for j, r2 in enumerate(self.plan):
                if (r2.get("lot") == current_lot
                        and r2["box"] > 0
                        and r2.get("note") not in ("Wait next lot", "Carry")
                        and self.actuals[j] is None):
                    if self._orig_targets[j] > min_reel + reject_sum:
                        return j
            return None

        # ════════════════════════════════════════════════════════
        # โหมด 1: วาง Remainder ด้วย target เต็ม
        #         → retarget reel ถัดไปถ้าทำได้
        #         → ถ้าไม่ได้ → ลองวาง Remainder หัก reject แทน
        # ════════════════════════════════════════════════════════
        for rem_idx in remainder_candidates:
            orig_t = self._orig_targets[rem_idx]

            # ลองวางด้วย target เต็มก่อน
            for box_id in sorted({r["box"] for r in self.plan if r["box"] > 0}):
                if not _box_can_accept(box_id, orig_t):
                    continue

                # หา reel ถัดไปที่รับ reject ได้
                next_j = _find_next_absorbable()
                if next_j is not None:
                    # วาง Remainder เต็ม + retarget reel ถัดไป
                    _place_remainder(rem_idx, box_id, orig_t)
                    new_t = self._orig_targets[next_j] - reject_sum
                    self.plan[next_j]["target"]  = new_t
                    self._orig_targets[next_j]   = new_t
                    self._logger.info(
                        f"[remainder mode1-A] rem={rem_idx} → Box {box_id} "
                        f"target={orig_t:,} (full). "
                        f"Retarget next j={next_j} → {new_t:,} (reject={reject_sum})"
                    )
                    self._refresh_future_targets()
                    return True

                # reel ถัดไปรับ reject ไม่ได้ → ลองวาง Remainder หัก reject
                deducted_t = orig_t - reject_sum
                if _box_can_accept(box_id, deducted_t):
                    _place_remainder(rem_idx, box_id, deducted_t)
                    self._logger.info(
                        f"[remainder mode1-B] rem={rem_idx} → Box {box_id} "
                        f"orig={orig_t:,} → deducted={deducted_t:,} "
                        f"(reject absorbed by Remainder, no next reel to retarget)"
                    )
                    return True
                break  # ถ้า box นี้รับเต็มได้แต่หักแล้วไม่ได้ ลอง box ถัดไป

        # ════════════════════════════════════════════════════════
        # โหมด 2: Remainder รับ reject เอง (orig_t - reject)
        # ════════════════════════════════════════════════════════
        for rem_idx in remainder_candidates:
            orig_t = self._orig_targets[rem_idx]
            new_t  = orig_t - reject_sum
            if new_t < min_reel:
                continue
            for box_id in sorted({r["box"] for r in self.plan if r["box"] > 0}):
                if _box_can_accept(box_id, new_t):
                    _place_remainder(rem_idx, box_id, new_t)
                    self._logger.info(
                        f"[remainder mode2] rem={rem_idx} → Box {box_id} "
                        f"orig={orig_t:,} → new_t={new_t:,} (reject deducted)"
                    )
                    return True

        self._logger.info(
            f"[remainder] no usable remainder for lot={current_lot} "
            f"reject={reject_sum} — proceed to replan"
        )
        return False

    # ──────────────────────────────────────────────────────────────
    def _find_best_borrow_candidate(self, confirmed_idx, reject_sum):
        """
        ค้นหา candidate reel ที่ดีที่สุดสำหรับการยืม reject (PATH B)

        เงื่อนไขผ่าน:
          (a) candidate > min_reel + reject  (flowchart diamond)
          (b) candidate box ยัง fillable หลังยืม
              — box_total หลังหัก reject + wait slots ที่เหลือ
                สามารถรวมถึง max_per_box ได้
          (c) real reels ใน candidate box ยังไม่เกิน RPB

        Returns: index ของ candidate ที่ผ่าน หรือ None
        """
        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))
        max_box  = int(getattr(self._config, 'max_per_box',  6400))
        rpb      = int(getattr(self._config, 'reels_per_box', 3))
        current_lot = self.plan[confirmed_idx].get("lot", "")
        curr_box    = self.plan[confirmed_idx]["box"]

        # รวบรวม candidates: same lot, next box, unconfirmed
        candidates = [
            i for i, r in enumerate(self.plan)
            if r.get("lot") == current_lot
            and r["box"] > 0
            and r["box"] != curr_box
            and r.get("note") not in ("Wait next lot", "Carry")
            and self.actuals[i] is None
        ]

        for cand_idx in candidates:
            orig_t = self._orig_targets[cand_idx]
            new_t  = orig_t - reject_sum

            # (a) flowchart: next reel > min_reel + reject
            if orig_t <= min_reel + reject_sum:
                self._logger.info(
                    f"[borrow] skip cand={cand_idx} "
                    f"orig={orig_t} ≤ min+reject={min_reel+reject_sum}"
                )
                continue

            # (b) box ของ candidate ยัง fillable หลังยืม
            box_id = self.plan[cand_idx]["box"]
            other_total = sum(
                (self.actuals[j].get("actual", 0)
                 if self.actuals[j] is not None else r2["target"])
                for j, r2 in enumerate(self.plan)
                if r2["box"] == box_id
                and j != cand_idx
                and r2.get("note") not in ("Wait next lot", "Carry")
            )
            new_box_total = other_total + new_t
            wait_slots = sum(
                1 for j, r2 in enumerate(self.plan)
                if r2["box"] == box_id
                and j != cand_idx
                and r2.get("note") == "Wait next lot"
            )
            deficit = max_box - new_box_total

            if deficit > 0:
                if wait_slots == 0:
                    self._logger.info(
                        f"[borrow] skip cand={cand_idx} box={box_id} "
                        f"deficit={deficit} but no wait slots"
                    )
                    continue
                if not (min_reel * wait_slots <= deficit <= max_reel * wait_slots):
                    self._logger.info(
                        f"[borrow] skip cand={cand_idx} box={box_id} "
                        f"deficit={deficit} out of range "
                        f"[{min_reel*wait_slots},{max_reel*wait_slots}]"
                    )
                    continue

            # (c) real reels ใน candidate box ≤ rpb (ไม่เกินกล่อง)
            real_reels = sum(
                1 for r2 in self.plan
                if r2["box"] == box_id
                and r2.get("note") not in ("Wait next lot", "Carry")
                and r2.get("target", 0) > 0
            )
            if real_reels > rpb:
                self._logger.info(
                    f"[borrow] skip cand={cand_idx} box={box_id} "
                    f"real_reels={real_reels} > rpb={rpb}"
                )
                continue

            return cand_idx  # ✅ ผ่านทุกเงื่อนไข

        return None  # ไม่มี candidate ผ่าน → replan

    # ──────────────────────────────────────────────────────────────
    def _move_reel_to_next_box(self, reel_idx):
        """
        Move this reel to the next box (flowchart: "Move this reel to the next box")
        ใช้เมื่อ next box reel ไม่ผ่าน can_absorb หลัง retarget same-box reel

        ค้นหา box ถัดไปที่มี wait slot ว่างและ reel นี้ใส่ได้
        ถ้าไม่มี → ไม่ทำอะไร (plan ดำเนินต่อไป)
        """
        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))
        max_box  = int(getattr(self._config, 'max_per_box',  6400))
        rpb      = int(getattr(self._config, 'reels_per_box', 3))

        curr_box    = self.plan[reel_idx]["box"]
        reel_target = self._orig_targets[reel_idx]

        # หา box ถัดไปที่มี wait slot
        for i, r in enumerate(self.plan):
            target_box = r["box"]
            if target_box <= curr_box or target_box == 0:
                continue
            if r.get("note") != "Wait next lot":
                continue

            # ตรวจ: ใส่ reel นี้แล้ว box ไม่เกิน max และ real reels ไม่เกิน rpb
            box_total = sum(
                (self.actuals[j].get("actual", 0)
                 if self.actuals[j] is not None else r2["target"])
                for j, r2 in enumerate(self.plan)
                if r2["box"] == target_box
                and r2.get("note") not in ("Wait next lot", "Carry")
            )
            real_reels = sum(
                1 for r2 in self.plan
                if r2["box"] == target_box
                and r2.get("note") not in ("Wait next lot", "Carry")
                and r2.get("target", 0) > 0
            )

            if box_total + reel_target > max_box:
                continue
            if real_reels + 1 > rpb:
                continue

            # ✅ ย้าย reel ไปยัง target_box และลบ wait slot ออก 1 ช่อง
            old_box = self.plan[reel_idx]["box"]
            self.plan[reel_idx]["box"] = target_box
            self.plan.pop(i)
            self.actuals.pop(i)
            self._orig_targets.pop(i)

            self._logger.info(
                f"[move-to-next-box] reel_idx={reel_idx} "
                f"moved from Box {old_box} → Box {target_box} "
                f"(filled wait slot, target={reel_target:,})"
            )
            self._populate_table()
            self._refresh_future_targets()
            return

        self._logger.info(
            f"[move-to-next-box] reel_idx={reel_idx} "
            f"no suitable next box found — plan continues as-is"
        )
        self._refresh_future_targets()

    # ──────────────────────────────────────────────────────────────
    def _show_and_apply_retarget(self, reject_sum, next_idx, orig, new_t):
        """Apply retarget to next reel (no popup — visible in table)."""
        # Apply
        self.plan[next_idx]["target"]  = new_t
        self._orig_targets[next_idx]   = new_t
        tr = self._trow(next_idx)
        T = THEME
        bg = QColor(self._BOX_COLORS[
            (self.plan[next_idx]["box"] - 1) % len(self._BOX_COLORS)])
        self._table.setItem(tr, 3,
            self._cell(f"{new_t:,}", T["accent_amber"], bg=bg))
        self._refresh_future_targets()

    # ══════════════════════════════════════════════════════════════
    #  monitor_page.py  →  _try_fill_box (แทนที่ทั้ง method)
    # ══════════════════════════════════════════════════════════════
    
    def _try_fill_box(self, confirmed_idx):
        """
        After retarget, check if the confirmed reel's box is still < max.
        Try to borrow from a next-box donor reel (same lot).
    
        Stage 1: Check if donor box remains fillable after borrow.
        If yes → apply partial borrow. If no → Stage 2.
    
        Stage 2: Pull entire donor reel to Remainder (box=0) + add wait slot in receiver box.
    
        [FIX-B2] Stage 2 guard: ตรวจนับ real reels ใน receiver box ก่อน insert wait slot
                ถ้า real_reels >= RPB-1 แสดงว่า box จะครบ RPB แล้วหลัง lot นี้ → ห้าม insert
        """
        from ui.theme import THEME
        from PyQt5.QtGui import QColor
    
        row = self.plan[confirmed_idx]
        curr_box = row["box"]
        current_lot = row.get("lot", "")
        if not current_lot:
            return
        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))
        max_box  = int(getattr(self._config, 'max_per_box', 6400))
        rpb      = int(getattr(self._config, 'reels_per_box', 3))   # [FIX-B2]
    
        # Sum everything in this box: confirmed actuals + unconfirmed targets
        box_total = 0
        last_unconfirmed_in_box = None
        for i, r in enumerate(self.plan):
            if r["box"] != curr_box:
                continue
            if r.get("note") in ("Wait next lot", "Carry"):
                continue
            if self.actuals[i] is not None:
                box_total += self.actuals[i].get("actual", 0)
            else:
                box_total += self.plan[i]["target"]
                if r.get("lot") == current_lot:
                    last_unconfirmed_in_box = i
    
        if box_total >= max_box or last_unconfirmed_in_box is None:
            return  # box already full or no receiver
    
        shortfall = max_box - box_total
        receiver_idx = last_unconfirmed_in_box
        receiver_target = self._orig_targets[receiver_idx]
    
        # Find donor: next unconfirmed reel of same lot, NOT in this box.
        # [FIX-DONOR-SELECT] Prefer donor whose box remains fillable after removal.
        # This avoids pulling a reel that is the sole contributor to its own box's
        # full-box plan (e.g. Reel 6 of Box 3 that would also fill Box 3 to max).
        #
        # Strategy:
        #   1. Collect ALL candidate donors (same lot, different box, unconfirmed)
        #   2. For each candidate, simulate removal and check if its box stays fillable
        #      (remaining reels + wait slots can still reach max_per_box)
        #   3. Pick first "safe" donor (box still fillable after pull)
        #   4. Fallback: if none are safe, pick the donor whose box has the
        #      highest remaining planned total after removal (least impact)

        def _donor_box_fillable_after_remove(candidate_idx):
            """
            Simulate removing candidate from its box and check if that box
            is still fillable. Returns False if the candidate is the only real
            reel in its box (removing it destroys the box's full-box plan).
            """
            cand_box = self.plan[candidate_idx]["box"]
            # Check that at least one other real reel exists in the same box
            other_real = any(
                True
                for j, r in enumerate(self.plan)
                if j != candidate_idx
                and r["box"] == cand_box
                and r.get("note") not in ("Wait next lot", "Carry")
                and r.get("target", 0) > 0
            )
            if not other_real:
                # Only real reel — removing empties the box → not safe
                return False
            # Temporarily hide candidate and check if the box is still fillable
            saved_box = self.plan[candidate_idx]["box"]
            self.plan[candidate_idx]["box"] = -999  # exclude from _is_box_fillable
            still_fillable = self._is_box_fillable(cand_box)
            self.plan[candidate_idx]["box"] = saved_box  # restore
            return still_fillable

        # Collect all candidates in plan order
        all_donors = []
        for i, r in enumerate(self.plan):
            if (r.get("lot") == current_lot
                    and r["box"] != curr_box
                    and r["box"] > 0
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and self.actuals[i] is None):
                all_donors.append(i)

        if not all_donors:
            return

        # Prefer safe donors first (box still fillable after removal)
        safe_donors = [i for i in all_donors if _donor_box_fillable_after_remove(i)]
        if safe_donors:
            donor_idx = safe_donors[0]
        else:
            # No safe donor — pick the one whose box has the most remaining
            # planned total (other reels) after removal → least impact on that box
            def _remaining_box_total_after(candidate_idx):
                cand_box = self.plan[candidate_idx]["box"]
                return sum(
                    (self.actuals[j].get("actual", 0) if self.actuals[j] is not None
                     else self.plan[j]["target"])
                    for j, r in enumerate(self.plan)
                    if r["box"] == cand_box
                    and j != candidate_idx
                    and r.get("note") not in ("Wait next lot", "Carry")
                )
            donor_idx = max(all_donors, key=_remaining_box_total_after)
            self._logger.info(
                f"[_try_fill_box] No safe donor — choosing donor idx={donor_idx} "
                f"(Box {self.plan[donor_idx]['box']}) with least impact on its box."
            )
    
        donor_target = self._orig_targets[donor_idx]
        donor_box = self.plan[donor_idx]["box"]

        # ══════════════════════════════════════════════════════════
        # Stage 0: Smart direct-fit check
        # ──────────────────────────────────────────────────────────
        # ก่อนทำ borrow/pull ตรวจสอบว่า donor reel สามารถย้ายเข้า
        # receiver box (curr_box) ได้ทันทีหรือไม่ โดยมีเงื่อนไข:
        #   (A) receiver box มี wait slot ว่างอยู่ (จะรับ donor มาแทนที่)
        #   (B) box_total หลังใส่ donor ≤ max_per_box
        #   (C) donor_target อยู่ใน [min_per_reel, max_per_reel]
        #   (D) lot ถัดไป (หลัง donor) สามารถเติม receiver box ที่เหลือได้
        #       หรือ receiver box ครบ max แล้วหลังรับ donor
        #   (E) donor box ยังคง fillable หลังสูญเสีย donor reel
        #       (มี wait slot หรือ reel อื่นพอที่จะ full ได้ หรือ empty ก็ยอมรับ)
        #   (F) จำนวน real reels ใน receiver box หลังรับ donor ≤ rpb
        #       (1 box pack ได้แค่ rpb reels เท่านั้น)
        # ══════════════════════════════════════════════════════════

        wait_slots_in_receiver = sum(
            1 for r in self.plan
            if r["box"] == curr_box and r.get("note") == "Wait next lot"
        )

        # (F) นับ real reels ปัจจุบันใน receiver box (ไม่นับ wait/carry)
        real_reels_in_receiver = sum(
            1 for r in self.plan
            if r["box"] == curr_box
            and r.get("note") not in ("Wait next lot", "Carry")
            and r.get("target", 0) > 0
        )
        # หลังรับ donor จะมี real reels เพิ่มอีก 1 → ต้องไม่เกิน rpb
        receiver_has_room = (real_reels_in_receiver + 1) <= rpb

        if wait_slots_in_receiver > 0 and min_reel <= donor_target <= max_reel and receiver_has_room:
            new_box_total = box_total + donor_target

            # (B) ไม่เกิน max_per_box
            if new_box_total <= max_box:
                # (D) ตรวจว่า receiver box จะ full ได้หลังรับ donor
                #     - เต็มพอดี (remaining_shortfall == 0) → OK
                #     - ยังขาด (remaining_shortfall > 0) → ต้องมี wait slot เหลืออยู่
                #       และ shortfall อยู่ใน range ที่ lot ถัดไปสามารถเติมได้
                remaining_shortfall = max_box - new_box_total
                remaining_wait_after = wait_slots_in_receiver - 1  # ใช้ไป 1 slot

                if remaining_shortfall == 0:
                    # เต็มพอดี → ย้ายได้เลย ไม่ต้องตรวจอื่น
                    can_future_fill = True
                elif remaining_wait_after <= 0:
                    # ยังขาดอยู่แต่ไม่มี wait slot เหลือ → lot ถัดไปเติมไม่ได้ → ห้ามย้าย
                    can_future_fill = False
                else:
                    # ยังขาดอยู่และมี wait slot เหลือ → ตรวจว่า shortfall อยู่ใน range
                    can_future_fill = (
                        min_reel * remaining_wait_after
                        <= remaining_shortfall
                        <= max_reel * remaining_wait_after
                    )

                # (E) ตรวจ donor box หลังสูญเสีย donor reel
                saved_box = self.plan[donor_idx]["box"]
                self.plan[donor_idx]["box"] = -999  # ซ่อนชั่วคราว
                donor_box_still_ok = (
                    self._is_box_fillable(saved_box)
                    or self._get_box_planned_total(saved_box) >= max_box
                    or not any(                         # donor box ว่างเปล่าหลังดึง → ยอมรับ
                        r["box"] == saved_box
                        and r.get("note") not in ("Wait next lot", "Carry")
                        and r.get("target", 0) > 0
                        for r in self.plan
                    )
                )
                self.plan[donor_idx]["box"] = saved_box  # restore

                if can_future_fill and donor_box_still_ok:
                    # ✅ Stage 0 สำเร็จ: ย้าย donor เข้า receiver box ทันที
                    old_donor_box = self.plan[donor_idx]["box"]
                    self.plan[donor_idx]["box"] = curr_box

                    # ลบ wait slot 1 ช่องออกจาก receiver box (donor มาแทนที่แล้ว)
                    for i, r in enumerate(self.plan):
                        if r["box"] == curr_box and r.get("note") == "Wait next lot":
                            self.plan.pop(i)
                            self.actuals.pop(i)
                            self._orig_targets.pop(i)
                            break

                    self._logger.info(
                        f"Stage 0 (direct-fit): donor idx={donor_idx} "
                        f"(target={donor_target:,}) moved from Box {old_donor_box} "
                        f"directly into Box {curr_box}. "
                        f"real_reels_before={real_reels_in_receiver}, rpb={rpb}, "
                        f"new_box_total={new_box_total:,}, "
                        f"remaining_shortfall={remaining_shortfall:,}, "
                        f"remaining_wait={remaining_wait_after}"
                    )
                    self._populate_table()
                    self._refresh_future_targets()
                    return

        # Stage 0 ไม่สำเร็จ → ดำเนินการ borrow/pull ตามปกติ
        lendable = donor_target - min_reel
        if lendable <= 0:
            return
        borrow = min(shortfall, lendable, max_reel - receiver_target)
        if borrow <= 0:
            return
    
        # ─── Stage 1: Check if donor box is fillable after borrow ────
        new_donor_after_borrow = donor_target - borrow
        self.plan[donor_idx]["target"] = new_donor_after_borrow
        self._orig_targets[donor_idx] = new_donor_after_borrow
    
        if self._is_box_fillable(donor_box):
            # Stage 1 success: Apply borrow to receiver & donor
            T = THEME
            new_receiver = receiver_target + borrow
    
            self.plan[receiver_idx]["target"]  = new_receiver
            self._orig_targets[receiver_idx]   = new_receiver
            tr_r = self._trow(receiver_idx)
            bg_r = QColor(self._BOX_COLORS[
                (self.plan[receiver_idx]["box"] - 1) % len(self._BOX_COLORS)])
            self._table.setItem(tr_r, 3,
                self._cell(f"{new_receiver:,}", T["accent_amber"], bg=bg_r))
    
            tr_d = self._trow(donor_idx)
            bg_d = QColor(self._BOX_COLORS[
                (donor_box - 1) % len(self._BOX_COLORS)])
            self._table.setItem(tr_d, 3,
                self._cell(f"{new_donor_after_borrow:,}", T["accent_amber"], bg=bg_d))
    
            self._refresh_future_targets()
            return
    
        # ─── Stage 2: Cannot partially borrow — try MOVING donor into receiver box ────
        # Restore donor to original target (undo Stage 1 simulation)
        self.plan[donor_idx]["target"] = donor_target
        self._orig_targets[donor_idx] = donor_target

        # Check if receiver box has a wait slot available to absorb donor reel
        wait_slots_in_receiver = sum(
            1 for r in self.plan
            if r["box"] == curr_box and r.get("note") == "Wait next lot"
        )

        if wait_slots_in_receiver > 0:
            # Stage 2A: Move entire donor reel into receiver box (fill its wait slot)
            # Check if donor box can still meet its own requirements after losing this reel
            saved_box = self.plan[donor_idx]["box"]
            self.plan[donor_idx]["box"] = -999  # simulate removal
            donor_box_ok = (
                self._is_box_fillable(saved_box)
                or self._get_box_planned_total(saved_box) >= max_box
                or not any(
                    r["box"] == saved_box
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and r.get("target", 0) > 0
                    for r in self.plan
                )
            )
            self.plan[donor_idx]["box"] = saved_box  # restore

            if donor_box_ok:
                # ตรวจว่าหลังย้าย donor เข้า box แล้ว box จะ full หรือยังขาดอยู่
                new_box_total_2a = box_total + donor_target
                remaining_after_2a = max_box - new_box_total_2a
                # wait slots ที่จะเหลือ: ถ้าลบออก 1 ช่อง → remaining_wait_2a = wait_slots_in_receiver - 1
                remaining_wait_2a = wait_slots_in_receiver - 1

                # ถ้ายังขาดอยู่ (remaining > 0) และไม่มี wait slot เหลือ → ต้องคง wait slot ไว้
                # เพราะถ้าลบ wait slot ออก lot ถัดไปจะเติมไม่ได้
                if remaining_after_2a > 0 and remaining_wait_2a <= 0:
                    # คง wait slot ไว้ แต่ย้าย donor เข้า box (ใช้ slot ที่มีอยู่แล้ว)
                    # → ย้าย donor เข้า box โดยไม่ลบ wait slot
                    old_donor_box = self.plan[donor_idx]["box"]
                    self.plan[donor_idx]["box"] = curr_box
                    self._logger.info(
                        f"Stage 2A replan: donor idx={donor_idx} moved from Box {old_donor_box} "
                        f"into Box {curr_box} (wait slot kept — box still needs {remaining_after_2a:,} more)"
                    )
                else:
                    # box จะ full หลังย้าย หรือมี wait slot เหลือพอ → ลบ wait slot 1 ช่อง
                    old_donor_box = self.plan[donor_idx]["box"]
                    self.plan[donor_idx]["box"] = curr_box
                    for i, r in enumerate(self.plan):
                        if r["box"] == curr_box and r.get("note") == "Wait next lot":
                            self.plan.pop(i)
                            self.actuals.pop(i)
                            self._orig_targets.pop(i)
                            break
                    self._logger.info(
                        f"Stage 2A replan: donor idx={donor_idx} moved from Box {old_donor_box} "
                        f"into Box {curr_box} (wait slot removed — box_total={new_box_total_2a:,})"
                    )
                self._populate_table()
                self._refresh_future_targets()
                return

        # Stage 2B: No wait slot in receiver, or donor box not OK after move.
        # Pull donor to Remainder (box=0) + add wait slot in DONOR's original box
        # so that the next lot can fill donor's box instead.
        donor_original_box = self.plan[donor_idx]["box"]
        self.plan[donor_idx]["box"] = 0

        # Count slots in donor's original box after removal
        real_reels_in_donor_box = sum(
            1 for r in self.plan
            if r["box"] == donor_original_box
            and r.get("note") not in ("Wait next lot", "Carry")
            and r.get("target", 0) > 0
        )
        existing_wait_in_donor_box = sum(
            1 for r in self.plan
            if r["box"] == donor_original_box
            and r.get("note") == "Wait next lot"
        )
        total_donor_slots = real_reels_in_donor_box + existing_wait_in_donor_box

        # Add wait slot in donor's original box only if it has room
        if total_donor_slots < rpb and existing_wait_in_donor_box == 0:
            wait_reel_num = max(
                (r.get("reel", 0) for r in self.plan if r["box"] == donor_original_box),
                default=0
            ) + 1
            wait_slot = {
                "box": donor_original_box,
                "reel": wait_reel_num,
                "lot": "—",
                "target": 0,
                "note": "Wait next lot"
            }
            # Insert after last real reel in donor box
            insert_pos = max(
                (i for i, r in enumerate(self.plan) if r["box"] == donor_original_box),
                default=len(self.plan) - 1
            ) + 1
            self.plan.insert(insert_pos, wait_slot)
            self.actuals.insert(insert_pos, None)
            self._orig_targets.insert(insert_pos, 0)
            self._logger.info(
                f"Stage 2B replan: donor idx={donor_idx} moved to Remainder, "
                f"wait slot added in donor Box {donor_original_box} "
                f"(real={real_reels_in_donor_box}, wait={existing_wait_in_donor_box})"
            )
        else:
            self._logger.info(
                f"Stage 2B replan: donor idx={donor_idx} moved to Remainder. "
                f"No wait slot added in donor Box {donor_original_box} "
                f"(real={real_reels_in_donor_box}, wait={existing_wait_in_donor_box}, RPB={rpb})"
            )

        self._populate_table()
        self._refresh_future_targets()
    
 

    def _do_replan_bottom(self, confirmed_idx, reject_sum):
        """Combined / Divided logic when reject cannot be absorbed"""
        current_lot = self.plan[confirmed_idx].get("lot", "")
        min_reel = int(getattr(self._config, 'min_per_reel', 1500))
        max_reel = int(getattr(self._config, 'max_per_reel', 3100))
        T = THEME

        # Find two unconfirmed reels of same lot (first two)
        unconfirmed = []
        for i, r in enumerate(self.plan):
            if (r.get("lot") == current_lot
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and self.actuals[i] is None):
                unconfirmed.append(i)
            if len(unconfirmed) >= 2:
                break
        if len(unconfirmed) < 2:
            # Only one reel left → convert to wait if below min
            if unconfirmed and self._orig_targets[unconfirmed[0]] < min_reel:
                self._convert_to_wait(unconfirmed[0])
            return

        i1, i2 = unconfirmed[0], unconfirmed[1]
        t1 = self._orig_targets[i1]
        t2 = self._orig_targets[i2]
        total = t1 + t2

        if total <= max_reel:
            # Combined — [L2] use _MonitorReplanDialog instead of QMessageBox
            details = {
                "merged_box": self.plan[i1]["box"],
                "merged_reel": self.plan[i1]["reel"],
                "merged_target": total,
                "wait_box": self.plan[i2]["box"],
                "wait_reel": self.plan[i2]["reel"],
            }
            dlg = _MonitorReplanDialog(reject_sum, "combined", details, ask_user=False, parent=self)
            if dlg.exec_() == QDialog.Accepted:
                self._apply_combined_replan(i1, i2, total)
        else:
            # Divided
            half = total // 2
            r1 = max(min_reel, min(half, max_reel))
            r2 = total - r1
            if r2 < min_reel:
                r2 = min_reel
                r1 = total - r2
            if r1 < min_reel or r2 < min_reel:
                # Cannot split viably → convert both to wait
                self._convert_to_wait(i1)
                self._convert_to_wait(i2)
                # [L2] use _MonitorReplanDialog for warning case
                details = {
                    "wait_box": self.plan[i1]["box"],
                    "wait_reel": self.plan[i1]["reel"],
                }
                dlg = _MonitorReplanDialog(reject_sum, "warning", details, ask_user=True, parent=self)
                dlg.exec_()
                return
            # [L2] use _MonitorReplanDialog for divided case
            details = {
                "reel1_box": self.plan[i1]["box"],
                "reel1_reel": self.plan[i1]["reel"],
                "reel1_target": r1,
                "reel2_box": self.plan[i2]["box"],
                "reel2_reel": self.plan[i2]["reel"],
                "reel2_target": r2,
            }
            dlg = _MonitorReplanDialog(reject_sum, "divided", details, ask_user=False, parent=self)
            if dlg.exec_() == QDialog.Accepted:
                self._apply_divided_replan(i1, i2, r1, r2)

    def _apply_combined_replan(self, idx1, idx2, total):
        """รวมสอง reel เข้าเป็น reel แรก, อีกอันเป็น Wait slot"""
        self.plan[idx1]["target"] = total
        self._orig_targets[idx1] = total
        self._convert_to_wait(idx2)
        self._refresh_future_targets()

    def _apply_divided_replan(self, idx1, idx2, t1, t2):
        self.plan[idx1]["target"] = t1
        self._orig_targets[idx1] = t1
        self.plan[idx2]["target"] = t2
        self._orig_targets[idx2] = t2
        self._refresh_future_targets()

    def _convert_to_wait(self, idx):
        """Convert a reel to Wait slot in plan + table."""
        T = THEME
        self.plan[idx]["note"]   = "Wait next lot"
        self.plan[idx]["target"] = 0
        self._orig_targets[idx]  = 0
        tr = self._trow(idx)
        bg = QColor(self._BOX_COLORS[
            (self.plan[idx]["box"] - 1) % len(self._BOX_COLORS)])
        for col, txt, clr in [
            (1, f"Reel {self.plan[idx]['reel']}", T["text_muted"]),
            (2, "—", T["text_muted"]), (3, "—", T["text_muted"]),
            (4, "—", T["text_muted"]), (5, "—", T["text_muted"]),
            (6, "—", T["text_muted"]),
            (7, "⏳ Wait", T["accent_amber"]),
        ]:
            self._table.setItem(tr, col,
                self._cell(txt, clr, bold=(col == 7), bg=bg))

    # ─── Below-min scrap check ───────────────────────────────

    def _check_below_min_after_confirm(self, idx):
        # [L5] Always check below-min regardless of _user_chose_continue flag
        row = self.plan[idx]
        if row.get("note") in ("Wait next lot", "Carry"):
            return
        act = self.actuals[idx]
        if act is None:
            return
        actual = act.get("actual", 0)
        reject = act.get("reject", 0)
        good   = actual - reject
        min_rl = int(getattr(self._config, 'min_per_reel', 1500))
        if good >= min_rl:
            return
        T = THEME
        
        # ✅ FIX: Box 0 (remainder) items should be deferred, not marked as reject
        is_box_0 = (row.get("box", 0) == 0)
        if is_box_0:
            # Remainder reels below min should be carried to next order
            # Do NOT mark all actual as reject - instead defer the entire reel
            self.actuals[idx]["note"] = "Deferred to next order (below min)"
            # Keep actual/reject as-is, don't change them
            bg = self._table.item(self._trow(idx), 0).background().color()
            self._table.setItem(self._trow(idx), 7, self._cell("⏳ Defer", T["accent_amber"], bold=True, bg=bg))
        else:
            # Regular box reel below min: Accept it with note
            self.actuals[idx]["note"] = "Below min, packed anyway"
            bg = self._table.item(self._trow(idx), 0).background().color()
            self._table.setItem(self._trow(idx), 7, self._cell("⚠ Below Min", T["accent_amber"], bold=True, bg=bg))

    # ─── Undo last ───────────────────────────────────────────

    def _undo_last(self):
        T = THEME
        if self.current_idx <= 0:
            return
        self.current_idx -= 1
        while (self.current_idx > 0 and
               self.plan[self.current_idx].get("note") == "Wait next lot"):
            self.current_idx -= 1
        
        # [L3] Restore from undo stack if available
        if self._undo_stack:
            undo_entry = self._undo_stack.pop()
            # Restore all affected indices from snapshot
            for i, target in enumerate(undo_entry["target_snapshot"]):
                self._orig_targets[i] = target
                self.plan[i]["target"] = target
        # [FIX-9] ลบ else branch เดิมที่เป็น no-op
        # (self._orig_targets[i] = self._orig_targets[i] ไม่ทำอะไรเลย)
        # ถ้า _undo_stack ว่าง ให้ใช้ค่า _orig_targets ปัจจุบันเป็น canonical
        # ซึ่งจะถูกเขียนกลับ plan["target"] ในบรรทัดถัดไป
        
        self.actuals[self.current_idx] = None
        self.plan[self.current_idx]["target"] = self._orig_targets[self.current_idx]
        self._user_chose_continue = False
        row = self.plan[self.current_idx]
        bg = QColor(self._BOX_COLORS[(row["box"] - 1) % len(self._BOX_COLORS)])
        tr = self._trow(self.current_idx)
        self._table.setItem(tr, 4, self._cell("—", T["text_muted"], bg=bg))
        self._table.setItem(tr, 5, self._cell("—", T["text_muted"], bg=bg))
        self._table.setItem(tr, 6, self._cell("—", T["text_muted"], bg=bg))
        self._table.setItem(tr, 7, self._cell("⏳ Pending", T["text_muted"], bg=bg))
        self._actual_spin.setEnabled(True)
        self._confirm_btn.setEnabled(True)
        self._note_edit.setEnabled(True)
        self._finish_btn.setEnabled(False)
        self._undo_btn.setEnabled(self.current_idx > 0)
        self._refresh_future_targets()
        self._highlight_current()

    # ─── Summary update ─────────────────────────────────────

    def _update_summary(self):
        T = THEME
        packable = [i for i, r in enumerate(self.plan) if r.get("note") != "Wait next lot"]
        wait_count = len(self.plan) - len(packable)
        total_target = sum(self.plan[i]["target"] for i in packable)
        confirmed = [a for a in self.actuals if a is not None]
        done = len(confirmed)
        total = len(packable)
        total_actual = sum(a["actual"] for a in confirmed)
        total_diff = total_actual - sum(
            self.plan[i]["target"] for i in range(len(self.plan))
            if self.actuals[i] is not None)
        total_reject = sum(a.get("reject", 0) for a in confirmed)

        wait_text = f" (+{wait_count} wait)" if wait_count > 0 else ""
        self._progress_lbl.setText(f"{done} / {total} Reels{wait_text}")
        if done >= total:
            self._progress_lbl.setStyleSheet(f"color:{T['accent_green']};background:transparent;")
        else:
            self._progress_lbl.setStyleSheet(f"color:{T['accent']};background:transparent;")
        self._sum_target.setText(f"Target: {total_target:,}")
        self._sum_actual.setText(f"Actual: {total_actual:,}" if done > 0 else "Actual: —")
        if done > 0 and total_reject > 0:
            self._sum_reject.setText(f"Reject: {total_reject:,}")
            self._sum_reject.setStyleSheet(f"color:{T['accent_red']};background:transparent;")
        else:
            self._sum_reject.setText("Reject: 0")
            self._sum_reject.setStyleSheet(f"color:{T['text_muted']};background:transparent;")
        if done > 0:
            if total_diff == 0:
                self._sum_diff.setText("Diff: 0")
                self._sum_diff.setStyleSheet(f"color:{T['accent_green']};background:transparent;")
            elif total_diff > 0:
                self._sum_diff.setText(f"Diff: +{total_diff:,}")
                self._sum_diff.setStyleSheet(f"color:{T['accent_amber']};background:transparent;")
            else:
                self._sum_diff.setText(f"Diff: {total_diff:,}")
                self._sum_diff.setStyleSheet(f"color:{T['accent_red']};background:transparent;")
        else:
            self._sum_diff.setText("Diff: —")
            self._sum_diff.setStyleSheet(f"color:{T['text_muted']};background:transparent;")
        self._update_box_summary()

    def _update_box_summary(self):
        T = THEME
        boxes = {}
        for i, row in enumerate(self.plan):
            b = row["box"]
            if b not in boxes:
                boxes[b] = {"target": 0, "actual": 0, "done": 0, "total": 0,
                            "reject": 0, "wait": 0}
            if row.get("note") == "Wait next lot":
                boxes[b]["wait"] += 1
            else:
                boxes[b]["target"] += row["target"]
                boxes[b]["total"] += 1
            if self.actuals[i] is not None:
                boxes[b]["actual"] += self.actuals[i]["actual"]
                boxes[b]["reject"] += self.actuals[i].get("reject", 0)
                boxes[b]["done"] += 1

        # Clear old cards
        while self._box_card_layout.count():
            w = self._box_card_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._box_cards.clear()

        max_box = int(getattr(self._config, 'max_per_box', 6400))

        # Separate box=0 (remainder reels) from real boxes
        remainder_info = boxes.pop(0, None)

        cols = min(4, max(1, len(boxes)))
        for idx, b in enumerate(sorted(boxes)):
            info = boxes[b]
            row_i, col_i = divmod(idx, cols)
            card = QFrame()
            done_all = (info["done"] == info["total"] and info["total"] > 0)
            has_wait = info["wait"] > 0
            diff = info["actual"] - info["target"]

            if done_all and diff == 0:
                border_col = T["accent_green"]
                status_icon, status_txt = "✅", "Complete"
            elif done_all:
                border_col = T["accent_amber"]
                status_icon, status_txt = "⚠", f"Done ({diff:+,})"
            elif info["done"] > 0:
                border_col = T["accent"]
                status_icon, status_txt = "▶", f"{info['done']}/{info['total']}"
            else:
                border_col = T["border"]
                status_icon, status_txt = "⏳", "Pending"

            card.setStyleSheet(f"""QFrame {{
                background: {T['bg_card']}; border: 1.5px solid {border_col};
                border-radius: {S(8)}px; border-left: 4px solid {border_col};
            }}""")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(S(8), S(6), S(8), S(6))
            cl.setSpacing(S(3))

            # Header: Box number + status
            hdr = QHBoxLayout()
            box_lbl = QLabel(f"📦 Box {b}")
            box_lbl.setStyleSheet(f"font-size:{F(11)}px;font-weight:bold;"
                                  f"color:{T['accent']};background:transparent;border:none;")
            st_lbl = QLabel(f"{status_icon} {status_txt}")
            st_lbl.setStyleSheet(f"font-size:{F(10)}px;font-weight:bold;"
                                 f"color:{border_col};background:transparent;border:none;")
            st_lbl.setAlignment(Qt.AlignRight)
            hdr.addWidget(box_lbl); hdr.addStretch(); hdr.addWidget(st_lbl)
            cl.addLayout(hdr)

            # Packed / Target
            pct = int(info["actual"] / max_box * 100) if max_box > 0 else 0
            val_lbl = QLabel(f"{info['actual']:,} / {max_box:,}")
            val_lbl.setStyleSheet(f"font-size:{F(12)}px;font-weight:bold;"
                                  f"color:{T['text_primary']};background:transparent;border:none;")
            cl.addWidget(val_lbl)

            # Mini info
            detail_parts = []
            if info["reject"] > 0:
                c_red = T["accent_red"]
                detail_parts.append(f"<span style='color:{c_red}'>Rej {info['reject']:,}</span>")
            if has_wait:
                c_amb = T["accent_amber"]
                detail_parts.append(f"<span style='color:{c_amb}'>{info['wait']} wait</span>")
            if detail_parts:
                det = QLabel(" · ".join(detail_parts))
                det.setTextFormat(Qt.RichText)
                det.setStyleSheet(f"font-size:{F(9)}px;background:transparent;border:none;")
                cl.addWidget(det)

            self._box_card_layout.addWidget(card, row_i, col_i)
            self._box_cards[b] = card

        # Render remainder reels card (box=0) with distinct style
        if remainder_info and remainder_info["total"] > 0:
            rem_col = "#9333EA"  # purple
            card = QFrame()
            card.setStyleSheet(f"""QFrame {{
                background: #FAF5FF; border: 1.5px solid {rem_col};
                border-radius: {S(8)}px; border-left: 4px solid {rem_col};
            }}""")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(S(8), S(6), S(8), S(6))
            cl.setSpacing(S(3))
            hdr = QHBoxLayout()
            box_lbl = QLabel("📋 Remainder (next order)")
            box_lbl.setStyleSheet(f"font-size:{F(11)}px;font-weight:bold;"
                                  f"color:{rem_col};background:transparent;border:none;")
            r_done = remainder_info["done"] == remainder_info["total"] and remainder_info["total"] > 0
            st_txt = "✅ Done" if r_done else f"▶ {remainder_info['done']}/{remainder_info['total']}"
            st_lbl = QLabel(st_txt)
            st_lbl.setStyleSheet(f"font-size:{F(10)}px;font-weight:bold;"
                                 f"color:{rem_col};background:transparent;border:none;")
            st_lbl.setAlignment(Qt.AlignRight)
            hdr.addWidget(box_lbl); hdr.addStretch(); hdr.addWidget(st_lbl)
            cl.addLayout(hdr)
            val_lbl = QLabel(f"{remainder_info['actual']:,} pcs · {remainder_info['total']} reel(s)")
            val_lbl.setStyleSheet(f"font-size:{F(12)}px;font-weight:bold;"
                                  f"color:{T['text_primary']};background:transparent;border:none;")
            cl.addWidget(val_lbl)
            row_i, col_i = divmod(len(boxes), max(cols, 1))
            self._box_card_layout.addWidget(card, row_i, col_i)
            self._box_cards[0] = card

        # Restore box=0 for live data push
        if remainder_info:
            boxes[0] = remainder_info

        self._push_live_data(boxes, max_box)

    # ─── Push data to live server ────────────────────────────

    def _push_live_data(self, boxes, max_box):
        try:
            # Include historical reels from previous lots
            hist_reels = []
            hist_boxes = {}
            saved = self._state.get("saved_state") or {}
            for h in saved.get("lot_history", []):
                for rd in h.get("reels", []):
                    note = rd.get("note", "")
                    if note.startswith("Pulled"):
                        continue
                    b = rd.get("box", 0)
                    actual_v = rd.get("actual", 0)
                    hist_reels.append({
                        "box": b, "reel": rd.get("reel", 0),
                        "lot": rd.get("lot", "—"),
                        "target": rd.get("target", 0),
                        "actual": actual_v,
                        "reject": rd.get("reject", 0),
                        "diff": rd.get("diff", 0),
                        "status": "done" if actual_v > 0 else "wait",
                        "note": note,
                    })
                    if b not in hist_boxes:
                        hist_boxes[b] = {
                            "target": 0, "actual": 0, "done": 0,
                            "total": 0, "reject": 0, "wait": 0}
                    hist_boxes[b]["total"] += 1
                    hist_boxes[b]["target"] += rd.get("target", 0)
                    hist_boxes[b]["actual"] += actual_v
                    hist_boxes[b]["reject"] += rd.get("reject", 0)
                    if actual_v > 0:
                        hist_boxes[b]["done"] += 1

            # Current lot reels
            reels = []
            for i, row in enumerate(self.plan):
                r = {"box": row["box"], "reel": row["reel"],
                     "target": row["target"],
                     "lot": row.get("lot", "—"),
                     "note": row.get("note", "")}
                a = self.actuals[i]
                if a is not None:
                    r["actual"] = a["actual"]
                    r["reject"] = a.get("reject", 0)
                    r["diff"] = a["actual"] - row["target"]
                    r["status"] = "done"
                elif i == self.current_idx:
                    r["status"] = "current"
                elif row.get("note") == "Wait next lot":
                    r["status"] = "wait"
                else:
                    r["status"] = "pending"
                reels.append(r)

            # Merge historical + current boxes
            box_data = {}
            for b, info in hist_boxes.items():
                box_data[str(b)] = dict(info)
            for b, info in boxes.items():
                sb = str(b)
                if sb in box_data:
                    box_data[sb]["target"] += info["target"]
                    box_data[sb]["actual"] += info["actual"]
                    box_data[sb]["done"] += info["done"]
                    box_data[sb]["total"] += info["total"]
                    box_data[sb]["reject"] += info["reject"]
                    box_data[sb]["wait"] += info["wait"]
                else:
                    box_data[sb] = {
                        "target": info["target"], "actual": info["actual"],
                        "done": info["done"], "total": info["total"],
                        "reject": info["reject"], "wait": info["wait"]}

            all_reels = hist_reels + reels
            packable = [r for r in all_reels if r.get("note") != "Wait next lot"]
            confirmed = [r for r in all_reels if r.get("status") == "done"]
            total_target = sum(r["target"] for r in packable)
            total_actual = sum(r.get("actual", 0) for r in confirmed)
            total_reject = sum(r.get("reject", 0) for r in confirmed)

            update_live_data({
                "invoice":   self._order_info.get("invoice", ""),
                "product":   self._order_info.get("product", ""),
                "order_qty": self._order_info.get("order_qty", 0),  # [FIX]
                "progress": f"{len(confirmed)}/{len(packable)}",
                "max_box": max_box,
                "totals": {
                    "target": total_target,
                    "actual": total_actual,
                    "reject": total_reject,
                    "diff": total_actual - total_target,
                },
                "reels": all_reels,
                "boxes": box_data,
            })
        except Exception:
            pass  # live server is optional — never block the main process

    # ─── Export CSV ──────────────────────────────────────────

    def _export_csv(self, auto_save=False):
        confirmed = [i for i, a in enumerate(self.actuals) if a is not None]
        if not confirmed:
            if not auto_save: QMessageBox.warning(self, "Warning", "No reels confirmed yet")
            return
        order = self._order_info
        inv_tag = order.get("invoice", "BATCH").replace("/", "-").replace("\\", "-")
        d = datetime.now()
        ship = order.get("ship_date", f"{d.year:04d}{d.month:02d}{d.day:02d}")
        dest = order.get("dest", "DEST").replace(" ", "")
        default_name = f"PackingLog_{inv_tag}_{ship}_{dest}.csv"
        output_dir = os.path.join(self._config.output_folder, "LogPack")
        os.makedirs(output_dir, exist_ok=True)
        if auto_save:
            fp = os.path.join(output_dir, default_name)
        else:
            fp, _ = QFileDialog.getSaveFileName(
                self, "Save Packing Log",
                os.path.join(output_dir, default_name), "CSV Files (*.csv)")
        if not fp:
            return
        try:
            self._write_csv(fp, confirmed)
            if not auto_save:
                QMessageBox.information(self, "Export Success", f"CSV exported: {os.path.basename(fp)}")
        except Exception as e:
            if not auto_save:
                QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")

    def _write_csv(self, filepath, indices):
        columns = ["DateTime", "InvoiceNo", "Box", "ReelNo", "Lot",
                    "OperatorID", "Shift", "Target", "Actual", "Reject",
                    "Diff", "BoxTargetTotal", "BoxActualTotal", "Note"]
        box_target, box_actual = {}, {}
        for i in indices:
            b = self.plan[i]["box"]
            box_target[b] = box_target.get(b, 0) + self.plan[i]["target"]
            box_actual[b] = box_actual.get(b, 0) + self.actuals[i]["actual"]
        order = self._order_info
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["# Invoice", order.get("invoice", "")])
            w.writerow(["# Operator", self._operator_edit.text().strip()])
            w.writerow(["# Shift", self._shift_combo.currentText()])
            w.writerow(["# Exported", datetime.now().replace(microsecond=0).isoformat(" ")])
            w.writerow([])
            dw = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            dw.writeheader()
            for i in indices:
                row = self.plan[i]; act = self.actuals[i]; b = row["box"]
                is_last = (i == indices[-1]) or (
                    i + 1 < len(self.plan) and self.plan[i + 1]["box"] != b)
                dw.writerow({
                    "DateTime": act["time"], "InvoiceNo": order.get("invoice", ""),
                    "Box": row["box"], "ReelNo": row["reel"], "Lot": row["lot"],
                    "OperatorID": self._operator_edit.text().strip(),
                    "Shift": self._shift_combo.currentText(),
                    "Target": row["target"], "Actual": act["actual"],
                    "Reject": act.get("reject", 0), "Diff": act["diff"],
                    "BoxTargetTotal": box_target[b] if is_last else "",
                    "BoxActualTotal": box_actual[b] if is_last else "",
                    "Note": act["note"],
                })

    # ─── Real-time backup ────────────────────────────────────

    def _backup_txt(self):
        try:
            output_dir = os.path.join(self._config.output_folder, "LogPack")
            os.makedirs(output_dir, exist_ok=True)
            order = self._order_info
            inv_tag = order.get("invoice", "BATCH").replace("/", "-").replace("\\", "-")
            d = datetime.now()
            ship = order.get("ship_date", f"{d.year:04d}{d.month:02d}{d.day:02d}")
            dest = order.get("dest", "DEST").replace(" ", "")
            fname = f"PackingLog_{inv_tag}_{ship}_{dest}_backup.txt"
            fpath = os.path.join(output_dir, fname)
            confirmed = [i for i, a in enumerate(self.actuals) if a is not None]
            if not confirmed:
                return
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(f"Packing Log Backup — {datetime.now().replace(microsecond=0).isoformat(' ')}\n")
                f.write(f"Invoice: {order.get('invoice','')}  |  "
                        f"Operator: {self._operator_edit.text().strip()}  |  "
                        f"Shift: {self._shift_combo.currentText()}\n")
                f.write(f"{'='*80}\n")
                f.write(f"{'Box':>5} {'Reel':>6} {'Lot':<14} {'Target':>8} {'Actual':>8} {'Reject':>8} {'Diff':>8}  Note\n")
                f.write(f"{'-'*80}\n")
                for i in confirmed:
                    r = self.plan[i]; a = self.actuals[i]
                    diff_s = f"+{a['diff']}" if a['diff'] > 0 else str(a['diff'])
                    f.write(f"{r['box']:>5} {r['reel']:>6} {r['lot']:<14} "
                            f"{r['target']:>8,} {a['actual']:>8,} {a.get('reject',0):>8,} "
                            f"{diff_s:>8}  {a.get('note','')}\n")
                f.write(f"{'-'*80}\n")
                tt = sum(self.plan[i]["target"] for i in confirmed)
                ta = sum(self.actuals[i]["actual"] for i in confirmed)
                tr = sum(self.actuals[i].get("reject", 0) for i in confirmed)
                td = ta - tt
                f.write(f"{'TOTAL':>26} {tt:>8,} {ta:>8,} {tr:>8,} "
                        f"{'+'if td>0 else ''}{td:>7,}\n")
                f.write(f"Progress: {len(confirmed)} / {len(self.plan)} reels\n")
        except Exception:
            pass

    # ─── Web sync ────────────────────────────────────────────

    def set_live_server(self, server):
        """Link the LiveServer instance so broadcasts work."""
        self._live_server = server

    def get_web_state(self) -> dict:
        """Serialize current monitor state for web clients."""
        plan_rows = []
        for i, row in enumerate(self.plan):
            act = self.actuals[i]
            is_wait = row.get("note") == "Wait next lot"
            if is_wait:
                status = "wait"
            elif act is not None:
                status = "done"
            elif i == self.current_idx:
                status = "current"
            else:
                status = "pending"
            plan_rows.append({
                "box":    row["box"],
                "reel":   row["reel"],
                "lot":    row.get("lot", ""),
                "target": row["target"],
                "actual": act.get("actual") if act else None,
                "reject": act.get("reject") if act else None,
                "status": status,
                "note":   row.get("note", ""),
            })

        total_actual = sum(
            self.actuals[i].get("actual", 0)
            for i in range(len(self.plan))
            if self.actuals[i] is not None
            and self.plan[i].get("note") != "Wait next lot"
            and self.plan[i].get("box", 0) != 0)
        total_reject = sum(
            self.actuals[i].get("reject", 0)
            for i in range(len(self.plan))
            if self.actuals[i] is not None)

        order_info  = self._order_info or {}
        saved_state = self._state.get("saved_state") or {}
        # [FIX] fallback to saved_state.order_qty if order_info doesn't carry it yet
        order_qty   = (order_info.get("order_qty")
                       or saved_state.get("order_qty", 0))
        prev_packed = saved_state.get("packed", 0)

        cur_reel = (self.plan[self.current_idx]["reel"]
                    if self.current_idx < len(self.plan) else None)

        return {
            "invoice":      order_info.get("invoice", ""),
            "dest":         order_info.get("dest", ""),
            "ship_date":    order_info.get("ship_date", ""),
            "order_qty":    order_qty,
            "total_packed": prev_packed + total_actual,
            "total_reject": total_reject,
            "remaining":    max(0, order_qty - prev_packed - total_actual),
            "current_reel": cur_reel,
            "plan":         plan_rows,
            "lot_history":  saved_state.get("lot_history", []),
            "timestamp":    datetime.now().isoformat(),
        }

    def apply_web_submit(self, reel_no: int, actual: int, reject: int):
        """
        Called on the Qt main thread (via _poll_web_queue).
        Confirms the given reel with the supplied values.
        Returns (success: bool, message: str).
        """
        if not self._has_plan:
            return False, "No active plan"

        # Ensure the requested reel is the current one
        if self.current_idx >= len(self.plan):
            return False, "All reels already confirmed"

        cur_row = self.plan[self.current_idx]
        if cur_row.get("reel") != reel_no:
            cur_r = cur_row.get("reel", "?")
            return False, (
                f"Can only submit current reel (R{cur_r}), received R{reel_no}")

        # Set spinbox values and confirm via the normal path
        self._actual_spin.setValue(actual)
        self._reject_spin.setValue(reject)
        self._note_edit.clear()
        self._web_submit_mode = True
        try:
            self._confirm_reel()
        finally:
            self._web_submit_mode = False

        return True, f"Reel {reel_no} confirmed: actual={actual:,}, reject={reject:,}"

    def _poll_web_queue(self):
        """QTimer slot — drain the submit queue on the Qt main thread."""
        try:
            while True:
                reel_no, actual, reject, ev, holder = \
                    self._web_queue.get_nowait()
                try:
                    if reel_no == "__replan__":
                        holder["success"] = False
                        holder["error"]   = "Manual replan not yet supported from web"
                    else:
                        ok, msg = self.apply_web_submit(reel_no, actual, reject)
                        holder["success"] = ok
                        holder["message"] = msg
                        if not ok:
                            holder["error"] = msg
                except Exception as exc:
                    holder["success"] = False
                    holder["error"]   = str(exc)
                finally:
                    ev.set()
        except queue.Empty:
            pass

    def _broadcast_web_state(self):
        """Push current state to all WebSocket clients if server is linked."""
        if self._live_server is None:
            return
        try:
            self._live_server.broadcast(self.get_web_state())
        except Exception:
            pass

    def _show_lan_info(self):
        """Open NetworkInfoDialog showing LAN URL and QR code."""
        try:
            from ui.network_info_dialog import show_network_info
            show_network_info(self, self._live_server)
        except Exception as exc:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "LAN Info", str(exc))

    # ─── Finish ──────────────────────────────────────────────

    def _finish(self):
        packable = [i for i, r in enumerate(self.plan) if r.get("note") != "Wait next lot"]
        confirmed = sum(1 for i in packable if self.actuals[i] is not None)
        total = len(packable)
        total_actual = sum(a["actual"] for a in self.actuals if a is not None)
        total_target = sum(self.plan[i]["target"] for i in packable)
        diff = total_actual - total_target
        if diff == 0:
            diff_text = "Exact match ✔"
        elif diff > 0:
            diff_text = f"Over by {diff:,} pcs."
        else:
            diff_text = f"Under by {abs(diff):,} pcs."

        wait_boxes = {}
        for i, row in enumerate(self.plan):
            b = row["box"]
            if b not in wait_boxes:
                wait_boxes[b] = {"wait_slots": 0, "packed": 0, "target": 0}
            if row.get("note") == "Wait next lot":
                wait_boxes[b]["wait_slots"] += 1
            else:
                wait_boxes[b]["target"] += row["target"]
                if self.actuals[i] is not None:
                    wait_boxes[b]["packed"] += self.actuals[i]["actual"]
        incomplete_boxes = {b: info for b, info in wait_boxes.items()
                           if info["wait_slots"] > 0 and b != 0}
        incomplete = confirmed < total
        dlg = _MonitorSummaryDialog(
            confirmed, total_target, total_actual, diff_text,
            incomplete=incomplete,
            incomplete_boxes=incomplete_boxes if incomplete_boxes else None,
            max_per_box=int(getattr(self._config, 'max_per_box', 6400)),
            parent=self)
        result = dlg.exec_()
        if result == _MonitorSummaryDialog.CANCEL_CODE:
            return
        if result == QDialog.Accepted:
            self._export_csv(auto_save=True)

        self._state["monitor_actuals"] = self.actuals
        self._state["monitor_plan"]    = self.plan
        self.monitor_finished.emit()