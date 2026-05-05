#!/usr/bin/env python3
"""
AutoPack VLO-127S — Main Entry Point
======================================
Single-window application with sidebar navigation and blue/white theme.
All business logic from the original planner is preserved.

FIXES APPLIED:
  [FIX-1] import math ย้ายขึ้นบนสุด (ออกจาก if-block)
  [FIX-2] plan_state ถูก snapshot ก่อน ป้องกัน mutation ระหว่าง loop
  [FIX-3] reel_details pull ใช้ index แทน box+reel lookup (ป้องกัน duplicate key)
  [FIX-4] carry_lot_val รับประกัน reset เมื่อ carry_remainder=0
  [FIX-5] box_total ใน reopen logic ใช้แหล่งเดียว (ลบ hist_actual_by_box ออก)
  [FIX-6] open_boxes_list เพิ่ม guard ตรวจ real reel count ป้องกัน Box ที่หายจาก tracking
  [FIX-7] _distribute_balanced_reels assert เปลี่ยนเป็น auto-fix (ใน calculation_engine)
"""
import sys, os, locale, math
from datetime import datetime
from collections import defaultdict

VERSION = "1.0.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QMessageBox, QDialog,
    QLabel, QPushButton, QFrame, QProgressBar,
)
from PyQt5.QtCore import Qt, QTimer, QLocale

from ui.theme import THEME, S, F, _screen_scale, make_stylesheet
from ui.sidebar import Sidebar
from ui.dashboard import DashboardPage
from ui.planner_page import PlannerPage
from ui.monitor_page import MonitorPage
from ui.history_page import HistoryPage
from ui.settings_page import SettingsPage
from ui.log_panel import LogPanel

from core.logger import AppLogger
from core.history import PlanHistoryStore
from core.state import _save_state, _load_state, _clear_state
from core.csv_export import export_leftover_csv, export_reject_csv, export_final_plan_csv, auto_save_logpack
from core.live_server import start_live_server, update_live_data, LiveServer
from core.smart_replan import find_smart_split

