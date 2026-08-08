# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

from typing import ClassVar, Any

from gitfourchette import settings
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.qt import *
from gitfourchette.syntax import LexJobCache, LexerCache, LexJob


class CodeWindow(QWidget):
    """
    Standalone window containing a vanilla CodeView.
    """

    _liveWindows: ClassVar[list[CodeWindow]] = []
    """Currently open CodeWindows. Wayland's quirks force us to use a None
    parent, so we must keep track of the window so it doesn't get garbage
    collected instantly."""

    def __init__(
            self,
            codeViewClass: type[CodeView] = CodeView,
            uniqueIdentifier: Any = None,
    ):
        # Don't parent the window to another widget, because Wayland forces the
        # child window to be on top of its parent at all times.
        super().__init__(None)

        self.setObjectName(self.__class__.__name__)
        self.setWindowFlag(Qt.WindowType.Window, True)

        # Keep reference around to avoid being GC'd instantly
        CodeWindow._liveWindows.append(self)

        codeView = codeViewClass(parent=self)
        codeView.setUpAsDetachedWindow()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(codeView.searchBar)
        layout.addWidget(codeView)

        self.setWindowTitle(self.objectName())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(codeView.idealDetachedSize())

        self.codeView = codeView
        self.uniqueIdentifier = uniqueIdentifier

    def setPlainText(self, text: str, path: str):
        self.codeView.setPlainText(text)
        self.codeText = text

        lexJob = self._getLexJob(text, path)
        if lexJob is not None:
            self.codeView.highlighter.installLexJob(lexJob)
            self.codeView.highlighter.rehighlight()

    @classmethod
    def activateExistingWindow(cls, ident: Any) -> CodeWindow | None:
        try:
            window = next(w for w in cls._liveWindows if w.uniqueIdentifier == ident)
            window.activateWindow()
            return window
        except StopIteration:
            return None

    def _getLexJob(self, text: str, path: str) -> LexJob | None:
        if not settings.prefs.isSyntaxHighlightingEnabled():
            return None

        cacheKey = f"CodeWindow:{self.uniqueIdentifier}"

        try:
            return LexJobCache.get(cacheKey)
        except KeyError:
            pass

        lexer = LexerCache.getLexerFromPath(path, settings.prefs.pygmentsPlugins)
        if lexer is None:
            return None

        lexJob = LexJob(lexer, text, cacheKey)
        if lexJob is None:
            return None

        LexJobCache.put(lexJob)
        return lexJob

    def closeEvent(self, event: QCloseEvent):
        assert self in CodeWindow._liveWindows
        CodeWindow._liveWindows.remove(self)

        super().closeEvent(event)

        if QT5:  # Qt5 in test mode needs an extra push
            self.deleteLater()
