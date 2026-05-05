"""
Application Logger — AutoPack VLO-127S
========================================
Writes activity log to file and notifies UI callbacks.
"""

import os
from datetime import datetime


class AppLogger:
    """Simple file + callback logger."""

    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self._path = os.path.join(folder, "activity_log.txt")
        self._callbacks = []

    def add_callback(self, fn):
        self._callbacks.append(fn)

    def log(self, msg, level="INFO"):
        ts = datetime.now().replace(microsecond=0).isoformat(" ")
        line = f"[{ts}] [{level}] {msg}"
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        for cb in self._callbacks:
            try:
                cb(line, level)
            except Exception:
                pass

    def info(self, msg):    self.log(msg, "INFO")
    def warn(self, msg):    self.log(msg, "WARN")
    def warning(self, msg): self.log(msg, "WARN")
    def error(self, msg):   self.log(msg, "ERROR")
    def plan(self, msg):    self.log(msg, "PLAN")
