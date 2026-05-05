"""
CSV Export Helpers — AutoPack VLO-127S
========================================
Post-monitor report generators: leftover, reject, and final plan CSVs.
"""

import os, csv
from datetime import datetime
from collections import defaultdict


def _build_unique_export_path(folder, prefix, tag, ext):
    """Return a collision-safe export path while keeping filenames readable."""
    candidate = os.path.join(folder, f"{prefix}_{tag}{ext}")
    if not os.path.exists(candidate):
        return candidate

    seq = 1
    while True:
        candidate = os.path.join(folder, f"{prefix}_{tag}_{seq:03d}{ext}")
        if not os.path.exists(candidate):
            return candidate
        seq += 1


def _build_order_remain_folder(base_folder, tag):
    """Return the order-specific folder for Box 0 remainder exports."""
    root_folder = os.path.dirname(base_folder)
    folder = os.path.join(root_folder, "Remain", tag)
    os.makedirs(folder, exist_ok=True)
    return folder


def _export_box0_remainder_csv(base_folder, tag, invoice_no, ship_date, dest, remain_reels):
    """Export Box 0 remainder detail into a dedicated folder for the order."""
    if not remain_reels:
        return None

    folder = _build_order_remain_folder(base_folder, tag)
    fp = _build_unique_export_path(folder, "RemainBox0", tag, ".csv")

    remain_reels = sorted(remain_reels, key=lambda rd: (rd.get("lot", ""), rd.get("reel", 0)))
    total_actual = sum(rd.get("actual", 0) for rd in remain_reels)
    total_reject = sum(rd.get("reject", 0) for rd in remain_reels)
    lots = sorted({rd.get("lot", "") for rd in remain_reels if rd.get("lot", "")})

    with open(fp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["# Box 0 Remainder Detail"])
        w.writerow(["# Product", invoice_no])
        w.writerow(["# Destination", dest])
        w.writerow(["# Shipment Date", ship_date])
        w.writerow(["# Lots", ", ".join(lots)])
        w.writerow(["# Reel Count", len(remain_reels)])
        w.writerow(["# Total Actual", total_actual])
        w.writerow(["# Total Reject", total_reject])
        w.writerow(["# Generated", datetime.now().replace(microsecond=0).isoformat(" ")])
        w.writerow([])
        w.writerow(["Box", "Reel", "Lot", "Target", "Actual", "Reject", "Diff", "Note"])
        for rd in remain_reels:
            w.writerow([
                rd.get("box", 0), rd.get("reel", ""),
                rd.get("lot", ""), rd.get("target", 0),
                rd.get("actual", 0), rd.get("reject", 0),
                rd.get("diff", 0), rd.get("note", ""),
            ])

    print(f"[RemainBox0] Saved: {fp}")
    return fp


def export_leftover_csv(config, invoice_no, ship_date, dest,
                        carry_remainder, carry_lot, lot_history):
    """Export remaining material to CSV for hand-off to next order."""
    if carry_remainder <= 0:
        return
    try:
        folder = os.path.join(config.output_folder, "Planner")
        os.makedirs(folder, exist_ok=True)
        tag = f"{invoice_no}_{ship_date}_{dest}".replace("/", "-").replace(" ", "")
        fp = _build_unique_export_path(folder, "Leftover", tag, ".csv")
        with open(fp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["# Leftover Material for Next Order"])
            w.writerow(["# Product", invoice_no])
            w.writerow(["# Destination", dest])
            w.writerow(["# ShipmentDate", ship_date])
            w.writerow(["# Generated", datetime.now().replace(microsecond=0).isoformat(" ")])
            w.writerow([])
            w.writerow(["Lot", "Leftover (pcs.)"])
            w.writerow([carry_lot, carry_remainder])
            w.writerow([])
            w.writerow(["# Lot History"])
            w.writerow(["Lot", "Input", "Packed", "Reject", "Remainder"])
            for h in lot_history:
                w.writerow([h.get("lot", ""), h.get("input", 0), h.get("packed", 0),
                            h.get("reject", 0), h.get("remainder", 0)])
        print(f"[Leftover] Saved: {fp}")
    except Exception as e:
        print(f"[Leftover] Error: {e}")


