"""
Smart Re-plan — AutoPack VLO-127S
===================================
Pure calculation: given a remainder quantity and a list of open boxes,
find the optimal split between one open box and Box-0 remainder reels.

Previously duplicated as "ULTRA SMART RE-PLAN" in both main.py and
planner_page.py (TODO-FIX-17).  Both callers now use find_smart_split()
for the search step, then apply their own insertion logic.
"""

import math

from app.core.calculation_engine import _distribute_reels


def find_smart_split(rem_qty, open_boxes, min_reel, max_reel, box_cap):
    """Return the best (box_id, take_qty, take_reels, rem_after, rem_reels_count).

    Searches open_boxes from newest (last) to oldest, trying every valid
    number of reels per box.  For older boxes the placement must fill
    the box exactly; for the newest box a partial fill is allowed.

    Returns (None, 0, 0, rem_qty, 0) when no valid split is found.
    """
    if not open_boxes or min_reel <= 0 or rem_qty <= 0:
        return None, 0, 0, rem_qty, 0

    newest_box_id = open_boxes[-1]["box"]

    for ob in reversed(open_boxes):
        ob_id      = ob["box"]
        ob_curr    = int(ob["current_total"])
        ob_slots   = int(ob["slots"])
        is_newest  = (ob_id == newest_box_id)
        deficit    = box_cap - ob_curr

        for try_reels in range(ob_slots, 0, -1):
            rem_slots = ob_slots - try_reels

            if rem_slots == 0:
                min_t_box = deficit
                max_t_box = deficit
            else:
                min_t_box = max(min_reel * try_reels,
                                deficit - max_reel * rem_slots)
                max_t_box = min(max_reel * try_reels,
                                deficit - min_reel * rem_slots)

            if min_t_box > max_t_box:
                continue

            # Older boxes must be filled to capacity exactly
            if not is_newest:
                if not (min_t_box <= deficit <= max_t_box):
                    continue
                min_t_box = max_t_box = deficit

            best_take = None
            best_rem_reels = 0

            # try_rem_reels == 0: put everything into the box, nothing left over
            if min_t_box <= rem_qty <= max_t_box:
                best_take = rem_qty
                best_rem_reels = 0
            else:
                # Compute the valid range for try_rem_reels analytically (O(1)).
                # Need: f_min = max(min_t_box, rem_qty - max_reel*n) <= min(max_t_box, rem_qty - min_reel*n) = f_max
                # That gives: n >= ceil((rem_qty - max_t_box) / max_reel)  [so f_min <= max_t_box]
                #              n <= (rem_qty - min_t_box) // min_reel        [so min_t_box <= f_max]
                #              n <= rem_qty // min_reel                      [so f_max >= 0]
                min_rem = max(1, math.ceil(max(0, rem_qty - max_t_box) / max_reel))
                max_rem = min(
                    rem_qty // min_reel,
                    max(0, rem_qty - min_t_box) // min_reel,
                )
                if min_rem <= max_rem:
                    try_rem_reels = min_rem
                    f_min = max(min_t_box, max(0, rem_qty - max_reel * try_rem_reels))
                    f_max = min(max_t_box, max(0, rem_qty - min_reel * try_rem_reels))
                    if f_min <= f_max:
                        mid = (f_min + f_max) // 2
                        take = mid
                        if take < f_min:
                            take = f_min
                        if take > f_max:
                            take = f_max
                        best_take = take
                        best_rem_reels = try_rem_reels

            if best_take is not None:
                return ob_id, best_take, try_reels, rem_qty - best_take, best_rem_reels

    return None, 0, 0, rem_qty, 0