"""
Plan Editor — AutoPack VLO-127S
=================================
Pure-Python validation and mutation logic for editing a packing plan
BEFORE it goes to the Monitor (i.e. while still on the Planner page).

Key principles:
  • Pending reels only — done/current reels are never touched here
  • Two-phase: validate first (no side effects) → apply (atomic)
  • Lot integrity preserved (no cross-lot moves)
  • Box capacity invariants preserved
  • Caller does not see internal state on validation failure
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict


# ════════════════════════════════════════════════════════════════════
#  RESULT TYPES
# ════════════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    ok:        bool
    reason:    str = ""
    warnings:  List[str] = field(default_factory=list)
    severity:  str = "info"


@dataclass
class BoxImpact:
    box:         int
    before:      int
    after:       int
    cap:         int
    reels_before: int
    reels_after:  int
    lots_before: List[str]
    lots_after:  List[str]


@dataclass
class PlanDiff:
    summary:    str
    boxes:      List[BoxImpact] = field(default_factory=list)
    warnings:   List[str]       = field(default_factory=list)
    reel_moved: Optional[Dict]  = None
    target_old: Optional[int]   = None
    target_new: Optional[int]   = None


class PlanEditError(Exception):
    pass


# ════════════════════════════════════════════════════════════════════
#  OPERATIONS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MoveReelOp:
    reel_id:    int
    target_box: int


@dataclass(frozen=True)
class ChangeTargetOp:
    reel_id:    int
    new_target: int


@dataclass(frozen=True)
class SwapReelsOp:
    reel_id_a:  int
    reel_id_b:  int


@dataclass(frozen=True)
class DeleteReelOp:
    reel_id:    int


# ════════════════════════════════════════════════════════════════════
#  EDITOR
# ════════════════════════════════════════════════════════════════════

class PlanEditor:
    """Stateful editor wrapping a plan + history + config constraints."""

    def __init__(self, plan: List[Dict],
                 history_reels: Optional[List[Dict]] = None,
                 config=None,
                 min_reel: Optional[int] = None,
                 max_reel: Optional[int] = None,
                 box_cap:  Optional[int] = None,
                 slots_per_box: Optional[int] = None):
        self._plan = plan
        self._history = list(history_reels or [])
        if config is not None:
            self._min_reel = getattr(config, "min_per_reel", min_reel or 1)
            self._max_reel = getattr(config, "max_per_reel", max_reel or 999_999_999)
            self._box_cap  = getattr(config, "max_per_box",  box_cap  or 999_999_999)
            self._slots    = getattr(config, "reels_per_box",
                             getattr(config, "slots_per_box", slots_per_box or 4))
        else:
            self._min_reel = min_reel or 1
            self._max_reel = max_reel or 999_999_999
            self._box_cap  = box_cap  or 999_999_999
            self._slots    = slots_per_box or 4

    # ── Accessors ──────────────────────────────────────────────

    @property
    def constraints(self) -> Dict:
        return {"min_reel": self._min_reel, "max_reel": self._max_reel,
                "box_cap": self._box_cap, "slots_per_box": self._slots}

    # ── Public API ─────────────────────────────────────────────

    def validate(self, op) -> ValidationResult:
        if isinstance(op, MoveReelOp):     return self._validate_move(op)
        if isinstance(op, ChangeTargetOp): return self._validate_target(op)
        if isinstance(op, SwapReelsOp):    return self._validate_swap(op)
        if isinstance(op, DeleteReelOp):   return self._validate_delete(op)
        return ValidationResult(False, f"Unknown op: {type(op).__name__}", severity="error")

    def preview(self, op) -> PlanDiff:
        v = self.validate(op)
        sandbox = deepcopy(self._plan)
        if v.ok:
            self._apply_to(sandbox, op)
        before_boxes = self._box_aggregate(self._plan)
        after_boxes  = self._box_aggregate(sandbox)
        return self._build_diff(op, v, before_boxes, after_boxes)

    def apply(self, op) -> PlanDiff:
        v = self.validate(op)
        if not v.ok:
            raise PlanEditError(v.reason)
        snapshot = deepcopy(self._plan)
        try:
            self._apply_to(self._plan, op)
            self._recompute_box_totals(self._plan)
        except Exception as e:
            self._plan.clear()
            self._plan.extend(snapshot)
            raise PlanEditError(f"Internal error during apply: {e}") from e
        return self.preview(op)

    def list_valid_target_boxes(self, reel_id: int) -> List[Dict]:
        """Return every box that could legally accept this reel + new-box option."""
        r = self._find_reel(reel_id)
        if r is None or r.get("note", "").startswith("Pulled"):
            return []

        boxes = self._box_aggregate(self._plan)
        all_box_ids = sorted(boxes.keys())
        result = []
        for b_id in all_box_ids:
            if b_id == r["box"]:
                continue
            v = self._validate_move(MoveReelOp(reel_id, b_id))
            agg = boxes[b_id]
            free_qty   = self._box_cap - agg["total"]
            free_slots = self._slots   - agg["count"]
            result.append({
                "box":           b_id,
                "ok":            v.ok,
                "current_total": agg["total"],
                "free":          free_qty,
                "slots_free":    free_slots,
                "lots":          sorted(agg["lots"]),
                "reason":        v.reason,
                "warnings":      v.warnings,
                "is_new":        False,
            })
        # Allow a brand-new box at the end
        next_box = max(all_box_ids) + 1 if all_box_ids else 1
        if next_box == 0:
            next_box = 1
        new_v = self._validate_move(MoveReelOp(reel_id, next_box))
        result.append({
            "box":           next_box,
            "ok":            new_v.ok,
            "current_total": 0,
            "free":          self._box_cap,
            "slots_free":    self._slots,
            "lots":          [],
            "reason":        new_v.reason,
            "warnings":      new_v.warnings,
            "is_new":        True,
        })
        return result

    # ── Validators ─────────────────────────────────────────────

    def _validate_move(self, op: MoveReelOp) -> ValidationResult:
        r = self._find_reel(op.reel_id)
        if r is None:
            return ValidationResult(False, f"Reel R{op.reel_id} not found",
                                    severity="error")
        if r.get("note", "").startswith("Pulled"):
            return ValidationResult(False, f"R{op.reel_id} was pulled — cannot move",
                                    severity="error")
        if r.get("note") == "Wait next lot":
            return ValidationResult(False, f"R{op.reel_id} is a wait-marker — cannot move",
                                    severity="error")
        if r["box"] == op.target_box:
            return ValidationResult(False,
                f"R{op.reel_id} is already in Box {op.target_box}", severity="info")
        if op.target_box < 0:
            return ValidationResult(False, f"Box {op.target_box} is invalid",
                                    severity="error")

        warnings: List[str] = []
        boxes = self._box_aggregate(self._plan)
        target_agg = boxes.get(op.target_box, {"total": 0, "count": 0, "lots": set()})
        src_box_id = r["box"]
        src_agg    = boxes[src_box_id]

        # Capacity
        new_total = target_agg["total"] + r["target"]
        if new_total > self._box_cap:
            return ValidationResult(False,
                f"Box {op.target_box} would overflow: "
                f"{target_agg['total']:,} + {r['target']:,} = {new_total:,} "
                f"> capacity {self._box_cap:,}", severity="error")

        # Slot check
        if target_agg["count"] >= self._slots:
            return ValidationResult(False,
                f"Box {op.target_box} has no free slots "
                f"({target_agg['count']}/{self._slots})", severity="error")

        # Lot integrity
        if target_agg["lots"] and r["lot"] not in target_agg["lots"]:
            return ValidationResult(False,
                f"Lot mismatch: Box {op.target_box} has Lot {','.join(sorted(target_agg['lots']))}, "
                f"R{op.reel_id} is Lot {r['lot']}", severity="error")

        # Source-box invariant warning
        all_box_ids   = sorted(b for b in boxes.keys() if b != 0)
        newest_box_id = max(all_box_ids) if all_box_ids else None
        src_after = src_agg["total"] - r["target"]
        if (src_box_id != 0 and src_box_id != newest_box_id
                and src_after > 0 and src_after < self._box_cap):
            warnings.append(
                f"Box {src_box_id} will be under-filled after move "
                f"({src_after:,}/{self._box_cap:,}). "
                f"Consider filling it from another reel before starting Monitor.")

        # Skipping box-numbers
        if op.target_box not in boxes and all_box_ids:
            if op.target_box > (newest_box_id or 0) + 1:
                warnings.append(
                    f"Skipping box numbers (next after {newest_box_id} should be "
                    f"{newest_box_id + 1}, not {op.target_box})")

        return ValidationResult(True, warnings=warnings,
                                severity="warn" if warnings else "info")

    def _validate_target(self, op: ChangeTargetOp) -> ValidationResult:
        r = self._find_reel(op.reel_id)
        if r is None:
            return ValidationResult(False, f"Reel R{op.reel_id} not found",
                                    severity="error")
        if r.get("note", "").startswith("Pulled"):
            return ValidationResult(False, f"R{op.reel_id} was pulled",
                                    severity="error")
        if op.new_target < self._min_reel or op.new_target > self._max_reel:
            return ValidationResult(False,
                f"Target {op.new_target:,} outside allowed range "
                f"[{self._min_reel:,}, {self._max_reel:,}]", severity="error")
        boxes = self._box_aggregate(self._plan)
        b_id = r["box"]
        new_total = boxes[b_id]["total"] - r["target"] + op.new_target
        if new_total > self._box_cap:
            return ValidationResult(False,
                f"Box {b_id} would overflow: new total {new_total:,} > {self._box_cap:,}",
                severity="error")
        return ValidationResult(True)

    def _validate_swap(self, op: SwapReelsOp) -> ValidationResult:
        if op.reel_id_a == op.reel_id_b:
            return ValidationResult(False, "Cannot swap a reel with itself",
                                    severity="error")
        ra = self._find_reel(op.reel_id_a)
        rb = self._find_reel(op.reel_id_b)
        if ra is None or rb is None:
            return ValidationResult(False, "Reel not found", severity="error")
        if ra["box"] == rb["box"]:
            return ValidationResult(False, "Both reels are in the same box",
                                    severity="info")
        v1 = self._validate_move(MoveReelOp(op.reel_id_a, rb["box"]))
        if not v1.ok:
            return ValidationResult(False, f"Cannot move R{op.reel_id_a}: {v1.reason}",
                                    severity="error")
        v2 = self._validate_move(MoveReelOp(op.reel_id_b, ra["box"]))
        if not v2.ok:
            return ValidationResult(False, f"Cannot move R{op.reel_id_b}: {v2.reason}",
                                    severity="error")
        return ValidationResult(True, warnings=v1.warnings + v2.warnings)

    def _validate_delete(self, op: DeleteReelOp) -> ValidationResult:
        r = self._find_reel(op.reel_id)
        if r is None:
            return ValidationResult(False, f"R{op.reel_id} not found", severity="error")
        warnings: List[str] = []
        boxes = self._box_aggregate(self._plan)
        b_id = r["box"]
        new_total = boxes[b_id]["total"] - r["target"]
        all_box_ids = sorted(b for b in boxes.keys() if b != 0)
        newest_box_id = max(all_box_ids) if all_box_ids else None
        if (b_id != 0 and b_id != newest_box_id
                and 0 < new_total < self._box_cap):
            warnings.append(f"Box {b_id} will be under-filled "
                            f"({new_total:,}/{self._box_cap:,})")
        return ValidationResult(True, warnings=warnings,
                                severity="warn" if warnings else "info")

    # ── Mutators ───────────────────────────────────────────────

    def _apply_to(self, plan: List[Dict], op):
        if isinstance(op, MoveReelOp):
            r = self._find_reel(op.reel_id, plan=plan)
            if r is None:
                raise PlanEditError(f"R{op.reel_id} disappeared")
            r["box"] = op.target_box
            return
        if isinstance(op, ChangeTargetOp):
            r = self._find_reel(op.reel_id, plan=plan)
            r["target"] = op.new_target
            return
        if isinstance(op, SwapReelsOp):
            ra = self._find_reel(op.reel_id_a, plan=plan)
            rb = self._find_reel(op.reel_id_b, plan=plan)
            ra["box"], rb["box"] = rb["box"], ra["box"]
            return
        if isinstance(op, DeleteReelOp):
            for i, r in enumerate(plan):
                if r.get("reel") == op.reel_id:
                    del plan[i]
                    return
            raise PlanEditError(f"R{op.reel_id} not found to delete")
        raise PlanEditError(f"Unknown op: {type(op).__name__}")

    # ── Helpers ────────────────────────────────────────────────

    def _find_reel(self, reel_id: int,
                   plan: Optional[List[Dict]] = None) -> Optional[Dict]:
        for r in (plan if plan is not None else self._plan):
            if r.get("reel") == reel_id and not r.get("note", "").startswith("Pulled"):
                return r
        return None

    def _box_aggregate(self, plan: List[Dict]) -> Dict[int, Dict]:
        agg: Dict[int, Dict] = defaultdict(
            lambda: {"total": 0, "count": 0, "lots": set(), "reels": []})
        for r in plan:
            if r.get("note") == "Wait next lot":
                continue
            if r.get("note", "").startswith("Pulled"):
                continue
            b = r["box"]
            agg[b]["total"] += r.get("target", 0)
            agg[b]["count"] += 1
            if r.get("lot"):
                agg[b]["lots"].add(r["lot"])
            agg[b]["reels"].append(r)
        for h in self._history:
            if h.get("note", "").startswith("Pulled"):
                continue
            b = h.get("box", 0)
            agg[b]["total"] += h.get("actual", h.get("target", 0))
            agg[b]["count"] += 1
            if h.get("lot"):
                agg[b]["lots"].add(h["lot"])
        return dict(agg)

    def _recompute_box_totals(self, plan: List[Dict]):
        agg = self._box_aggregate(plan)
        for r in plan:
            r["box_total"] = agg.get(r["box"], {}).get("total", 0)

    def _build_diff(self, op, v: ValidationResult,
                    before: Dict, after: Dict) -> PlanDiff:
        boxes_changed: List[BoxImpact] = []
        all_box_ids = sorted(set(before.keys()) | set(after.keys()))
        for b_id in all_box_ids:
            b_before = before.get(b_id, {"total": 0, "count": 0, "lots": set()})
            b_after  = after.get(b_id,  {"total": 0, "count": 0, "lots": set()})
            if b_before["total"] != b_after["total"] or b_before["count"] != b_after["count"]:
                boxes_changed.append(BoxImpact(
                    box=b_id, before=b_before["total"], after=b_after["total"],
                    cap=self._box_cap,
                    reels_before=b_before["count"], reels_after=b_after["count"],
                    lots_before=sorted(b_before["lots"]),
                    lots_after=sorted(b_after["lots"]),
                ))
        if isinstance(op, MoveReelOp):
            r = self._find_reel(op.reel_id)
            summary = (f"Move R{op.reel_id} from Box {r['box']} → Box {op.target_box}"
                       if r else f"Move R{op.reel_id} → Box {op.target_box}")
            return PlanDiff(summary=summary, boxes=boxes_changed,
                            warnings=v.warnings, reel_moved=r)
        if isinstance(op, ChangeTargetOp):
            r = self._find_reel(op.reel_id)
            old_t = r["target"] if r else None
            return PlanDiff(
                summary=(f"Set R{op.reel_id} target: {old_t:,} → {op.new_target:,}"
                         if old_t else f"Set R{op.reel_id} target → {op.new_target:,}"),
                boxes=boxes_changed, warnings=v.warnings,
                target_old=old_t, target_new=op.new_target)
        if isinstance(op, SwapReelsOp):
            return PlanDiff(summary=f"Swap R{op.reel_id_a} ⇄ R{op.reel_id_b}",
                            boxes=boxes_changed, warnings=v.warnings)
        if isinstance(op, DeleteReelOp):
            return PlanDiff(summary=f"Delete R{op.reel_id}",
                            boxes=boxes_changed, warnings=v.warnings)
        return PlanDiff(summary=str(op), boxes=boxes_changed, warnings=v.warnings)