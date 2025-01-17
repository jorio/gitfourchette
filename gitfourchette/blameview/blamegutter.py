# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import TYPE_CHECKING

from pygit2 import Commit

from gitfourchette import settings
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.blameview.blametextedit import BlameTextEdit


class BlameGutter(QWidget):
    textEdit: BlameTextEdit
    model: BlameModel

    def __init__(self, model, parent):
        super().__init__(parent)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.SmallestReadableFont)
        setFontFeature(font, "tnum")  # Tabular numbers
        self.setFont(font)

        self.model = model
        self.textEdit = parent

        self.refreshMetrics()

        # Enable customContextMenuRequested signal
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.installEventFilter(self)

    def refreshMetrics(self):
        fontMetrics = self.fontMetrics()

        maxLineNumber = self.textEdit.blockCount()

        dateWidth = fontMetrics.horizontalAdvance("2000-00-00 ")
        authorWidth = fontMetrics.horizontalAdvance("M" * 8)
        lnWidth = fontMetrics.horizontalAdvance(" " + "0" * len(str(maxLineNumber)))

        self.columnMetrics = []
        x = 2
        for w in (dateWidth, authorWidth, lnWidth):
            self.columnMetrics.append((x, w))
            x += w
        x += 3
        self.preferredWidth = x

        self.lineHeight = max(fontMetrics.height(), self.textEdit.fontMetrics().height())

    def syncModel(self):
        self.refreshMetrics()

    def calcWidth(self) -> int:
        return self.preferredWidth

    def onParentUpdateRequest(self, rect: QRect, dy: int):
        if dy != 0:
            self.scroll(0, dy)
        else:
            self.update(0, rect.y(), self.width(), rect.height())

    def sizeHint(self) -> QSize:
        return QSize(self.calcWidth(), 0)

    def wheelEvent(self, event: QWheelEvent):
        # Forward mouse wheel to parent widget
        self.parentWidget().wheelEvent(event)

    def eventFilter(self, watched, event: QEvent):
        if event.type() == QEvent.Type.ToolTip:
            return self.doToolTip(event)
        return False

    def paintEvent(self, event: QPaintEvent):
        blame = self.model.currentBlame
        textEdit = self.textEdit
        painter = QPainter(self)

        # Set up colors
        palette = self.palette()
        themeBG = palette.color(QPalette.ColorRole.Base)  # standard theme background color
        themeFG = palette.color(QPalette.ColorRole.Text)  # standard theme foreground color
        if isDarkTheme(palette):
            gutterColor = themeBG.darker(105)  # light theme
        else:
            gutterColor = themeBG.lighter(140)  # dark theme
        lineColor = QColor(*themeFG.getRgb()[:3], 80)
        textColor = QColor(*themeFG.getRgb()[:3], 128)

        # Gather some metrics
        paintRect = event.rect()
        gutterRect = self.rect()
        rightEdge = gutterRect.width() - 1
        lh = self.lineHeight

        # Clip painting to QScrollArea viewport rect (don't draw beneath horizontal scroll bar)
        vpRect = textEdit.viewport().rect()
        vpRect.setWidth(paintRect.width())  # vpRect is adjusted by gutter width, so undo this
        paintRect = paintRect.intersected(vpRect)
        painter.setClipRect(paintRect)

        # Draw background
        painter.fillRect(paintRect, gutterColor)

        # Draw vertical separator line
        painter.fillRect(rightEdge, paintRect.y(), 1, paintRect.height(), lineColor)

        block: QTextBlock = textEdit.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = round(textEdit.blockBoundingGeometry(block).translated(textEdit.contentOffset()).top())
        bottom = top + round(textEdit.blockBoundingRect(block).height())

        lc2 = QColor(lineColor)
        lc2.setAlphaF(lc2.alphaF()/2)
        linePen = QPen(lc2)#, 1, Qt.PenStyle.DashLine)
        textPen = QPen(textColor)
        painter.setPen(textPen)

        locale = QLocale()
        lastCaptionDrawnAtLine = -1
        hunkTraceNode = blame[0]
        hunkStartLine = 1

        alignLeft = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        alignRight = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        while block.isValid() and top <= paintRect.bottom():
            if block.isVisible() and bottom >= paintRect.top():
                lineNumber = 1 + blockNumber

                colL, colW = self.columnMetrics[-1]
                painter.drawText(colL, top, colW, lh, alignRight, str(lineNumber))

                try:
                    blameNode = blame[lineNumber].traceNode
                except IndexError:
                    break
                if blameNode is not hunkTraceNode:
                    hunkTraceNode = blameNode
                    hunkStartLine = lineNumber

                if lastCaptionDrawnAtLine != hunkStartLine:
                    drawSeparator = lastCaptionDrawnAtLine > 0
                    lastCaptionDrawnAtLine = lineNumber

                    commit: Commit = self.model.repo[blameNode.commitId]
                    sig = commit.author

                    # Date
                    commitQdt = QDateTime.fromSecsSinceEpoch(sig.time, Qt.TimeSpec.OffsetFromUTC, sig.offset * 60)
                    commitTimeStr = locale.toString(commitQdt, "yyyy-MM-dd")
                    colL, colW = self.columnMetrics[0]
                    painter.drawText(colL, top, colW, lh, alignLeft, commitTimeStr)

                    # Author
                    name = abbreviatePerson(sig, AuthorDisplayStyle.LastName)
                    colL, colW = self.columnMetrics[1]
                    FittedText.draw(painter, QRect(colL, top, colW, lh), alignLeft, name)

                    # Hunk separator line
                    if drawSeparator:
                        y = top
                        painter.setPen(linePen)
                        painter.drawLine(QLine(0, y, rightEdge-1, y))
                        painter.setPen(textPen)  # restore text pen

            block = block.next()
            top = bottom
            bottom = top + round(textEdit.blockBoundingRect(block).height())
            blockNumber += 1

        painter.end()

    def doToolTip(self, event: QHelpEvent):
        assert isinstance(event, QHelpEvent)

        blame = self.model.currentBlame

        pos = event.globalPos()
        editLocalPos = self.textEdit.mapFromGlobal(pos)
        textCursor = self.textEdit.cursorForPosition(editLocalPos)
        lineNumber = 1 + textCursor.blockNumber()

        try:
            node = blame[lineNumber].traceNode
        except IndexError:
            return False

        text = "<table style='white-space: pre'>"

        def newLine(heading, caption):
            return f"<tr><td style='color:{mutedToolTipColorHex()}; text-align: right;'>{heading} </td><td>{caption}</td>"

        commit = self.model.repo.peel_commit(node.commitId)
        text += newLine(_("commit:"), shortHash(commit.id))
        text += newLine(_("author:"), commit.author.name)
        text += newLine(_("date:"), signatureDateFormat(commit.author, settings.prefs.shortTimeFormat))
        text += newLine(_("file name:"), node.path)

        text += "</table>"
        text += "<p>" + escape(commit.message.rstrip()).replace("\n", "<br>") + "</p>"

        QToolTip.showText(event.globalPos(), text, self)
        event.accept()
        return True
