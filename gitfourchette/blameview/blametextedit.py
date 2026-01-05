# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamegutter import BlameGutter
from gitfourchette.blameview.blamemodel import BlameModel, TraceNode
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, GetCommitInfo
from gitfourchette.toolbox import *


class BlameTextEdit(CodeView):
    selectNode = Signal(TraceNode)
    jumpToCommit = Signal(NavLocator)

    model: BlameModel
    gutter: BlameGutter

    def __init__(self, model, parent=None):
        super().__init__(gutterClass=BlameGutter, parent=parent)
        self.model = model
        self.gutter.model = model

    def contextMenuActions(self, clickedCursor: QTextCursor):
        lineNumber = clickedCursor.blockNumber() + 1
        lineNumber = min(lineNumber, len(self.model.currentBlame.lines) - 1)

        commitId = self.model.currentBlame.lines[lineNumber].commitId
        node = self.model.trace.nodeForCommit(commitId)
        locator = node.toLocator()
        isWorkdir = locator.context.isWorkdir()

        if isWorkdir:
            blameLabel = _("Blame File at Uncommitted Revision")
            gotoLabel = _("Show Diff in Working Directory")
        else:
            blameLabel = _("Blame File at {0}", tquo(shortHash(commitId)))
            gotoLabel = _("Show {0} in Repo", tquo(shortHash(commitId)))

        canInvoke = bool(self.model.taskInvoker)

        return [
            ActionDef(
                blameLabel,
                icon="git-blame",
                callback=lambda: self.selectNode.emit(node)
            ),

            ActionDef(
                gotoLabel,
                enabled=canInvoke,
                icon="go-window",
                callback=lambda: self.jumpToCommit.emit(locator)
            ),

            TaskBook.action(
                self.model.taskInvoker,
                GetCommitInfo,
                taskArgs=[commitId, False, self.window()],
                icon="SP_MessageBoxInformation",
                enabled=canInvoke and not isWorkdir,
            ),
        ]
