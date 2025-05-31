# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.blameview.blamescrubberdelegate import BlameScrubberDelegate
from gitfourchette.blameview.blamescrubbermodel import BlameScrubberModel
from gitfourchette.graphview.commitlogdelegate import CommitLogDelegate
from gitfourchette.qt import *
from gitfourchette.toolbox import enforceComboBoxMaxVisibleItems


class BlameScrubber(QComboBox):
    def __init__(self, blameModel: BlameModel, parent: QWidget):
        super().__init__(parent)

        self.scrubberModel = BlameScrubberModel(blameModel, parent=self)
        self.setModel(self.scrubberModel)

        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(128)
        self.setStyleSheet("QListView::item { max-height: 18px; }")  # Breeze-themed combobox gets unwieldy otherwise
        self.setIconSize(QSize(16, 16))  # Required if enforceComboBoxMaxVisibleItems kicks in
        enforceComboBoxMaxVisibleItems(self, QApplication.primaryScreen().availableSize().height() // 18 - 1)

        self.scrubberDelegate = BlameScrubberDelegate(blameModel, parent=self)
        self.setItemDelegate(self.scrubberDelegate)

    def paintEvent(self, e):
        painter = QStylePainter(self)

        controlOption = QStyleOptionComboBox()
        self.initStyleOption(controlOption)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, controlOption)

        rect = painter.style().subElementRect(QStyle.SubElement.SE_ComboBoxFocusRect, controlOption, self)

        delegate: CommitLogDelegate = self.itemDelegate()
        itemOption = QStyleOptionViewItem()
        itemOption.initFrom(self)
        itemOption.widget = self
        itemOption.rect = rect
        modelIndex = self.model().index(self.currentIndex(), 0)
        delegate.paint(painter, itemOption, modelIndex, fillBackground=False)
