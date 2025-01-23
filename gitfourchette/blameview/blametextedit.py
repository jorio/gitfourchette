# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamegutter import BlameGutter
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, GetCommitInfo
from gitfourchette.toolbox import *


class BlameTextEdit(CodeView):
    selectIndex = Signal(int)
    jumpToCommit = Signal(NavLocator)

    model: BlameModel
    gutter: BlameGutter

    def __init__(self, model, parent=None):
        super().__init__(gutterClass=BlameGutter, parent=parent)
        self.model = model
        self.gutter.model = model

    # ---------------------------------------------
    # Context menu

    def contextMenuActions(self, clickedCursor: QTextCursor):
        lineNumber = clickedCursor.blockNumber() + 1

        blame = self.model.currentBlame
        node = blame.lines[lineNumber].traceNode
        commitId = node.commitId
        path = node.path
        locator = NavLocator.inCommit(commitId, path)

        try:
            commitIndex = self.model.trace.indexOfCommit(commitId)
        except ValueError:
            commitIndex = -1

        return [
            ActionDef(
                _("Blame File at {0}").format(shortHash(commitId)),
                enabled=commitIndex >= 0,
                callback=lambda: self.selectIndex.emit(commitIndex)
            ),

            ActionDef(
                _("Go to {0} in Repo").format(shortHash(commitId)),
                enabled=bool(self.model.taskInvoker),
                callback=lambda: self.jumpToCommit.emit(locator),
            ),

            TaskBook.action(
                self.model.taskInvoker,
                GetCommitInfo,
                taskArgs=[commitId, False],
                enabled=bool(self.model.taskInvoker),
            ),
        ]
