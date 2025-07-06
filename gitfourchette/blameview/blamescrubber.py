# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.blameview.blamescrubberdelegate import BlameScrubberDelegate
from gitfourchette.blameview.blamescrubbermodel import BlameScrubberModel
from gitfourchette.qt import *
from gitfourchette.toolbox import enforceComboBoxMaxVisibleItems


class BlameScrubber(QComboBox):
    def __init__(self, blameModel: BlameModel, parent: QWidget):
        super().__init__(parent)

        self.scrubberListDelegate = BlameScrubberDelegate(blameModel, singleItem=False, parent=self)
        self.scrubberMiniDelegate = BlameScrubberDelegate(blameModel, singleItem=True, parent=self)
        self.scrubberModel = BlameScrubberModel(blameModel, parent=self)

        self.setMinimumWidth(128)
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)

        # For performance, prevent Qt from looking at every item in the model during initialization
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.view().setUniformItemSizes(True)

        self.setItemDelegate(self.scrubberListDelegate)
        self.setModel(self.scrubberModel)

        enforceComboBoxMaxVisibleItems(self, 25)

    def paintEvent(self, e):
        painter = QStylePainter(self)

        controlOption = QStyleOptionComboBox()
        self.initStyleOption(controlOption)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, controlOption)

        rect = painter.style().subElementRect(QStyle.SubElement.SE_ComboBoxFocusRect, controlOption, self)

        itemOption = QStyleOptionViewItem()
        itemOption.initFrom(self)
        itemOption.widget = self
        itemOption.rect = rect
        modelIndex = self.model().index(self.currentIndex(), 0)
        self.scrubberMiniDelegate.paint(painter, itemOption, modelIndex, fillBackground=False)
