"""
Settings Page — AutoPack VLO-127S
==================================
Page 4: Packing constraints, algorithm mode, and output folder config.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QFrame, QGroupBox, QSpinBox, QComboBox, QLineEdit,
    QMessageBox, QFileDialog,
)
from PyQt5.QtCore import Qt, QLocale

from ui.theme import THEME, S
from ui.widgets import SectionHeader, make_btn, make_label


MODE_DESCRIPTIONS = {
    0: "Auto: เปรียบเทียบ FIFO กับ Optimize แล้วเลือกผลที่เหมาะกว่าอัตโนมัติ",
    1: "FIFO (v5): เรียงใช้ lot ตามลำดับที่กรอก และพยายามเติมกล่องเปิดก่อน",
    2: "Optimize (v6): ปรับลำดับและปริมาณเพื่อให้ตรง order และลด shortfall/scrap",
    3: "Lot-by-Lot: ใช้ flow ทีละ lot แบบ monitor จริง รองรับการคิวหลาย lot ต่อเนื่อง",
}


class SettingsPage(QWidget):
    def __init__(self, config, logger, parent=None):
        super().__init__(parent)
        self._config = config
        self._logger = logger
        self._build()

    def _build(self):
        T = THEME
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        hdr = SectionHeader("Settings", "การตั้งค่าระบบ")
        root.addWidget(hdr)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)
        body = QWidget(); scroll.setWidget(body)
        vlay = QVBoxLayout(body)
        vlay.setContentsMargins(S(20), S(16), S(20), S(20))
        vlay.setSpacing(S(14))

        # Packing constraints
        pack_grp = QGroupBox("Packing Constraints")
        pack_form = QGridLayout(pack_grp)
        pack_form.setSpacing(S(10))
        self._s_max_box = QSpinBox(); self._s_max_box.setRange(1, 99999)
        self._s_max_box.setValue(self._config.max_per_box); self._s_max_box.setSuffix(" pcs.")
        self._s_max_box.setLocale(QLocale(QLocale.C))
        self._s_max_reel = QSpinBox(); self._s_max_reel.setRange(1, 99999)
        self._s_max_reel.setValue(self._config.max_per_reel); self._s_max_reel.setSuffix(" pcs.")
        self._s_max_reel.setLocale(QLocale(QLocale.C))
        self._s_min_reel = QSpinBox(); self._s_min_reel.setRange(0, 99999)
        self._s_min_reel.setValue(self._config.min_per_reel); self._s_min_reel.setSuffix(" pcs.")
        self._s_min_reel.setLocale(QLocale(QLocale.C))
        self._s_rpb = QSpinBox(); self._s_rpb.setRange(1, 99)
        self._s_rpb.setValue(self._config.reels_per_box); self._s_rpb.setSuffix(" reels")
        self._s_rpb.setLocale(QLocale(QLocale.C))
        for i, (lbl_txt, w) in enumerate([
            ("Max / Box", self._s_max_box), ("Max / Reel", self._s_max_reel),
            ("Min / Reel", self._s_min_reel), ("Reels / Box", self._s_rpb),
        ]):
            row, col = divmod(i, 2)
            lbl = make_label(lbl_txt, size=10, color=T["text_muted"])
            lbl.setStyleSheet(f"color:{T['text_muted']};background:transparent;font-weight:700;")
            pack_form.addWidget(lbl, row * 2, col)
            pack_form.addWidget(w, row * 2 + 1, col)
        vlay.addWidget(pack_grp)

        # Algorithm
        algo_grp = QGroupBox("Algorithm")
        algo_lay = QHBoxLayout(algo_grp)
        algo_lay.addWidget(make_label("Mode:", size=11, color=T["text_secondary"]))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems([
            "Auto",
            "FIFO (v5)",
            "Optimize (v6)",
            "Lot-by-Lot",
        ])
        self._mode_combo.setCurrentIndex(self._config.ui_mode or 0)
        self._mode_combo.currentIndexChanged.connect(self._update_mode_description)
        algo_lay.addWidget(self._mode_combo)
        algo_lay.addStretch()
        self._mode_desc = make_label("", size=10, color=T["text_muted"])
        self._mode_desc.setWordWrap(True)
        self._mode_desc.setStyleSheet(
            f"color:{T['text_muted']};background:transparent;padding:{S(2)}px 0;")
        self._update_mode_description(self._mode_combo.currentIndex())
        algo_lay.addWidget(self._mode_desc, stretch=1)
        vlay.addWidget(algo_grp)

        # Output folder
        out_grp = QGroupBox("Output Folder")
        out_lay = QHBoxLayout(out_grp)
        self._folder_edit = QLineEdit(self._config.output_folder)
        self._folder_edit.setReadOnly(True)
        browse_btn = make_btn("Browse", "ghost")
        browse_btn.clicked.connect(self._browse_folder)
        out_lay.addWidget(self._folder_edit)
        out_lay.addWidget(browse_btn)
        vlay.addWidget(out_grp)

        save_btn = make_btn("💾  Save Settings", "success")
        save_btn.clicked.connect(self._save)
        vlay.addWidget(save_btn)
        vlay.addStretch()

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder",
                                                   self._folder_edit.text())
        if folder:
            self._folder_edit.setText(folder)

    def _update_mode_description(self, index):
        self._mode_desc.setText(MODE_DESCRIPTIONS.get(index, ""))

    def _save(self):
        self._config.set("packing", "max_per_box", self._s_max_box.value())
        self._config.set("packing", "max_per_reel", self._s_max_reel.value())
        self._config.set("packing", "min_per_reel", self._s_min_reel.value())
        self._config.set("packing", "reels_per_box", self._s_rpb.value())
        self._config.set("ui", "mode", self._mode_combo.currentIndex())
        folder = self._folder_edit.text().strip()
        if folder:
            self._config.set("output", "folder", folder)
        self._config.save()
        self._logger.info("Settings saved")
        QMessageBox.information(self, "Saved", "บันทึกการตั้งค่าสำเร็จ")
