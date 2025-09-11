# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import gc
import logging
import time

import pygit2

from gitfourchette.qt import *
from gitfourchette.toolbox.qtutils import setFontFeature

logger = logging.getLogger(__name__)


class MemoryIndicator(QPushButton):
    def __init__(self, parent):
        super().__init__(parent)

        self.setObjectName("MemoryIndicator")
        self.setText("Memory")

        # No border: don't let it thicken the status bar
        self.setStyleSheet("border: none; text-align: right; padding-right: 8px;")

        font: QFont = self.font()
        font.setPointSize(font.pointSize() * 85 // 100)
        setFontFeature(font, "tnum")  # Tabular numbers
        self.setFont(font)

        width = 220

        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self.clicked.connect(self.onMemoryIndicatorClicked)
        self.setToolTip("Force GC")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lastUpdate = 0.0

    def onMemoryIndicatorClicked(self):
        gc.collect()

        windows = '\n'.join(f'\t* {w.__class__.__name__} {w.objectName()}' for w in QApplication.topLevelWindows())
        widgets = '\n'.join(f'\t* {w.__class__.__name__} {w.objectName()}' for w in QApplication.topLevelWidgets())
        report = f"\nTop-Level Windows:\n{windows}\nTop-Level Widgets:\n{widgets}\n"
        logging.info(report)

        self.lastUpdate = 0.0
        self.updateMemoryIndicator()

    def paintEvent(self, e):
        self.updateMemoryIndicator()
        super().paintEvent(e)

    def updateMemoryIndicator(self):
        now = time.time()
        if now - self.lastUpdate < 0.03:
            return
        self.lastUpdate = time.time()

        allIds = set()
        for w in QApplication.topLevelWidgets():
            allIds.add(id(w))
            allIds.update(id(o) for o in w.findChildren(QObject))
        numQObjects = len(allIds)

        cacheMem, _dummy = pygit2.settings.cached_memory
        fds = QLocale().formattedDataSize(cacheMem, 0, QLocale.DataSizeFormat.DataSizeSIFormat)
        self.setText(f"git: {fds}    qto: {numQObjects}    pyo: {len(gc.get_objects())}")
