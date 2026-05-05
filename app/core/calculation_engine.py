"""
Packing Calculation Engine — VLO-127S
Pure calculation algorithms for reel packing.
"""
import os, csv, math, logging
from datetime import datetime
from itertools import permutations as _permutations
from PyQt5.QtWidgets import QApplication

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
#  RESPONSIVE HELPER
# ══════════════════════════════════════════════════

# Global scale override — set by dialog from config, used by screen_scale()
_scale_override = 0.0          # 0 = auto-detect

def screen_scale():
    """
    Scale factor relative to 1920×1080.
    Uses the smaller of width/height ratio → safe on all resolutions.
    1366×768 → 0.71,  1920×1080 → 1.0,  2560×1440 → 1.33
    If _scale_override > 0, use that instead.
    """
    if _scale_override > 0:
        return max(0.65, min(_scale_override, 1.6))
    g = QApplication.primaryScreen().geometry()
    base = min(g.width() / 1920.0, g.height() / 1080.0)
    return max(0.65, min(base, 1.6))

def scaled(px, s=None):
    """Return px scaled to current screen, as int."""
    if s is None:
        s = screen_scale()
    return max(1, int(round(px * s)))


# ══════════════════════════════════════════════════
#  CALCULATION ENGINE
# ══════════════════════════════════════════════════

def _extract_open_boxes(plan, rpb):
    """
    Extract open boxes (with wait slots) from current plan.
    Returns: [{box: int, current_total: int, slots: int}, ...]
    """
    open_boxes = {}
    for r in plan:
        box = r["box"]
        if box not in open_boxes:
            open_boxes[box] = {"box": box, "reels": 0, "total": 0}
        if r.get("note") != "Wait next lot" and r["target"] > 0:
            open_boxes[box]["reels"] += 1
            open_boxes[box]["total"] += r["target"]
    
    result = []
    for box_info in sorted(open_boxes.values(), key=lambda x: x["box"]):
        actual_reels = box_info["reels"]
        if actual_reels < rpb:
            result.append({
                "box": box_info["box"],
                "slots": rpb - actual_reels,
                "current_total": box_info["total"]
            })
    return result

def _optimize_open_box_fill(plan, lots, max_per_box, max_per_reel, min_per_reel, reels_per_box):
    """
    Post-process plan: Move material from new boxes to open boxes if possible.
    This fixes the issue where open boxes aren't filled before creating new ones.
    
    After filling attempt, validates each open box:
    - If box is underfull + has wait slots → mark remaining slots as "Wait next lot"
    - If box has remainder < min_per_reel → move to remainder reels (Box 0)
    """
    rpb = max(1, reels_per_box)
    
    # Extract open boxes
    open_boxes = _extract_open_boxes(plan, rpb)
    if not open_boxes:
        return plan  # No open boxes to fill
    
    # Find material in new boxes that can fit into open boxes
    reel_no = max((r.get("reel", 0) for r in plan), default=0) + 1
    
    for ob in open_boxes:
        box_id = ob["box"]
        available_slots = ob["slots"]
        current_total = ob["current_total"]
        remaining_capacity = max_per_box - current_total
        
        if available_slots <= 0 or remaining_capacity < min_per_reel:
            continue
        
        # Find reels in newer boxes that can be moved here
        reels_to_move = []
        for i, r in enumerate(plan):
            if (r.get("note") == "Wait next lot" or r.get("box", 0) <= box_id 
                    or r.get("target", 0) <= 0):
                continue
            
            # This reel is in a newer box
            if (r.get("target", 0) <= remaining_capacity and r.get("target", 0) >= min_per_reel
                    and available_slots > 0):
                reels_to_move.append((i, r))
                available_slots -= 1
                remaining_capacity -= r.get("target", 0)
                current_total += r.get("target", 0)
        
        # Move reels to open box and renumber
        for idx, reel in reels_to_move:
            plan[idx]["box"] = box_id
            plan[idx]["reel"] = reel_no
            reel_no += 1

        # Refresh box_total for every row in this box (pre-existing + newly moved)
        if reels_to_move:
            for r in plan:
                if r["box"] == box_id:
                    r["box_total"] = current_total
    
    # ⚠️ NEW: POST-FILL VALIDATION - Ensure all open boxes are in valid state
    # After attempting to fill, check each open box and add "Wait next lot" slots if needed
    boxes_to_verify = set(r["box"] for r in plan if r.get("note") != "Wait next lot" and r["box"] > 0)
    
    for box_id in sorted(boxes_to_verify):
        # Count actual reels in this box (excluding wait slots)
        real_reels = [r for r in plan if r["box"] == box_id and r.get("note") != "Wait next lot"]
        existing_waits = [r for r in plan if r["box"] == box_id and r.get("note") == "Wait next lot"]
        
        real_count = len(real_reels)
        wait_count = len(existing_waits)
        total_reels = real_count + wait_count
        
        # Calculate box totals
        box_total = sum(r["target"] for r in real_reels)
        
        # Determine expected wait slots (if not full box)
        if box_total < max_per_box and real_count > 0:
            expected_waits = rpb - real_count
            deficit = max_per_box - box_total
            
            if min_per_reel > 0:
                min_needed = expected_waits * min_per_reel
                max_possible = expected_waits * max_per_reel
                
                # Check if deficit is valid for the wait slots
                if expected_waits > 0 and min_needed <= deficit <= max_possible:
                    # Deficit is valid → add/keep wait slots
                    if wait_count < expected_waits:
                        # Need to add more wait slots
                        for _ in range(expected_waits - wait_count):
                            plan.append({
                                "box": box_id,
                                "reel": 0,
                                "lot": "",
                                "target": 0,
                                "box_total": box_total,
                                "note": "Wait next lot"
                            })
                            wait_count += 1
                        
                        # Log: inform about box state
                        _log.debug(f"[INFO] Box {box_id}: Packed {box_total:,}/{max_per_box:,} pcs "
                              f"({expected_waits} wait slot(s) created for next {min_needed:,}–{max_possible:,} pcs)")
                    
                    # Update box_total for all rows in this box
                    for r in plan:
                        if r["box"] == box_id:
                            r["box_total"] = box_total
                
                elif expected_waits > 0 and deficit < min_needed:
                    # Deficit too small (dead scrap) → reduce last reel + create remainder
                    _log.debug(f"[ADJUST] Box {box_id}: Deficit={deficit:,} < Min needed={min_needed:,} "
                          f"→ Moving excess to Remainder Reel")
                    
                    for r in real_reels[-1:]:  # Process last reel
                        reduction = box_total - (max_per_box - min_needed)
                        if reduction > 0 and r["target"] - reduction >= min_per_reel:
                            r["target"] -= reduction
                            box_total -= reduction
                            # Create new remainder reel (box=0)
                            plan.append({
                                "box": 0,
                                "reel": max((pr.get("reel", 0) for pr in plan), default=0) + 1,
                                "lot": r["lot"],
                                "target": reduction,
                                "box_total": None,
                                "note": "Remainder Reel (Box Adjustment)"
                            })
                    
                    # Update box_total
                    for r in plan:
                        if r["box"] == box_id and r.get("note") != "Wait next lot":
                            r["box_total"] = box_total
                    
                    # Add wait slots
                    for _ in range(expected_waits):
                        plan.append({
                            "box": box_id,
                            "reel": 0,
                            "lot": "",
                            "target": 0,
                            "box_total": box_total,
                            "note": "Wait next lot"
                        })

            # ══════════════════════════════════════════════════════
            # 🔍 CRITICAL FIX: No wait slots left (expected_waits==0)
            #    but box is still underfull → last reel from new lot
            #    was shoved in but deficit < min_per_reel → box stuck.
            #    → Pull last reel back out to Remainder + add Wait slot.
            # ══════════════════════════════════════════════════════
            if (min_per_reel > 0
                    and expected_waits == 0
                    and wait_count == 0
                    and 0 < deficit < min_per_reel):
                # หา reel สุดท้ายที่เพิ่งเข้ามา (box ใหม่กว่า → ย้ายมา)
                # เลือก reel ที่มี target น้อยที่สุด (น่าจะเป็นตัวที่ยัดเข้ามาไม่สมบูรณ์)
                candidates = [r for r in real_reels if r["target"] < min_per_reel]
                if not candidates:
                    # ถ้า reel ทุกตัว >= min แต่ deficit ยังเล็กอยู่ 
                    # → ดึง reel สุดท้ายออก (reel ที่เพิ่งย้ายมา)
                    candidates = real_reels[-1:]
                
                for pull_r in candidates[:1]:  # ดึงแค่ 1 reel
                    pulled_qty = pull_r["target"]
                    new_reel_no = max((pr.get("reel", 0) for pr in plan), default=0) + 1
                    
                    # แปลง reel ที่ stuck เป็น "Wait next lot"
                    pull_r["target"] = 0
                    pull_r["note"]   = "Wait next lot"
                    pull_r["lot"]    = ""
                    pull_r["reel"]   = 0
                    
                    # สร้าง Remainder reel (box=0)
                    plan.append({
                        "box": 0,
                        "reel": new_reel_no,
                        "lot": "",  # lot info lost after move — mark generic
                        "target": pulled_qty,
                        "box_total": None,
                        "note": "Remainder Reel (Box Adjustment)"
                    })
                    
                    new_box_total = box_total - pulled_qty
                    _log.debug(f"[POST-FILL FIX] Box {box_id}: pulled {pulled_qty:,} pcs "
                          f"(deficit was {deficit:,} < min {min_per_reel:,}). "
                          f"Box now {new_box_total:,}/{max_per_box:,} "
                          f"with 1 Wait slot added.")
                    
                    # อัปเดต box_total
                    for r in plan:
                        if r["box"] == box_id:
                            r["box_total"] = new_box_total
    
    return plan

def calculate_pack_plan_with_open_box_tracking(invoice_qty, max_per_box, max_per_reel, lots,
                                                min_per_reel=0, reels_per_box=3):
    """
    Enhanced sequential lot fill with open box tracking.
    
    Improvements:
    1. First pass: use calculate_pack_plan() to get initial plan
    2. Post-process: Move material to fill open boxes
    3. Extract open boxes from the result
    4. Validate all constraints: order qty, max_per_box, min/max_per_reel
    
    Returns: (plan_list, scrap_list, validation_errors)
    """
    # Use standard algorithm first
    plan, scrap_list = calculate_pack_plan(invoice_qty, max_per_box, max_per_reel, 
                                           lots, min_per_reel, reels_per_box, _avoid_scrap=True)
    
    if plan:
        # Optimize: try to fill open boxes with material from new boxes
        plan = _optimize_open_box_fill(plan, lots, max_per_box, max_per_reel, 
                                       min_per_reel, reels_per_box)
    
    validation_errors = []
    rpb = max(1, reels_per_box)
    
    # Validation checks
    if not plan:
        return plan, scrap_list, ["No plan could be created"]
    
    # Check 1: Total packed vs target
    total_packed = sum(r["target"] for r in plan if r.get("target", 0) > 0)
    if total_packed < invoice_qty:
        shortfall = invoice_qty - total_packed
        validation_errors.append(f"❌ SHORTFALL: {shortfall:,} pcs short of target {invoice_qty:,}")
    elif total_packed == invoice_qty:
        validation_errors.insert(0, f"✅ Order quantity met: {total_packed:,} = {invoice_qty:,} pcs")
    
    # Check 2: All boxes respect max_per_box and min_per_reel
    box_totals = {}
    box_reel_counts = {}
    for r in plan:
        if r["box"] > 0 and r.get("note") != "Wait next lot":
            box_totals[r["box"]] = box_totals.get(r["box"], 0) + r.get("target", 0)
            box_reel_counts[r["box"]] = box_reel_counts.get(r["box"], 0) + 1
    
    for box, total in box_totals.items():
        if total > max_per_box:
            validation_errors.append(f"❌ BOX {box}: {total:,} pcs exceeds max {max_per_box:,}")
        if min_per_reel > 0 and 0 < total < min_per_reel:
            validation_errors.append(f"❌ BOX {box}: {total:,} pcs below min_per_reel {min_per_reel:,}")
        reel_count = box_reel_counts.get(box, 0)
        if reel_count > rpb:
            validation_errors.append(f"❌ BOX {box}: {reel_count} reels exceeds max {rpb}")
    
    # Check 3: All reels respect max_per_reel
    for r in plan:
        if r.get("target", 0) > max_per_reel and r.get("note") != "Wait next lot":
            validation_errors.append(f"❌ REEL {r['reel']} (Box {r['box']}): "
                                    f"{r['target']:,} pcs exceeds max {max_per_reel:,}")
    
    # Check 4: Extract and verify open boxes
    open_boxes = _extract_open_boxes(plan, rpb)
    if open_boxes:
        total_open_slots = sum(ob.get("slots", 0) for ob in open_boxes)
        validation_errors.append(f"⚠️  {len(open_boxes)} open box(es) with {total_open_slots} wait slot(s)")
    
    # Add positive confirmations
    if not any(err.startswith("❌") for err in validation_errors):
        validation_errors.append("✅ All constraints satisfied!")
    
    return plan, scrap_list, validation_errors