def export_reject_csv(config, invoice_no, ship_date, dest, lot_history):
    """Export reject report CSV."""
    total_rej = sum(h.get("reject", 0) for h in lot_history)
    if total_rej <= 0:
        return None
    try:
        folder = os.path.join(config.output_folder, "Planner")
        os.makedirs(folder, exist_ok=True)
        tag = f"{invoice_no}_{ship_date}_{dest}".replace("/", "-").replace(" ", "")
        fp = _build_unique_export_path(folder, "Reject", tag, ".csv")
        with open(fp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["# Reject Report"])
            w.writerow(["# Product", invoice_no])
            w.writerow(["# Destination", dest])
            w.writerow(["# ShipmentDate", ship_date])
            w.writerow(["# Generated", datetime.now().replace(microsecond=0).isoformat(" ")])
            w.writerow([])
            w.writerow(["Lot", "Box", "Reel", "Target", "Actual", "Reject", "Note"])
            for h in lot_history:
                for rd in h.get("reels", []):
                    if rd.get("reject", 0) > 0:
                        w.writerow([
                            rd.get("lot", h["lot"]), rd.get("box", ""),
                            rd.get("reel", ""), rd.get("target", ""),
                            rd.get("actual", ""), rd.get("reject", 0),
                            rd.get("note", ""),
                        ])
            w.writerow([])
            w.writerow(["# Summary by Lot"])
            w.writerow(["Lot", "Input", "Packed", "Total Reject", "Scrap"])
            for h in lot_history:
                if h.get("reject", 0) > 0 or h.get("scrap", 0) > 0:
                    w.writerow([h.get("lot", ""), h.get("input", 0), h.get("packed", 0),
                                h.get("reject", 0), h.get("scrap", 0)])
            w.writerow([])
            w.writerow(["# Grand Total Reject", total_rej])
        print(f"[Reject] Saved: {fp}")
        return fp
    except Exception as e:
        print(f"[Reject] Error: {e}")
        return None


