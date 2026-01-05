# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamegutter import BlameGutter
from gitfourchette.blameview.blamemodel import BlameModel, Revision
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, GetCommitInfo
from gitfourchette.toolbox import *


class BlameTextEdit(CodeView):
    showRevision = Signal(Revision)
    jumpToCommit = Signal(NavLocator)

    model: BlameModel
    gutter: BlameGutter

    def __init__(self, model, parent=None):
        super().__init__(gutterClass=BlameGutter, parent=parent)
        self.model = model
        self.gutter.model = model

    def contextMenuActions(self, clickedCursor: QTextCursor):
        lineNumber = clickedCursor.blockNumber() + 1
        lineNumber = min(lineNumber, len(self.model.currentRevision.blameLines) - 1)

        commitId = self.model.currentRevision.blameLines[lineNumber].commitId
        revision = self.model.revList.revisionForCommit(commitId)
        locator = revision.toLocator()
        isWorkdir = locator.context.isWorkdir()

        if isWorkdir:
            blameLabel = _("Blame File at Uncommitted Revision")
            gotoLabel = _("Show Diff in Working Directory")
        else:
            blameLabel = _("Blame File at {0}", tquo(shortHash(commitId)))
            gotoLabel = _("Show {0} in Repo", tquo(shortHash(commitId)))

        return [
            ActionDef(
                blameLabel,
                icon="git-blame",
                callback=lambda: self.showRevision.emit(revision)
            ),

            ActionDef(
                gotoLabel,
                icon="go-window",
                callback=lambda: self.jumpToCommit.emit(locator)
            ),

            TaskBook.action(
                self,
                GetCommitInfo,
                taskArgs=[commitId, False, self.onGetInfoLocator],
                icon="SP_MessageBoxInformation",
                enabled=not isWorkdir,
            ),
        ]

    def onGetInfoLocator(self, locator: NavLocator):
        self.jumpToCommit.emit(locator)
