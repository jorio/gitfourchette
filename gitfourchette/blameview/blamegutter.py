# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from pygit2 import Commit

from gitfourchette import settings, colors
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.codeview.codegutter import CodeGutter
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class BlameGutter(CodeGutter):
    model: BlameModel

    def __init__(self, parent):
        super().__init__(parent)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.SmallestReadableFont)
        setFontFeature(font, "tnum")  # Tabular numbers
        self.setFont(font)

        self.boldFont = QFont(font)
        self.boldFont.setBold(True)

        self.model = None

        self.installEventFilter(self)

        self.columnMetrics = []
        self.preferredWidth = 0
        self.lineHeight = 12
        self.refreshMetrics()

    def syncFont(self, codeFont: QFont):
        pointSize = codeFont.pointSizeF()
        defaultFont = self.font()
        defaultFont.setPointSizeF(pointSize)
        self.boldFont.setPointSizeF(pointSize)
        self.setFont(defaultFont)

    def refreshMetrics(self):
        fontMetrics = self.fontMetrics()

        maxLineNumber = self.codeView.blockCount()

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

        self.lineHeight = max(fontMetrics.height(), self.codeView.fontMetrics().height())

    def calcWidth(self) -> int:
        return self.preferredWidth

    def eventFilter(self, watched, event: QEvent):
        if event.type() == QEvent.Type.ToolTip:
            return self.doToolTip(event)
        return False

    def paintEvent(self, event: QPaintEvent):
        blame = self.model.currentBlame
        painter = QPainter(self)

        # Set up colors
        palette = self.palette()
        themeFG = palette.color(QPalette.ColorRole.Text)  # standard theme foreground color
        lineColor = QColor(*themeFG.getRgb()[:3], 80)
        textColor = QColor(*themeFG.getRgb()[:3], 160)
        boldTextColor = QColor(*themeFG.getRgb()[:3], 210)
        heatColor = QColor(colors.orange)

        # Gather some metrics
        rightEdge = self.rect().width() - 1
        lh = self.lineHeight

        lc2 = QColor(lineColor)
        lc2.setAlphaF(lc2.alphaF()/2)
        linePen = QPen(lc2)#, 1, Qt.PenStyle.DashLine)
        textPen = QPen(textColor)
        boldTextPen = QPen(boldTextColor)
        painter.setPen(textPen)

        locale = QLocale()
        lastCaptionDrawnAtLine = -1
        hunkTraceNode = None
        hunkStartLine = 1

        alignLeft = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        alignRight = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        topNode = blame.traceNode
        topCommitId = topNode.commitId

        for block, top, bottom in self.paintBlocks(event, painter, lineColor):
            lineNumber = 1 + block.blockNumber()
            try:
                blameNode = blame.lines[lineNumber].traceNode
            except IndexError:
                break

            if blameNode is not hunkTraceNode:
                hunkTraceNode = blameNode
                hunkStartLine = lineNumber
                isCurrent = blameNode.commitId == topCommitId
                painter.setFont(self.boldFont if isCurrent else self.font())
                painter.setPen(boldTextPen if isCurrent else textPen)
                # Compute heat color
                heat = blameNode.revisionNumber / topNode.revisionNumber
                heat = heat ** 2  # ease in cubic
                heatColor.setAlphaF(lerp(.0, .6, heat))

            # Fill heat rectangle
            heatTop = top if lastCaptionDrawnAtLine >= 0 else 0
            painter.fillRect(QRect(0, heatTop, rightEdge, bottom-heatTop), heatColor)

            colL, colW = self.columnMetrics[-1]
            painter.drawText(colL, top, colW, lh, alignRight, str(lineNumber))

            if lastCaptionDrawnAtLine < hunkStartLine:
                drawSeparator = lastCaptionDrawnAtLine > 0
                lastCaptionDrawnAtLine = lineNumber

                commit: Commit = self.model.repo[blameNode.commitId]
                sig = commit.author

                # Date
                commitQdt = QDateTime.fromSecsSinceEpoch(sig.time, Qt.TimeSpec.OffsetFromUTC, sig.offset * 60)
                commitTimeStr = locale.toString(commitQdt, "yyyy-MM-dd")
                colL, colW = self.columnMetrics[0]
                FittedText.draw(painter, QRect(colL, top, colW, lh), alignLeft, commitTimeStr, bypassSetting=True)

                # Author
                name = abbreviatePerson(sig, AuthorDisplayStyle.LastName)
                colL, colW = self.columnMetrics[1]
                FittedText.draw(painter, QRect(colL, top, colW, lh), alignLeft, name)

                # Hunk separator line
                if drawSeparator:
                    y = top
                    penBackup = painter.pen()
                    painter.setPen(linePen)
                    painter.drawLine(QLine(0, y, rightEdge-1, y))
                    painter.setPen(penBackup)  # restore text pen

        painter.end()

    def doToolTip(self, event: QHelpEvent):
        assert isinstance(event, QHelpEvent)

        blame = self.model.currentBlame

        pos = event.globalPos()
        editLocalPos = self.codeView.mapFromGlobal(pos)
        textCursor = self.codeView.cursorForPosition(editLocalPos)
        lineNumber = 1 + textCursor.blockNumber()

        try:
            node = blame.lines[lineNumber].traceNode
        except IndexError:
            return False

        text = "<table style='white-space: pre'>"

        muted = mutedToolTipColorHex()
        colon = _(":")
        def newLine(heading, caption):
            return f"<tr><td style='color:{muted}; text-align: right;'>{heading}{colon} </td><td>{caption}</td>"

        commit = self.model.repo.peel_commit(node.commitId)
        text += newLine(_("commit"), shortHash(commit.id))
        text += newLine(_("author"), commit.author.name)
        text += newLine(_("date"), signatureDateFormat(commit.author, settings.prefs.shortTimeFormat))
        text += newLine(_("file name"), node.path)
        text += newLine(_("revision"), node.revisionNumber)

        text += "</table>"
        text += "<p>" + escape(commit.message.rstrip()).replace("\n", "<br>") + "</p>"

        QToolTip.showText(event.globalPos(), text, self)
        event.accept()
        return True
