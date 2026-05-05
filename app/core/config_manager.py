"""
Configuration Manager
Loads and saves YAML configuration, provides defaults.
"""

import os
import yaml
import copy


DEFAULT_CONFIG = {
    "output": {
        "folder": os.path.join(
            os.path.expanduser("~"),
            "Desktop",
            "Auto reel packing visualization VLO-127S",
        ),
        "product_code": "VLO-127S",
    },
    "ui": {
        "fullscreen": True,
        "theme": "dark",
        "language": "th",
        "scale": 0.0,         # 0 = auto-detect from screen resolution
        "mode": 0,            # 0=Auto, 1=FIFO(v5), 2=Optimize(v6), 3=Lot-by-Lot
    },
    "packing": {
        "max_per_box": 6400,
        "max_per_reel": 3100,
        "min_per_reel": 1500,
        "reels_per_box": 3,
        "replan_trigger_pct": 0.70,
        "replan_warn_pct": 0.85,
    },
    "reels": {
        "max_reels": 5,
    },
}


class ConfigManager:
    """Manages application configuration via YAML file."""

    def __init__(self, config_path=None):
        if config_path is None:
            # Default: config.yaml next to main.py
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config.yaml")

        self.config_path = config_path
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self):
        """Load config from YAML file. Use defaults for missing keys."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                self._merge(self.config, loaded)
            except Exception as e:
                print(f"[ConfigManager] Warning: Could not load config: {e}")
                print("[ConfigManager] Using default configuration.")

        # Expand ~ in all path fields
        folder = self.config["output"]["folder"]
        self.config["output"]["folder"] = os.path.expanduser(folder)

        det = self.config.get("detection", {})
        for key in ("template_path", "yolo_model_path"):
            if key in det and isinstance(det[key], str):
                det[key] = os.path.expanduser(det[key])
        tpaths = det.get("template_paths", [])
        if isinstance(tpaths, list):
            det["template_paths"] = [os.path.expanduser(p) for p in tpaths]

        # Ensure output folder exists
        self._ensure_output_dir()

    def _merge(self, base: dict, override: dict):
        """Recursively merge override into base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def _ensure_output_dir(self):
        """Create the output directory if it doesn't exist.
        Falls back to default Desktop path if the configured path fails."""
        folder = self.config["output"]["folder"]
        if self._try_create_dir(folder):
            return
        # Configured path invalid (e.g. another user's Desktop) → reset
        fallback = os.path.join(
            os.path.expanduser("~"), "Desktop",
            "Auto reel packing visualization VLO-127S")
        print(f"[ConfigManager] Cannot use '{folder}', "
              f"falling back to '{fallback}'")
        self.config["output"]["folder"] = fallback
        if not self._try_create_dir(fallback):
            print(f"[ConfigManager] Warning: fallback also failed")

    @staticmethod
    def _try_create_dir(path):
        """Create dir and verify it's writable. Returns True on success."""
        try:
            os.makedirs(path, exist_ok=True)
            # Verify write access
            test = os.path.join(path, ".write_test")
            with open(test, "w") as f:
                f.write("t")
            os.remove(test)
            return True
        except Exception:
            return False

    def save(self):
        """Save current config back to YAML file."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")

    def get(self, section, key=None):
        """Get a config value. Returns section dict if key is None."""
        if section in self.config:
            if key is None:
                return self.config[section]
            return self.config[section].get(key)
        return None

    def set(self, section, key, value):
        """Set a config value."""
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value

    @property
    def output_folder(self):
        return self.config["output"]["folder"]

    @property
    def product_code(self):
        return self.config["output"]["product_code"]

    @property
    def is_fullscreen(self):
        return self.config["ui"]["fullscreen"]

    @property
    def theme(self):
        return self.config["ui"]["theme"]

    @property
    def ui_scale(self):
        return float(self.config["ui"].get("scale", 0.0))

    @property
    def ui_mode(self):
        return int(self.config["ui"].get("mode", 0))

    @property
    def destinations(self):
        return self.config["ui"].get("destinations", ["IRELAND", "HONG KONG"])

    @property
    def max_reels(self):
        return self.config["reels"]["max_reels"]

    @property
    def max_per_box(self):
        return int(self.config.get("packing", {}).get("max_per_box", 6400))

    @property
    def max_per_reel(self):
        return int(self.config.get("packing", {}).get("max_per_reel", 3100))

    @property
    def min_per_reel(self):
        return int(self.config.get("packing", {}).get("min_per_reel", 1500))

    @property
    def reels_per_box(self):
        return int(self.config.get("packing", {}).get("reels_per_box", 3))

    @property
    def replan_trigger_pct(self):
        """70%+ → auto re-plan."""
        return float(self.config.get("packing", {}).get("replan_trigger_pct", 0.70))

    @property
    def replan_warn_pct(self):
        """85%+ → ask user before re-plan."""
        return float(self.config.get("packing", {}).get("replan_warn_pct", 0.85))

    @property
    def detect_threshold(self):
        return self.config["detection"]["threshold"]

    @property
    def detect_cooldown(self):
        return self.config["detection"]["cooldown_frames"]

    @property
    def detect_roi(self):
        """Returns (x1, y1, x2, y2)"""
        d = self.config["detection"]
        return (d["roi_x1"], d["roi_y1"], d["roi_x2"], d["roi_y2"])

    @property
    def detect_count_line_y(self):
        return self.config["detection"]["count_line_y"]

    @property
    def detect_template_paths(self):
        return self.config["detection"].get("template_paths", [])

    @property
    def detect_mode(self):
        return self.config["detection"].get("mode", "template")

    @property
    def yolo_model_path(self):
        return self.config["detection"].get("yolo_model_path", "")

    @property
    def yolo_conf(self):
        return float(self.config["detection"].get("yolo_conf", 0.45))

    @property
    def yolo_iou(self):
        return float(self.config["detection"].get("yolo_iou", 0.45))

    @property
    def yolo_imgsz(self):
        return int(self.config["detection"].get("yolo_imgsz", 320))