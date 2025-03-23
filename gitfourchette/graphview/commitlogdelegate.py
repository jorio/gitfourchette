# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import math
import traceback
from contextlib import suppress
from dataclasses import dataclass

from gitfourchette import settings
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow, CommitToolTipZone
from gitfourchette.graphview.graphpaint import paintGraphFrame
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.toolbox import *


@dataclass
class RefBox:
    prefix: str
    icon: str
    color: QColor
    keepPrefix: bool = False


REFBOXES = [
    RefBox("refs/remotes/", "git-remote", QColor(Qt.GlobalColor.darkCyan)),
    RefBox("refs/tags/", "git-tag", QColor(Qt.GlobalColor.darkYellow)),
    RefBox("refs/heads/", "git-branch", QColor(Qt.GlobalColor.darkMagenta)),

    # detached HEAD as returned by Repo.map_commits_to_refs
    RefBox("HEAD", "git-head-detached", QColor(Qt.GlobalColor.darkRed), keepPrefix=True),

    # Fallback
    RefBox("", "hint", QColor(Qt.GlobalColor.gray), keepPrefix=True)
]


ELISION = " […]"
ELISION_LENGTH = len(ELISION)


MAX_AUTHOR_CHARS = {
    AuthorDisplayStyle.Initials: 7,
    AuthorDisplayStyle.FullName: 20,
    AuthorDisplayStyle.FullEmail: 24,
}


XMARGIN = 4
XSPACING = 6

NARROW_WIDTH = (500, 750)