def export_final_plan_csv(config, invoice_no, ship_date, dest,
                          order_qty, lot_history):
    """Export consolidated final plan CSV, with Box 0 remainder split out."""
    try:
        folder = os.path.join(config.output_folder, "Planner")
        os.makedirs(folder, exist_ok=True)
        tag = f"{invoice_no}_{ship_date}_{dest}".replace("/", "-").replace(" ", "")
        fp = _build_unique_export_path(folder, "FinalPlan", tag, ".csv")

        all_reels = []
        remain_reels = []
        for h in lot_history:
            for rd in h.get("reels", []):
                if rd.get("note", "").startswith("Pulled"):
                    continue
                if rd.get("box", 0) == 0:
                    remain_reels.append(rd)
                    continue
                all_reels.append(rd)
        all_reels.sort(key=lambda rd: (rd.get("box", 0), rd.get("reel", 0)))

        _export_box0_remainder_csv(folder, tag, invoice_no, ship_date, dest, remain_reels)

        box_totals = defaultdict(int)
        box_reels_count = defaultdict(int)
        box_lots = defaultdict(set)
        for rd in all_reels:
            box_totals[rd["box"]] += rd.get("actual", 0)
            box_reels_count[rd["box"]] += 1
            box_lots[rd["box"]].add(rd.get("lot", "?"))

        total_packed = sum(h.get("packed", 0) for h in lot_history)
        total_reject = sum(h.get("reject", 0) for h in lot_history)
        total_scrap  = sum(h.get("scrap", 0) for h in lot_history)

        with open(fp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["# Final Packing Plan"])
            w.writerow(["# Product", invoice_no])
            w.writerow(["# Destination", dest])
            w.writerow(["# Shipment Date", ship_date])
            w.writerow(["# Order Qty", order_qty])
            w.writerow(["# Total Packed", total_packed])
            w.writerow(["# Total Reject", total_reject])
            w.writerow(["# Total Scrap", total_scrap])
            w.writerow(["# Total Lots", len(lot_history)])
            w.writerow(["# Total Boxes", len(box_totals)])
            w.writerow(["# Generated", datetime.now().replace(microsecond=0).isoformat(" ")])
            w.writerow([])
            w.writerow(["Box", "Reel", "Lot", "Target", "Actual",
                         "Reject", "Diff", "Box Total", "Note"])

            prev_box = None
            for rd in all_reels:
                box = rd.get("box", 0)
                if prev_box is not None and box != prev_box:
                    w.writerow([
                        f"Box {prev_box} Total", "",
                        ", ".join(sorted(box_lots[prev_box])),
                        "", box_totals[prev_box], "", "",
                        f"{box_reels_count[prev_box]} reels", "",
                    ])
                    w.writerow([])
                prev_box = box
                w.writerow([
                    f"Box {box}", f"Reel {rd.get('reel', '')}",
                    rd.get("lot", ""), rd.get("target", ""),
                    rd.get("actual", ""), rd.get("reject", 0),
                    rd.get("diff", 0), "", rd.get("note", ""),
                ])
            if prev_box is not None:
                w.writerow([
                    f"Box {prev_box} Total", "",
                    ", ".join(sorted(box_lots[prev_box])),
                    "", box_totals[prev_box], "", "",
                    f"{box_reels_count[prev_box]} reels", "",
                ])

            w.writerow([])
            w.writerow(["# Lot Summary"])
            w.writerow(["Lot", "Input", "Packed", "Reject", "Scrap",
                         "Remainder", "Deviation"])
            for h in lot_history:
                w.writerow([
                    h.get("lot", ""), h.get("input", 0), h.get("packed", 0),
                    h.get("reject", 0), h.get("scrap", 0),
                    h.get("remainder", 0), h.get("deviation", 0),
                ])

        print(f"[FinalPlan] Saved: {fp}")
        return fp
    except Exception as e:
        print(f"[FinalPlan] Error: {e}")
        return None


