"""
Plan History Store — AutoPack VLO-127S
========================================
Saves and retrieves past order plans in JSON format.
"""

import os, json, csv
from datetime import datetime


class PlanHistoryStore:
    """Stores order history as JSON files in a History/ folder."""

    def __init__(self, folder):
        self._folder = os.path.join(folder, "History")
        os.makedirs(self._folder, exist_ok=True)

    def _build_unique_order_path(self, tag):
        d = datetime.now()
        ts = (
            f"{d.year:04d}{d.month:02d}{d.day:02d}_"
            f"{d.hour:02d}{d.minute:02d}{d.second:02d}_{d.microsecond:06d}"
        )
        fp = os.path.join(self._folder, f"{tag}_{ts}.json")
        if not os.path.exists(fp):
            return fp

        # Extremely rare fallback in case two saves happen in the same microsecond.
        i = 1
        while True:
            alt = os.path.join(self._folder, f"{tag}_{ts}_{i:02d}.json")
            if not os.path.exists(alt):
                return alt
            i += 1

    def save_order(self, order):
        tag = order.get("invoice", "ORDER").replace("/", "-").replace(" ", "_")
        fp = self._build_unique_order_path(tag)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
        return fp

    def save_completed_order(self, invoice_no, dest, ship_date, order_qty,
                             lot_history, carry_remainder=0, carry_lot=""):
        """Save completed order with full actual packing data."""
        all_reels = []
        for h in lot_history:
            for rd in h.get("reels", []):
                if rd.get("note", "").startswith("Pulled"):
                    continue
                all_reels.append(rd)
        all_reels.sort(key=lambda rd: (rd.get("box", 0), rd.get("reel", 0)))

        total_packed = sum(h.get("packed", 0) for h in lot_history)
        total_reject = sum(h.get("reject", 0) for h in lot_history)
        total_scrap = sum(h.get("scrap", 0) for h in lot_history)

        order = {
            "invoice": invoice_no,
            "dest": dest,
            "ship_date": ship_date,
            "order_qty": order_qty,
            "total_packed": total_packed,
            "total_reject": total_reject,
            "total_scrap": total_scrap,
            "carry_remainder": carry_remainder,
            "carry_lot": carry_lot,
            "total_lots": len(lot_history),
            "total_boxes": len(set(rd.get("box", 0) for rd in all_reels)),
            "completed": True,
            "completed_at": datetime.now().isoformat(),
            "plan": [
                {
                    "box": rd.get("box", 0),
                    "reel": rd.get("reel", 0),
                    "lot": rd.get("lot", ""),
                    "target": rd.get("target", 0),
                    "actual": rd.get("actual", 0),
                    "reject": rd.get("reject", 0),
                    "diff": rd.get("diff", 0),
                    "note": rd.get("note", ""),
                }
                for rd in all_reels
            ],
            "lot_summary": [
                {
                    "lot": h.get("lot", ""),
                    "input": h.get("input", 0),
                    "packed": h.get("packed", 0),
                    "reject": h.get("reject", 0),
                    "scrap": h.get("scrap", 0),
                    "remainder": h.get("remainder", 0),
                }
                for h in lot_history
            ],
        }
        return self.save_order(order)

    def list_orders(self):
        result = []
        for fn in os.listdir(self._folder):
            if not fn.endswith(".json"):
                continue
            fp = os.path.join(self._folder, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    result.append((fn, json.load(f)))
            except Exception:
                pass

        def _sort_key(item):
            fn, data = item
            completed_at = data.get("completed_at", "")
            if completed_at:
                try:
                    return datetime.fromisoformat(completed_at)
                except ValueError:
                    pass
            # Fallback: parse timestamp digits embedded in the filename.
            # Filename format: TAG_YYYYMMDD_HHMMSS[_microseconds][_seq].json
            stem = os.path.splitext(fn)[0]
            parts = stem.split("_")
            for i, p in enumerate(parts):
                if len(p) == 8 and p.isdigit() and i + 1 < len(parts):
                    nxt = parts[i + 1]
                    if len(nxt) >= 6 and nxt[:6].isdigit():
                        try:
                            return datetime.strptime(p + nxt[:6], "%Y%m%d%H%M%S")
                        except ValueError:
                            pass
            return datetime.min

        result.sort(key=_sort_key, reverse=True)
        return result

    def export_csv(self, order, out_path):
        plan = order.get("plan", [])
        if not plan:
            return
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["# Invoice", order.get("invoice", "")])
            w.writerow(["# Destination", order.get("dest", "")])
            w.writerow(["# Shipment Date", order.get("ship_date", "")])
            w.writerow(["# Generated", datetime.now().replace(microsecond=0).isoformat(" ")])
            w.writerow([])
            is_completed = order.get("completed", False)
            if is_completed:
                w.writerow(["Box", "Reel", "Lot", "Target", "Actual", "Reject", "Diff", "Note"])
            else:
                w.writerow(["Box", "Reel", "Lot", "Target (pcs)", "Note"])
            for row in plan:
                if is_completed:
                    w.writerow([
                        row.get("box"), row.get("reel"),
                        row.get("lot"), row.get("target"),
                        row.get("actual", ""), row.get("reject", ""),
                        row.get("diff", ""), row.get("note", ""),
                    ])
                else:
                    w.writerow([
                        row.get("box"), row.get("reel"),
                        row.get("lot"), row.get("target"),
                        row.get("note", ""),
                    ])
