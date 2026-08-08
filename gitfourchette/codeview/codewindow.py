# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

from typing import ClassVar

from gitfourchette import settings
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.qt import *
from gitfourchette.syntax import LexJobCache, LexerCache, LexJob


class CodeWindow(QWidget):
    """
    Standalone window containing a vanilla CodeView.
    """

    _liveWindows: ClassVar[list[CodeWindow]] = []
    "Currently open CodeWindows (prevent early GC)"

    def __init__(self, text: str, path: str):
        super().__init__(None)
        self.setObjectName(self.__class__.__name__)

        # Keep reference around to avoid being GC'd instantly
        CodeWindow._liveWindows.append(self)

        codeView = CodeView(parent=self)
        codeView.setPlainText(text)
        codeView.setUpAsDetachedWindow()

        lexJob = self._getLexJob(text, path)
        if lexJob is not None:
            codeView.highlighter.installLexJob(lexJob)
            codeView.highlighter.rehighlight()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(codeView.searchBar)
        layout.addWidget(codeView)

        self.setWindowTitle(path)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(codeView.idealDetachedSize())

        self.codeView = codeView
        self.codeText = text

    @classmethod
    def findWindow(cls, text: str):
        try:
            return next(w for w in cls._liveWindows if w.codeText == text)
        except StopIteration as ex:
            raise KeyError("no window currently open with this text") from ex

    @staticmethod
    def _getLexJob(text: str, path: str) -> LexJob | None:
        if not settings.prefs.isSyntaxHighlightingEnabled():
            return None

        cacheKey = f"CodeWindow:{hash(text)}"

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