class CommitLogDelegate(QStyledItemDelegate):
    def __init__(self, repoWidget, parent=None):
        super().__init__(parent)

        self.repoWidget = repoWidget

        self.mustRefreshMetrics = True
        self.hashCharWidth = 0
        self.dateMaxWidth = 0
        self.activeCommitFont = QFont()
        self.uncommittedFont = QFont()
        self.refboxFont = QFont()
        self.homeRefboxFont = QFont()

    def invalidateMetrics(self):
        self.mustRefreshMetrics = True

    def refreshMetrics(self, option: QStyleOptionViewItem):
        if not self.mustRefreshMetrics:
            return

        self.mustRefreshMetrics = False

        self.hashCharWidth = max(option.fontMetrics.horizontalAdvance(c) for c in "0123456789abcdef")

        self.activeCommitFont = QFont(option.font)
        self.activeCommitFont.setBold(True)

        self.uncommittedFont = QFont(option.font)
        self.uncommittedFont.setItalic(True)

        self.refboxFont = QFont(option.font)

        self.homeRefboxFont = QFont(self.refboxFont)
        self.homeRefboxFont.setWeight(QFont.Weight.Bold)

        wideDate = QDateTime.fromString("2999-12-25T23:59:59.999", Qt.DateFormat.ISODate)
        dateText = option.locale.toString(wideDate, settings.prefs.shortTimeFormat)
        if settings.prefs.authorDiffAsterisk:
            dateText += "*"
        self.dateMaxWidth = QFontMetrics(self.activeCommitFont).horizontalAdvance(dateText + " ")
        self.dateMaxWidth = int(self.dateMaxWidth)  # make sure it's an int for pyqt5 compat

    @property
    def repoModel(self) -> RepoModel:
        return self.repoWidget.repoModel

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(painter, option, index)
        except Exception as exc:  # pragma: no cover
            painter.restore()
            painter.save()
            self._paintError(painter, option, index, exc)
        painter.restore()

    def _paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        toolTips: list[CommitToolTipZone] = []

        hasFocus = option.state & QStyle.StateFlag.State_HasFocus
        isSelected = option.state & QStyle.StateFlag.State_Selected
        style = option.widget.style()
        palette: QPalette = option.palette
        outlineColor = palette.color(QPalette.ColorRole.Base)
        colorGroup = QPalette.ColorGroup.Normal if hasFocus else QPalette.ColorGroup.Inactive

        # Draw default background
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)

        if isSelected:
            painter.setPen(palette.color(colorGroup, QPalette.ColorRole.HighlightedText))

        # Get metrics of '0' before setting a custom font,
        # so that alignments are consistent in all commits regardless of bold or italic.
        self.refreshMetrics(option)
        hcw = self.hashCharWidth

        # Set up rect
        rect = QRect(option.rect)
        rect.setLeft(rect.left() + XMARGIN)
        rect.setRight(rect.right() - XMARGIN)

        # Compute column bounds
        authorWidth = hcw * MAX_AUTHOR_CHARS.get(settings.prefs.authorDisplayStyle, 16)
        dateWidth = self.dateMaxWidth
        if rect.width() < NARROW_WIDTH[0]:
            authorWidth = 0
            dateWidth = 0
        elif rect.width() <= NARROW_WIDTH[1]:
            authorWidth = int(lerp(authorWidth/2, authorWidth, rect.width(), NARROW_WIDTH[0], NARROW_WIDTH[1]))
        leftBoundHash = rect.left()
        leftBoundSummary = leftBoundHash + hcw * settings.prefs.shortHashChars + XSPACING
        leftBoundDate = rect.width() - dateWidth
        leftBoundName = leftBoundDate - authorWidth
        rightBound = rect.right()

        # Get the info we need about the commit
        commit: Commit | None = index.data(CommitLogModel.Role.Commit)
        if commit and commit.id != UC_FAKEID:
            oid = commit.id
            author = commit.author
            committer = commit.committer

            summaryText, contd = messageSummary(commit.message, ELISION)
            hashText = shortHash(commit.id)
            authorText = abbreviatePerson(author, settings.prefs.authorDisplayStyle)

            qdt = QDateTime.fromSecsSinceEpoch(author.time)
            dateText = option.locale.toString(qdt, settings.prefs.shortTimeFormat)

            if settings.prefs.authorDiffAsterisk:
                if author.email != committer.email:
                    authorText += "*"
                if author.time != committer.time:
                    dateText += "*"

            if self.repoModel.headCommitId == commit.id:
                painter.setFont(self.activeCommitFont)

            searchBar: SearchBar = self.parent().searchBar
            searchTerm: str = searchBar.searchTerm
            searchTermLooksLikeHash: bool = searchBar.searchTermLooksLikeHash

            if not searchBar.isVisible():
                searchTerm = ""
        else:
            commit = None
            oid = None
            hashText = "·" * settings.prefs.shortHashChars
            authorText = ""
            dateText = ""
            searchTerm = ""
            searchTermLooksLikeHash = False
            painter.setFont(self.uncommittedFont)

            specialRowKind: SpecialRow = index.data(CommitLogModel.Role.SpecialRow)

            if specialRowKind == SpecialRow.UncommittedChanges:
                oid = UC_FAKEID
                summaryText = _("Working Directory")
                # Append change count if available
                numChanges = self.repoModel.numUncommittedChanges
                if numChanges == 0:
                    summaryText += " " + _("(Clean)")
                elif numChanges > 0:
                    summaryText += " " + _n("({n} change)", "({n} changes)", numChanges)
                # Append draft message if any
                draftMessage = self.repoModel.prefs.draftCommitMessage
                if draftMessage:
                    draftMessage = messageSummary(draftMessage)[0].strip()
                    draftIntro = _("Commit draft:")
                    summaryText += f" – {draftIntro} {tquo(draftMessage)}"

            elif specialRowKind == SpecialRow.TruncatedHistory:
                if self.repoModel.prefs.hiddenRefPatterns:
                    summaryText = _("History truncated to {0} commits (including hidden branches)")
                else:
                    summaryText = _("History truncated to {0} commits")
                summaryText = summaryText.format(option.widget.locale().toString(self.repoModel.numRealCommits))

            elif specialRowKind == SpecialRow.EndOfShallowHistory:
                summaryText = _("Shallow clone – End of commit history")

            else:  # pragma: no cover
                summaryText = f"*** Unsupported special row {specialRowKind}"

        # Get metrics now so the message gets elided according to the custom font style
        # that may have been just set for this commit.
        metrics: QFontMetrics = painter.fontMetrics()

        def elide(text):
            return metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())

        def highlight(fullText: str, needlePos: int, needleLen: int):
            SearchBar.highlightNeedle(painter, rect, fullText, needlePos, needleLen)

        # ------ Hash
        charRect = QRect(leftBoundHash, rect.top(), hcw, rect.height())
        painter.save()
        if not isSelected:  # use muted color for hash if not selected
            painter.setPen(palette.color(colorGroup, QPalette.ColorRole.PlaceholderText))
        for hashChar in hashText:
            painter.drawText(charRect, Qt.AlignmentFlag.AlignCenter, hashChar)
            charRect.translate(hcw, 0)
        painter.restore()

        # ------ Highlight searched hash
        if searchTerm and searchTermLooksLikeHash and commit and str(commit).startswith(searchTerm):
            x1 = 0
            x2 = min(len(hashText), len(searchTerm)) * hcw
            SearchBar.highlightNeedle(painter, rect, hashText, 0, len(searchTerm), x1, x2)

        # ------ Graph
        rect.setLeft(leftBoundSummary)
        if oid is not None:
            paintGraphFrame(self.repoModel, oid, painter, rect, outlineColor)
            rect.setLeft(rect.right())

        # ------ Set refbox/message area rect
        if oid is not None and oid != UC_FAKEID:
            rect.setRight(leftBoundName - XMARGIN)
        else:
            rect.setRight(rightBound)

        # ------ Refboxes
        refsHere = self.repoModel.refsAt.get(oid, None)
        if refsHere:
            homeBranch = RefPrefix.HEADS + self.repoModel.homeBranch
            painter.save()
            painter.setClipRect(rect)
            maxRefboxX = painter.clipBoundingRect().right()
            darkRefbox = painter.pen().color().lightnessF() > .5
            for refName in refsHere:
                if refName in self.repoModel.hiddenRefs:  # skip refboxes for hidden refs
                    continue
                x1 = rect.left()
                self._paintRefbox(painter, rect, refName, refName == homeBranch, darkRefbox)
                x2 = rect.left()
                toolTips.append(CommitToolTipZone(x1, x2, "ref", refName))
                if x2 >= maxRefboxX:
                    break
            painter.restore()

        # ------ Icons
        if oid == UC_FAKEID:
            r = QRect(rect)
            r.setWidth(min(16, r.height()))
            icon = stockIcon("git-workdir")
            iconMode = QIcon.Mode.Normal
            if isSelected:
                iconMode = QIcon.Mode.Selected if hasFocus else QIcon.Mode.SelectedInactive
            icon.paint(painter, r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, mode=iconMode)
            rect.setLeft(r.right() + 4)

        # ------ Message
        # use muted color for foreign commit messages if not selected
        if not isSelected and commit and commit.id in self.repoModel.foreignCommits:
            painter.setPen(Qt.GlobalColor.gray)

        elidedSummaryText = elide(summaryText)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, elidedSummaryText)

        if len(elidedSummaryText) == 0 or elidedSummaryText.endswith(("…", ELISION)):
            toolTips.append(CommitToolTipZone(rect.left(), rect.right(), "message"))

        # ------ Highlight search term
        if searchTerm and commit and searchTerm in commit.message.lower():
            needlePos = summaryText.lower().find(searchTerm)
            if needlePos < 0:
                needlePos = len(summaryText) - ELISION_LENGTH
                needleLen = ELISION_LENGTH
            else:
                needleLen = len(searchTerm)
            highlight(summaryText, needlePos, needleLen)

        # ------ Author
        if authorWidth != 0:
            rect.setLeft(leftBoundName)
            rect.setRight(leftBoundDate - XMARGIN)
            FittedText.draw(painter, rect, Qt.AlignmentFlag.AlignVCenter, authorText, minStretch=QFont.Stretch.ExtraCondensed)

        # ------ Highlight searched author
        if searchTerm and commit:
            needlePos = authorText.lower().find(searchTerm)
            if needlePos >= 0:
                highlight(authorText, needlePos, len(searchTerm))

        # ------ Date
        if dateWidth != 0:
            rect.setLeft(leftBoundDate)
            rect.setRight(rightBound)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, elide(dateText))

        if authorWidth != 0 or dateWidth != 0:
            toolTips.append(CommitToolTipZone(leftBoundName, rightBound, "author"))

        # ----------------

        # Tooltip metrics
        model = index.model()
        model.setData(index, leftBoundName if authorWidth != 0 else -1, CommitLogModel.Role.AuthorColumnX)
        model.setData(index, toolTips, CommitLogModel.Role.ToolTipZones)

    def _paintRefbox(self, painter: QPainter, rect: QRect, refName: str, isHome: bool, dark: bool):
        if refName == 'HEAD' and not self.repoModel.headIsDetached:
            return

        refboxDef = next(d for d in REFBOXES if refName.startswith(d.prefix))

        if not refboxDef.keepPrefix:
            text = refName.removeprefix(refboxDef.prefix)
        else:
            text = refName
        color = refboxDef.color
        bgColor = QColor(color)
        iconName = refboxDef.icon

        # Omit remote name if there's a single remote
        if refboxDef.prefix == RefPrefix.REMOTES and len(self.repoModel.remotes) == 1:
            text = text.split('/', 1)[-1]

        if dark:
            color = color.lighter(300)
            bgColor.setAlphaF(.5)
        else:
            bgColor.setAlphaF(.066)

        if isHome:
            font = self.homeRefboxFont
            iconName = "git-head"
        elif refName == 'HEAD' and self.repoModel.headIsDetached:
            text = _("Detached HEAD")
            font = self.homeRefboxFont
        else:
            font = self.refboxFont

        painter.setFont(font)
        painter.setPen(color)

        hPadding = 3
        vMargin = max(0, math.ceil((rect.height() - 16) / 4))

        if iconName:
            iconRect = QRect(rect)
            iconRect.adjust(hPadding, vMargin, 0, -vMargin)
            iconSize = min(16, iconRect.height())
            iconRect.setWidth(iconSize)
        else:
            iconSize = 0

        maxWidth = settings.prefs.refBoxMaxWidth
        if maxWidth != 0:
            text, fittedFont, textWidth = FittedText.fit(
                font, maxWidth, text, Qt.TextElideMode.ElideMiddle, limit=QFont.Stretch.Condensed)
        else:
            textWidth = -hPadding

        boxRect = QRect(rect)
        boxRect.setWidth(hPadding + iconSize + 2 + textWidth + hPadding)

        frameRect = QRectF(boxRect)
        frameRect.adjust(.5, vMargin + .5, .5, -(vMargin + .5))

        framePath = QPainterPath()
        framePath.addRoundedRect(frameRect, 4, 4)
        painter.fillPath(framePath, bgColor)
        painter.drawPath(framePath)

        if iconName:
            icon = stockIcon(iconName, f"gray={color.name()}")
            icon.paint(painter, iconRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if textWidth > 0:
            textRect = QRect(boxRect)
            textRect.adjust(0, 0, -hPadding, 0)
            painter.setFont(fittedFont)
            painter.drawText(textRect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            painter.setFont(font)

        # Advance caller rectangle
        rect.setLeft(boxRect.right() + 6)

    def _paintError(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, exc: BaseException):  # pragma: no cover
        """Last-resort row drawing routine used if _paint raises an exception."""

        # We want this to fail in unit tests.
        from gitfourchette.settings import TEST_MODE
        if TEST_MODE:
            raise exc

        text = "?" * 7
        with suppress(BaseException):
            commit: Commit = index.data(CommitLogModel.Role.Commit)
            text = str(commit.id)[:7]
        with suppress(BaseException):
            details = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
            text += " " + shortenTracebackPath(details[-2].splitlines(False)[0]) + ":: " + repr(exc)

        if option.state & QStyle.StateFlag.State_Selected:
            bg, fg = QColor(Qt.GlobalColor.red), QColor(Qt.GlobalColor.white)
        else:
            bg, fg = option.palette.color(QPalette.ColorRole.Base), QColor(Qt.GlobalColor.red)

        painter.fillRect(option.rect, bg)
        painter.setPen(fg)
        painter.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.SmallestReadableFont))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignVCenter, text)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        mult = settings.prefs.graphRowHeight
        r = super().sizeHint(option, index)
        r.setHeight(option.fontMetrics.height() * mult // 100)
        return r
