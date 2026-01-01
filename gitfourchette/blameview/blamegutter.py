# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from gitfourchette import settings, colors
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.codeview.codegutter import CodeGutter
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
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
        if blame is None:
            return

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

        lastCaptionDrawnAtLine = -1
        hunkCommitId = None
        hunkStartLine = 1

        alignRight = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        topCommitId = blame.commitId
        topRevisionNumber = self.model.trace.revisionNumber(topCommitId)

        for block, top, bottom in self.paintBlocks(event, painter, lineColor):
            lineNumber = 1 + block.blockNumber()
            try:
                annotatedLine = blame.lines[lineNumber]
                lineCommitId = annotatedLine.commitId
            except IndexError:
                break

            if lineCommitId != hunkCommitId:
                hunkCommitId = lineCommitId
                hunkStartLine = lineNumber
                isCurrent = lineCommitId == topCommitId
                painter.setFont(self.boldFont if isCurrent else self.font())
                painter.setPen(boldTextPen if isCurrent else textPen)
                # Compute heat color
                revisionNumber = self.model.trace.revisionNumber(lineCommitId)
                heat = revisionNumber / topRevisionNumber
                heat = heat ** 2  # ease in cubic
                heatColor.setAlphaF(lerp(.0, .6, heat))

            # Fill heat rectangle
            heatTop = top if lastCaptionDrawnAtLine >= 0 else 0
            painter.fillRect(QRect(0, heatTop, rightEdge, bottom-heatTop), heatColor)

            # Draw line number
            lineNumL, lineNumW = self.columnMetrics[-1]
            painter.drawText(lineNumL, top, lineNumW, lh, alignRight, str(lineNumber))

            # Draw caption + separator line
            if lastCaptionDrawnAtLine < hunkStartLine:
                self.drawBlameCaption(lineCommitId, painter, top, lh)

                # Hunk separator line
                if lastCaptionDrawnAtLine > 0:
                    penBackup = painter.pen()
                    painter.setPen(linePen)
                    painter.drawLine(QLine(0, top, rightEdge-1, top))
                    painter.setPen(penBackup)  # restore text pen

                lastCaptionDrawnAtLine = lineNumber

        painter.end()

    def drawBlameCaption(self, commitId: Oid, painter: QPainter, top: int, lh: int):
        alignLeft = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        dateL, dateW = self.columnMetrics[0]
        nameL, nameW = self.columnMetrics[1]

        if commitId == UC_FAKEID:
            dateText = self.locale().toString(QDateTime.currentDateTime(), "yyyy-MM-dd")
            nameText = _("(Uncommitted)")
        else:
            commit = self.model.repo.peel_commit(commitId)
            sig = commit.author
            dateText = signatureDateFormat(sig, "yyyy-MM-dd", localTime=True)
            nameText = abbreviatePerson(sig, AuthorDisplayStyle.LastName)

        # Date
        FittedText.draw(painter, QRect(dateL, top, dateW, lh), alignLeft, dateText, bypassSetting=True)

        # Author
        FittedText.draw(painter, QRect(nameL, top, nameW, lh), alignLeft, nameText)

    def doToolTip(self, event: QHelpEvent):
        assert isinstance(event, QHelpEvent)

        pos = event.globalPos()
        editLocalPos = self.codeView.mapFromGlobal(pos)
        textCursor = self.codeView.cursorForPosition(editLocalPos)
        lineNumber = 1 + textCursor.blockNumber()

        try:
            commitId = self.model.currentBlame.lines[lineNumber].commitId
            node = self.model.trace.nodeForCommit(commitId)
        except IndexError:
            return False

        text = "<table style='white-space: pre'>"

        muted = mutedToolTipColorHex()
        colon = _(":")
        def newLine(heading, caption):
            return f"<tr><td style='color:{muted}; text-align: right;'>{heading}{colon} </td><td>{caption}</td>"

        isWorkdir = commitId == UC_FAKEID
        if isWorkdir:
            text += newLine(_("commit"), _("Not Committed Yet"))
        else:
            commit = self.model.repo.peel_commit(commitId)
            text += newLine(_("commit"), shortHash(commitId))
            text += newLine(_("author"), commit.author.name)
            text += newLine(_("date"), signatureDateFormat(commit.author, settings.prefs.shortTimeFormat, localTime=False))
        text += newLine(_("file name"), node.path)
        text += newLine(_("revision"), self.model.trace.revisionNumber(commitId))
        text += "</table>"
        if not isWorkdir:
            text += "<p>" + escape(commit.message.rstrip()).replace("\n", "<br>") + "</p>"

        QToolTip.showText(event.globalPos(), text, self)
        event.accept()
        return True
