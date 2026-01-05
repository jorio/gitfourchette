# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.graphview.commitlogdelegate import CommitLogDelegate
from gitfourchette.graphview.commitlogmodel import CommitToolTipZone
from gitfourchette.graphview.graphpaint import paintGraphFrame
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon


class BlameScrubberDelegate(CommitLogDelegate):
    def __init__(self, blameModel: BlameModel, singleItem: bool, parent: QWidget):
        self.blameModel = blameModel
        self.singleItem = singleItem
        super().__init__(repoModel=blameModel.repoModel, parent=parent)

    def isBold(self, oid: Oid) -> bool:
        return not self.singleItem and oid == self.blameModel.currentRevision.commitId

    def isDim(self, oid: Oid) -> bool:
        return False

    def paintPrivate(
            self,
            painter: QPainter,
            option: QStyleOptionViewItem,
            rect: QRect,
            oid: Oid,
            toolTips: list[CommitToolTipZone]
    ):
        revision = self.blameModel.revList.revisionForCommit(oid)

        # Graph frame
        if not self.singleItem:
            graphRect = QRect(rect)
            paintGraphFrame(painter, graphRect, oid, self.blameModel.graph, set())
            rect.setLeft(graphRect.right())

        # Icon
        iconRect = QRect(rect)
        iconSize = min(16, iconRect.height())
        iconRect.setWidth(iconSize)
        icon = stockIcon(f"status_{revision.status.lower()}")
        icon.paint(painter, iconRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rect.setLeft(iconRect.right() + 5)

    def uncommittedChangesMessage(self) -> str:
        return _("Uncommitted Changes in Working Directory")
