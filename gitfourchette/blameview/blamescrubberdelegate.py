# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.filelists.filelistmodel import STATUS_ICON_LETTERS
from gitfourchette.graphview.commitlogdelegate import CommitLogDelegate
from gitfourchette.graphview.commitlogmodel import CommitToolTipZone
from gitfourchette.graphview.graphpaint import paintGraphFrame
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon


class BlameScrubberDelegate(CommitLogDelegate):
    def __init__(self, blameModel: BlameModel, parent: QWidget):
        self.blameModel = blameModel
        super().__init__(repoModel=blameModel.repoModel, parent=parent)

    def isBold(self, index):
        return False

    def paintPrivate(
            self,
            painter: QPainter,
            option: QStyleOptionViewItem,
            rect: QRect,
            oid: Oid,
            toolTips: list[CommitToolTipZone]
    ):
        node = self.blameModel.trace.nodeForCommit(oid)

        # Graph frame
        graphRect = QRect(rect)
        paintGraphFrame(painter, graphRect, oid, self.blameModel.graph, set())
        rect.setLeft(graphRect.right())

        # Icon
        iconRect = QRect(rect)
        iconSize = min(16, iconRect.height())
        iconRect.setWidth(iconSize)
        icon = stockIcon("status_" + STATUS_ICON_LETTERS[int(node.status)])
        icon.paint(painter, iconRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rect.setLeft(iconRect.right() + 5)

    def uncommittedChangesMessage(self) -> str:
        return _("Uncommitted Changes in Working Directory")
