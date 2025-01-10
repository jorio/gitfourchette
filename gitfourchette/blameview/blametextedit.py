# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.blameview.blamegutter import BlameGutter
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, GetCommitInfo, Jump
from gitfourchette.toolbox import *


class BlameTextEdit(QPlainTextEdit):
    selectIndex = Signal(int)

    model: BlameModel

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)

        self.gutter = BlameGutter(model, self)
        self.gutter.customContextMenuRequested.connect(lambda p: self.execContextMenu(self.gutter.mapToGlobal(p)))
        self.updateRequest.connect(self.gutter.onParentUpdateRequest)
        self.syncViewportMarginsWithGutter()

        # Initialize font
        self.refreshPrefs()

        # self.horizontalScrollBar().setContentsMargins(50,0,0,0)
        # self.horizontalScrollBar().setMaximumWidth(60)

    def refreshPrefs(self):
        monoFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if settings.prefs.font:
            monoFont.fromString(settings.prefs.font)
        self.setFont(monoFont)

        currentDocument = self.document()
        if currentDocument:
            currentDocument.setDefaultFont(monoFont)

        tabWidth = settings.prefs.tabSpaces
        self.setTabStopDistance(QFontMetricsF(monoFont).horizontalAdvance(' ' * tabWidth))
        self.refreshWordWrap()
        self.setCursorWidth(2)

        self.gutter.setFont(monoFont)
        self.syncViewportMarginsWithGutter()

    def refreshWordWrap(self):
        if settings.prefs.wordWrap:
            wrapMode = QPlainTextEdit.LineWrapMode.WidgetWidth
        else:
            wrapMode = QPlainTextEdit.LineWrapMode.NoWrap
        self.setLineWrapMode(wrapMode)

    def toggleWordWrap(self):
        settings.prefs.wordWrap = not settings.prefs.wordWrap
        settings.prefs.write()
        self.refreshWordWrap()

    # ---------------------------------------------
    # Context menu

    def contextMenu(self, globalPos: QPoint):
        # Don't show the context menu if we're empty
        if self.document().isEmpty():
            return None

        # Get position of click in document
        lineNumber = self.cursorForPosition(self.mapFromGlobal(globalPos)).blockNumber()
        lineNumber += 1

        blame = self.model.currentBlame
        hunk = blame.for_line(lineNumber)
        commitId = hunk.orig_commit_id

        try:
            commitIndex = self.model.trace.indexOfCommit(commitId)
        except ValueError:
            commitIndex = -1

        actions = [
            ActionDef(
                _("Blame File at {0}").format(shortHash(commitId)),
                enabled=commitIndex >= 0,
                callback=lambda: self.selectIndex.emit(commitIndex)
            ),

            TaskBook.action(
                self,
                Jump,
                name=_("Jump to {0} in Repo").format(shortHash(commitId)),
                taskArgs=NavLocator.inCommit(commitId, hunk.orig_path)),

            TaskBook.action(self, GetCommitInfo, taskArgs=[
                commitId, False, self
            ]),
        ]

        bottom: QMenu = self.createStandardContextMenu()
        menu = ActionDef.makeQMenu(self, actions, bottom)
        bottom.deleteLater()  # don't need this menu anymore
        menu.setObjectName("BlameTextEditContextMenu")
        return menu

    def execContextMenu(self, globalPos: QPoint):  # pragma: no cover
        try:
            menu = self.contextMenu(globalPos)
            if not menu:
                return
            menu.exec(globalPos)
            menu.deleteLater()
        except Exception as exc:
            # Avoid exceptions in contextMenuEvent at all costs to prevent a crash
            excMessageBox(exc, message="Failed to create DiffView context menu")

    # ---------------------------------------------
    # Gutter

    def resizeGutter(self):
        cr: QRect = self.contentsRect()
        cr.setWidth(self.gutter.calcWidth())
        self.gutter.setGeometry(cr)

    def syncViewportMarginsWithGutter(self):
        gutterWidth = self.gutter.calcWidth()

        # Prevent Qt freeze if margin width exceeds widget width, e.g. when window is very narrow
        # (especially prevalent with word wrap?)
        self.setMinimumWidth(gutterWidth * 2)

        self.setViewportMargins(gutterWidth, 0, 0, 0)

    # ---------------------------------------------
    # Qt events

    def resizeEvent(self, event: QResizeEvent):
        """Update gutter geometry"""
        super().resizeEvent(event)
        self.resizeGutter()

    # ---------------------------------------------

    def syncModel(self):
        pass