def auto_save_logpack(config, invoice_no, ship_date, dest, order_qty, lot_history):
    """Auto-save comprehensive packing log with per-box/reel detail.

    Writes a single text file per order with all boxes, reels, defects,
    rejects, and lot summary — no manual action required.
    """
    try:
        folder = os.path.join(config.output_folder, "LogPack")
        os.makedirs(folder, exist_ok=True)
        tag = f"{invoice_no}_{ship_date}_{dest}".replace("/", "-").replace(" ", "")
        fp = _build_unique_export_path(folder, "PackingDetail", tag, ".txt")

        all_reels = []
        for h in lot_history:
            for rd in h.get("reels", []):
                if rd.get("note", "").startswith("Pulled"):
                    continue
                # ✅ FIX: Exclude Box 0 (remainder) items from display output (deferred to next order)
                if rd.get("box", 0) == 0:
                    continue
                all_reels.append(rd)
        all_reels.sort(key=lambda rd: (rd.get("box", 0), rd.get("reel", 0)))

        # Group by box
        box_groups = defaultdict(list)
        for rd in all_reels:
            box_groups[rd.get("box", 0)].append(rd)

        total_packed = sum(h.get("packed", 0) for h in lot_history)
        total_reject = sum(h.get("reject", 0) for h in lot_history)
        total_scrap = sum(h.get("scrap", 0) for h in lot_history)

        with open(fp, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("  PACKING DETAIL LOG — AUTO GENERATED\n")
            f.write("=" * 80 + "\n")
            f.write(f"  Product      : {invoice_no}\n")
            f.write(f"  Destination  : {dest}\n")
            f.write(f"  Shipment Date: {ship_date}\n")
            f.write(f"  Order Qty    : {order_qty:,} pcs\n")
            f.write(f"  Total Packed : {total_packed:,} pcs\n")
            f.write(f"  Total Reject : {total_reject:,} pcs\n")
            f.write(f"  Total Scrap  : {total_scrap:,} pcs\n")
            f.write(f"  Total Lots   : {len(lot_history)}\n")
            f.write(f"  Total Boxes  : {len(box_groups)}\n")
            f.write(f"  Generated    : {datetime.now().replace(microsecond=0).isoformat(' ')}\n")
            f.write("=" * 80 + "\n\n")

            # Per-box detail
            for b in sorted(box_groups.keys()):
                reels_in_box = box_groups[b]
                box_actual = sum(rd.get("actual", 0) for rd in reels_in_box)
                box_reject = sum(rd.get("reject", 0) for rd in reels_in_box)
                box_lots = sorted(set(rd.get("lot", "?") for rd in reels_in_box))
                reel_count = len(reels_in_box)

                f.write(f"┌{'─' * 78}┐\n")
                f.write(f"│  📦 Box {b:<4}  "
                        f"Reels: {reel_count}  │  "
                        f"Packed: {box_actual:>8,} pcs  │  "
                        f"Reject: {box_reject:>6,}  │  "
                        f"Lots: {', '.join(box_lots):<12}│\n")
                f.write(f"├{'─' * 78}┤\n")
                f.write(f"│ {'Reel':>6}  {'Lot':<12} {'Target':>8}  "
                        f"{'Actual':>8}  {'Reject':>8}  {'Diff':>8}  {'Note':<14}│\n")
                f.write(f"├{'─' * 78}┤\n")
                for rd in reels_in_box:
                    actual = rd.get("actual", 0)
                    target = rd.get("target", 0)
                    reject = rd.get("reject", 0)
                    diff = rd.get("diff", actual - target)
                    diff_s = f"+{diff}" if diff > 0 else str(diff)
                    note = rd.get("note", "")
                    if len(note) > 13:
                        note = note[:13]
                    f.write(f"│ R{rd.get('reel', '?'):>4}  "
                            f"{rd.get('lot', '—'):<12} {target:>8,}  "
                            f"{actual:>8,}  {reject:>8,}  "
                            f"{diff_s:>8}  {note:<14}│\n")
                f.write(f"├{'─' * 78}┤\n")
                f.write(f"│ {'TOTAL':>19} {sum(rd.get('target', 0) for rd in reels_in_box):>8,}  "
                        f"{box_actual:>8,}  {box_reject:>8,}  "
                        f"{'':>8}  {'':>14}│\n")
                f.write(f"└{'─' * 78}┘\n\n")

            # Lot summary
            f.write("=" * 80 + "\n")
            f.write("  LOT SUMMARY\n")
            f.write("=" * 80 + "\n")
            f.write(f"  {'Lot':<14} {'Input':>8}  {'Packed':>8}  "
                    f"{'Reject':>8}  {'Scrap':>8}  {'Carry':>8}\n")
            f.write(f"  {'-' * 68}\n")
            for h in lot_history:
                f.write(f"  {h.get('lot', '?'):<14} {h.get('input', 0):>8,}  "
                        f"{h.get('packed', 0):>8,}  {h.get('reject', 0):>8,}  "
                        f"{h.get('scrap', 0):>8,}  {h.get('remainder', 0):>8,}\n")
            f.write(f"  {'-' * 68}\n")
            f.write(f"  {'TOTAL':<14} "
                    f"{sum(h.get('input', 0) for h in lot_history):>8,}  "
                    f"{total_packed:>8,}  {total_reject:>8,}  "
                    f"{total_scrap:>8,}  "
                    f"{sum(h.get('remainder', 0) for h in lot_history):>8,}\n")
            f.write("=" * 80 + "\n")

        print(f"[LogPack] Saved: {fp}")
        return fp
    except Exception as e:
        print(f"[LogPack] Error: {e}")
        return None
