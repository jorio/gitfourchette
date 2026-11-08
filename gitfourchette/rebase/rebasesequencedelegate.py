# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import math

from gitfourchette import settings, colors
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.rebase.rebasemodel import RebaseLine, RebaseOp, RebaseOpColors, RebaseOpLetters
from gitfourchette.rebase.rebasesequencemodel import RebaseSequenceModel
from gitfourchette.toolbox import shortHash, mixColors, lerp, stockIcon, isDarkTheme

_FallbackColor = QColor(Qt.GlobalColor.magenta)
_ColumnPadding = 8


class RebaseSequenceDelegate(QStyledItemDelegate):
    ignoreMouseOverState: bool

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ignoreMouseOverState = False
        self.textLeft = 0
        self.hoverPill = False
        self.lastPillWidth = 0

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        height = settings.prefs.calcRowHeight(option.fontMetrics)
        size = super().sizeHint(option, index)
        size.setHeight(height)
        return size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if self.ignoreMouseOverState:  # pragma: no cover - Always false in offscreen mode because startDrag returns immediately
            option.state &= ~QStyle.StateFlag.State_MouseOver

        widget = option.widget
        isActive = bool(option.state & QStyle.StateFlag.State_Active)
        isHovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        isSelected = bool(option.state & QStyle.StateFlag.State_Selected)
        colorGroup = QPalette.ColorGroup.Active if isActive else QPalette.ColorGroup.Inactive

        # Gather data from model
        item: RebaseLine = index.data(RebaseSequenceModel.RebaseLineRole)
        isDangling: bool = index.data(RebaseSequenceModel.RebaseDanglingRole)

        # Begin painting
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRect(option.rect)
        rect.adjust(2, 0, -2, 0)

        # Draw default background
        # Note: PySide6 crashes accessing widget.style() if it's a proxy style
        style = QApplication.style() if PYSIDE6 else widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, widget)

        # Draw pill
        blendOlder, blendNewer = self.pillBlending(index)
        self.drawPill(painter, rect, item.op, blendOlder, blendNewer,
                      hoverPill=self.hoverPill and isHovered)
        self.lastPillWidth = rect.left()
        rect.adjust(_ColumnPadding, 0, 0, 0)

        # Draw hash
        hcw = max(option.fontMetrics.horizontalAdvance(c) for c in "0123456789abcdef")
        charRect = QRect(rect.left(), rect.top(), hcw, rect.height())
        mutedRole = QPalette.ColorRole.HighlightedText if isSelected else QPalette.ColorRole.PlaceholderText
        mutedColor = option.palette.color(colorGroup, mutedRole)
        painter.setPen(mutedColor)
        for hashChar in shortHash(item.hexHash):
            painter.drawText(charRect, Qt.AlignmentFlag.AlignCenter, hashChar)
            charRect.translate(hcw, 0)
        rect.setLeft(charRect.left() + _ColumnPadding)
        self.textLeft = rect.left()

        # Figure out message text, message styling, and hint text
        messageRole = QPalette.ColorRole.HighlightedText if isSelected else QPalette.ColorRole.WindowText
        messageColor = option.palette.color(colorGroup, messageRole)
        messageFont = QFont(painter.font())
        message = item.displayMessage()
        hint = ""
        hintIcon = ""

        if item.verifiedEmpty:
            hint = _("empty commit")

        if item.op == RebaseOp.Drop:
            messageFont.setStrikeOut(True)
        elif item.op == RebaseOp.Fixup:
            # hint = _("message discarded by {fixup}", fixup="fixup")
            messageFont.setWeight(QFont.Weight.Light)
            messageColor = mutedColor
        elif item.op == RebaseOp.FakeStart:
            messageColor = mutedColor
            hintIcon = "action-unavailable"
        elif item.op.isEditable():
            if item.payload:
                hint = _("reworded")
            elif MACOS:  # pragma: no cover
                hint = _("double-click to reword")
            else:
                hint = _("double-click/{key} to reword", key="F2")

        if isDangling:
            hint = _("can’t {0} the starting commit!", item.op)
            hintIcon = "achtung"

        if hintIcon:
            icon = stockIcon(hintIcon)
            icon.paint(painter, QRect(rect.right() - 16, rect.top(), 16, rect.height()))
            rect.adjust(0, 0, -20, 0)

        # Draw hint if we've got enough room
        if hint and rect.width() > painter.fontMetrics().horizontalAdvance("M"*20):
            hintFont = QFont(painter.font())
            hintFont.setPointSize(round(hintFont.pointSize() * 90 / 100.0))
            hintFont.setBold(True)
            hintFont.setItalic(True)
            hintWidth = QFontMetricsF(hintFont).horizontalAdvance(hint)
            hintAlign = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            painter.setFont(hintFont)
            painter.setPen(mutedColor if isSelected or not isDangling else colors.red)
            painter.drawText(rect.adjusted(0, 0, -4, 0), hintAlign, hint)
            rect.adjust(0, 0, -int(hintWidth) - 8, 0)

        # Draw message
        message = painter.fontMetrics().elidedText(message, option.textElideMode, rect.width())
        painter.setPen(messageColor)
        painter.setFont(messageFont)
        painter.drawText(rect, option.displayAlignment, message)

        # Finish painting
        painter.restore()

    @staticmethod
    def drawPill(
            painter: QPainter,
            rect: QRect,
            op: RebaseOp,
            olderOp: RebaseOp | None = None,
            newerOp: RebaseOp | None = None,
            width: int = 0,
            meldingSeqNum: int = 0,
            hoverPill: bool = False,
    ):
        bottomUp = settings.prefs.rebaseBottomUp
        opAbove = newerOp if bottomUp else olderOp
        opBelow = olderOp if bottomUp else newerOp

        isNarrow = 0 < width <= 70
        isCramped = 0 < width <= 40

        font = QFont(painter.font())
        font.setBold(not isNarrow)

        vMargin = max(0, math.ceil((rect.height() - 16) / 4))  # Vertical margin
        rrRadius = rect.height() // 2
        if not width:
            width = QFontMetrics(font).horizontalAdvance("oooooi") + 2 * rrRadius
            width += 12  # make room for arrow

        textRect = QRectF(rect)
        textRect.adjust(0, vMargin, 0, -vMargin)
        textRect.setWidth(width)

        # Snap pill to pixel grid;
        # Extend pill beyond vertical bounds if connecting above and/or below
        pillRect = textRect.adjusted(
            .5,
            .5 - (vMargin+rrRadius if opAbove else 0),
            .5,
            -.5 + (vMargin+rrRadius if opBelow else 0))
        pillPath = QPainterPath()
        pillPath.addRoundedRect(pillRect, rrRadius, rrRadius)

        # Gradient
        colorText = QColor(Qt.GlobalColor.white)
        colorCenter = RebaseOpColors.get(op, _FallbackColor)
        colorAbove = RebaseOpColors.get(opAbove or op, _FallbackColor)
        colorBelow = RebaseOpColors.get(opBelow or op, _FallbackColor)
        colorAbove = mixColors(colorCenter, colorAbove)
        colorBelow = mixColors(colorCenter, colorBelow)

        if hoverPill:
            colorCenter = colorCenter.darker(120)

        gradientSpan = .2
        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom() + 1)
        gradient.setColorAt(0, colorAbove)
        gradient.setColorAt(gradientSpan, colorCenter)
        gradient.setColorAt(1-gradientSpan, colorCenter)
        gradient.setColorAt(1, colorBelow)

        # Op name
        # Add question mark if attempting to fixup nothing
        if op == RebaseOp.FakeStop:
            chevron = "🞂" if not MACOS else "▶"
            opText = chevron*3 if isNarrow else (_("stop") + " " + chevron*3)
        elif op == RebaseOp.FakeStart:
            opText = _("start")
        elif op == RebaseOp.FakeDone:
            opText = "\u2713"
        elif op == RebaseOp.FakeDoneRW:
            opText = "\u2713*"
        elif op == RebaseOp.FakeRewrite:
            opText = "*" + _("rewrite")
            font.setPointSize(min(8, font.pointSize()))
            font.setBold(False)
        else:
            opText = str(op) if not isCramped else RebaseOpLetters.get(op, op[0])

        if meldingSeqNum > 0 and op.isMelding():
            opText = f"{opText[:3]}\u2192{meldingSeqNum}"

        # Draw pill, or just the text for rewritten/done
        drawPillBackground = op not in {RebaseOp.FakeRewrite, RebaseOp.FakeDone, RebaseOp.FakeDoneRW}
        painter.save()
        painter.setFont(font)
        painter.setClipRect(rect)  # confine drawing to row
        if drawPillBackground:
            painter.fillPath(pillPath, gradient)
        else:
            painter.drawText(textRect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, opText)

        # Make room for arrow, if any
        textRectAdj = QRectF(textRect)
        if opAbove or opBelow:
            textRectAdj.adjust(0, 0, -14, 0)

        # Overlay text/arrows: first pass is shadow, second pass is white
        painter.translate(2, 2)
        for overlayPass in range(2 if drawPillBackground else 0):
            if overlayPass == 0:
                colorText = QColor(Qt.GlobalColor.black)
                colorText.setAlphaF(.3 if isDarkTheme() else .2)
            else:
                colorText = QColor(Qt.GlobalColor.white)
            painter.setPen(colorText)
            painter.translate(-1, -1)

            # Draw text
            painter.drawText(textRectAdj, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, opText)

            # Draw arrows from fixup/squash to concrete commit
            if not (opAbove or opBelow):
                continue

            lx = textRect.right() - 9.0   # line X
            cy = textRect.center().y() + 1
            ty = rect.top()
            by = rect.bottom()
            arrowBaseX = lx - 5.5
            arrowTipX = arrowBaseX - 4.5

            # Don't draw arrow if fixup/squash is first in the sequence
            drawArrowHere = not (opBelow if bottomUp else opAbove) and not op.isMelding()

            path = QPainterPath()
            if not drawArrowHere:
                # Straight line
                path.moveTo(lx, ty if opAbove else cy)
                path.lineTo(lx, by if opBelow else cy)
            else:
                # Curve
                curveStartY = ty if bottomUp else by
                path.moveTo(lx, curveStartY)
                path.lineTo(lx, lerp(curveStartY, cy, .33))
                path.cubicTo(lx, cy, arrowBaseX+1, cy, arrowBaseX+1, cy)

            # Fill arrow triangle, commit circle
            painter.setBrush(colorText)
            if drawArrowHere:
                painter.drawPolygon([  # type: ignore[call-overload]  # inaccurate stubs
                    QPointF(arrowBaseX, cy-4),
                    QPointF(arrowBaseX, cy+4),
                    QPointF(arrowTipX, cy)])
            elif op != RebaseOp.Drop:
                painter.drawEllipse(QPointF(lx, cy + .5), 2.5, 2.5)

            # Draw straight line or curve
            pen = QPen(colorText, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.BevelJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawPath(path)

        # Draw pill outline on top
        if drawPillBackground:
            painter.setPen(colorText)
            painter.drawPath(pillPath)

        painter.restore()

        rect.setLeft(round(textRect.right()))

    @staticmethod
    def pillBlending(index: QModelIndex) -> tuple[RebaseOp | None, RebaseOp | None]:
        connectOlder = False
        connectNewer = False
        olderOp: RebaseOp | None = None
        newerOp: RebaseOp | None = None

        model = index.model()
        assert isinstance(model, RebaseSequenceModel)
        startRow = model.flipRow(index.row())
        startOp = model.sequence[startRow].op

        if startOp.isFake():
            return olderOp, newerOp

        for row in range(startRow + 1, len(model.sequence)):
            op = model.sequence[row].op
            if op != RebaseOp.Drop:
                connectNewer |= op.isMelding()
                break

        if startOp.isMelding():
            connectOlder = True
        elif startOp == RebaseOp.Drop:
            connectOlder = connectNewer

        if connectOlder and startRow >= 1:
            olderOp = model.sequence[startRow - 1].op

        if connectNewer:
            assert startRow + 1 < len(model.sequence)
            newerOp = model.sequence[startRow + 1].op

        # Don't blend to older fake operation (i.e. "start")
        if olderOp and olderOp.isFake():
            olderOp = None

        # There are no situations where we might blend into a newer fake op
        if newerOp:
            assert not newerOp.isFake()

        return olderOp, newerOp

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget:
        editor = QLineEdit(parent)
        editor.setFrame(True)  # honored by Fusion but ignored by Breeze, hence some extra QSS to get a border anyway
        editor.setClearButtonEnabled(True)
        editor.setPlaceholderText(_("Leave blank to reset original message"))
        return editor

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        assert isinstance(editor, QLineEdit)

        leftOffset = self.textLeft - 2 - 2 - 2  # QSS border - QSS padding - QLineEdit internal padding
        rect = option.rect.adjusted(leftOffset, -1, 0, 1)

        # For very long lines, option.rect may extend beyond the viewport.
        # Clamp the QLineEdit to the right edge of the viewport.
        parent = self.parent()
        assert isinstance(parent, QAbstractScrollArea)
        rect.setRight(parent.viewport().width() - 2)

        editor.setGeometry(rect)