def calculate_pack_plan(invoice_qty, max_per_box, max_per_reel, lots,
                        min_per_reel=0, reels_per_box=3, _avoid_scrap=True):
    """
    Sequential lot fill — covers all cases:

    1. Material flows in lot order; lots can mix within a box
    2. Full boxes have reels_per_box reels; last box may have fewer
    3. Redistribution: if filling box to max leaves remainder < min → reduce box so next box gets >= min
    4. Scrap avoidance (2-pass): if using lot leaves remainder < min → skip to next lot
    5. Shortfall avoidance: small lot can't fill cap → skip to larger lot (small lot preserved for later)
    6. Round to multiple of 50 (last slot not rounded)
    7. Skipped lots are not lost → _first_avail re-scans every iteration
    8. Shortfall recovery: if scrap avoidance causes shortfall, retry with scrap avoidance off

    Returns: (plan_list, scrap_list)
    """
    lot_queue  = [[l["lot_no"], l["qty"]] for l in lots if l["qty"] > 0]
    plan       = []
    scrap_list = []
    box_no     = 1
    reel_no    = 1
    rpb        = max(1, reels_per_box)
    packed     = 0

    def _first_avail():
        """Find index of first lot with remaining qty (not a forward-only pointer)"""
        for i, lq in enumerate(lot_queue):
            if lq[1] > 0:
                return i
        return None

    prev_packed = -1                             # prevent infinite loop

    while packed < invoice_qty:
        qi = _first_avail()
        if qi is None:
            break
        if packed == prev_packed:                 # no progress → stop
            break
        prev_packed = packed

        # --- Determine box size & reel count ---
        total_remaining = invoice_qty - packed
        box_budget = min(max_per_box, total_remaining)

        # Redistribution: if filling box to max leaves remainder < min_per_reel
        # → reduce this box so next box gets at least min_per_reel
        # Condition 1: mid-chain — there ARE more items after this box
        if (min_per_reel > 0
                and total_remaining > box_budget
                and 0 < (total_remaining - box_budget) < min_per_reel):
            box_budget = total_remaining - min_per_reel
        # Condition 2: last-box edge case — remainder would be tiny even when
        # total_remaining == box_budget (subsumes condition 1 in that case)
        _rem_after = total_remaining - box_budget
        if min_per_reel > 0 and 0 < _rem_after < min_per_reel:
            box_budget = total_remaining - min_per_reel

        # Material-based redistribution: when available material slightly
        # exceeds budget, filling to budget creates scrap < min.  Reduce
        # budget so the material remainder is >= min_per_reel.
        _avail = sum(q[1] for q in lot_queue if q[1] > 0)
        if (min_per_reel > 0
                and _avail > box_budget
                and 0 < (_avail - box_budget) < min_per_reel):
            box_budget = _avail - min_per_reel

        if min_per_reel > 0:
            slots = min(rpb, box_budget // min_per_reel)
        else:
            slots = rpb
        if slots <= 0:
            break

        # When box can't reach max, reduce slots to leave fillable
        # wait-slots for future lots (avoid sealed underfull boxes).
        if min_per_reel > 0 and box_budget < max_per_box:
            for _try_s in range(slots, 0, -1):
                _w = rpb - _try_s
                if _w > 0 and _box_fillable(
                        min(box_budget, _try_s * max_per_reel), _w,
                        max_per_box, min_per_reel, max_per_reel):
                    slots = _try_s
                    break

        cap = box_budget
        box_rows = []
        _scrap_before = len(scrap_list)

        while slots > 0 and cap > 0:
            if min_per_reel > 0 and cap < min_per_reel:
                break
            pick = _pick_lot(lot_queue, qi, cap, slots,
                             max_per_reel, min_per_reel, scrap_list,
                             _avoid_scrap)
            if pick is None:
                break
            li, take = pick
            box_rows.append({"lot": lot_queue[li][0], "target": take})
            lot_queue[li][1] -= take
            cap   -= take
            slots -= 1

        # --- Seal box ---
        if box_rows:
            bt = sum(r["target"] for r in box_rows)

            # Post-build fillability: if box is underfull and more order
            # to fill, trim excess reels to leave fillable wait-slots.
            if (bt < max_per_box
                    and packed + bt < invoice_qty
                    and min_per_reel > 0):
                _actual = len(box_rows)
                for _trim in range(_actual, 0, -1):
                    _w = rpb - _trim
                    if _w <= 0:
                        continue
                    _bt = sum(r["target"] for r in box_rows[:_trim])
                    if _box_fillable(_bt, _w, max_per_box,
                                     min_per_reel, max_per_reel):
                        # Return trimmed material to lot_queue
                        for _row in box_rows[_trim:]:
                            for lq in lot_queue:
                                if lq[0] == _row["lot"]:
                                    lq[1] += _row["target"]
                                    break
                        box_rows = box_rows[:_trim]
                        bt = _bt
                        break

                # Undo any scrap added during this box's fill —
                # the post-build trim may have freed slots, and the
                # scrapped material can now be placed in a future box.
                for _s in scrap_list[_scrap_before:]:
                    for lq in lot_queue:
                        if lq[0] == _s["lot"]:
                            lq[1] += _s["qty"]
                            break
                del scrap_list[_scrap_before:]

            packed += bt
            for r in box_rows:
                plan.append({"box": box_no, "reel": reel_no,
                    "lot": r["lot"], "target": r["target"],
                    "box_total": None, "note": ""})
                reel_no += 1
            # Add wait-slot rows when box is underfull
            actual_reels = len(box_rows)
            wait_count = rpb - actual_reels
            if wait_count > 0 and bt < max_per_box:
                for _ in range(wait_count):
                    plan.append({"box": box_no, "reel": 0,
                        "lot": None, "target": 0,
                        "box_total": None, "note": "Wait next lot"})
            _seal(plan, box_no, bt)
            box_no += 1
        else:
            break

    # Shortfall recovery: if scrap avoidance caused shortfall, retry without it
    if _avoid_scrap and packed < invoice_qty:
        remaining_material = sum(q[1] for q in lot_queue if q[1] > 0)
        if remaining_material > 0:
            return calculate_pack_plan(invoice_qty, max_per_box, max_per_reel,
                                       lots, min_per_reel, reels_per_box,
                                       _avoid_scrap=False)

    return plan, scrap_list


def _pick_lot(lot_queue, qi, cap, slots, max_per_reel, min_per_reel, scrap_list,
              avoid_scrap=True):
    """
    Find best lot for the next reel (Two-pass).

    Pass 1 (avoid=True):  avoid scrap — if using lot leaves remainder < min → skip
    Pass 2 (avoid=False): accept scrap if unavoidable

    Within each pass:
    - Calculate take (average / whole lot / round ×50)
    - Shortfall avoidance: small lot can't fill → skip if larger lot exists
    - Scrap avoidance: reduce take or skip to avoid remainder < min

    Returns: (lot_index, take_qty) or None
    """
    passes = (True, False) if avoid_scrap else (False,)
    for avoid in passes:
        for li in range(qi, len(lot_queue)):
            lot_name = lot_queue[li][0]
            lot_rem  = lot_queue[li][1]
            if lot_rem <= 0:
                continue

            # === Calculate take ===
            need_after = (slots - 1) * min_per_reel if slots > 1 else 0

            if (lot_rem <= max_per_reel
                    and lot_rem <= cap
                    and (lot_rem >= min_per_reel or min_per_reel == 0)
                    and (cap - lot_rem) >= need_after):
                take = lot_rem                         # take whole lot
            else:
                take = cap // slots
                # B1 fix: clamp BEFORE rounding so rounding never drops below min
                take = min(take, lot_rem, max_per_reel)
                if slots > 1 and take >= 100:          # round down to ×50
                    take = (take // 50) * 50
                    # Re-floor after rounding in case rounding crossed min boundary
                    if min_per_reel > 0 and take < min_per_reel:
                        take = min_per_reel
                # Ensure take never exceeds lot availability after fix-up
                take = min(take, lot_rem)
                if min_per_reel > 0 and take < min_per_reel:
                    if lot_rem < min_per_reel:
                        if not avoid:
                            scrap_list.append({"lot": lot_name, "qty": lot_rem,
                                "reason": f"Remainder < {min_per_reel:,}"})
                            lot_queue[li][1] = 0
                        continue
                    take = min_per_reel

            take = min(take, cap)
            if take <= 0 or (min_per_reel > 0 and take < min_per_reel):
                continue

            # === Lot-boundary waste avoidance (1-reel lookahead) ===
            # When 2 slots remain and current lot can't fill remaining cap,
            # the next reel's shortfall avoidance will skip to a larger lot.
            # If that larger lot would leave waste < min, reduce current take
            # so the larger lot can be used in full (zero waste).
            if min_per_reel > 0 and slots == 2:
                rem_lot = lot_rem - take
                rem_cap = cap - take
                if 0 < rem_lot < rem_cap:
                    for nli in range(li + 1, len(lot_queue)):
                        if lot_queue[nli][1] <= 0:
                            continue
                        nq = lot_queue[nli][1]
                        if nq >= rem_cap and 0 < nq - rem_cap < min_per_reel:
                            alt = cap - nq
                            alt_rem = lot_rem - alt
                            if (min_per_reel <= alt <= max_per_reel
                                    and alt <= cap
                                    and (alt_rem == 0
                                         or alt_rem >= min_per_reel)):
                                take = alt
                        break

            # === Shortfall avoidance ===
            # Last slot: this lot is exhausted but doesn't fill cap
            # If another lot can fill cap → skip to larger lot
            # Small lot preserved for next iteration (not lost thanks to _first_avail)
            # Limited to last slot → preserves FIFO order for earlier slots
            if slots == 1 and take == lot_rem and take < cap:
                if any(lot_queue[lj][1] >= cap
                       for lj in range(li + 1, len(lot_queue))
                       if lot_queue[lj][1] > 0):
                    continue

            # === Scrap avoidance ===
            new_rem = lot_rem - take
            if min_per_reel > 0 and 0 < new_rem < min_per_reel:
                # Option A: reduce take → keep lot remainder >= min_per_reel
                safe_take = lot_rem - min_per_reel
                if safe_take >= 100:
                    safe_take = (safe_take // 50) * 50
                leftover_cap = cap - safe_take
                if (safe_take >= min_per_reel
                        and safe_take <= max_per_reel
                        and safe_take <= cap
                        and (leftover_cap == 0
                             or leftover_cap >= min_per_reel)):
                    return (li, safe_take)

                # Option A2: take the whole lot (0 remainder = 0 scrap)
                # — only when the lot fits entirely in this reel & cap
                if (lot_rem <= cap
                        and lot_rem <= max_per_reel
                        and (lot_rem >= min_per_reel or min_per_reel == 0)
                        and (cap - lot_rem == 0
                             or (cap - lot_rem) >= need_after)):
                    return (li, lot_rem)

                # Option B: skip to next lot
                if avoid:
                    continue
                # Pass 2: accept scrap

            return (li, take)

    return None


def _seal(plan, box_no, total):
    for r in plan:
        if r["box"] == box_no:
            r["box_total"] = total


# ══════════════════════════════════════════════════
#  v6 — GLOBAL OPTIMIZATION
# ══════════════════════════════════════════════════

def calculate_pack_plan_v6(invoice_qty, max_per_box, max_per_reel, lots,
                           min_per_reel=0, reels_per_box=3):
    """
    Global optimization — minimize waste by trying multiple lot usages
    and orderings, picking the plan with least scrap + shortfall.

    1. Concentrate excess material into one lot at a time
    2. For each configuration, try multiple lot orderings through v5
    3. Return the best result

    Returns: (plan_list, scrap_list)
    """
    lot_list = [{"lot_no": l["lot_no"], "qty": l["qty"]}
                for l in lots if l.get("qty", 0) > 0]
    n = len(lot_list)
    if n == 0:
        return [], []

    total_material = sum(ld["qty"] for ld in lot_list)
    to_pack = min(invoice_qty, total_material)
    slack = total_material - to_pack

    # ── Candidate lot configurations ────────────────────────
    candidates = [lot_list]                        # original lots

    if slack > 0:
        for ti in range(n):
            reduced = lot_list[ti]["qty"] - slack
            if reduced <= 0:
                continue
            if min_per_reel > 0 and reduced < min_per_reel:
                continue
            adj = [{"lot_no": lot_list[i]["lot_no"],
                    "qty": reduced if i == ti else lot_list[i]["qty"]}
                   for i in range(n)]
            candidates.append(adj)

    # ── Ordering generator ──────────────────────────────────
    def _orderings(active):
        na = len(active)
        # Exhaustive up to n=7 (5040 orderings × fast calculate_pack_plan ≈ <1 s)
        if na <= 7:
            return list(_permutations(range(na)))
        idxs = list(range(na))
        ords = set()
        ords.add(tuple(idxs))                                            # FIFO
        ords.add(tuple(sorted(idxs, key=lambda i: active[i]["qty"])))   # ascending
        ords.add(tuple(sorted(idxs, key=lambda i: -active[i]["qty"])))  # descending
        # Interleave: largest, smallest, 2nd-largest, 2nd-smallest…
        srt = sorted(idxs, key=lambda i: active[i]["qty"])
        inter = []
        lo, hi = 0, len(srt) - 1
        while lo <= hi:
            if lo == hi:
                inter.append(srt[lo])
            else:
                inter.append(srt[hi]); inter.append(srt[lo])
            lo += 1; hi -= 1
        ords.add(tuple(inter))
        ords.add(tuple(inter[::-1]))
        return list(ords)

    # ── Search best plan ────────────────────────────────────
    best_plan, best_scrap, best_score = None, None, float('inf')
    best_box_count = float('inf')   # Q7: secondary tie-breaker — fewer boxes
    best_active_ref = None          # for local-swap refinement
    best_ordering_ref = None

    def _evaluate(active, ordering):
        reordered = [active[i] for i in ordering]
        p, s = calculate_pack_plan(
            to_pack, max_per_box, max_per_reel, reordered, min_per_reel, reels_per_box)
        if not p:
            return None, None, float('inf'), float('inf')
        packed    = sum(r["target"] for r in p)
        shortfall = max(0, to_pack - packed)
        scrap_qty = sum(x["qty"] for x in s)
        sc        = shortfall * 10 + scrap_qty
        bc        = len({r["box"] for r in p})
        return p, s, sc, bc

    for cand in candidates:
        active = [l for l in cand if l["qty"] > 0]
        if not active:
            continue
        for ordering in _orderings(active):
            plan, scrap, score, box_count = _evaluate(active, ordering)
            if plan is None:
                continue
            if (score, box_count) < (best_score, best_box_count):
                best_score       = score
                best_box_count   = box_count
                best_plan        = plan
                best_scrap       = scrap
                best_active_ref  = active
                best_ordering_ref = list(ordering)
            # Early-exit only when tie-breaker also satisfied
            if score == 0 and box_count <= best_box_count:
                break
        if best_score == 0:
            break

    # ── Local-swap hill-climb for n > 7 (exhaustive permutation is infeasible) ──
    # Iteratively try all pairwise swaps on the best ordering found above;
    # accept any swap that strictly improves (score, box_count). Repeat until
    # no swap helps (convergence usually in 1–2 passes, O(n²) per pass).
    if n > 7 and best_plan is not None and best_active_ref is not None:
        improved = True
        while improved and best_score > 0:
            improved = False
            na = len(best_ordering_ref)
            for i in range(na - 1):
                for j in range(i + 1, na):
                    trial = best_ordering_ref[:]
                    trial[i], trial[j] = trial[j], trial[i]
                    plan, scrap, score, box_count = _evaluate(best_active_ref, trial)
                    if plan is None:
                        continue
                    if (score, box_count) < (best_score, best_box_count):
                        best_score        = score
                        best_box_count    = box_count
                        best_plan         = plan
                        best_scrap        = scrap
                        best_ordering_ref = trial
                        improved          = True
                        if best_score == 0:
                            break
                if best_score == 0 or improved:
                    break

    return best_plan or [], best_scrap or []


def write_plan_csv(filepath, plan, meta, lot_remainders=None):
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        for k, v in meta.items(): w.writerow([f"# {k}", v])
        w.writerow([])
        w.writerow(["Box","Reel","Lot","Target","BoxTotal","Note"])
        for r in plan:
            w.writerow([r["box"],r["reel"],r["lot"],r["target"],
                        r["box_total"] or "",r["note"]])
        if lot_remainders:
            w.writerow([])
            w.writerow(["# Lot Remainder"])
            w.writerow(["Lot","Available","Used","Scrap","Remainder"])
            for lr in lot_remainders:
                w.writerow([lr["lot"], lr["available"], lr["used"],
                            lr["scrap"], lr["remainder"]])

# ══════════════════════════════════════════════════
#  NEW HELPER: FORECAST OPEN BOXES FILLABILITY
# ══════════════════════════════════════════════════

def _forecast_open_boxes_fillability(open_boxes, order_remaining, packed_so_far,
                                      max_per_box, min_per_reel, max_per_reel):
    """
    คำนวณว่า material ที่เหลืออยู่ (order_remaining - packed_so_far)
    สามารถเติม open boxes ทั้งหมดให้เต็ม max_per_box ได้หรือไม่
    คืนค่า (can_fill_all, deficit_total, min_needed)
    """
    deficit_total = 0
    wait_slots = 0
    for ob in open_boxes:
        current = ob.get("current_total", 0)
        if current < max_per_box:
            deficit_total += max_per_box - current
        wait_slots += ob.get("slots", 0)
    if min_per_reel > 0:
        min_needed = wait_slots * min_per_reel
    else:
        min_needed = deficit_total
    effective_needed = max(deficit_total, min_needed)
    remaining_material = order_remaining - packed_so_far
    can_fill = remaining_material >= effective_needed
    return can_fill, deficit_total, effective_needed

def _box_fillable(placed_total: int, slots_remaining: int,
                  max_per_box: int, min_per_reel: int, max_per_reel: int) -> bool:
    """ตรวจสอบว่า box ที่เติมบางส่วนสามารถเติมให้เต็มด้วย slots ที่เหลือได้หรือไม่"""
    if min_per_reel <= 0:
        return True
    needed = max_per_box - placed_total
    if slots_remaining <= 0:
        return needed == 0
    min_fill = slots_remaining * min_per_reel
    max_fill = slots_remaining * max_per_reel
    return min_fill <= needed <= max_fill

# ══════════════════════════════════════════════════
#  SAFE ALLOCATION CALCULATOR (Phase 0-1 helper)
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
#  BOX SPLIT OPTIMIZER (Option A — forward-aware fill)
# ══════════════════════════════════════════════════

def find_best_box_split(deficit, slots, lot_remaining, min_r, max_r):
    """
    Find the optimal way to place part of a lot into an open box.

    Rules:
      - Each placed reel must be in [min_r, max_r]
      - If any wait slots remain, the leftover deficit must be fillable
        (wait_after * min_r <= box_rem_after <= wait_after * max_r)
        OR wait_after == 0 and box_rem_after == 0 (box sealed full)
      - If lot has leftover, it must be >= min_r (valid carry) OR == 0

    Strategy: prefer fewer reels now, then prefer leftover_lot == 0.

    Returns:
      dict with keys (n, qty, leftover_lot, wait_after, box_rem, type)
      OR None if no valid split exists → caller should defer entire box.
    """
    if slots <= 0 or lot_remaining <= 0 or deficit <= 0:
        return None
    if min_r <= 0:
        # No min constraint: place as much as possible in fewest reels
        qty = min(lot_remaining, deficit, slots * max_r)
        n = max(1, -(-qty // max_r))
        return {
            "n": n, "qty": qty, "leftover_lot": lot_remaining - qty,
            "wait_after": slots - n, "box_rem": deficit - qty, "type": "no-min"
        }

    candidates = []
    for n in range(1, slots + 1):
        wait_after = slots - n
        qty_min_in_reels = n * min_r
        qty_max_in_reels = n * max_r

        # ── Case A: use ALL lot_remaining in these n reels ──
        if qty_min_in_reels <= lot_remaining <= qty_max_in_reels and lot_remaining <= deficit:
            box_rem_after = deficit - lot_remaining
            if wait_after == 0:
                if box_rem_after == 0:
                    candidates.append({
                        "n": n, "qty": lot_remaining, "leftover_lot": 0,
                        "wait_after": 0, "box_rem": 0, "type": "A-full"
                    })
            else:
                if wait_after * min_r <= box_rem_after <= wait_after * max_r:
                    candidates.append({
                        "n": n, "qty": lot_remaining, "leftover_lot": 0,
                        "wait_after": wait_after, "box_rem": box_rem_after,
                        "type": "A-wait"
                    })

        # ── Case B: leave leftover >= min_r in lot (for carry forward) ──
        if wait_after == 0:
            qty_deficit_min = deficit
            qty_deficit_max = deficit
        else:
            qty_deficit_min = max(0, deficit - wait_after * max_r)
            qty_deficit_max = deficit - wait_after * min_r

        qty_lo = max(qty_min_in_reels, qty_deficit_min)
        qty_hi = min(qty_max_in_reels, qty_deficit_max, deficit,
                     lot_remaining - min_r)

        if qty_lo <= qty_hi:
            # Pick max qty (pack more now, smaller carry).
            # Prefer multiples of 50 when possible, else fall back to qty_hi.
            qty_b = (qty_hi // 50) * 50
            if qty_b < qty_lo:
                # Try rounding UP instead (nearest 50)
                qty_b_up = ((qty_lo + 49) // 50) * 50
                if qty_b_up <= qty_hi:
                    qty_b = qty_b_up
                else:
                    # Range too narrow for any multiple of 50 → use raw qty_hi
                    qty_b = qty_hi
            if qty_lo <= qty_b <= qty_hi:
                candidates.append({
                    "n": n, "qty": qty_b,
                    "leftover_lot": lot_remaining - qty_b,
                    "wait_after": wait_after,
                    "box_rem": deficit - qty_b, "type": "B-carry"
                })

    if not candidates:
        return None

    # [FIX-EFFICIENCY-1] Sort priority ใหม่ — เลียนแบบ manual heuristic:
    #   1. ปิด box (box_rem == 0) ก่อน — manual ปิด box เต็มเสมอเมื่อทำได้
    #   2. ใช้ lot หมด (leftover_lot == 0) — ลด carry forward
    #   3. qty มาก — ใช้ material คุ้มค่า
    #   4. n น้อย — สำรอง reel ไว้
    candidates.sort(key=lambda c: (
        c["box_rem"] != 0,
        c["leftover_lot"] != 0,
        -c["qty"],
        c["n"],
    ))
    return candidates[0]


def calculate_safe_allocation(deficit, slots_remaining, lot_remaining,
                              min_reel, max_reel, max_per_box=None,
                              buffer_pct=0.15):
    """
    Calculate safe allocation range for filling an open box.
    
    Ensures that:
    1. The quantity fits within buffer constraints (safety margin)
    2. Remaining slots can be filled by future lots
    3. No scrap/waste is created from the allocation
    
    Args:
        deficit: Amount needed to fill box to max_per_box
        slots_remaining: Number of empty reel slots in box
        lot_remaining: Material available from current lot
        min_reel: Minimum per reel
        max_reel: Maximum per reel
        max_per_box: Maximum per box (for reference)
        buffer_pct: Safety buffer percentage (default 15%)
    
    Returns:
        (min_take, max_take) tuple if safe allocation exists
        None if no safe allocation possible (should defer)
    """
    if slots_remaining <= 0 or deficit <= 0:
        return None
    
    if min_reel <= 0:
        # No min constraint: any amount is safe
        return (0, min(deficit, lot_remaining))
    
    # Calculate buffer (safety margin for next lot)
    safe_min = int(min_reel * (1 + buffer_pct))  # e.g., 1500 * 1.15 = 1725
    
    # === Calculate box_min_take ===
    # We need to leave room for the remaining slots to potentially reach max_per_box
    # Worst case: each remaining slot takes min_reel
    slots_after_this = slots_remaining - 1  # After placing 1 reel in this slot
    if slots_after_this > 0:
        # Remaining slots need at least slots_after_this * min_reel to be valid
        box_min_take = deficit - (slots_after_this * max_reel)
    else:
        # Last slot: must fill deficit completely or not at all
        box_min_take = deficit
    
    # === Calculate box_max_take ===
    # We need to leave minimum headroom for remaining slots
    if slots_after_this > 0:
        box_max_take = deficit - (slots_after_this * safe_min)
    else:
        box_max_take = deficit
    
    # === Clamp to actual constraints ===
    actual_min = max(min_reel, box_min_take)
    actual_max = min(max_reel, box_max_take, deficit, lot_remaining)
    
    # === Validate: can remaining slots still fill to max_per_box? ===
    if slots_after_this > 0:
        deficit_after = deficit - actual_min
        min_fillable = slots_after_this * min_reel
        max_fillable = slots_after_this * max_reel
        
        if not (min_fillable <= deficit_after <= max_fillable):
            # This take amount creates an unreachable deficit for remaining slots
            return None
    
    # === Final validation ===
    if actual_min > actual_max:
        return None
    
    if actual_min < 0 or actual_max < 0:
        return None
    
    return (actual_min, actual_max)


# ══════════════════════════════════════════════════
#  LOT-BY-LOT PLANNING v2 (UPDATED)
# ══════════════════════════════════════════════════

def calculate_single_lot_plan(lot_no, lot_qty, order_remaining,
                              max_per_box, max_per_reel, min_per_reel=0,
                              reels_per_box=3,
                              start_box=1, start_reel=1,
                              open_box_slots=0,
                              carry_remainder=0, carry_lot="",
                              resume_reel=None,
                              open_boxes=None,
                              invoice_qty=None,
                              defer_last_reel=False,
                              pre_filled_reels=None):
    """
    Plan packing for a single lot (lot-by-lot mode) with Order Blueprint & Safe Allocation.
    
    Enhanced with:
    - Phase 0: Order Blueprint (max_expected_boxes = ceil(invoice_qty / max_per_box))
    - Phase 1: Fill open boxes with Safe Allocation Range validation
    - Phase 2: Create new boxes with guardrails (don't exceed max_expected_boxes)
    - Phase 3: Ultimate Fallback (defer unsafe fills vs override with remaining material)
    
    Args:
        invoice_qty:      Total order quantity (for box blueprint calculation)
        defer_last_reel:  [FINAL LOT ONLY] If True and remainder < min_per_reel,
                          pull the last reel out of the last box, convert it to a
                          "Wait next lot" slot, and carry the material forward as
                          remainder instead of creating a sub-min Remainder Reel.
                          Default False preserves original behaviour.
        Other args: as before
    
    Return: (plan, plan_state) dict
    """
    rpb = max(1, reels_per_box)
    plan = []
    newly_open_boxes = []
    box_no = start_box
    reel_no = start_reel

    # ══════════════════════════════════════════════════════════════
    # PHASE 0: ORDER BLUEPRINT SETUP
    # Calculate maximum expected boxes to prevent overpacking
    # ══════════════════════════════════════════════════════════════
    max_expected_boxes = None
    if invoice_qty is not None and invoice_qty > 0:
        max_expected_boxes = math.ceil(invoice_qty / max_per_box)
        _log.debug(f"[BLUEPRINT] Invoice Qty: {invoice_qty:,}, Max Expected Boxes: {max_expected_boxes}")
    
    def _seal_box_rows(bno, base_total=0):
        bt = base_total + sum(r["target"] for r in plan if r["box"] == bno)
        for r in plan:
            if r["box"] == bno:
                r["box_total"] = bt

    def _add_wait_slots(bno, count):
        for _ in range(count):
            plan.append({
                "box": bno, "reel": 0,
                "lot": "", "target": 0,
                "box_total": None, "note": "Wait next lot"
            })

    # ── Phase 1: Fill previously open boxes ──
    pending_open = [dict(ob) for ob in open_boxes] if open_boxes else []
    if open_box_slots > 0 and not pending_open:
        pending_open = [{"box": box_no, "slots": open_box_slots, "current_total": 0}]

    # เรียง open boxes ตาม deficit น้อยไปมาก (box ที่ใกล้เต็มก่อน)
    # เรียง open boxes ตาม deficit น้อยไปมาก (box ที่ใกล้เต็มก่อน)
    pending_open.sort(key=lambda ob: max_per_box - ob["current_total"])

    # ══════════════════════════════════════════════════════════════
    # [FIX-BUG] ลอจิก Look-Ahead และ Overpack Fallback ป้องกัน Infinite Loop
    # ══════════════════════════════════════════════════════════════
    if min_per_reel > 0 and 0 < order_remaining < min_per_reel:
        # ถ้ายอด Order เหลือให้เทน้อยกว่า min_per_reel 
        # ยอม Overpack ดึงมาให้เท่ากับ min_per_reel เพื่อให้วางลงกล่องได้ (ไม่เป็น scrap)
        lot_remaining = min(lot_qty, min_per_reel)
    else:
        lot_remaining = min(lot_qty, order_remaining)
        if min_per_reel > 0:
            # Look-Ahead: เช็คยอดที่จะตกไปถึง Lot ถัดไป (future_remaining)
            _future_rem = order_remaining - lot_remaining
            if 0 < _future_rem < min_per_reel:
                # ถ้าปล่อยไป Lot หน้าจะแพ็คไม่ได้ (เพราะยอด < min)
                # ลดการแพ็คใน Lot นี้ลง เพื่อดันยอด (shortfall) ไปรวมกับ Lot หน้า
                _shortfall = min_per_reel - _future_rem
                if lot_remaining > _shortfall:
                    lot_remaining -= _shortfall
                else:
                    lot_remaining = 0

    pack_limit = lot_remaining
    _carry_in_original = carry_remainder
    _is_final_lot = (lot_qty + carry_remainder >= order_remaining)

    # ══════════════════════════════════════════════════════════════
    # [FIX-NEG-REEL v2] ORDER-CAP REORDER (final lot only)
    # ──────────────────────────────────────────────────────────────
    # ปัญหาเดิม: เมื่อ order_remaining น้อยกว่าผลรวม min_per_reel ของ
    # open boxes ทั้งหมด (เช่น order=2,465, Box1 ต้องการ ≥1,500,
    # Box2 ต้องการ ≥3,000) ระบบจะเริ่มเติม Box1 ก่อนเพราะ deficit น้อย
    # แล้ว Box2 เหลือ lot ไม่พอ → reel ติดลบ
    #
    # แก้: ถ้าเป็น final lot และมี box ที่รับ lot_remaining ได้ทั้งหมด
    # ในตัวเดียว (deficit >= lot_remaining >= min_per_reel) ให้ลำดับ
    # box นั้นมาก่อน เพื่อปิด order ในกล่องเดียวจบ ไม่ต้อง split
    # ──────────────────────────────────────────────────────────────
    if (_is_final_lot and min_per_reel > 0
            and lot_remaining >= min_per_reel
            and len(pending_open) > 1):
        single_fit = []
        others = []
        for ob in pending_open:
            deficit = max_per_box - ob["current_total"]
            # Box รับ lot_remaining ได้ใน 1 reel: deficit ≥ lot_remaining,
            # lot_remaining ≤ max_per_reel, มี slot เหลือ
            if (ob["slots"] >= 1
                    and deficit >= lot_remaining
                    and lot_remaining <= max_per_reel):
                single_fit.append(ob)
            else:
                others.append(ob)
        if single_fit:
            # เรียง single_fit ตาม deficit น้อยไปมาก เหมือนเดิม
            single_fit.sort(key=lambda ob: max_per_box - ob["current_total"])
            others.sort(key=lambda ob: max_per_box - ob["current_total"])
            pending_open = single_fit + others
            _log.debug(f"[ORDER-CAP REORDER] lot_remaining={lot_remaining:,} "
                       f"fits in 1 reel of box(es) "
                       f"{[ob['box'] for ob in single_fit]} → reordered first")

    # =========================================================
    # 🔒 Optimizer DISABLED (Option A patch)
    # ═══════════════════════════════════════════════════════════
    # _optimize_open_boxes_allocation ถูกแทนที่ด้วย find_best_box_split
    # ในแต่ละ ob loop (ดู PHASE 1) ซึ่งให้ผลสอดคล้องกันกว่า
    # ไม่ cap budget เป็น max_per_reel ผิดๆ
    # =========================================================
    ob_budgets = {}
    # =========================================================

    # ──────────────────────────────────────────────────────────
    #  Priority filling: Fill as much as possible into open boxes
    # ──────────────────────────────────────────────────────────
    # (ลบโค้ด Priority filling แบบเก่าที่เป็น [SMART FILL] ทิ้งไปได้เลย 
    # เพราะ Optimizer ของเราเก่งกว่าและจัดการยอดให้ตั้งแต่ต้นแล้ว)

    # วาง carry ที่ >= min_per_reel ลง open boxes (ข้าม carry ที่ < min)
    _can_defer_carry = False
    if (carry_remainder >= min_per_reel and carry_lot
            and len(pending_open) > 1):
        for _ob in pending_open[1:]:
            if (_ob["slots"] > 0
                    and (max_per_box - _ob["current_total"]) >= min_per_reel):
                _can_defer_carry = True
                break

    for _ob_idx, ob in enumerate(pending_open):
        hist_total = ob["current_total"]
        if ob["slots"] <= 0:
            _seal_box_rows(ob["box"], base_total=hist_total)
            if ob["box"] >= box_no:
                box_no = ob["box"] + 1
            continue

        # เริ่มต้น Budget จาก Deficit พื้นฐาน
        box_budget = max_per_box - ob["current_total"]

        # =========================================================
        # 🌟 บังคับใช้ Budget จาก Optimizer (ถ้ามี)
        # =========================================================
        if ob["box"] in ob_budgets and ob_budgets[ob["box"]] > 0:
            box_budget = ob_budgets[ob["box"]]
        elif ob["box"] in ob_budgets and ob_budgets[ob["box"]] == 0:
            # Optimizer บอกว่าห้ามเติมกล่องนี้ (เพื่อป้องกัน Scrap/Wait slot พัง)
            # ให้บันทึกเป็น Wait slot ต่อไปแล้วข้ามเลย
            if ob["slots"] > 0:
                _add_wait_slots(ob["box"], ob["slots"])
                newly_open_boxes.append({
                    "box": ob["box"], "slots": ob["slots"], "current_total": ob["current_total"]
                })
                ob["slots"] = 0
            _seal_box_rows(ob["box"], base_total=hist_total)
            if ob["box"] >= box_no: box_no = ob["box"] + 1
            continue
        # วาง carry (เฉพาะ >= min_per_reel)
        if (carry_remainder >= min_per_reel and min_per_reel > 0
                and carry_lot and ob["slots"] > 0
                and box_budget >= min_per_reel
                and not (_ob_idx == 0 and _can_defer_carry)):
            if carry_remainder <= max_per_reel:
                num_carry = 1
            else:
                num_carry = min(ob["slots"],
                                -(-carry_remainder // min_per_reel))
                while num_carry > 1:
                    per = carry_remainder // num_carry
                    if per < min_per_reel:
                        num_carry -= 1
                    else:
                        break
            carry_for_box = min(carry_remainder, box_budget,
                                num_carry * max_per_reel)
            if carry_for_box >= min_per_reel:
                nc = min(num_carry, carry_for_box // min_per_reel)
                nc = max(1, nc)
                carry_for_box = min(carry_for_box, nc * max_per_reel)

                slots_after_carry = ob["slots"] - nc
                total_after_carry = ob["current_total"] + carry_for_box
                if not _box_fillable(total_after_carry, slots_after_carry,
                                     max_per_box, min_per_reel, max_per_reel):
                    # ข้ามการวาง carry ใน box นี้ถ้าทำให้ box เติมไม่เต็ม
                    pass
                else:
                    c_reels = _distribute_balanced_reels(carry_for_box, nc,
                                                min_per_reel, max_per_reel)
                    for cq in c_reels:
                        plan.append({
                            "box": ob["box"], "reel": reel_no,
                            "lot": carry_lot, "target": cq,
                            "box_total": None, "note": "Carry"
                        })
                        reel_no += 1
                        ob["slots"] -= 1
                        ob["current_total"] += cq
                        carry_remainder -= cq
                    box_budget = min(box_budget, max_per_box - ob["current_total"])
                    
        actual_target = min(lot_remaining, box_budget)
        
        # ══════════════════════════════════════════════════════════════
        # PHASE 1 (Option A): FORWARD-AWARE BOX SPLIT
        # ใช้ find_best_box_split เพื่อหา split ที่ดีที่สุดแทน
        # safe_allocation + optimizer ที่เคยขัดแย้งกัน
        #
        # Logic: พยายามใช้ reel น้อยที่สุดก่อน และ
        #   - ถ้าใช้ lot หมดได้โดย wait_slot ถัดไปรับได้ → A-wait/A-full
        #   - ถ้าต้องเหลือ carry → ต้อง >= min_per_reel (valid carry)
        #   - ถ้าไม่มี split ไหน valid → DEFER entire box
        # ══════════════════════════════════════════════════════════════
        if (min_per_reel > 0 and ob["slots"] > 0 and lot_remaining > 0
                and not _is_final_lot):
            deficit = max_per_box - ob["current_total"]
            split = find_best_box_split(
                deficit, ob["slots"], lot_remaining,
                min_per_reel, max_per_reel
            )
            if split is None:
                # No valid split: defer this box
                _log.debug(f"[DEFER BOX {ob['box']}] deficit={deficit:,}, "
                      f"slots={ob['slots']}, lot_remaining={lot_remaining:,} "
                      f"→ find_best_box_split returned None. Deferring.")
                if ob["slots"] > 0:
                    _add_wait_slots(ob["box"], ob["slots"])
                    newly_open_boxes.append({
                        "box": ob["box"], "slots": ob["slots"],
                        "current_total": ob["current_total"]
                    })
                _seal_box_rows(ob["box"], base_total=hist_total)
                if ob["box"] >= box_no:
                    box_no = ob["box"] + 1
                continue

            # Split found: set can_fill / use_fill from split result
            can_fill = split["n"]
            use_fill = split["qty"]
            _log.debug(f"[SPLIT BOX {ob['box']}] type={split['type']}, "
                       f"n={split['n']}, qty={split['qty']:,}, "
                       f"lot_left={split['leftover_lot']:,}, "
                       f"wait_after={split['wait_after']}, "
                       f"box_rem={split['box_rem']:,}")
        elif min_per_reel > 0:
            # Final lot path: use direct deficit filling
            deficit = max_per_box - ob["current_total"]
            if box_budget >= deficit:
                # [FIX-NEG-REEL v2] เดิม: can_fill = ob["slots"] เสมอ → ถ้า
                # use_fill < slots * min_per_reel จะเกิด reel ติดลบ
                # (เช่น use_fill=965, slots=2, min=1500 → [1500, -535])
                # แก้: clamp can_fill ตาม use_fill ให้ทุก reel >= min_per_reel
                use_fill = min(deficit, lot_remaining)
                if use_fill <= 0:
                    can_fill = 0
                elif min_per_reel > 0 and use_fill < min_per_reel:
                    # use_fill น้อยกว่า min_per_reel → ใส่ box นี้ไม่ได้เลย
                    # ปล่อยให้ Phase 2 จัดการเป็น remainder reel (Box 0)
                    can_fill = 0
                    use_fill = 0
                else:
                    # หา can_fill ที่ทำให้ทุก reel อยู่ใน [min_per_reel, max_per_reel]
                    if min_per_reel > 0:
                        max_by_min = use_fill // min_per_reel
                    else:
                        max_by_min = ob["slots"]
                    min_by_max = -(-use_fill // max_per_reel) if max_per_reel > 0 else 1
                    # เลือก can_fill น้อยสุดเท่าที่จำเป็น (ใช้ reel ใหญ่ก่อน) ภายใน slots
                    can_fill = max(1, min_by_max)
                    can_fill = min(can_fill, max_by_min, ob["slots"])
                    if can_fill <= 0:
                        # use_fill > slots * max_per_reel — เกินที่ box นี้รับได้
                        # ใช้ทั้งหมด slot, ที่เหลือไป Phase 2
                        can_fill = ob["slots"]
                        use_fill = min(use_fill, can_fill * max_per_reel)
            else:
                if actual_target <= 0:
                    can_fill = 0
                    use_fill = 0
                else:
                    needed_slots = math.ceil(actual_target / max_per_reel)
                    can_fill = min(ob["slots"], needed_slots)
                    use_fill = min(actual_target, can_fill * max_per_reel)
                    # [FIX-NEG-REEL v2] guard เดียวกันกับ branch บน
                    if min_per_reel > 0 and 0 < use_fill < min_per_reel:
                        can_fill = 0
                        use_fill = 0
                    elif min_per_reel > 0 and use_fill > 0:
                        max_by_min = use_fill // min_per_reel
                        if max_by_min < can_fill:
                            can_fill = max(1, max_by_min)
                            use_fill = min(use_fill, can_fill * max_per_reel)

            # หมายเหตุ: เดิมมี fallback "can_fill==0 → ตั้งเป็น 1 reel" สำหรับ
            # final lot — ลบออก เพราะถ้า lot_remaining < min_per_reel จริง ๆ
            # การยัด 1 reel ที่ < min ลง open box ผิด constraint
            # ปล่อยให้ Phase 2 จัดการเป็น Remainder Reel ดีกว่า
        else:
            can_fill = min(ob["slots"],
                        max(1, (actual_target + max_per_reel - 1) // max_per_reel))
            use_fill = min(actual_target, can_fill * max_per_reel)

        if can_fill > 0 and lot_remaining > 0:
            if use_fill > 0:
                fill_reels = _distribute_balanced_reels(use_fill, can_fill,
                                               min_per_reel, max_per_reel)
                # ── ปรับ fill_reels ให้แต่ละ reel ไม่ทำให้ deficit หลัง fill > max_per_reel ──
                # (สำคัญเมื่อ box_budget < deficit: reel แรกต้องทิ้งช่องว่างพอดีสำหรับ reel ถัดไป)
                if min_per_reel > 0 and can_fill > 1:
                    adjusted = list(fill_reels)
                    for fi in range(len(adjusted) - 1):
                        sim_total = ob["current_total"] + sum(adjusted[:fi+1])
                        deficit_after = max_per_box - sim_total
                        slots_left    = ob["slots"] - (fi + 1)
                        if slots_left > 0 and deficit_after > max_per_reel:
                            # reel นี้มากเกินไป → ลด qty เพื่อให้ deficit ≤ max_per_reel × slots
                            max_allowed = max_per_box - ob["current_total"] - sum(adjusted[:fi]) - (slots_left * min_per_reel)
                            max_allowed = min(max_allowed, max_per_reel)
                            if max_allowed >= min_per_reel:
                                overflow   = adjusted[fi] - max_allowed
                                # [FIX-NEG-REEL v2] ปรับเฉพาะ overflow บวก
                                # (reel ปัจจุบันใหญ่เกิน max_allowed) — ถ้า
                                # overflow ≤ 0 หมายความว่า reel ปัจจุบันไม่ใหญ่
                                # เกินอยู่แล้ว การ "+= overflow" จะทำให้ reel
                                # ถัดไปติดลบเปล่า ๆ
                                if overflow > 0:
                                    adjusted[fi]    = max_allowed
                                    adjusted[fi+1] += overflow
                                    # clamp next reel to max
                                    if adjusted[fi+1] > max_per_reel:
                                        adjusted[fi+1] = max_per_reel
                    fill_reels = adjusted

                for fi, qty in enumerate(fill_reels):
                    slots_after = ob["slots"] - 1
                    total_after = ob["current_total"] + qty
                    if (min_per_reel > 0
                            and slots_after > 0
                            and not _is_final_lot
                            and not _box_fillable(total_after, slots_after,
                                                  max_per_box, min_per_reel, max_per_reel)):
                        lot_remaining += sum(fill_reels[fi + 1:])
                        break
                    plan.append({
                        "box": ob["box"], "reel": reel_no,
                        "lot": lot_no, "target": qty,
                        "box_total": None, "note": ""
                    })
                    reel_no += 1
                    ob["slots"] -= 1
                    ob["current_total"] += qty
                    lot_remaining -= qty

        if ob["slots"] > 0 and not _is_final_lot:
            _add_wait_slots(ob["box"], ob["slots"])
            # อัปเดต open boxes list
            newly_open_boxes.append({
                "box": ob["box"],
                "slots": ob["slots"],
                "current_total": ob["current_total"]
            })
            ob["slots"] = 0

        # ══════════════════════════════════════════════════════════════
        # 🔍 POST-FILL VALIDATION: ตรวจสอบหลังจาก slots หมดแล้ว
        #    ถ้า box ไม่เต็ม (current_total < max_per_box) และ slots == 0
        #    → box จะ "stuck" ไม่มีทางเติมให้เต็มได้ ต้องจัดการ 2 กรณี:
        #
        #    กรณี A: deficit อยู่ใน [n*min_per_reel, n*max_per_reel] สำหรับ n >= 1
        #    → เพิ่ม "Wait next lot" n slots (box ยังรอ lot ถัดไปได้)
        #
        #    กรณี B: deficit < min_per_reel (ยัดเพิ่มไม่ได้เลย)
        #    → ถอน reel สุดท้ายที่เพิ่งวางออกไปเป็น Remainder
        #    → เพิ่ม "Wait next lot" แทน
        # ══════════════════════════════════════════════════════════════
        if (not _is_final_lot
                and min_per_reel > 0
                and ob["slots"] == 0
                and ob["current_total"] < max_per_box):

            deficit = max_per_box - ob["current_total"]

            # หาจำนวน wait slots ที่พอดีกับ deficit
            # นับ wait slots ที่มีอยู่แล้วใน plan สำหรับ box นี้
            existing_wait_in_plan = sum(
                1 for r in plan
                if r["box"] == ob["box"] and r.get("note") == "Wait next lot"
            )
            total_wait_needed = existing_wait_in_plan  # เริ่มจากที่มีอยู่แล้ว

            # n slots ใช้ได้ถ้า n*min_per_reel <= deficit <= n*max_per_reel
            needed_wait = 0
            max_slots_possible = rpb - sum(
                1 for r in plan
                if r["box"] == ob["box"]
                and r.get("note") not in ("Wait next lot", "Carry")
                and r["target"] > 0
            )
            for n in range(1, max_slots_possible + 1):
                if n * min_per_reel <= deficit <= n * max_per_reel:
                    needed_wait = n
                    break

            # ── กรณี A: deficit ใน range fillable → เพิ่ม wait slots เท่าที่ขาด ──
            if needed_wait > 0:
                slots_to_add = max(0, needed_wait - existing_wait_in_plan)
                if slots_to_add > 0:
                    _add_wait_slots(ob["box"], slots_to_add)
                    ob["slots"] += slots_to_add
                for nob in newly_open_boxes:
                    if nob["box"] == ob["box"]:
                        nob["slots"]         = ob["slots"]
                        nob["current_total"] = ob["current_total"]
                        break
                else:
                    newly_open_boxes.append({
                        "box":           ob["box"],
                        "slots":         ob["slots"],
                        "current_total": ob["current_total"]
                    })
                _log.debug(f"[POST-FILL FIX-A] Box {ob['box']}: added {slots_to_add} Wait slot(s) "
                      f"(deficit {deficit:,} ∈ [{needed_wait*min_per_reel:,},{needed_wait*max_per_reel:,}]). "
                      f"Box now {ob['current_total']:,}/{max_per_box:,} waiting for next lot.")

            # ── กรณี B: deficit < min_per_reel → ถอน reel ออก + wait slot ──
            elif 0 < deficit < min_per_reel:
                new_reels_in_box = [
                    i for i, r in enumerate(plan)
                    if r["box"] == ob["box"]
                    and r.get("lot") == lot_no
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and r["target"] > 0
                ]
                if new_reels_in_box:
                    last_new_idx = new_reels_in_box[-1]
                    pulled_qty   = plan[last_new_idx]["target"]

                    # แปลง reel สุดท้ายเป็น "Wait next lot"
                    plan[last_new_idx]["target"] = 0
                    plan[last_new_idx]["note"]   = "Wait next lot"
                    plan[last_new_idx]["lot"]    = ""
                    plan[last_new_idx]["reel"]   = 0

                    # คืน qty กลับสู่ lot_remaining
                    lot_remaining       += pulled_qty
                    ob["current_total"] -= pulled_qty
                    ob["slots"]         += 1

                    for nob in newly_open_boxes:
                        if nob["box"] == ob["box"]:
                            nob["slots"]         = ob["slots"]
                            nob["current_total"] = ob["current_total"]
                            break
                    else:
                        newly_open_boxes.append({
                            "box":           ob["box"],
                            "slots":         ob["slots"],
                            "current_total": ob["current_total"]
                        })

                    _log.debug(f"[POST-FILL FIX-B] Box {ob['box']}: pulled back {pulled_qty:,} pcs "
                          f"(deficit {deficit:,} < min {min_per_reel:,}). "
                          f"Box now {ob['current_total']:,}/{max_per_box:,} "
                          f"with {ob['slots']} Wait slot(s). "
                          f"lot_remaining restored to {lot_remaining:,}")

        _seal_box_rows(ob["box"], base_total=hist_total)
        if ob["box"] >= box_no:
            box_no = ob["box"] + 1
    
    # ⚠️ NEW: Validate all remaining open boxes are still fillable
    # (important after carry placement — ensure no box becomes unfillable)
    for newly_ob in newly_open_boxes:
        remaining_wait = newly_ob.get("slots", 0)
        current_total = newly_ob.get("current_total", 0)
        if remaining_wait > 0:
            deficit = max_per_box - current_total
            if min_per_reel > 0:
                min_needed = remaining_wait * min_per_reel
                max_possible = remaining_wait * max_per_reel
                if not (min_needed <= deficit <= max_possible):
                    _log.warning(f"Box {newly_ob['box']} has unfillable deficit={deficit} "
                          f"with {remaining_wait} wait slots (need [{min_needed}, {max_possible}])")

    # ══════════════════════════════════════════════════════════════
    # [FIX-BOX4] POST-PHASE-1: Adjust lot_remaining for carry
    # Carry placed in Phase 1 counts toward order fulfillment.
    # If carry has already satisfied order_remaining, lot material
    # should NOT create new boxes — it should go to Box 0.
    # ══════════════════════════════════════════════════════════════
    _carry_placed_phase1 = _carry_in_original - carry_remainder
    _lot_placed_phase1   = pack_limit - lot_remaining
    _total_placed_phase1 = _carry_placed_phase1 + _lot_placed_phase1
    if _is_final_lot and _total_placed_phase1 > 0:
        _effective_remaining = max(0, order_remaining - _total_placed_phase1 - carry_remainder)
        if lot_remaining > _effective_remaining:
            _excess = lot_remaining - _effective_remaining
            _log.debug(f"[FIX-BOX4] Carry placed {_carry_placed_phase1:,} in Phase 1. "
                       f"order_remaining={order_remaining:,}, effective_remaining={_effective_remaining:,}. "
                       f"Capping lot_remaining from {lot_remaining:,} to {_effective_remaining:,} "
                       f"(excess {_excess:,} → will become remainder)")
            lot_remaining = _effective_remaining

    # ── Phase 2: Distribute remaining material into NEW boxes ──
    # newly_open_boxes is initialized at the top
    is_final_lot = _is_final_lot

    if lot_remaining > 0 and (min_per_reel == 0 or lot_remaining >= min_per_reel
                              or is_final_lot):

        if is_final_lot:
            # ========== FINAL LOT: pack everything, no wait slots ==========
            # Place remaining carry (if any) as reels in first new box
            if (carry_remainder >= min_per_reel and carry_lot
                    and lot_remaining >= min_per_reel):
                if carry_remainder <= max_per_reel:
                    num_carry = 1
                else:
                    num_carry = min(rpb, -(-carry_remainder // min_per_reel))
                    while num_carry > 1:
                        per = carry_remainder // num_carry
                        if per < min_per_reel:
                            num_carry -= 1
                        else:
                            break
                carry_reels = _distribute_balanced_reels(carry_remainder, num_carry,
                                                min_per_reel, max_per_reel)
                for cq in carry_reels:
                    plan.append({
                        "box": box_no, "reel": reel_no,
                        "lot": carry_lot, "target": cq,
                        "box_total": None, "note": "Carry"
                    })
                    reel_no += 1
                    carry_remainder -= cq
                remaining_slots = rpb - num_carry
                if remaining_slots > 0 and lot_remaining > 0:
                    box_share = min(lot_remaining, remaining_slots * max_per_reel,
                                    max_per_box - sum(carry_reels))
                    if box_share >= min_per_reel:
                        num_reels = min(remaining_slots, box_share // min_per_reel)
                        num_reels = max(1, num_reels)
                        box_share = min(box_share, num_reels * max_per_reel)
                        box_reels = _distribute_balanced_reels(box_share, num_reels,
                                                      min_per_reel, max_per_reel)
                        for qty in box_reels:
                            plan.append({
                                "box": box_no, "reel": reel_no,
                                "lot": lot_no, "target": qty,
                                "box_total": None, "note": ""
                            })
                            reel_no += 1
                            lot_remaining -= qty
                _seal_box_rows(box_no)
                box_no += 1

            # Pack the rest into full boxes or remainder reels
            while lot_remaining > 0:
                if min_per_reel > 0 and lot_remaining < min_per_reel:
                    # ══════════════════════════════════════════════════════
                    # [DEFER LAST REEL] ถ้า caller ส่ง defer_last_reel=True
                    # → ดึง reel สุดท้ายออกจาก box ล่าสุด + แปลงเป็น Wait slot
                    # → ส่งยอด (pulled + lot_remaining) กลับเป็น remainder
                    # แทนที่จะสร้าง Remainder Reel < min_per_reel
                    # ══════════════════════════════════════════════════════
                    if defer_last_reel:
                        # หา reel สุดท้ายใน plan (ไม่ใช่ Wait slot / box=0)
                        last_packable_idx = -1
                        for _i in range(len(plan) - 1, -1, -1):
                            _r = plan[_i]
                            if (_r.get("note") not in ("Wait next lot", "Carry")
                                    and _r["box"] != 0
                                    and _r["target"] > 0):
                                last_packable_idx = _i
                                break

                        if last_packable_idx >= 0:
                            _pulled = plan[last_packable_idx]
                            pulled_qty = _pulled["target"]
                            pulled_box = _pulled["box"]

                            # แปลง reel เป็น "Wait next lot"
                            _pulled["target"] = 0
                            _pulled["note"]   = "Wait next lot"
                            _pulled["lot"]    = ""
                            _pulled["reel"]   = 0

                            # อัปเดต box_total ของ box ที่ดึงออก
                            new_bt = sum(
                                r["target"] for r in plan
                                if r["box"] == pulled_box
                                and r.get("note") != "Wait next lot"
                            )
                            for r in plan:
                                if r["box"] == pulled_box:
                                    r["box_total"] = new_bt

                            # รวม pulled + lot_remaining
                            lot_remaining += pulled_qty
                            _log.debug(f"[DEFER LAST REEL] Box {pulled_box}: pulled {pulled_qty:,} pcs. "
                                  f"lot_remaining now {lot_remaining:,}")

                            # ── ลอง redistribute lot_remaining เข้า open box อื่นที่รับได้ ──
                            # (เช่น Box 2 ที่มี wait slot อยู่รับ reel ใหม่ได้)
                            for _ob_r in sorted(
                                    newly_open_boxes,
                                    key=lambda x: x["box"]):
                                if _ob_r["box"] == pulled_box:
                                    continue  # ข้าม box ที่เพิ่งดึงออก
                                _ob_slots = _ob_r.get("slots", 0)
                                _ob_curr  = _ob_r.get("current_total", 0)
                                _ob_deficit = max_per_box - _ob_curr
                                if _ob_slots <= 0 or _ob_deficit < min_per_reel:
                                    continue
                                # ตรวจว่า lot_remaining พอดึงลงได้
                                _can_put = min(lot_remaining, _ob_deficit,
                                               _ob_slots * max_per_reel)
                                if _can_put < min_per_reel:
                                    continue
                                _rem_after_ob = lot_remaining - _can_put
                                # เช็คว่าเศษที่เหลือหลังวาง == 0 หรือ >= min
                                if _rem_after_ob > 0 and _rem_after_ob < min_per_reel:
                                    # ลอง reduce _can_put ให้เศษ = 0 หรือ >= min
                                    _try_put = lot_remaining  # ใส่ทั้งหมด
                                    if (_try_put <= _ob_deficit
                                            and _try_put >= min_per_reel
                                            and _try_put <= _ob_slots * max_per_reel):
                                        _can_put = _try_put
                                        _rem_after_ob = 0
                                    else:
                                        continue  # ไม่มี allocation ที่ปลอดภัย
                                # จัดจำนวน reels
                                _n_put = min(_ob_slots,
                                             max(1, -(-_can_put // max_per_reel)))
                                while _n_put > 1 and (_can_put // _n_put) < min_per_reel:
                                    _n_put -= 1
                                _put_reels = _distribute_balanced_reels(
                                    _can_put, _n_put, min_per_reel, max_per_reel)
                                for _pq in _put_reels:
                                    plan.append({
                                        "box": _ob_r["box"], "reel": reel_no,
                                        "lot": lot_no, "target": _pq,
                                        "box_total": None, "note": ""
                                    })
                                    reel_no += 1
                                    _ob_r["current_total"] += _pq
                                    _ob_r["slots"] -= 1
                                new_ob_bt = _ob_r["current_total"]
                                for r in plan:
                                    if r["box"] == _ob_r["box"]:
                                        r["box_total"] = new_ob_bt
                                lot_remaining -= _can_put
                                _log.debug(f"[DEFER LAST REEL] Redistributed {_can_put:,} pcs "
                                      f"into Box {_ob_r['box']}. "
                                      f"lot_remaining now {lot_remaining:,}")
                                break  # วางได้กล่องเดียวก็พอ

                        # break ออก — lot_remaining ที่เหลือจะกลายเป็น remainder
                        break
                    # Tiny remainder: try to merge into last reel of previous box
                    merged = False
                    # หา current_total เดิมของแต่ละ open_box เพื่อใช้ตรวจ box capacity
                    _ob_current = {ob["box"]: ob["current_total"]
                                   for ob in (open_boxes or [])}
                    for i in range(len(plan)-1, -1, -1):
                        if plan[i].get("note") == "Wait next lot":
                            continue
                        if plan[i]["box"] != 0 and plan[i]["target"] + lot_remaining <= max_per_reel:
                            # [FIX-NEG-REEL v2] guard: ห้ามทำให้ Box overflow
                            # เดิมเช็คแค่ reel constraint แต่ไม่เช็ค box capacity
                            target_box = plan[i]["box"]
                            # box_total เต็ม = current_total เดิม + targets ใน plan
                            full_box_total = _ob_current.get(target_box, 0) + sum(
                                r["target"] for r in plan
                                if r["box"] == target_box
                                and r.get("note") != "Wait next lot"
                            )
                            if full_box_total + lot_remaining > max_per_box:
                                # merge ลง reel นี้จะทำให้ box เกิน — ลอง reel อื่น
                                continue
                            plan[i]["target"] += lot_remaining
                            new_full_total = full_box_total + lot_remaining
                            for r in plan:
                                if r["box"] == target_box:
                                    r["box_total"] = new_full_total
                            lot_remaining = 0
                            merged = True
                            break
                    if merged:
                        break
                    else:
                        # Create remainder reel (box=0)
                        rem_reels = _distribute_balanced_reels(lot_remaining, 1,
                                                      min_per_reel, max_per_reel)
                        for rq in rem_reels:
                            plan.append({
                                "box": 0, "reel": reel_no,
                                "lot": lot_no, "target": rq,
                                "box_total": None,
                                "note": "Remainder Reel (Next Plan)"
                            })
                            reel_no += 1
                            lot_remaining -= rq
                    break

                # ══════════════════════════════════════════════════════════════
                # [FIX-BOX4] GUARDRAIL: Don't exceed max_expected_boxes
                # Route excess material to Box 0 (remainder) instead of
                # creating new boxes beyond the order's box blueprint.
                # ══════════════════════════════════════════════════════════════
                if (max_expected_boxes is not None
                        and box_no > max_expected_boxes):
                    _log.debug(f"[FIX-BOX4 GUARDRAIL] box_no={box_no} > "
                               f"max_expected={max_expected_boxes} → "
                               f"routing {lot_remaining:,} pcs to Box 0")
                    if lot_remaining >= min_per_reel:
                        _num_rem = max(1, -(-lot_remaining // max_per_reel))
                        while _num_rem > 1 and (lot_remaining // _num_rem) < min_per_reel:
                            _num_rem -= 1
                        _rem_reels = _distribute_balanced_reels(
                            lot_remaining, _num_rem, min_per_reel, max_per_reel)
                        for rq in _rem_reels:
                            plan.append({
                                "box": 0, "reel": reel_no,
                                "lot": lot_no, "target": rq,
                                "box_total": None,
                                "note": "Remainder Reel (Box limit reached)"
                            })
                            reel_no += 1
                            lot_remaining -= rq
                    elif lot_remaining > 0:
                        # lot_remaining < min_per_reel: merge into last reel or create small remainder
                        _merged = False
                        for _mi in range(len(plan) - 1, -1, -1):
                            if plan[_mi].get("note") == "Wait next lot":
                                continue
                            if (plan[_mi]["box"] != 0
                                    and plan[_mi]["target"] + lot_remaining <= max_per_reel):
                                plan[_mi]["target"] += lot_remaining
                                _bt = sum(r["target"] for r in plan
                                          if r["box"] == plan[_mi]["box"]
                                          and r.get("note") != "Wait next lot")
                                for r in plan:
                                    if r["box"] == plan[_mi]["box"]:
                                        r["box_total"] = _bt
                                lot_remaining = 0
                                _merged = True
                                break
                        if not _merged:
                            plan.append({
                                "box": 0, "reel": reel_no,
                                "lot": lot_no, "target": lot_remaining,
                                "box_total": None,
                                "note": "Remainder Reel (Box limit reached)"
                            })
                            reel_no += 1
                            lot_remaining = 0
                    break

                use_box = min(lot_remaining, max_per_box, rpb * max_per_reel)
                if min_per_reel > 0:
                    num_reels = min(rpb, use_box // min_per_reel)
                else:
                    num_reels = min(rpb, (use_box + max_per_reel - 1) // max_per_reel)
                num_reels = max(1, num_reels)
                use_box = min(use_box, num_reels * max_per_reel)
                if num_reels == 0:
                    break

                box_reels = _distribute_balanced_reels(use_box, num_reels,
                                              min_per_reel, max_per_reel)
                for qty in box_reels:
                    plan.append({
                        "box": box_no, "reel": reel_no,
                        "lot": lot_no, "target": qty,
                        "box_total": None, "note": ""
                    })
                    reel_no += 1
                    lot_remaining -= qty
                _seal_box_rows(box_no)
                box_no += 1

        else:
            # ========== NOT FINAL LOT ==========
            # Step A: Fill FULL BOXES (rpb reels, total = max_per_box) as many as possible
            while lot_remaining >= max_per_box:
                # ══════════════════════════════════════════════════════════════
                # PHASE 2: GUARDRAIL - Don't exceed max_expected_boxes
                # ══════════════════════════════════════════════════════════════
                if (max_expected_boxes is not None 
                        and box_no > max_expected_boxes):
                    _log.debug(f"[PHASE 2 BREAK] box_no={box_no} > max_expected_boxes={max_expected_boxes}")
                    break
                
                # [NEW] มองล่วงหน้า: ถ้าเติมกล่องเต็มแล้วเหลือเศษน้อยกว่า min_per_reel (จะเกิด Scrap)
                if min_per_reel > 0:
                    leftover = lot_remaining - max_per_box
                    if 0 < leftover < min_per_reel:
                        break  # หยุดสร้างกล่องเต็มทันที เพื่อเก็บยอดทั้งหมดไปให้ Step B ถัวลงกล่องเปิดแทน
                
                full_box_reels = _distribute_balanced_reels(max_per_box, rpb,
                                                   min_per_reel, max_per_reel)
                for qty in full_box_reels:
                    plan.append({
                        "box": box_no, "reel": reel_no,
                        "lot": lot_no, "target": qty,
                        "box_total": None, "note": ""
                    })
                    reel_no += 1
                    lot_remaining -= qty
                _seal_box_rows(box_no)
                box_no += 1

            # Step B: Spread remaining material into open boxes (try rpb-1 down to 1 reels + wait slots)
            # [SMART CHECK] Before creating an open box, verify its wait slots can
            # realistically be filled to max_per_box by future lots.
            # If filling is impossible at any reel count, defer the entire box
            # (emit only "Wait next lot" rows) so the next lot can open it properly.
            while lot_remaining > 0 and (min_per_reel == 0 or lot_remaining >= min_per_reel):
                # ══════════════════════════════════════════════════════════════
                # PHASE 2: GUARDRAIL - Don't exceed max_expected_boxes (Step B)
                # ══════════════════════════════════════════════════════════════
                if (max_expected_boxes is not None 
                        and box_no > max_expected_boxes):
                    _log.debug(f"[PHASE 2 BREAK Step B] box_no={box_no} > max_expected_boxes={max_expected_boxes}")
                    break
                
                best_num_reels = 0
                best_box_share = 0

                # [FIX-EFFICIENCY-2] เดิม max_possible_reels = rpb-1 (สำรอง wait slot
                # เสมอ) → ใช้ได้แค่ 2 reels/box ทั้งที่ lot มี material พอเติม 3 reels
                # แก้: ลอง rpb reels ก่อน — material พอครบก็ปิด box ในรอบนี้เลย
                max_possible_reels = rpb
                for try_reels in range(max_possible_reels, 0, -1):
                    wait_slots = rpb - try_reels

                    # Cap box_share so wait slots still have room to reach max_per_box
                    max_fillable_share = max_per_box
                    if min_per_reel > 0:
                        max_fillable_share = max_per_box - (wait_slots * min_per_reel)

                    box_share = min(lot_remaining, try_reels * max_per_reel,
                                    max_per_box, max_fillable_share)

                    # [FIX-EFFICIENCY-3] Avoid leaving a remainder below min_per_reel
                    # เดิม: ลด box_share ลง min ทั้งที่ try_reels ปิด box ได้พอดี
                    # แก้: ถ้า try_reels ปิด box (wait_slots=0) และ box_share ปิดเต็มได้
                    # → ใช้ค่านั้น ปล่อยให้ leftover loop ใหม่
                    if min_per_reel > 0:
                        after = lot_remaining - box_share
                        if 0 < after < min_per_reel:
                            if wait_slots == 0 and box_share >= max_per_box:
                                pass  # keep box_share at max_per_box
                            else:
                                box_share = lot_remaining - min_per_reel
                                if box_share < min_per_reel:
                                    box_share = lot_remaining

                    # Primary fillability check: can wait slots fill this box to max?
                    if not _box_fillable(box_share, wait_slots,
                                         max_per_box, min_per_reel, max_per_reel):
                        continue

                    # [NEW] Secondary fillability check: even if arithmetic says "yes",
                    # verify that the actual deficit is reachable within [min, max] per slot.
                    # e.g. box_share=5950, wait_slots=1, max=6400 → deficit=450 < min=1500
                    #      → future lot can NEVER fill this slot → reject this configuration.
                    if min_per_reel > 0 and wait_slots > 0:
                        deficit = max_per_box - box_share
                        min_needed = wait_slots * min_per_reel
                        max_possible_fill = wait_slots * max_per_reel
                        if deficit < min_needed or deficit > max_possible_fill:
                            # This open box can never be filled to max_per_box.
                            # Try reducing num_reels (more wait slots = more flexibility)
                            continue

                    best_num_reels = try_reels
                    best_box_share = box_share
                    break

                # Fallback: no valid configuration found — all reels counts create
                # an open box whose deficit is unreachable by any future lot.
                # → Emit a fully-deferred box (all wait slots, no material placed now).
                #   The next lot will open this box fresh with the right split.
                if best_num_reels == 0:
                    # Only defer if there genuinely is a next lot to fill this box.
                    # If we're out of options, place 1 reel so material isn't lost.
                    if min_per_reel > 0 and lot_remaining >= min_per_reel:
                        # Check whether a deferred (pure wait) box makes sense:
                        # It does when lot_remaining alone cannot produce a valid split.
                        can_defer = True
                        for try_reels in range(max_possible_reels, 0, -1):
                            _ws = rpb - try_reels
                            _share = min(lot_remaining, try_reels * max_per_reel)
                            if _share >= min_per_reel and _box_fillable(
                                    _share, _ws, max_per_box, min_per_reel, max_per_reel):
                                # At least one reel count works without the deficit check —
                                # prefer placing material (don't fully defer).
                                can_defer = False
                                best_num_reels = try_reels
                                best_box_share = _share
                                break
                        if can_defer:
                            # Defer: emit pure wait-slot box, return all material to
                            # carry so next lot handles it.
                            _add_wait_slots(box_no, rpb)
                            newly_open_boxes.append({
                                "box": box_no,
                                "slots": rpb,
                                "current_total": 0
                            })
                            _seal_box_rows(box_no)
                            box_no += 1
                            # Don't consume lot_remaining — break so caller carries it
                            break
                    if best_num_reels == 0:
                        # Last resort: place 1 reel, accept the open box as-is
                        best_num_reels = 1
                        best_box_share = min(lot_remaining, max_per_reel)
                        if min_per_reel > 0:
                            after = lot_remaining - best_box_share
                            if 0 < after < min_per_reel:
                                best_box_share = lot_remaining - min_per_reel
                                if best_box_share < min_per_reel:
                                    best_box_share = lot_remaining

                num_reels = best_num_reels
                box_share = best_box_share
                wait_this = rpb - num_reels

                # Distribute into reels
                box_reels = _distribute_balanced_reels(box_share, num_reels,
                                              min_per_reel, max_per_reel)
                for qty in box_reels:
                    plan.append({
                        "box": box_no, "reel": reel_no,
                        "lot": lot_no, "target": qty,
                        "box_total": None, "note": ""
                    })
                    reel_no += 1
                    lot_remaining -= qty

                # Add wait slots
                if wait_this > 0:
                    _add_wait_slots(box_no, wait_this)
                    newly_open_boxes.append({
                        "box": box_no,
                        "slots": wait_this,
                        "current_total": sum(r["target"] for r in plan
                                             if r["box"] == box_no
                                             and r.get("note") != "Wait next lot")
                    })

                _seal_box_rows(box_no)
                box_no += 1

    packed_this_lot = pack_limit - lot_remaining
    packed_this_lot = min(packed_this_lot, order_remaining)
    wait_count = sum(1 for r in plan if r["note"] == "Wait next lot")
    carry_was_placed = any(r.get("note") == "Carry" for r in plan)

    lot_excess = max(0, lot_qty - pack_limit)
    remainder_total = lot_remaining + lot_excess

    # ══════════════════════════════════════════════════════════════
    # [DEFER LAST REEL — LOT EXCESS PATH]
    # ถ้า defer_last_reel=True และ remainder_total < min_per_reel
    # (เกิดจาก lot_excess ไม่ใช่ lot_remaining)
    # → ดึง reel สุดท้ายออก + ลอง redistribute ลง open box อื่น
    # ══════════════════════════════════════════════════════════════
    if (defer_last_reel
            and min_per_reel > 0
            and 0 < remainder_total < min_per_reel):
        # หา reel สุดท้ายที่ pack ได้จริง
        last_packable_idx = -1
        for _i in range(len(plan) - 1, -1, -1):
            _r = plan[_i]
            if (_r.get("note") not in ("Wait next lot", "Carry")
                    and _r["box"] != 0
                    and _r["target"] > 0):
                last_packable_idx = _i
                break

        if last_packable_idx >= 0:
            _pulled = plan[last_packable_idx]
            pulled_qty = _pulled["target"]
            pulled_box = _pulled["box"]

            # แปลง reel เป็น "Wait next lot"
            _pulled["target"] = 0
            _pulled["note"]   = "Wait next lot"
            _pulled["lot"]    = ""
            _pulled["reel"]   = 0
            wait_count += 1

            # อัปเดต box_total
            new_bt = sum(
                r["target"] for r in plan
                if r["box"] == pulled_box
                and r.get("note") != "Wait next lot"
            )
            for r in plan:
                if r["box"] == pulled_box:
                    r["box_total"] = new_bt

            # ยอดรวมที่ต้อง redistribute = pulled + remainder_total
            redist_qty = pulled_qty + remainder_total
            packed_this_lot -= pulled_qty
            lot_excess = 0
            remainder_total = redist_qty  # อัปเดตชั่วคราว

            _log.debug(f"[DEFER LAST REEL excess] Box {pulled_box}: pulled {pulled_qty:,} pcs. "
                  f"redist_qty={redist_qty:,}")

            # ลอง redistribute redist_qty ลง open box ที่มี wait slot
            # ตรวจ pending_open (input open boxes) ก่อน แล้วค่อย newly_open_boxes
            _candidate_boxes = []
            for _ob_src in (pending_open or []) + (newly_open_boxes or []):
                _box_id = _ob_src["box"]
                if _box_id == pulled_box:
                    continue
                # นับ wait slots จาก plan จริง (หลังจาก Phase 1 fill)
                _real_wait = sum(
                    1 for r in plan
                    if r["box"] == _box_id and r.get("note") == "Wait next lot"
                )
                _real_total = sum(
                    r["target"] for r in plan
                    if r["box"] == _box_id and r.get("note") != "Wait next lot"
                ) + _ob_src.get("current_total", 0) - sum(
                    r["target"] for r in plan
                    if r["box"] == _box_id and r.get("note") not in ("Wait next lot", "Carry")
                    # ระวัง double count: ใช้แค่ current_total จาก input ob
                )
                # ใช้ current_total จาก ob (ซึ่งรวม history แล้ว) + สิ่งที่ plan เพิ่งวางลงไป
                _plan_added = sum(
                    r["target"] for r in plan
                    if r["box"] == _box_id
                    and r.get("note") not in ("Wait next lot", "Carry")
                    and r["target"] > 0
                )
                _hist_total = _ob_src.get("current_total", 0)
                _box_now = _hist_total + _plan_added
                _deficit  = max_per_box - _box_now
                if _real_wait > 0 and _deficit >= min_per_reel:
                    _candidate_boxes.append({
                        "box": _box_id,
                        "slots": _real_wait,
                        "current_total": _box_now,
                        "deficit": _deficit,
                    })

            _placed_in_open = 0
            for _ob_r in sorted(_candidate_boxes, key=lambda x: x["box"]):
                _ob_slots   = _ob_r["slots"]
                _ob_deficit = _ob_r["deficit"]
                _can_put = min(redist_qty, _ob_deficit,
                               _ob_slots * max_per_reel)
                if _can_put < min_per_reel:
                    continue
                _rem_after = redist_qty - _can_put
                if 0 < _rem_after < min_per_reel:
                    if (redist_qty <= _ob_deficit
                            and redist_qty >= min_per_reel
                            and redist_qty <= _ob_slots * max_per_reel):
                        _can_put = redist_qty
                        _rem_after = 0
                    else:
                        continue
                _n_put = min(_ob_slots, max(1, -(-_can_put // max_per_reel)))
                while _n_put > 1 and (_can_put // _n_put) < min_per_reel:
                    _n_put -= 1
                _put_reels = _distribute_balanced_reels(
                    _can_put, _n_put, min_per_reel, max_per_reel)
                for _pq in _put_reels:
                    plan.append({
                        "box": _ob_r["box"], "reel": reel_no,
                        "lot": lot_no, "target": _pq,
                        "box_total": None, "note": ""
                    })
                    reel_no += 1
                new_ob_bt = _ob_r["current_total"] + _can_put
                for r in plan:
                    if r["box"] == _ob_r["box"]:
                        r["box_total"] = new_ob_bt
                _placed_in_open = _can_put
                redist_qty -= _can_put
                packed_this_lot += _can_put
                _log.debug(f"[DEFER LAST REEL excess] Redistributed {_can_put:,} pcs "
                      f"into Box {_ob_r['box']}. redist_qty left={redist_qty:,}")
                break

            # อัปเดต lot_excess / remainder_total ใหม่
            lot_excess = redist_qty
            remainder_total = lot_remaining + lot_excess
            wait_count = sum(1 for r in plan if r["note"] == "Wait next lot")

            # ── Fix 1: เพิ่ม pulled_box เข้า newly_open_boxes ──
            # เพื่อให้ main.py สร้าง open_boxes_list ถูกต้องใน next lot
            _pulled_box_waits = sum(
                1 for r in plan
                if r["box"] == pulled_box and r.get("note") == "Wait next lot"
            )
            # current_total ของ pulled_box = ยอดจริงใน plan หลัง defer
            # (ไม่ใช่จาก pending_open ที่ถูก mutate แล้ว)
            _pulled_box_plan_total = sum(
                r["target"] for r in plan
                if r["box"] == pulled_box
                and r.get("note") not in ("Wait next lot", "Carry")
                and r["target"] > 0
            )
            # บวก history ที่มาก่อนหน้า lot นี้ (ก่อน Phase 1 เติม)
            # ใช้ค่าจาก original open_boxes input (open_boxes parameter)
            _hist_pulled_original = next(
                (ob.get("current_total", 0)
                 for ob in (open_boxes or [])
                 if ob["box"] == pulled_box),
                0
            )
            _pulled_box_total = _hist_pulled_original + _pulled_box_plan_total
            if _pulled_box_waits > 0:
                _existing_nob = next(
                    (ob for ob in newly_open_boxes if ob["box"] == pulled_box), None)
                if _existing_nob:
                    _existing_nob["slots"]         = _pulled_box_waits
                    _existing_nob["current_total"] = _pulled_box_total
                else:
                    newly_open_boxes.append({
                        "box":           pulled_box,
                        "slots":         _pulled_box_waits,
                        "current_total": _pulled_box_total,
                    })

            # ── Fix 2: แก้ packed_this_lot ให้ตรง ──
            # คำนวณใหม่จาก plan จริง (ไม่รวม box=0)
            packed_this_lot = sum(
                r["target"] for r in plan
                if r.get("box", 0) != 0
                and r.get("note") not in ("Wait next lot", "Carry")
                and r["target"] > 0
            )
            packed_this_lot = min(packed_this_lot, order_remaining)

            # ── Fix 3: ตั้ง lot_remainder = redist_qty ──
            # เพื่อให้ main.py คำนวณ algo_carry = redist_qty - reject
            # และ carry_remainder ถูกต้องใน new_state
            lot_remaining = redist_qty
            lot_excess = 0                   # excess ถูกดูดเข้า lot_remaining แล้ว
            remainder_total = lot_remaining  # = redist_qty
    remainder_reels = []
    if remainder_total > 0:
        # [FIX-BUG-D] ถ้าเป็น final lot ของ order → label "Remainder Reel"
        # แทน "Remainder Reel (Next Plan)" เพราะไม่มี next plan อีกแล้ว
        _rem_note = ("Remainder Reel" if _is_final_lot
                     else "Remainder Reel (Next Plan)")
        if remainder_total >= min_per_reel:
            num_rem = max(1, -(-remainder_total // max_per_reel))
            while num_rem > 1 and (remainder_total // num_rem) < min_per_reel:
                num_rem -= 1
            rem_reels = _distribute_balanced_reels(remainder_total, num_rem,
                                          min_per_reel, max_per_reel)
            for rq in rem_reels:
                remainder_reels.append({
                    "box": 0, "reel": reel_no,
                    "lot": lot_no, "target": rq,
                    "box_total": None,
                    "note": _rem_note
                })
                reel_no += 1
        else:
            # [Option A FIX]
            # remainder < min_per_reel → ห้ามสร้าง Remainder Reel ที่ต่ำกว่า min
            # (เคยเป็นจุดบัคที่สร้าง Reel 1,090 pcs ทั้งที่ min=1500)
            # แทนที่ด้วยการปล่อยเป็น carry ผ่าน plan_state (lot_remainder)
            # lot ถัดไปจะรับต่อและรวมกับ fresh lot ตามปกติ
            _log.debug(f"[SKIP REMAINDER REEL] remainder_total={remainder_total:,} "
                       f"< min={min_per_reel:,} → carry forward via plan_state")

    return plan, {
        "next_box":        box_no,
        "next_reel":       reel_no,
        "open_box_slots":  wait_count,
        "open_boxes":      newly_open_boxes,
        "packed_this_lot": packed_this_lot,
        "lot_remainder":   lot_remaining,
        "lot_excess":      lot_excess,
        "remainder_total": remainder_total,
        "wait_slots":      wait_count,
        "carry_placed":    carry_was_placed,
        "carry_remainder_out": carry_remainder,
        "remainder_reels": remainder_reels,
    }

def _optimize_open_boxes_allocation(pending_open, lot_remaining, min_per_reel, max_per_reel, max_per_box):
    """
    จัดสรรโควต้าให้กล่องที่เปิดอยู่ โดยเน้นสร้าง Reel ให้ได้ max_per_reel มากที่สุด
    และรับประกันว่า Wait Slot จะไม่ผิดเงื่อนไข (ไม่มี Scrap)

    กฎสำคัญ:
    - ถ้าจัดสรรให้ box แล้ว deficit ที่เหลือ < min_per_reel (wait slot ไม่สามารถรับได้)
      → ต้องเติมเต็ม (deficit ทั้งหมด) หรือข้ามเลย (0) ไม่มีทางกลาง
    - allocation แบบ partial ได้เฉพาะเมื่อ (deficit - allocation) ∈ [n*min, n*max]
      สำหรับ n ≥ 1 (wait slot ยังรับได้)
    """
    allocations = {ob["box"]: 0 for ob in pending_open}
    
    # 1. สร้างขอบเขตที่ปลอดภัย (Domain)
    boxes = []
    for ob in pending_open:
        deficit = max_per_box - ob["current_total"]
        # max_p คือยอดสูงสุดที่วางได้แบบ partial โดย wait slot ยังรับได้
        # ต้องมี deficit - max_p >= min_per_reel → max_p <= deficit - min_per_reel
        max_p = deficit - min_per_reel
        can_p = max_p >= min_per_reel  # partial ได้ถ้า max_p >= min (มีช่องว่างพอ)

        # ── กฎเพิ่มเติม: ตรวจว่า allocation แบบ partial จริงๆ มี range ที่ valid ──
        # หา n ที่เหมาะสมสำหรับ wait slots หลัง partial fill
        # wait slots ที่เหลือ = ob["slots"] - reels_placed
        # กฎสำคัญ: ไม่นับ POST-FILL FIX-A (auto-add wait slot) เพราะ:
        #   partial fill ที่ต้องพึ่ง FIX-A = box มี lots mixed + wait slot ที่ถูกสร้างใหม่
        #   → ไม่เสถียร, ผู้ใช้ไม่ต้องการ → ต้อง full-fill หรือ 0 เท่านั้น
        # ต้องมี n*min_per_reel <= (deficit - alloc) <= n*max_per_reel
        # โดย n ≤ slots_left (slots ที่มีอยู่จริง ไม่รวม FIX-A)
        if can_p and min_per_reel > 0:
            slots_available = ob.get("slots", 1)
            has_valid_partial = False
            # O(slots) instead of O(deficit/min_reel): for each possible slots_left,
            # compute the valid alloc_try range analytically and test for a multiple of
            # min_per_reel in that range — no inner scan needed.
            for slots_left in range(1, slots_available):
                slots_used = slots_available - slots_left
                lo = max(
                    (slots_used - 1) * max_per_reel + 1,
                    slots_used * min_per_reel,
                    deficit - slots_left * max_per_reel,
                )
                hi = min(slots_used * max_per_reel, max_p)
                if lo > hi:
                    continue
                if math.ceil(lo / min_per_reel) * min_per_reel <= hi:
                    has_valid_partial = True
                    break
            can_p = has_valid_partial

        boxes.append({
            "box": ob["box"], 
            "deficit": deficit,
            "min_p": min_per_reel if can_p else 0,
            "max_p": max_p if can_p else 0,
            "can_p": can_p, 
            "slots": ob.get("slots", 1),
            "fulfilled": False
        })
        
    # เรียงจาก Deficit น้อยไปมาก
    boxes.sort(key=lambda x: x["deficit"])
    remaining = lot_remaining

    # ─── REMAINDER SAFETY: ปรับ max_p ทุก box ให้หลังจ่ายแล้ว lot_remaining เหลือ ≥ min หรือ = 0 ───
    # Simulate Step 2 to find which must-fill boxes actually get filled
    # (some will be skipped by other_min_needed check)
    sim_remaining = remaining
    sim_filled = []
    sim_boxes_sorted = sorted([b for b in boxes], key=lambda x: x["deficit"])
    for b in sim_boxes_sorted:
        if b["can_p"]:
            continue  # partial boxes handled later
        if sim_remaining >= b["deficit"]:
            # Check if filling this box leaves enough for others
            after_r = sim_remaining - b["deficit"]
            other_partial_min = sum(ob["min_p"] for ob in sim_boxes_sorted 
                                   if ob["can_p"] and ob["box"] != b["box"])
            if after_r >= other_partial_min:
                sim_filled.append(b["box"])
                sim_remaining -= b["deficit"]
    
    must_fill_total = sum(b["deficit"] for b in boxes if b["box"] in sim_filled)
    available_for_partial = remaining - must_fill_total
    
    if min_per_reel > 0 and available_for_partial > 0:
        for b in boxes:
            if not b["can_p"]:
                continue
            # max alloc ที่ปลอดภัย: available - min_per_reel (เหลือ remainder ≥ min)
            # ยกเว้น available ≤ max_p (ใช้หมดได้ → remainder=0)
            safe_max = available_for_partial - min_per_reel
            if safe_max < 0:
                safe_max = 0
            
            # ── Preference: ใช้ 1 reel + wait slots มากขึ้น ──
            # เพื่อเก็บ remainder ไว้ให้ lot ถัดไป (ไม่เปิด box ใหม่)
            # safe_max ถูก cap ให้ max_per_reel เพื่อใช้แค่ 1 reel
            if b["slots"] >= 2 and safe_max > max_per_reel:
                safe_max = max_per_reel

            if b["max_p"] > safe_max and available_for_partial != b["max_p"]:
                old_max = b["max_p"]
                b["max_p"] = max(b["min_p"], safe_max)
                if b["max_p"] < b["min_p"]:
                    b["can_p"] = False
                    b["max_p"] = 0
                    b["min_p"] = 0

    # 2. จัดการกรณี Over-supply (ของเยอะจนต้องมีกล่องถูกซีลปิด)
    while remaining > 0 and boxes:
        total_max_partial = sum(b["max_p"] for b in boxes if b["can_p"] and not b["fulfilled"])
        if remaining <= total_max_partial:
            break # ของเหลืออยู่ในช่วงที่เกลี่ยแบบ Partial ได้ปลอดภัย
        
        # บังคับเติมเต็มกล่องที่ต้องการของน้อยที่สุด
        for i, b in enumerate(boxes):
            if not b["fulfilled"]:
                target = boxes.pop(i)
                if remaining >= target["deficit"]:
                    # ตรวจว่าหลังเติมเต็มกล่องนี้แล้ว กล่องที่เหลือยังรับได้ขั้นต่ำไหม
                    after_remaining = remaining - target["deficit"]
                    other_boxes = [ob for ob in boxes if not ob["fulfilled"]]
                    other_min_needed = sum(
                        ob["min_p"] for ob in other_boxes if ob["can_p"]
                    )
                    if after_remaining >= other_min_needed:
                        # ปลอดภัย: เติมเต็มกล่องนี้ได้
                        allocations[target["box"]] = target["deficit"]
                        remaining -= target["deficit"]
                    else:
                        # ไม่ปลอดภัย: เติมเต็มแล้วกล่องอื่นรับไม่พอ → ข้ามกล่องนี้
                        # (allocations[target["box"]] ยังเป็น 0)
                        _log.debug(f"[OPTIMIZER] Skip full-fill Box{target['box']} "
                              f"(deficit={target['deficit']:,}): after-fill remaining "
                              f"{after_remaining:,} < other_min_needed {other_min_needed:,}")
                elif target["can_p"]:
                    allocations[target["box"]] = target["max_p"]
                    remaining -= target["max_p"]
                target["fulfilled"] = True
                break

    # 3. จัดสรรแบบ Production-Elegant (พยายามปั้นยอด max_per_reel)
    partial_boxes = [b for b in boxes if not b["fulfilled"] and b["can_p"]]
    if partial_boxes and remaining > 0:
        for b in partial_boxes:
            if remaining <= 0: break
            if b["fulfilled"]: continue
            
            # ลองเทยอดให้กล่องนี้เท่ากับ max_per_reel (เช่น 3000)
            target_chunk = max_per_reel
            if b["min_p"] <= target_chunk <= b["max_p"]:
                # เช็คว่าเศษที่เหลือ โยนให้กล่องอื่นรอดไหม?
                other_min = sum(ob["min_p"] for ob in partial_boxes if ob != b and not ob["fulfilled"])
                other_max = sum(ob["max_p"] for ob in partial_boxes if ob != b and not ob["fulfilled"])
                leftover = remaining - target_chunk
                
                # ── Remainder safety: leftover ต้อง ≥ min หรือ = 0 ──
                if leftover > 0 and leftover < min_per_reel and other_min == 0:
                    continue  # leftover เป็น scrap → ข้าม chunk นี้
                
                if other_min <= leftover <= other_max:
                    # สมบูรณ์แบบ! กล่องนี้รับม้วนเต็มไปเลย
                    allocations[b["box"]] = target_chunk
                    remaining -= target_chunk
                    b["fulfilled"] = True

        # 4. เกลี่ยยอดที่เหลือ (ถ้ามี) ให้กล่องที่ยังไม่ได้โควต้า (Water-filling)
        unfulfilled = [b for b in partial_boxes if not b["fulfilled"]]
        if unfulfilled and remaining > 0:
            # จ่ายขั้นต่ำเป็นฐานก่อน
            for b in unfulfilled:
                if remaining >= b["min_p"]:
                    allocations[b["box"]] = b["min_p"]
                    remaining -= b["min_p"]
            
            # ทบยอดที่เหลือจนกว่าของจะหมด
            for b in unfulfilled:
                if remaining <= 0: break
                can_add = min(remaining, b["max_p"] - b["min_p"])
                
                # ── Remainder safety: หลังเติมแล้ว remaining ที่เหลือต้อง ≥ min หรือ = 0 ──
                # ตรวจว่ายังมี box อื่นที่รับได้ไหม ถ้าไม่มี remaining จะเป็น remainder reel
                other_unfulfilled_after = [
                    ob for ob in unfulfilled 
                    if ob != b and not ob["fulfilled"]
                    and allocations.get(ob["box"], 0) < ob["max_p"]
                ]
                if not other_unfulfilled_after:
                    # ไม่มี box อื่นรับแล้ว → remaining จะเป็น remainder reel
                    # ต้อง ≥ min_per_reel หรือ = 0
                    leftover = remaining - can_add
                    if 0 < leftover < min_per_reel:
                        # ลด can_add เพื่อให้ leftover ≥ min_per_reel
                        safe_add = remaining - min_per_reel
                        if safe_add >= 0:
                            can_add = safe_add
                        else:
                            # remaining ทั้งหมด < min → ใส่ทั้งหมด (remainder=0)
                            can_add = remaining
                
                allocations[b["box"]] += can_add
                remaining -= can_add

    return allocations
# ══════════════════════════════════════════════════════════════
#  calculation_engine.py  →  _distribute_balanced_reels (แทนที่ทั้ง function)
# ══════════════════════════════════════════════════════════════
 
def _distribute_balanced_reels(total_qty, num_reels, min_per_reel, max_per_reel):
    """
    Balanced Distribution (Custom for v2 Lot-by-Lot).
    Distributes total evenly, prioritizing modulo 50 and last reel >= min_per_reel.
    [FIX-B3] เปลี่ยน assert เป็น auto-fix:ถ้า sum(result) != total_qty หลัง rounding ให้ adjust result[-1] แทน crash
    """
    max_possible = num_reels * max_per_reel
    if total_qty > max_possible:
        _log.warning(f"_distribute_balanced_reels: total_qty {total_qty} > max_possible {max_possible}, clamping")
        total_qty = max_possible
 
    if num_reels <= 0:
        return []
    if num_reels == 1:
        return [total_qty]

    # [FIX-NEG-REEL v2] Early guard: ถ้า total_qty < num_reels * min_per_reel
    # การแจกออกเป็น num_reels reels ที่ทุก reel >= min_per_reel เป็นไปไม่ได้
    # → ส่งกลับ list เดียวเพื่อให้ caller จัดการ remainder เอง
    # (กันบั๊ก [1500, -535] ที่ sum ดูถูกต้องแต่ค่าติดลบ)
    if min_per_reel > 0 and total_qty < num_reels * min_per_reel:
        _log.error(
            f"_distribute_balanced_reels: infeasible split — "
            f"total_qty={total_qty} < num_reels({num_reels}) × "
            f"min_per_reel({min_per_reel}) = {num_reels * min_per_reel}. "
            f"Falling back to single reel of {total_qty}."
        )
        return [total_qty]

    avg_qty = total_qty // num_reels
    if avg_qty >= 100:
        avg_qty = (avg_qty // 50) * 50
 
    # Strictly bind avg_qty
    if min_per_reel > 0:
        avg_qty = max(min_per_reel, avg_qty)
    avg_qty = min(max_per_reel, avg_qty)
 
    result = [avg_qty] * (num_reels - 1)
    last_qty = total_qty - sum(result)
    result.append(last_qty)
 
    # ── Last-to-First Replenishment (if last reel < min) ──
    if min_per_reel > 0:
        idx = len(result) - 2
        while result[-1] < min_per_reel and idx >= 0:
            diff = min_per_reel - result[-1]
            take = min(result[idx] - min_per_reel, diff)
            if take > 0:
                if take >= 50:
                    take = (take // 50) * 50
                take = min(take, result[idx] - min_per_reel)
                result[idx] -= take
                result[-1] += take
            idx -= 1
 
    # ── Last-to-First Excess Transfer (if last reel > max) ──
    idx = len(result) - 2
    while result[-1] > max_per_reel and idx >= 0:
        diff = result[-1] - max_per_reel
        give = min(max_per_reel - result[idx], diff)
        if give > 0:
            if give >= 50:
                give = (give // 50) * 50
            give = min(give, max_per_reel - result[idx])
            result[idx] += give
            result[-1] -= give
        idx -= 1
 
    # [FIX-B3] แทน assert ด้วย auto-fix: ปรับ result[-1] ให้ผลรวมถูกต้องเสมอ
    current_sum = sum(result)
    if current_sum != total_qty:
        diff = total_qty - current_sum
        result[-1] += diff
        
        # ⚠️ NEW: Enhanced fallback redistribution (more aggressive search)
        if min_per_reel > 0:
            # Final validation loop: if last reel still < min after fix, pull from ALL
            max_retries = 5
            retry_count = 0
            while (result[-1] < min_per_reel and result[-1] > 0 
                   and retry_count < max_retries):
                retry_count += 1
                # Try to pull from ANY reel that can spare, prioritize rightmost
                spare_found = False
                for i in range(len(result) - 2, -1, -1):
                    spare = result[i] - min_per_reel
                    if spare > 0:
                        need = min_per_reel - result[-1]
                        give = min(spare, need)
                        result[i] -= give
                        result[-1] += give
                        spare_found = True
                        if result[-1] >= min_per_reel:
                            break
                if not spare_found:
                    break  # No reel can spare
        
        # Check if overflow correction is needed (last reel > max)
        if max_per_reel > 0 and result[-1] > max_per_reel:
            overflow = result[-1] - max_per_reel
            result[-1] = max_per_reel
            # Distribute overflow to neighbors with space
            for i in range(len(result) - 2, -1, -1):
                space = max_per_reel - result[i]
                if space > 0:
                    give = min(space, overflow)
                    result[i] += give
                    overflow -= give
                if overflow <= 0:
                    break
        
        # Log warning if still invalid
        if sum(result) != total_qty or (min_per_reel > 0 and result[-1] < min_per_reel and result[-1] > 0):
            _log.warning(f"_distribute_balanced_reels: sum={sum(result)} vs target={total_qty}, "
                  f"result={result}, last reel={result[-1]} (min={min_per_reel})")
 
    return result


def _distribute_reels(total_qty, num_reels, min_per_reel, max_per_reel):
    # Safety: total_qty ต้องไม่เกิน num_reels * max_per_reel
    max_possible = num_reels * max_per_reel
    if total_qty > max_possible:
        _log.warning(f"total_qty {total_qty} > max_possible {max_possible}, clamping")
        total_qty = max_possible
    """
    Distribute total_qty across num_reels.
    Strategy: front-load at max_per_reel when feasible (matches physical
    process), otherwise distribute evenly.
    Returns list of quantities.
    """
    if num_reels <= 0:
        return []
    if num_reels == 1:
        return [min(total_qty, max_per_reel)]

    # ── Try front-loading at max_per_reel ──
    # Each reel gets max_per_reel, last reel gets remainder.
    # Only valid if last reel >= min_per_reel.
    last_if_front = total_qty - max_per_reel * (num_reels - 1)
    if last_if_front >= (min_per_reel or 1) and last_if_front <= max_per_reel:
        return [max_per_reel] * (num_reels - 1) + [last_if_front]

    # ── Fallback: even distribution (front rounded to 50, last gets rest) ──
    front_qty = total_qty // num_reels
    if front_qty >= 100:
        front_qty = (front_qty // 50) * 50
    front_qty = min(front_qty, max_per_reel)
    if min_per_reel > 0:
        front_qty = max(front_qty, min_per_reel)

    front_total = front_qty * (num_reels - 1)
    last_qty = total_qty - front_total

    # B2 fix: if last reel overflows max_per_reel, step up front_qty one unit
    # at a time until last_qty fits. This guarantees sum(result) == total_qty
    # with no second clamp that would silently drop items.
    if last_qty > max_per_reel:
        found = False
        for adjusted_front in range(front_qty + 1, max_per_reel + 1):
            front_total = adjusted_front * (num_reels - 1)
            last_qty = total_qty - front_total
            if last_qty <= max_per_reel:
                front_qty = adjusted_front
                found = True
                break
        if not found:
            # total_qty > num_reels * max_per_reel — caller passed bad args.
            # Best-effort: fill all reels at max, last gets whatever remains.
            front_qty = max_per_reel
            front_total = front_qty * (num_reels - 1)
            last_qty = total_qty - front_total
            _log.debug(f"[_distribute_reels] Warning: total_qty={total_qty} exceeds "
                  f"num_reels={num_reels} * max_per_reel={max_per_reel}. "
                  f"last_qty={last_qty} will exceed max.")

    # Floor last reel to min_per_reel only (never clamp to max — that would drop items)
    if min_per_reel > 0 and last_qty < min_per_reel:
        last_qty = min_per_reel

    result = [front_qty] * (num_reels - 1) + [last_qty]
    return result