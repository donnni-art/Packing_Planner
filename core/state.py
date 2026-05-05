"""
Lot-by-Lot State Management — AutoPack VLO-127S
==================================================
Persist / restore in-progress lot-by-lot state to JSON.
Atomic write (tmp→rename) + .bak fallback to survive power cuts.
"""

import os, json, shutil

STATE_FILENAME = "_lot_state.json"


def _state_path(config):
    out = config.output_folder
    if out:
        d = os.path.join(out, "Planner")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, STATE_FILENAME)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), STATE_FILENAME)


def _save_state(config, state):
    fp  = _state_path(config)
    tmp = fp + ".tmp"
    # keep one rolling backup before overwriting
    if os.path.exists(fp):
        try:
            shutil.copy2(fp, fp + ".bak")
        except OSError:
            pass
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    shutil.move(tmp, fp)   # atomic rename on NTFS / ext4


def _load_state(config):
    fp = _state_path(config)
    # try primary, then backup
    for candidate in (fp, fp + ".bak"):
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError, ValueError):
                continue   # corrupt → try backup
    return None


def _clear_state(config):
    fp = _state_path(config)
    for path in (fp, fp + ".bak", fp + ".tmp"):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