from app.core.config_manager import ConfigManager
from app.core.calculation_engine import _distribute_reels
# ══════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self._config = config or ConfigManager()

        self._app_state = {
            "saved_state": None,
            "current_monitor": None,
            "monitor_actuals": None,
            "monitor_plan": None,
        }
        self._live_server: LiveServer | None = None

        folder = self._config.output_folder
        os.makedirs(folder, exist_ok=True)
        self._logger = AppLogger(folder)
        self._history = PlanHistoryStore(folder)
        self._current_plan = []
        self._current_order_info = {}

        self._setup_window()
        self._build_ui()
        self._connect_logger()

        saved = _load_state(self._config)
        if saved:
            self._handle_saved_state(saved)
        else:
            self._planner_page.load_defaults()

        self._logger.info("AutoPack VLO-127S started (Modern UI)")

    def _setup_window(self):
        sc = _screen_scale()
        self.setWindowTitle(f"AutoPack VLO-127S  v{VERSION}  —  Packing Planner")
        self.setMinimumSize(S(900), S(580))
        self.setStyleSheet(make_stylesheet(sc))
        self.showMaximized()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.page_changed.connect(self._on_page_change)
        root.addWidget(self._sidebar)

        right_area = QWidget()
        right_lay = QVBoxLayout(right_area)
        right_lay.setContentsMargins(0, 0, 0, 0); right_lay.setSpacing(0)

        self._stack = QStackedWidget()

        self._dashboard_page = DashboardPage(self._app_state)
        self._planner_page = PlannerPage(
            self._config, self._app_state, self._logger, self._history)
        self._monitor_page = MonitorPage(
            self._config, self._app_state, self._logger)
        self._history_page = HistoryPage(self._history, self._logger)
        self._settings_page = SettingsPage(self._config, self._logger)

        for page in [self._dashboard_page, self._planner_page,
                     self._monitor_page, self._history_page, self._settings_page]:
            self._stack.addWidget(page)

        right_lay.addWidget(self._stack)
        self._log_panel = LogPanel()
        right_lay.addWidget(self._log_panel)
        root.addWidget(right_area)

        self._planner_page.plan_ready.connect(self._on_plan_ready)
        self._monitor_page.monitor_finished.connect(self._on_monitor_finished)

        # Start legacy redirect (:5050) + interactive LAN monitor (:8000 HTTP + :8001 WS)
        # start_live_server() auto-wires MonitorPage → LiveServer.
        self._live_server = start_live_server(
            port=5050,                       # legacy redirect server
            live_port=8000,                  # interactive HTTP/WS server
            monitor_page=self._monitor_page,
            config=self._config,
            logger=self._logger,
        )
        if self._live_server is None:
            self._logger.warning(
                "LAN interactive monitor did NOT start — "
                "install 'websockets' with:  pip install websockets")

    def _connect_logger(self):
        self._logger.add_callback(
            lambda line, lvl: QTimer.singleShot(
                0, lambda: self._log_panel.append(line, lvl)))

    def _on_page_change(self, idx):
        self._stack.setCurrentIndex(idx)
        if idx == 0:
            self._dashboard_page.refresh()
        elif idx == 3:
            self._history_page.reload()

    def _handle_saved_state(self, saved):
        self._app_state["saved_state"] = saved

        packed = saved.get("packed", 0)
        order = saved.get("order_qty", 0)
        product = saved.get("product", "")
        carry = saved.get("carry_remainder", 0)
        carry_lot = saved.get("carry_lot", "")

        carry_msg = f"\nCarry from {carry_lot}: {carry:,} pcs." if carry > 0 else ""

        resume_dlg = QMessageBox()
        resume_dlg.setWindowTitle("Resume Lot-by-Lot")
        resume_dlg.setText(
            f"Found saved progress for {product}:\n"
            f"Packed: {packed:,} / {order:,}  ({packed*100//max(order,1)}%)"
            f"{carry_msg}\n\n"
            f"Resume or start a new order?")
        btn_resume = resume_dlg.addButton("Resume", QMessageBox.AcceptRole)
        btn_new = resume_dlg.addButton("New Order", QMessageBox.RejectRole)
        resume_dlg.setDefaultButton(btn_resume)
        resume_dlg.exec_()

        if resume_dlg.clickedButton() == btn_new:
            _clear_state(self._config)
            self._app_state["saved_state"] = None
            # If carry exists, offer to import it into the new order
            if carry > 0:
                carry_state = {
                    "carry_remainder": carry,
                    "carry_lot":       carry_lot,
                    "lot_history":     [],
                    "max_box":         self._config.max_per_box,
                    "max_reel":        self._config.max_per_reel,
                    "min_reel":        self._config.min_per_reel,
                    "reels_per_box":   self._config.reels_per_box,
                }
                self._planner_page.load_state(carry_state)
            else:
                self._planner_page.load_defaults()
        else:
            # Load state into planner AND app_state
            self._app_state["saved_state"] = saved
            self._planner_page.load_state(saved)
            self._dashboard_page.refresh()
            self._sidebar.select(1)

    def _on_plan_ready(self, plan, order_info):
        self._current_plan = plan
        self._current_order_info = order_info
        self._monitor_page.set_plan(plan, order_info)
        self._sidebar.select(2)
        self._logger.plan(f"Plan ready: {len(plan)} reels → switching to Monitor")

    # ══════════════════════════════════════════════════════════
    #  POST-MONITOR PROCESSING
    # ══════════════════════════════════════════════════════════

    def _on_monitor_finished(self):
        """Called after MonitorPage finishes — run post-processing.

        FIXES:
          [FIX-1] math imported at top of file
          [FIX-2] plan_state snapshot → commit once at end
          [FIX-3] pull row lookup by index (not box+reel)
          [FIX-4] carry_lot_val always reset when carry_remainder=0
          [FIX-5] reopen box_total uses single source (no double-count)
          [FIX-6] open_boxes_list guaranteed to include all under-filled boxes
        """
        monitor_actuals = self._monitor_page.actuals
        monitor_plan = self._monitor_page.plan
        pack_plan = monitor_plan if monitor_plan else self._current_plan

        planner = self._planner_page
        plan_state = planner._plan_state
        is_lot_by_lot = (plan_state is not None)

        invoice_no = planner.product_edit.text().strip()
        d_qt = planner.shipment_date.date()
        ship_date = f"{d_qt.year():04d}{d_qt.month():02d}{d_qt.day():02d}"
        dest = planner.dest_combo.currentText()

        if not is_lot_by_lot:
            self._logger.info("Batch mode monitor complete")
            self._sidebar.select(0)
            return

        # [FIX-2] Snapshot plan_state — ป้องกัน mutation ระหว่าง loop
        # ใช้ local_ps แทน plan_state ตลอด แล้ว commit กลับทีเดียวตอนท้าย
        local_ps = dict(plan_state)

        st = getattr(planner, '_saved_state', None) or {}
        actuals = monitor_actuals

        # ── Gather actuals (skip wait rows) ──
        total_actual, total_reject, reel_details = \
            self._gather_actuals(pack_plan, actuals)

        prev_packed = st.get("packed", 0)
        lot_history = st.get("lot_history", [])
        # [FIX-11] ปรับปรุง fallback ของ current_lot ให้ robust
        # ถ้า pack_plan ทุกตัวเป็น Carry/Wait (เช่นหลัง Defer ทั้งลอต) ต้องดึงจาก planner_page
        current_lot = self._resolve_current_lot(pack_plan, planner)

        # [FIX-BUG-A] Map lot_input ตาม current_lot (ไม่ใช่ row 0 ตาบอด)
        # เดิม: lot_input = planner._lot_rows[0].qty_spin.value()
        # ปัญหา: ถ้า lot ปัจจุบันไม่ใช่ row แรก (เช่น lot 2,3,...) input จะผิด
        # ทำให้ Lot Summary ใน CSV มี Input ไม่ตรงกับ Packed
        lot_input = 0
        for _row in planner._lot_rows:
            _d = _row.get_data()
            if _d.get("lot_no") == current_lot:
                lot_input = _d.get("qty", 0)
                break
        if lot_input == 0 and planner._lot_rows:
            # Fallback เผื่อ UI sync ไม่ทัน (เช่น lot ถูกลบไปแล้ว)
            lot_input = planner._lot_rows[0].qty_spin.value()
            self._logger.warning(
                f"[lot_input fallback] current_lot={current_lot!r} not found in "
                f"_lot_rows → using row[0] qty={lot_input}")

        # ── carry_remainder calculation ──
        algo_remainder = local_ps.get("lot_remainder", 0)
        algo_carry = max(0, algo_remainder - total_reject)
        carry_placed = local_ps.get("carry_placed", False)
        carry_remainder_out = local_ps.get("carry_remainder_out", 0)
        MIN_CARRY = st.get("min_reel", planner._c_min_reel)
        MAX_BOX = st.get("max_box", planner._c_max_box)

        scrap_qty = 0
        carry_remainder = 0
        carry_lot_val = ""      # [FIX-4] เริ่มต้นเป็น "" เสมอ

        if carry_placed:
            carry_remainder = algo_carry
            carry_lot_val = current_lot if algo_carry > 0 else ""
            if carry_remainder_out > 0:
                if carry_remainder_out >= MIN_CARRY:
                    if algo_carry >= MIN_CARRY:
                        if algo_carry > carry_remainder_out:
                            scrap_qty += carry_remainder_out
                        else:
                            scrap_qty += algo_carry
                            carry_remainder = carry_remainder_out
                            carry_lot_val = st.get("carry_lot", "") if carry_remainder > 0 else ""
                    else:
                        if algo_carry > 0:
                            scrap_qty += algo_carry
                        carry_remainder = carry_remainder_out
                        carry_lot_val = st.get("carry_lot", "") if carry_remainder > 0 else ""
                else:
                    scrap_qty += carry_remainder_out
        else:
            prev_carry = carry_remainder_out
            prev_carry_lot = st.get("carry_lot", "")
            if prev_carry > 0:
                carry_remainder = prev_carry
                carry_lot_val = prev_carry_lot if prev_carry > 0 else ""
            else:
                carry_remainder = algo_carry
                carry_lot_val = current_lot if algo_carry > 0 else ""
            if carry_placed is False and prev_carry > 0 and algo_carry > 0:
                if algo_carry < MIN_CARRY:
                    scrap_qty += algo_carry
                else:
                    if algo_carry > prev_carry:
                        scrap_qty += prev_carry
                        carry_remainder = algo_carry
                        carry_lot_val = current_lot
                    else:
                        scrap_qty += algo_carry

        # [FIX-4] ล็อก: ถ้า carry_remainder=0 ให้ carry_lot_val="" เสมอ
        if carry_remainder <= 0:
            carry_remainder = 0
            carry_lot_val = ""

        # ── Redistribute / reject-pull logic ──
        extra_carry_reels = []      # list of (src_idx_in_reel_details, box_id)
        forced_wait_boxes = {}
        redist_pulled = []
        redist_new_boxes = {}

        MAX_REEL = st.get("max_reel", planner._c_max_reel)
        RPB = st.get("reels_per_box", planner._c_reels_per_box)

        if 0 < carry_remainder < MIN_CARRY:
            redistributed = False
            order_qty_pre = st.get("order_qty", planner.invoice_qty_spin.value())
            if prev_packed + total_actual < order_qty_pre:
                for rd_idx, rd in enumerate(reversed(reel_details)):
                    real_idx = len(reel_details) - 1 - rd_idx   # index จริงใน reel_details
                    if rd.get("reject", 0) <= 0:
                        continue
                    pulled_actual = rd.get("actual", 0)
                    redist_total = carry_remainder + pulled_actual
                    if redist_total < 2 * MIN_CARRY:
                        continue
                    box_id = rd["box"]
                    orig_reject = rd["reject"]

                    # [FIX-3] Disable โดยใช้ index จริง ไม่ใช่ box+reel lookup
                    reel_details[real_idx]["note"] = f"Pulled (redistribute, rej {orig_reject:,})"
                    reel_details[real_idx]["actual"] = 0
                    reel_details[real_idx]["target"] = 0
                    reel_details[real_idx]["diff"] = 0
                    total_actual -= pulled_actual

                    src_plan_idx = rd.get("_src_idx")
                    if src_plan_idx is not None:
                        redist_pulled.append((src_plan_idx, pack_plan[src_plan_idx],
                                              actuals[src_plan_idx], box_id))
                        forced_wait_boxes[box_id] = forced_wait_boxes.get(box_id, 0) + 1

                    num_redist = min(RPB - 1, redist_total // MIN_CARRY)
                    num_redist = max(1, num_redist)
                    while num_redist > 1:
                        per = redist_total // num_redist
                        if per > MAX_REEL:
                            num_redist += 1; num_redist = min(num_redist, RPB - 1); break
                        if per < MIN_CARRY:
                            num_redist -= 1
                        else:
                            break
                    num_redist = max(1, min(num_redist, RPB - 1))
                    redist_reels = _distribute_reels(redist_total, num_redist, MIN_CARRY, MAX_REEL)

                    # [FIX-2] ใช้ local_ps แทน plan_state
                    if redist_total < MAX_BOX:
                        new_reel_start = local_ps.get("next_reel", rd["reel"] + 1)
                        for ri, rq in enumerate(redist_reels):
                            reel_details.append({
                                "_src_idx": None,
                                "box": 0, "reel": new_reel_start + ri, "lot": current_lot,
                                "target": rq, "actual": rq, "diff": 0, "reject": 0,
                                "note": f"Remainder (Redistributed Rej:{orig_reject:,})" if ri == 0 else "Remainder (Redistributed)",
                            })
                        local_ps["next_reel"] = new_reel_start + num_redist
                    else:
                        new_box = local_ps.get("next_box", box_id + 1)
                        new_reel_start = local_ps.get("next_reel", rd["reel"] + 1)
                        for ri, rq in enumerate(redist_reels):
                            reel_details.append({
                                "_src_idx": None,
                                "box": new_box, "reel": new_reel_start + ri, "lot": current_lot,
                                "target": rq, "actual": rq, "diff": 0, "reject": 0,
                                "note": f"Redistributed Rej:{orig_reject:,}" if ri == 0 else "Redistributed",
                            })
                            total_actual += rq
                        wait_in_new = RPB - num_redist
                        redist_new_boxes[new_box] = {"total": sum(redist_reels), "wait": wait_in_new}
                        local_ps["next_reel"] = new_reel_start + num_redist + wait_in_new
                        local_ps["next_box"] = new_box + 1

                    carry_remainder = 0
                    carry_lot_val = ""          # [FIX-4]
                    redistributed = True
                    break
            if not redistributed:
                scrap_qty += carry_remainder
                carry_remainder = 0
                carry_lot_val = ""              # [FIX-4]

        # ── Reject/Diff-pull: reopen under-filled boxes ──
        order_qty_check = st.get("order_qty", planner.invoice_qty_spin.value())
        new_packed_check = prev_packed + total_actual

        # [FIX-AUTO-PULL] เช็คว่า lot นี้ "ปิด order" แล้วหรือยัง:
        # ถ้า packed รวมในรอบนี้ + carry ที่จะ pack ใน lot ถัดไป >= order_qty
        # = lot นี้คือ lot สุดท้ายที่ pack จริง — ไม่ควร auto-pull (silent)
        # เพราะไม่มี lot ในอนาคตจะมาเติม Box ที่ underfill
        # หมายเหตุ: ถ้ามี reject/diff ผู้ใช้ยังควรเห็น dialog เพื่อตัดสินใจเอง
        _will_carry_pack_next = carry_remainder if carry_remainder >= MIN_CARRY else 0
        _is_order_closing_lot = (new_packed_check + _will_carry_pack_next
                                 >= order_qty_check)

        if new_packed_check < order_qty_check:
            box_reels_map = defaultdict(list)
            for i, r in enumerate(pack_plan):
                if r.get("note") == "Wait next lot":
                    continue
                if actuals[i] is None:
                    continue
                box_reels_map[r["box"]].append((i, r, actuals[i]))

            saved_open_boxes = st.get("open_boxes", [])
            hist_box_totals = {ob["box"]: ob.get("current_total", 0) for ob in saved_open_boxes}
            hist_reel_count = defaultdict(int)
            for h in lot_history:
                for rd in h.get("reels", []):
                    if not rd.get("note", "").startswith("Pulled"):
                        hist_reel_count[rd["box"]] += 1

            for box_id, box_entries in box_reels_map.items():
                has_wait = any(r.get("note") == "Wait next lot"
                              for r in pack_plan if r["box"] == box_id)
                if has_wait:
                    continue
                hist_total = hist_box_totals.get(box_id, 0)
                plan_actual = sum(a.get("actual", 0) for _, _, a in box_entries)
                box_actual = hist_total + plan_actual
                box_reject = sum(a.get("reject", 0) for _, _, a in box_entries)
                if box_actual >= MAX_BOX:
                    continue
                has_diff_underfill = any(
                    a.get("actual", 0) < r.get("target", 0)
                    and a.get("reject", 0) <= 0
                    for _, r, a in box_entries)
                current_reels = len(box_entries)
                total_phys = hist_reel_count.get(box_id, 0) + current_reels
                has_full_reel_underfill = (total_phys >= RPB and box_actual < MAX_BOX)
                if (box_reject <= 0 and not has_diff_underfill
                        and not has_full_reel_underfill):
                    continue
                lot_entries = [(i, r, a) for i, r, a in box_entries
                               if r.get("note") != "Carry" and r.get("lot") == current_lot]
                if not lot_entries:
                    continue
                last_idx, last_row, last_act = lot_entries[-1]
                last_actual = last_act.get("actual", 0)
                if last_actual < MIN_CARRY:
                    continue

                if total_phys >= RPB:
                    deficit = MAX_BOX - box_actual
                    auto_pull = has_full_reel_underfill and not (box_reject > 0 or has_diff_underfill)

                    # [FIX-AUTO-PULL] ห้าม silent auto-pull ถ้า lot นี้ปิด order
                    # เหตุผล: auto-pull มีไว้สำหรับกรณี Box ยัง underfill แต่
                    # ยังมี lot ในอนาคตจะมาเติม → pull reel ออกไป Box ใหม่
                    # เพื่อให้ Box เดิมรอ lot ถัดไป.  แต่ถ้า lot นี้ปิด order
                    # แล้ว ไม่มี lot ใหม่จะมาเติม → pull ออกแล้ว Box ใหม่ก็ไม่
                    # เต็มเหมือนเดิม + อาจวน loop (pack→pull→pack→pull)
                    # ในกรณีนี้ user ควรปิด Box ตามจริง (under-full OK)
                    if auto_pull and _is_order_closing_lot:
                        self._logger.info(
                            f"Box {box_id} underfull ({box_actual:,}/{MAX_BOX:,}, "
                            f"{total_phys} reels): SKIP auto-pull because this "
                            f"lot closes the order (no future lot to refill)")
                        continue

                    if not auto_pull:
                        reason = "Reject" if box_reject > 0 else "Diff"
                        msg = QMessageBox(self)
                        msg.setWindowTitle("Box Underfill")
                        msg.setIcon(QMessageBox.Warning)
                        msg.setText(
                            f"Box {box_id} มี {total_phys} reels แล้ว (สูงสุด {RPB})\n"
                            f"ยอดรวม {box_actual:,} / {MAX_BOX:,} (ขาด {deficit:,})\n"
                            f"สาเหตุ: {reason}\n\n"
                            f"ดึง Reel สุดท้าย ({last_actual:,} pcs) ไป Box ใหม่\n"
                            f"แล้วรอ Lot ถัดไปเติม Box {box_id} ให้ครบ {MAX_BOX:,}?")
                        btn_new = msg.addButton("เปิด Box ใหม่", QMessageBox.AcceptRole)
                        btn_skip = msg.addButton("ปิด Box ตามจริง", QMessageBox.RejectRole)
                        msg.setDefaultButton(btn_new)
                        msg.exec_()
                        if msg.clickedButton() == btn_skip:
                            continue
                    else:
                        self._logger.info(
                            f"Box {box_id} underfull ({box_actual:,}/{MAX_BOX:,}, "
                            f"{total_phys} reels): auto-pull Reel {last_row['reel']} "
                            f"({last_actual:,}) → new Box")

                    # [FIX-1] math อยู่บนสุดแล้ว ไม่ต้อง import ซ้ำ
                    needed_boxes = math.ceil(order_qty_check / max(1, MAX_BOX))
                    all_box_nums = set(r["box"] for r in pack_plan) | set(hist_reel_count.keys())
                    new_box_no = max(all_box_nums) + 1 if all_box_nums else 1
                    overflow_new_box = max(new_box_no, local_ps.get("next_box", 1))  # [FIX-2]

                    if overflow_new_box > needed_boxes:
                        target_box = 0
                        # [FIX-8] หัก total_actual เฉพาะเมื่อ reel นี้เคยถูกบวกเข้าไปจริง
                        # Carry reel (box=0) ถูก skip ใน Gather actuals loop → ไม่ต้องหัก
                        # (ป้องกัน packed ติดลบเมื่อ auto-pull carry reel ไป Box 0)
                        _orig_row = pack_plan[last_idx]
                        if (_orig_row.get("box", 0) != 0
                                and _orig_row.get("note") != "Wait next lot"):
                            total_actual -= last_actual
                    else:
                        target_box = overflow_new_box
                        redist_new_boxes[target_box] = {"total": last_actual, "wait": RPB - 1}
                        local_ps["next_box"] = target_box + 1  # [FIX-2]

                    extra_carry_reels.append((last_idx, last_row, last_act, box_id))
                    reel_details.append({
                        "_src_idx": None,
                        "box": target_box, "reel": last_row["reel"], "lot": last_row["lot"],
                        "target": last_row["target"], "actual": last_actual,
                        "reject": last_act.get("reject", 0),
                        "diff": last_actual - last_row["target"],
                        "note": f"{'Remainder reel (next order)' if target_box == 0 else ''} Moved from Box {box_id} ({'underfill' if auto_pull else 'overflow'})".strip(),
                    })

                    # [FIX-3] ค้นหาแถวที่ต้อง disable โดยใช้ _src_idx ก่อน ถ้าไม่มีค่อย fallback
                    _disabled = False
                    for _rd in reel_details:
                        if (_rd.get("_src_idx") == last_idx
                                and _rd["box"] == box_id
                                and not _rd.get("note", "").startswith("Pulled")):
                            reason = "reject" if last_act.get("reject", 0) > 0 else "diff"
                            _rd["note"] = f"Pulled ({reason})"
                            _rd["actual"] = 0; _rd["target"] = 0; _rd["diff"] = 0
                            _disabled = True
                            break
                    if not _disabled:
                        # fallback: หาจาก reel+box (เผื่อไม่มี _src_idx)
                        for _rd in reel_details:
                            if (_rd["reel"] == last_row["reel"]
                                    and _rd["box"] == box_id
                                    and not _rd.get("note", "").startswith("Pulled")):
                                reason = "reject" if last_act.get("reject", 0) > 0 else "diff"
                                _rd["note"] = f"Pulled ({reason})"
                                _rd["actual"] = 0; _rd["target"] = 0; _rd["diff"] = 0
                                break

                    forced_wait_boxes[box_id] = forced_wait_boxes.get(box_id, 0) + 1
                    continue

                # total_phys < RPB branch
                needed_boxes = math.ceil(order_qty_check / max(1, MAX_BOX))   # [FIX-1]
                all_box_nums = set(r["box"] for r in pack_plan) | set(hist_reel_count.keys())
                new_box_no = max(all_box_nums) + 1 if all_box_nums else 1
                overflow_new_box = max(new_box_no, local_ps.get("next_box", 1))  # [FIX-2]

                if overflow_new_box > needed_boxes:
                    target_box = 0
                    # [FIX-8] หัก total_actual เฉพาะเมื่อ reel นี้เคยถูกบวกเข้าไปจริง
                    # Carry reel (box=0) ถูก skip ใน Gather actuals loop → ไม่ต้องหัก
                    _orig_row = pack_plan[last_idx]
                    if (_orig_row.get("box", 0) != 0
                            and _orig_row.get("note") != "Wait next lot"):
                        total_actual -= last_actual
                else:
                    target_box = overflow_new_box
                    redist_new_boxes[target_box] = {"total": last_actual, "wait": RPB - 1}
                    local_ps["next_box"] = target_box + 1  # [FIX-2]

                extra_carry_reels.append((last_idx, last_row, last_act, box_id))
                reel_details.append({
                    "_src_idx": None,
                    "box": target_box, "reel": last_row["reel"], "lot": last_row["lot"],
                    "target": last_row["target"], "actual": last_actual,
                    "reject": last_act.get("reject", 0),
                    "diff": last_actual - last_row["target"],
                    "note": f"{'Remainder reel (next order)' if target_box == 0 else ''} Moved from Box {box_id}".strip(),
                })

                # [FIX-3] ค้นหาแถว disable ด้วย _src_idx ก่อน
                _disabled = False
                for _rd in reel_details:
                    if (_rd.get("_src_idx") == last_idx
                            and _rd["box"] == box_id
                            and not _rd.get("note", "").startswith("Pulled")):
                        reason = "reject" if last_act.get("reject", 0) > 0 else "diff"
                        _rd["note"] = f"Pulled ({reason})"
                        _rd["actual"] = 0; _rd["target"] = 0; _rd["diff"] = 0
                        _disabled = True
                        break
                if not _disabled:
                    for _rd in reel_details:
                        if (_rd["reel"] == last_row["reel"]
                                and _rd["box"] == box_id
                                and not _rd.get("note", "").startswith("Pulled")):
                            reason = "reject" if last_act.get("reject", 0) > 0 else "diff"
                            _rd["note"] = f"Pulled ({reason})"
                            _rd["actual"] = 0; _rd["target"] = 0; _rd["diff"] = 0
                            break

                forced_wait_boxes[box_id] = 1

        # ── Build open_boxes list ──
        wait_by_box = defaultdict(int)
        actual_by_box = defaultdict(int)
        for i, r in enumerate(pack_plan):
            if r.get("note") == "Wait next lot":
                wait_by_box[r["box"]] += 1
            else:
                if actuals[i] is not None:
                    actual_by_box[r["box"]] += actuals[i].get("actual", 0)
                else:
                    actual_by_box[r["box"]] += r.get("target", 0)

        _saved_ob = st.get("open_boxes", [])
        hist_box_totals_all = {ob["box"]: ob.get("current_total", 0) for ob in _saved_ob}

        open_boxes_list = []
        for box_id in sorted(wait_by_box.keys()):
            if box_id == 0:
                continue
            hist_total_ob = hist_box_totals_all.get(box_id, 0)
            open_boxes_list.append({
                "box": box_id, "slots": wait_by_box[box_id],
                "current_total": actual_by_box[box_id] + hist_total_ob,
            })

        all_pulled = extra_carry_reels + redist_pulled
        for box_id, slots in forced_wait_boxes.items():
            saved_open_boxes_fw = st.get("open_boxes", [])
            hist_fw = next((ob.get("current_total", 0)
                            for ob in saved_open_boxes_fw if ob["box"] == box_id), 0)
            pulled_in_box = set(row["reel"] for _, row, _, bid in all_pulled if bid == box_id)
            plan_actual_adj = sum(
                actuals[i].get("actual", 0)
                for i, r in enumerate(pack_plan)
                if r["box"] == box_id and r.get("note") != "Wait next lot"
                and actuals[i] is not None and r["reel"] not in pulled_in_box)
            box_actual_adj = hist_fw + plan_actual_adj
            existing = next((ob for ob in open_boxes_list if ob["box"] == box_id), None)
            if existing:
                existing["slots"] += slots; existing["current_total"] = box_actual_adj
            else:
                open_boxes_list.append({"box": box_id, "slots": slots, "current_total": box_actual_adj})
        open_boxes_list.sort(key=lambda ob: ob["box"])

        for new_box_id, info in redist_new_boxes.items():
            existing = next((ob for ob in open_boxes_list if ob["box"] == new_box_id), None)
            if existing:
                existing["slots"] += info["wait"]; existing["current_total"] = info["total"]
            else:
                open_boxes_list.append({"box": new_box_id, "slots": info["wait"], "current_total": info["total"]})
        open_boxes_list.sort(key=lambda ob: ob["box"])

        # ── Reopen underfilled sealed boxes ──
        # [FIX-5] ลบ hist_actual_by_box ออกจาก box_total (เคย double-count)
        # [FIX-6] เพิ่ม guard: ตรวจ reel count จริงก่อน reopen
        _pulled_idx_set = ({idx for idx, _, _, _ in extra_carry_reels}
                           | {idx for idx, _, _, _ in redist_pulled})
        all_box_ids_in_plan = set()
        reels_by_box = defaultdict(int)
        for i, r in enumerate(pack_plan):
            if i in _pulled_idx_set:
                continue
            if r.get("note") == "Wait next lot":
                continue
            all_box_ids_in_plan.add(r["box"])
            if actuals[i] is not None:
                reels_by_box[r["box"]] += 1

        hist_reels_by_box = defaultdict(int)
        for h in lot_history:
            for rd in h.get("reels", []):
                if not rd.get("note", "").startswith("Pulled"):
                    hist_reels_by_box[rd["box"]] += 1

        open_box_ids = {ob["box"] for ob in open_boxes_list}
        _saved_ob_check = st.get("open_boxes", [])
        # [FIX-5] ใช้แค่ hist_totals_check (open_boxes state) + actual_by_box ปัจจุบัน
        # ไม่บวก hist_actual_by_box อีก เพราะ hist_totals_check รวม previous actuals ไว้แล้ว
        hist_totals_check = {ob["box"]: ob.get("current_total", 0)
                             for ob in _saved_ob_check}

        for box_id in sorted(all_box_ids_in_plan | set(hist_reels_by_box.keys())):
            if box_id == 0:
                continue
            if box_id in open_box_ids:
                continue  # already open
            total_reels = reels_by_box.get(box_id, 0) + hist_reels_by_box.get(box_id, 0)

            # [FIX-5] box_total จาก 2 แหล่งเท่านั้น (ไม่มี hist_actual_by_box)
            box_total = (actual_by_box.get(box_id, 0)
                         + hist_totals_check.get(box_id, 0))

            # [FIX-6] ตรวจ reel count จริงก่อน reopen
            # ถ้า total_reels >= RPB แสดงว่า box เต็มแล้ว ไม่ควร reopen
            if total_reels >= RPB:
                continue

            if total_reels < RPB and box_total < MAX_BOX:
                remaining_slots = RPB - total_reels
                open_boxes_list.append({
                    "box": box_id,
                    "slots": remaining_slots,
                    "current_total": box_total,
                })
                self._logger.info(
                    f"Reopened Box {box_id}: {box_total:,}/{MAX_BOX:,}, "
                    f"{remaining_slots} slots available")
        open_boxes_list.sort(key=lambda ob: ob["box"])

        redist_wait = sum(v["wait"] for v in redist_new_boxes.values())
        reopened_wait = sum(ob["slots"] for ob in open_boxes_list
                           if ob["box"] not in wait_by_box
                           and ob["box"] not in forced_wait_boxes
                           and ob["box"] not in redist_new_boxes)
        wait_slots = (local_ps.get("wait_slots", 0)          # [FIX-2] ใช้ local_ps
                      + sum(forced_wait_boxes.values())
                      + redist_wait + reopened_wait)

        # ── Deviation ──
        pulled_indices = ({idx for idx, _, _, _ in extra_carry_reels}
                          | {idx for idx, _, _, _ in redist_pulled})
        total_deviation = sum(
            (pack_plan[i]["target"] - actuals[i].get("actual", 0))
            for i in range(len(pack_plan))
            if actuals[i] is not None
            and pack_plan[i].get("note") != "Wait next lot"
            and i not in pulled_indices)

        # ── Remainder reels ──
        remainder_reels = local_ps.get("remainder_reels", [])   # [FIX-2]
        has_remainder_in_plan = any(r.get("box", 0) == 0 for r in pack_plan)
        if not has_remainder_in_plan:
            for rr in remainder_reels:
                reel_details.append({
                    "_src_idx": None,
                    "box": 0, "reel": rr["reel"], "lot": rr["lot"],
                    "target": rr["target"], "actual": rr["target"],
                    "reject": 0, "diff": 0,
                    "note": rr.get("note", "Remainder reel (next order)"),
                })

        # ── Scrap warning: lot excess below min_reel ──
        _lot_excess = local_ps.get("lot_excess", 0)             # [FIX-2]
        _remainder_total = local_ps.get("remainder_total", 0)   # [FIX-2]
        if (not remainder_reels and _remainder_total > 0
                and _remainder_total < MIN_CARRY):
            _pullable_rd = None
            _pullable_rd_idx = None
            for _ri, _rd in enumerate(reversed(reel_details)):
                _real_i = len(reel_details) - 1 - _ri
                if (_rd.get("note", "").startswith("Pulled")
                        or _rd.get("box", 0) == 0
                        or _rd.get("actual", 0) <= 0
                        or _rd.get("lot") != current_lot):
                    continue
                _pullable_rd = _rd
                _pullable_rd_idx = _real_i
                break

            if _pullable_rd is not None:
                _p_reel = _pullable_rd["reel"]
                _p_qty = _pullable_rd["actual"]
                _p_box = _pullable_rd["box"]
                _new_rem = _p_qty + _remainder_total

                msg = QMessageBox(self)
                msg.setWindowTitle("Scrap Warning")
                msg.setIcon(QMessageBox.Warning)
                msg.setText(
                    f"เศษ {_remainder_total:,} pcs. (< min {MIN_CARRY:,})\n"
                    f"จะถูกทิ้งเป็น Scrap\n\n"
                    f"ต้องการดึง Reel {_p_reel} ({_p_qty:,} pcs.) จาก Box {_p_box}\n"
                    f"รวม {_remainder_total:,} + {_p_qty:,} = {_new_rem:,} pcs.\n"
                    f"เพื่อ Pack เป็น Remainder Reel สำหรับ Order ถัดไป?")
                _btn_pull = msg.addButton("ดึง Reel & สร้าง Remainder", QMessageBox.AcceptRole)
                _btn_scrap = msg.addButton("ยอมรับ Scrap", QMessageBox.RejectRole)
                msg.setDefaultButton(_btn_pull)
                msg.exec_()

                if msg.clickedButton() == _btn_pull:
                    # [FIX-3] ใช้ index จริงในการ disable แถวเดิมที่โดนดึงของออก
                    reel_details[_pullable_rd_idx]["note"] = "Pulled → remainder (scrap avoid)"
                    reel_details[_pullable_rd_idx]["actual"] = 0
                    reel_details[_pullable_rd_idx]["target"] = 0
                    reel_details[_pullable_rd_idx]["diff"] = 0
                    total_actual -= _p_qty

                    _MIN = int(MIN_CARRY); _MAX = int(MAX_REEL)
                    _rem_qty = int(_new_rem)

                    _target_box, _take_qty, _take_reels, _rem_after, _rem_reels_count = \
                        find_smart_split(_rem_qty, open_boxes_list, _MIN, _MAX, int(MAX_BOX))

                    _max_rn = max(
                        (d.get("reel", 0) for d in reel_details if d.get("reel", 0) != 0),
                        default=0)

                    _added_rem_reels = 0
                    if _target_box and _take_qty > 0:
                        _smart_reels = _distribute_reels(_take_qty, _take_reels, _MIN, _MAX)
                        for _ri2, _rq in enumerate(_smart_reels):
                            reel_details.append({
                                "_src_idx": None,
                                "box": _target_box, "reel": _max_rn + 1 + _ri2,
                                "lot": current_lot, "target": _rq, "actual": _rq,
                                "reject": 0, "diff": 0,
                                "note": f"Smart Planned (Box {_target_box})",
                            })

                        if _rem_after > 0:
                            _rem_reels_list = _distribute_reels(
                                _rem_after, _rem_reels_count, _MIN, _MAX)
                            for _ri2, _rq in enumerate(_rem_reels_list):
                                reel_details.append({
                                    "_src_idx": None, "box": 0,
                                    "reel": _max_rn + 1 + len(_smart_reels) + _ri2,
                                    "lot": current_lot, "target": _rq, "actual": _rq,
                                    "reject": 0, "diff": 0,
                                    "note": "Remainder reel (next order)",
                                })
                            _added_rem_reels = len(_rem_reels_list)

                        total_actual += _take_qty
                        carry_remainder = _rem_after
                        carry_lot_val = current_lot if carry_remainder > 0 else ""

                        _ex_ob = next(
                            (ob for ob in open_boxes_list if ob["box"] == _target_box), None)
                        if _ex_ob:
                            _ex_ob["slots"] -= _take_reels
                            _ex_ob["current_total"] += _take_qty
                            wait_slots -= _take_reels
                            if _ex_ob["slots"] <= 0:
                                open_boxes_list.remove(_ex_ob)

                        local_ps["next_box"] = max(
                            local_ps.get("next_box", 1), _target_box + 1)
                        self._logger.info(
                            f"Smart Re-plan: Split {_rem_qty:,} → "
                            f"Box {_target_box}: {_take_qty:,}, Rem: {_rem_after:,}")

                    else:
                        _n_rem = max(1, _rem_qty // _MAX + (1 if _rem_qty % _MAX else 0))
                        _n_rem = max(1, min(_n_rem, _rem_qty // _MIN))
                        _rem_reels = _distribute_reels(_rem_qty, _n_rem, _MIN, _MAX)
                        _added_rem_reels = len(_rem_reels)
                        for _ri2, _rq in enumerate(_rem_reels):
                            reel_details.append({
                                "_src_idx": None, "box": 0,
                                "reel": _max_rn + 1 + _ri2,
                                "lot": current_lot, "target": _rq, "actual": _rq,
                                "reject": 0, "diff": 0,
                                "note": "Remainder reel (next order)",
                            })

                    forced_wait_boxes[_p_box] = (forced_wait_boxes.get(_p_box, 0) + 1)
                    _exist_ob = next(
                        (ob for ob in open_boxes_list if ob["box"] == _p_box), None)
                    if _exist_ob:
                        _exist_ob["slots"] += 1
                        _exist_ob["current_total"] -= _p_qty
                    else:
                        _saved_ob_sc = st.get("open_boxes", [])
                        _hist_sc = next(
                            (ob.get("current_total", 0)
                             for ob in _saved_ob_sc
                             if ob["box"] == _p_box), 0)
                        # [FIX-5] ใช้แค่ hist_sc + plan actual ไม่ double-count
                        _plan_act_sc = sum(
                            d["actual"] for d in reel_details
                            if d["box"] == _p_box and d["actual"] > 0
                            and not d.get("note", "").startswith("Pulled"))
                        open_boxes_list.append({
                            "box": _p_box, "slots": 1,
                            "current_total": _hist_sc + _plan_act_sc,
                        })
                    open_boxes_list.sort(key=lambda ob: ob["box"])
                    wait_slots += 1

                    self._logger.info(
                        f"Scrap avoid: pulled Reel {_p_reel} ({_p_qty:,}) "
                        f"from Box {_p_box}, created {_added_rem_reels} "
                        f"remainder reels ({_new_rem:,} pcs.)")
                else:
                    scrap_qty += _remainder_total
                    self._logger.info(f"User accepted scrap: {_remainder_total:,} pcs.")

        # ── Strip internal _src_idx field ก่อน save ──
        for rd in reel_details:
            rd.pop("_src_idx", None)

        # ── Save lot history ──
        lot_history.append({
            "lot": current_lot, "input": lot_input, "packed": total_actual,
            "reject": total_reject, "scrap": scrap_qty,
            "remainder": carry_remainder, "deviation": total_deviation,
            "reels": reel_details,
        })

        new_packed = prev_packed + total_actual
        order_qty = st.get("order_qty", planner.invoice_qty_spin.value())

        # ── Push complete data to live server ──
        self._push_live_data(
            invoice_no, st, lot_history, new_packed, MAX_BOX)

        # ── next_box / next_reel — คำนวณจาก max ทั้งหมด ──
        _all_reel_nos = set()
        for r in pack_plan:
            if r.get("reel", 0) != 0:
                _all_reel_nos.add(r["reel"])
        for _h in lot_history:
            for _rd in _h.get("reels", []):
                _rn = _rd.get("reel", 0)
                if _rn != 0:
                    _all_reel_nos.add(_rn)
        for _rd in reel_details:
            _rn = _rd.get("reel", 0)
            if _rn != 0:
                _all_reel_nos.add(_rn)
        state_next_reel = (max(_all_reel_nos) + 1) if _all_reel_nos else 1

        if open_boxes_list:
            _all_box_ids_nb = set(r["box"] for r in pack_plan if r["box"] != 0)
            for _h in lot_history:
                for _rd in _h.get("reels", []):
                    if not _rd.get("note", "").startswith("Pulled"):
                        b_id = _rd["box"]
                        if b_id != 0:
                            _all_box_ids_nb.add(b_id)
            state_next_box = (max(_all_box_ids_nb) + 1
                              if _all_box_ids_nb
                              else local_ps.get("next_box", 1))
        else:
            state_next_box = local_ps.get("next_box", 1)  # [FIX-2]

        # [FIX-2] Commit local_ps กลับไป plan_state ทีเดียว
        plan_state.update(local_ps)

        new_state = {
            "order_qty": order_qty, "packed": new_packed,
            "next_box": state_next_box, "next_reel": state_next_reel,
            "open_box_slots": wait_slots, "open_boxes": open_boxes_list,
            "carry_remainder": carry_remainder,
            "carry_lot": carry_lot_val,     # [FIX-4] carry_lot_val="" ถ้า carry=0 แล้ว
            "current_lot": (st.get("pending_lots", [{}])[0].get("lot_no", "")
                             if st.get("pending_lots") else ""),
            "pending_lots": st.get("pending_lots", []),
            "lot_history": lot_history, "product": invoice_no,
            "destination": dest, "shipment_date": ship_date,
            "max_box": planner._c_max_box, "max_reel": planner._c_max_reel,
            "min_reel": planner._c_min_reel,
            "reels_per_box": planner._c_reels_per_box,
            "wait_slots": wait_slots,
            "resume_reel": plan_state.get("next_reel", state_next_reel),
            "deviation": total_deviation,
        }

        if new_packed >= order_qty:
            # ── Order complete ──
            _clear_state(self._config)
            if carry_remainder > 0:
                export_leftover_csv(self._config, invoice_no, ship_date, dest,
                                    carry_remainder, carry_lot_val, lot_history)
            export_reject_csv(self._config, invoice_no, ship_date, dest, lot_history)
            export_final_plan_csv(self._config, invoice_no, ship_date, dest, order_qty, lot_history)
            auto_save_logpack(self._config, invoice_no, ship_date, dest, order_qty, lot_history)
            self._history.save_completed_order(
                invoice_no, dest, ship_date, order_qty, lot_history,
                carry_remainder, carry_lot_val)

            total_scrap = sum(h.get('scrap', 0) for h in lot_history)
            total_rej = sum(h['reject'] for h in lot_history)

            self._show_order_complete_dialog(
                invoice_no, new_packed, order_qty, lot_history,
                total_rej, total_scrap, carry_remainder, carry_lot_val)

            self._app_state["saved_state"] = None
            completed_entry = {
                "product": invoice_no, "order_qty": order_qty,
                "packed": new_packed, "lots": len(lot_history),
                "reject": total_rej, "scrap": total_scrap,
                "carry": carry_remainder, "carry_lot": carry_lot_val,
                "lot_history": lot_history,
                "destination": dest, "shipment_date": ship_date,
                "completed_at": datetime.now().replace(microsecond=0).time().isoformat(),
            }
            self._app_state["last_completed"] = completed_entry
            self._app_state.setdefault("completed_orders", []).append(completed_entry)
            self._dashboard_page.refresh()
            self._history_page.reload()
            self._logger.info(f"Order complete: {invoice_no}")

            idx = self._stack.indexOf(self._planner_page)
            self._stack.removeWidget(self._planner_page)
            self._planner_page.deleteLater()
            self._planner_page = PlannerPage(
                self._config, self._app_state, self._logger, self._history)
            self._planner_page.plan_ready.connect(self._on_plan_ready)
            self._stack.insertWidget(idx, self._planner_page)

            # Pass carry_remainder to new order so RemainderImportDialog triggers
            if carry_remainder > 0:
                carry_state = {
                    "carry_remainder": carry_remainder,
                    "carry_lot":       carry_lot_val,
                    "lot_history":     [],   # empty = signals new order to load_state()
                    "max_box":         self._config.max_per_box,
                    "max_reel":        self._config.max_per_reel,
                    "min_reel":        self._config.min_per_reel,
                    "reels_per_box":   self._config.reels_per_box,
                }
                self._planner_page.load_state(carry_state)
                self._logger.info(
                    f"[OrderComplete] Carry {carry_remainder:,} pcs "
                    f"({carry_lot_val}) \u2192 passed to new order"
                )

            midx = self._stack.indexOf(self._monitor_page)
            self._stack.removeWidget(self._monitor_page)
            self._monitor_page.deleteLater()
            self._monitor_page = MonitorPage(
                self._config, self._app_state, self._logger)
            self._monitor_page.monitor_finished.connect(self._on_monitor_finished)
            self._stack.insertWidget(midx, self._monitor_page)

            if self._live_server:
                self._live_server.update_monitor_page(self._monitor_page)
                self._monitor_page.set_live_server(self._live_server)

            self._sidebar.select(0)
        else:
            # ── Save state and prepare for next lot ──
            _save_state(self._config, new_state)
            self._app_state["saved_state"] = new_state

            self._show_lot_complete_dialog(
                current_lot, total_actual, total_reject,
                carry_remainder, carry_lot_val, scrap_qty,
                new_packed, order_qty, open_boxes_list)

            self._logger.plan(
                f"Lot {current_lot} done: packed={total_actual:,}, "
                f"carry={carry_remainder:,}, total={new_packed:,}/{order_qty:,}")

            self._dashboard_page.refresh()
            self._rebuild_planner_for_next_lot(new_state)
            self._sidebar.select(1)

    # ══════════════════════════════════════════════════════════
    #  POST-MONITOR HELPERS
    # ══════════════════════════════════════════════════════════

    def _gather_actuals(self, pack_plan, actuals):
        """Build total_actual, total_reject and per-reel detail list."""
        total_actual = 0
        total_reject = 0
        reel_details = []
        for i, a in enumerate(actuals):
            if a is None:
                continue
            if i < len(pack_plan) and pack_plan[i].get("note") == "Wait next lot":
                continue
            is_remainder = (i < len(pack_plan) and pack_plan[i].get("box", 0) == 0)
            if not is_remainder:
                total_actual += a.get("actual", 0)
                total_reject += a.get("reject", 0)
            reel_details.append({
                "_src_idx": i,
                "box":    pack_plan[i]["box"],
                "reel":   pack_plan[i]["reel"],
                "lot":    pack_plan[i]["lot"],
                "target": pack_plan[i]["target"],
                "actual": a.get("actual", 0),
                "reject": a.get("reject", 0),
                "diff":   a.get("actual", 0) - pack_plan[i]["target"],
                "note":   pack_plan[i].get("note", ""),
            })
        return total_actual, total_reject, reel_details

    def _resolve_current_lot(self, pack_plan, planner):
        """Return the current lot number from the plan or planner inputs."""
        for r in pack_plan:
            if r.get("note") not in ("Carry", "Wait next lot") and r.get("lot"):
                return r["lot"]
        if planner._lot_rows:
            lot_no = planner._lot_rows[0].get_data().get("lot_no")
            if lot_no:
                return lot_no
        self._logger.warning(
            "current_lot fallback to 'Unknown' — no lot info in plan or planner_page")
        return "Unknown"

    def _push_live_data(self, invoice_no, st, lot_history, new_packed, max_box):
        """Push aggregated data to the live dashboard server."""
        try:
            all_reels_live = []
            all_boxes_live = {}
            for h in lot_history:
                for rd in h.get("reels", []):
                    note = rd.get("note", "")
                    if note.startswith("Pulled"):
                        continue
                    b = rd.get("box", 0)
                    actual_v = rd.get("actual", 0)
                    if b != 0:
                        if b not in all_boxes_live:
                            all_boxes_live[b] = {
                                "target": 0, "actual": 0, "done": 0,
                                "total": 0, "reject": 0, "wait": 0}
                        all_boxes_live[b]["total"]  += 1
                        all_boxes_live[b]["target"] += rd.get("target", 0)
                        all_boxes_live[b]["actual"] += actual_v
                        all_boxes_live[b]["reject"] += rd.get("reject", 0)
                        if actual_v > 0:
                            all_boxes_live[b]["done"] += 1
                    all_reels_live.append({
                        "box": b, "reel": rd.get("reel", 0),
                        "lot": rd.get("lot", "—"),
                        "target": rd.get("target", 0),
                        "actual": actual_v,
                        "reject": rd.get("reject", 0),
                        "diff":   rd.get("diff", 0),
                        "status": "done" if actual_v > 0 else "wait",
                        "note": note,
                    })
            done_count = sum(1 for r in all_reels_live if r["status"] == "done")
            update_live_data({
                "invoice":  invoice_no,
                "product":  st.get("product", invoice_no),
                "progress": f"{done_count}/{len(all_reels_live)}",
                "max_box":  max_box,
                "totals": {
                    "target": sum(r["target"] for r in all_reels_live),
                    "actual": new_packed,
                    "reject": sum(h.get("reject", 0) for h in lot_history),
                    "diff":   new_packed - sum(r["target"] for r in all_reels_live),
                },
                "reels": all_reels_live,
                "boxes": {str(b): info for b, info in sorted(all_boxes_live.items())},
            })
        except Exception:
            pass

    def _show_order_complete_dialog(self, invoice_no, new_packed, order_qty,
                                    lot_history, total_rej, total_scrap,
                                    carry_remainder, carry_lot_val):
        """Build and show the auto-countdown Order Complete dialog."""
        T = THEME
        dlg = QDialog(self)
        dlg.setWindowTitle("Order Complete")
        dlg.setFixedWidth(S(480))
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet(f"""
            QDialog {{ background: {T['bg_card']}; border: 2px solid {T['accent_green']};
                       border-radius: {S(10)}px; }}
            QLabel {{ color: {T['text_primary']}; background: transparent; }}
        """)
        dlay = QVBoxLayout(dlg)
        dlay.setContentsMargins(S(24), S(20), S(24), S(20))
        dlay.setSpacing(S(12))

        tr = QHBoxLayout()
        ico = QLabel("✅"); ico.setStyleSheet(f"font-size:{F(28)}px;")
        ttl = QLabel("Order Complete")
        ttl.setStyleSheet(f"font-size:{F(18)}px;font-weight:bold;color:{T['accent_green']};")
        tr.addWidget(ico); tr.addWidget(ttl); tr.addStretch()
        dlay.addLayout(tr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{T['border']};max-height:1px;")
        dlay.addWidget(sep)

        info_items = [
            ("Product:",      invoice_no,                              T["accent"]),
            ("Total Packed:", f"{new_packed:,} / {order_qty:,}",      T["accent_green"]),
            ("Total Lots:",   str(len(lot_history)),                   T["accent2"]),
            ("Total Reject:", f"{total_rej:,}",                       T["accent_amber"]),
            ("Total Scrap:",  f"{total_scrap:,}",                     T["accent_red"]),
        ]
        if carry_remainder > 0:
            info_items.append(
                ("Leftover:", f"{carry_remainder:,} pcs. ({carry_lot_val})", "#9333EA"))
        for lbl_txt, val_txt, col in info_items:
            row = QHBoxLayout()
            l = QLabel(lbl_txt)
            l.setStyleSheet(f"font-size:{F(14)}px;color:{T['text_muted']};")
            l.setFixedWidth(S(140))
            v = QLabel(val_txt)
            v.setStyleSheet(f"font-size:{F(15)}px;font-weight:bold;color:{col};")
            row.addWidget(l); row.addWidget(v); row.addStretch()
            dlay.addLayout(row)

        dlay.addSpacing(S(8))
        _countdown = [5]
        ok_btn = QPushButton(f"ปิดอัตโนมัติ ({_countdown[0]})")
        ok_btn.setFixedHeight(S(38))
        ok_btn.setStyleSheet(f"""QPushButton{{
            background:{T['accent_green']};color:#fff;border:none;
            border-radius:{S(7)}px;font-size:{F(14)}px;font-weight:bold;
            min-width:{S(180)}px;}}
            QPushButton:hover{{background:#15803D;}}""")
        ok_btn.clicked.connect(dlg.accept)
        br = QHBoxLayout(); br.addStretch(); br.addWidget(ok_btn); br.addStretch()
        dlay.addLayout(br)

        _timer = QTimer(dlg)
        def _tick():
            _countdown[0] -= 1
            if _countdown[0] <= 0:
                _timer.stop(); dlg.accept()
            else:
                ok_btn.setText(f"ปิดอัตโนมัติ ({_countdown[0]})")
        _timer.timeout.connect(_tick)
        _timer.start(1000)
        dlg.exec_()

    def _show_lot_complete_dialog(self, current_lot, total_actual, total_reject,
                                  carry_remainder, carry_lot_val, scrap_qty,
                                  new_packed, order_qty, open_boxes_list):
        """Build and show the Lot Complete summary dialog."""
        T = THEME
        pct = int(new_packed / order_qty * 100) if order_qty > 0 else 0
        dlg = QDialog(self)
        dlg.setWindowTitle("Lot Complete — Preparing Next")
        dlg.setFixedWidth(S(500))
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet(f"""
            QDialog {{ background: {T['bg_card']}; border: 2px solid {T['accent']};
                       border-radius: {S(10)}px; }}
            QLabel {{ color: {T['text_primary']}; background: transparent; }}
        """)
        dlay = QVBoxLayout(dlg)
        dlay.setContentsMargins(S(24), S(20), S(24), S(20))
        dlay.setSpacing(S(10))

        tr = QHBoxLayout()
        ico = QLabel("📦"); ico.setStyleSheet(f"font-size:{F(28)}px;")
        ttl = QLabel(f"Lot {current_lot} Complete")
        ttl.setStyleSheet(f"font-size:{F(18)}px;font-weight:bold;color:{T['accent']};")
        tr.addWidget(ico); tr.addWidget(ttl); tr.addStretch()
        dlay.addLayout(tr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{T['border']};max-height:1px;")
        dlay.addWidget(sep)

        info_items = [
            ("Packed:", f"{total_actual:,}", T["accent_green"]),
            ("Reject:", f"{total_reject:,}",
             T["accent_red"] if total_reject else T["text_muted"]),
        ]
        if carry_remainder > 0:
            info_items.append(
                ("Carry:", f"{carry_remainder:,} pcs. ({carry_lot_val})", "#9333EA"))
        if scrap_qty > 0:
            info_items.append(("Scrap:", f"{scrap_qty:,} pcs.", T["accent_red"]))
        for lbl_txt, val_txt, col in info_items:
            row = QHBoxLayout()
            l = QLabel(lbl_txt)
            l.setStyleSheet(f"font-size:{F(14)}px;color:{T['text_muted']};")
            l.setFixedWidth(S(120))
            v = QLabel(val_txt)
            v.setStyleSheet(f"font-size:{F(15)}px;font-weight:bold;color:{col};")
            row.addWidget(l); row.addWidget(v); row.addStretch()
            dlay.addLayout(row)

        dlay.addSpacing(S(4))
        prog = QProgressBar()
        prog.setRange(0, 100); prog.setValue(pct)
        prog.setFixedHeight(S(18))
        prog.setFormat(f" {new_packed:,} / {order_qty:,}  ({pct}%)")
        prog.setStyleSheet(f"""QProgressBar{{
            background:{T['border']};border-radius:{S(6)}px;
            text-align:center;font-size:{F(12)}px;font-weight:bold;
            color:{T['text_primary']};border:none;}}
            QProgressBar::chunk{{background:{T['accent']};border-radius:{S(6)}px;}}""")
        dlay.addWidget(prog)

        if open_boxes_list:
            ob_txt = "กล่องที่รอ Lot ถัดไป: " + ", ".join(
                f"Box {ob['box']} ({ob['slots']} slot)" for ob in open_boxes_list)
            ob_lbl = QLabel(ob_txt)
            ob_lbl.setWordWrap(True)
            ob_lbl.setStyleSheet(
                f"font-size:{F(12)}px;color:{T['accent_amber']};"
                f"background:{T['bg_tag_amber']};border-radius:{S(4)}px;"
                f"padding:{S(4)}px {S(8)}px;")
            dlay.addWidget(ob_lbl)

        next_lbl = QLabel("ไปหน้า Planner เพื่อกรอก Lot ถัดไป")
        next_lbl.setStyleSheet(f"font-size:{F(13)}px;color:{T['accent']};font-weight:bold;")
        dlay.addWidget(next_lbl)
        dlay.addSpacing(S(4))

        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(S(38))
        ok_btn.setStyleSheet(f"""QPushButton{{
            background:{T['accent']};color:#fff;border:none;
            border-radius:{S(7)}px;font-size:{F(14)}px;font-weight:bold;
            min-width:{S(120)}px;}}
            QPushButton:hover{{background:#1D4ED8;}}""")
        ok_btn.clicked.connect(dlg.accept)
        br = QHBoxLayout(); br.addStretch(); br.addWidget(ok_btn); br.addStretch()
        dlay.addLayout(br)
        dlg.exec_()

    def _rebuild_planner_for_next_lot(self, new_state):
        idx = self._stack.indexOf(self._planner_page)
        self._stack.removeWidget(self._planner_page)
        self._planner_page.deleteLater()

        self._planner_page = PlannerPage(
            self._config, self._app_state, self._logger, self._history)
        self._planner_page.load_state(new_state)
        self._planner_page.plan_ready.connect(self._on_plan_ready)
        self._stack.insertWidget(idx, self._planner_page)
        if self._live_server:
            self._live_server.update_monitor_page(self._monitor_page)

        if self._config.ui_mode == 3 and new_state.get("pending_lots"):
            self._logger.info(
                f"[LotQueue] Auto-calculating next queued lot: "
                f"{new_state['pending_lots'][0].get('lot_no', '?')}")
            QTimer.singleShot(0, self._planner_page._run_plan)

# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main():
    try:
        locale.setlocale(locale.LC_ALL, 'C')
    except Exception:
        pass

    QLocale.setDefault(QLocale(QLocale.C))

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Packing Planner")
    app.setOrganizationName("VLO-127S")

    config = ConfigManager()
    win = MainWindow(config)
    win.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()