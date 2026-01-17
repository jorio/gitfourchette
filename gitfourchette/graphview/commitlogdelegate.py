# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import math
import traceback
from contextlib import suppress
from dataclasses import dataclass

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow, CommitToolTipZone
from gitfourchette.graphview.graphpaint import paintGraphFrame
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, UC_FAKEREF, RepoModel, GpgStatus
from gitfourchette.toolbox import *


@dataclass
class RefBox:
    prefix: str
    icon: str
    color: QColor
    keepPrefix: bool = False


REFBOXES = [
    RefBox(RefPrefix.REMOTES, "git-remote", QColor(Qt.GlobalColor.darkCyan)),
    RefBox(RefPrefix.TAGS, "git-tag", QColor(Qt.GlobalColor.darkYellow)),
    RefBox(RefPrefix.HEADS, "git-branch", QColor(Qt.GlobalColor.darkMagenta)),

    # detached HEAD as returned by Repo.map_commits_to_refs
    RefBox("HEAD", "git-head-detached", QColor(Qt.GlobalColor.darkRed), keepPrefix=True),

    # Working Directory
    RefBox(UC_FAKEREF, "git-workdir", QColor("#808080")),

    # Mounted
    RefBox("FAKEREF_FUSEMOUNT", "git-mount", QColor(Qt.GlobalColor.gray)),

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
    requestSignatureVerification = Signal(Oid)

    def __init__(self, repoModel: RepoModel, searchBar: SearchBar | None=None, parent: QWidget | None=None):
        super().__init__(parent)

        self.repoModel = repoModel
        self.searchBar = searchBar

        self.mustRefreshMetrics = True
        self.hashCharWidth = 0
        self.dateMaxWidth = 0
        self.authorMaxWidth = 0
        self.activeCommitFont = QFont()
        self.uncommittedFont = QFont()
        self.refboxFont = QFont()
        self.homeRefboxFont = QFont()

        self.mounts = GFApplication.instance().mountManager

    def prepareForDeletion(self):
        del self.repoModel
        del self.searchBar
        del self.mounts

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

        self.authorMaxWidth = self.hashCharWidth * MAX_AUTHOR_CHARS.get(settings.prefs.authorDisplayStyle, 16)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, fillBackground=True):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(painter, option, index, fillBackground)
        except Exception as exc:  # pragma: no cover
            painter.restore()
            painter.save()
            self._paintError(painter, option, index, exc)
        painter.restore()

    def _paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, fillBackground: bool):
        assert index.isValid()

        toolTips: list[CommitToolTipZone] = []

        hasFocus = option.state & QStyle.StateFlag.State_HasFocus
        isSelected = option.state & QStyle.StateFlag.State_Selected
        palette: QPalette = option.palette
        colorGroup = QPalette.ColorGroup.Normal if hasFocus else QPalette.ColorGroup.Inactive

        # Draw default background
        if fillBackground:
            style = option.widget.style()
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
        authorWidth = self.authorMaxWidth
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
        gpgStatus = GpgStatus.Unsigned
        if commit and commit.id != UC_FAKEID:
            oid = commit.id
            author = commit.author
            committer = commit.committer

            summaryText, contd = messageSummary(commit.message, ELISION)
            hashText = shortHash(oid)
            authorText = abbreviatePerson(author, settings.prefs.authorDisplayStyle)
            dateText = signatureDateFormat(author, settings.prefs.shortTimeFormat, localTime=True)
            gpgStatus, _gpgKeyInfo = self.repoModel.getCachedGpgStatus(commit)

            if gpgStatus == GpgStatus.Pending and settings.prefs.verifyGpgOnTheFly:
                self.requestSignatureVerification.emit(oid)

            if settings.prefs.authorDiffAsterisk:
                if author.email != committer.email:
                    authorText += "*"
                if author.time != committer.time:
                    dateText += "*"

            if self.searchBar:
                searchTerm: str = self.searchBar.searchTerm
                searchTermLooksLikeHash: bool = self.searchBar.searchTermLooksLikeHash
                if not self.searchBar.isVisible():
                    searchTerm = ""
            else:
                searchTerm = ""
                searchTermLooksLikeHash = False
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
                summaryText = self.uncommittedChangesMessage()

            elif specialRowKind == SpecialRow.TruncatedHistory:
                if self.repoModel.hiddenCommits and self.repoModel.hiddenRefs:
                    summaryText = _("History truncated to {0} commits (including hidden branches)")
                else:
                    summaryText = _("History truncated to {0} commits")
                summaryText = summaryText.format(option.widget.locale().toString(self.repoModel.numRealCommits))

            elif specialRowKind == SpecialRow.EndOfShallowHistory:
                summaryText = _("Shallow clone – End of commit history")

            else:  # pragma: no cover
                summaryText = f"*** Unsupported special row {specialRowKind}"

        if self.isBold(oid):
            painter.setFont(self.activeCommitFont)

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

        # ------ Set private/message area rect
        rect.setLeft(leftBoundSummary)
        if oid is not None and oid != UC_FAKEID:
            rect.setRight(leftBoundName - XMARGIN)
        else:
            rect.setRight(rightBound)

        # ------ Private
        self.paintPrivate(painter, option, rect, oid, toolTips)

        # ------ Message
        # use muted color for foreign commit messages if not selected
        if not isSelected and self.isDim(oid):
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

            # Draw seal for signed commits
            if gpgStatus > GpgStatus.Pending or (settings.prefs.verifyGpgOnTheFly and gpgStatus >= GpgStatus.Pending):
                rect.setRight(leftBoundName + 16)
                icon = stockIcon(gpgStatus.iconName())
                icon.paint(painter, rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                rect.setLeft(rect.right() + 4)

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
        # Block model signals to update it - otherwise QComboBox will constantly redraw itself
        model = index.model()
        with QSignalBlockerContext(model):
            model.setData(index, leftBoundName if authorWidth != 0 else -1, CommitLogModel.Role.AuthorColumnX)
            model.setData(index, toolTips, CommitLogModel.Role.ToolTipZones)

    def _paintRefboxes(self, painter: QPainter, rect: QRect, refs: list[str], toolTips: list[CommitToolTipZone]):
        repoModel = self.repoModel
        homeBranch = RefPrefix.HEADS + repoModel.homeBranch
        xMax = painter.clipBoundingRect().right()

        # Group refs in clusters (branches with same upstream)
        clusters = {}
        nonLooseRefs = set()
        for refName in refs:
            # Skip refboxes for hidden refs
            if refName in repoModel.hiddenRefs:
                continue

            # Look for local branches
            if not refName.startswith(RefPrefix.HEADS):
                continue
            localName = refName.removeprefix(RefPrefix.HEADS)

            # Find the upstream for this local branch
            try:
                upstreamShorthand = repoModel.upstreams[localName]
                assert not upstreamShorthand.startswith(RefPrefix.REMOTES)
                upstreamRef = RefPrefix.REMOTES + upstreamShorthand
            except KeyError:
                continue

            # Don't create a cluster if the upstream isn't on the same row
            if upstreamRef not in refs:
                continue

            # Don't create a cluster if the upstream is hidden
            if upstreamRef in repoModel.hiddenRefs:
                continue

            # Append to the cluster
            try:
                clusters[upstreamRef].append(refName)
            except KeyError:
                clusters[upstreamRef] = [refName]

            nonLooseRefs.add(upstreamRef)
            nonLooseRefs.add(refName)

        # Draw clusters first
        for upstreamRef, localRefList in clusters.items():
            # See if we can omit the name of the remote branch
            if repoModel.singleRemote and len(localRefList) == 1:
                assert upstreamRef.startswith(RefPrefix.REMOTES)
                upstreamShorthand = upstreamRef.removeprefix(RefPrefix.REMOTES)
                remoteName, remoteBranchName = split_remote_branch_shorthand(upstreamShorthand)
                _localBranchPrefix, localBranchName = RefPrefix.split(localRefList[0])
                omitRemoteName = remoteBranchName == localBranchName
            else:
                omitRemoteName = False

            # Draw local branches
            for i, localRef in enumerate(localRefList):
                self._paintRefbox(painter, rect, toolTips, localRef,
                                  clipLeft=i != 0, clipRight=True, isHome=localRef == homeBranch)

            # Draw upstream at end of cluster
            self._paintRefbox(painter, rect, toolTips, upstreamRef, clipLeft=True, forceOmitName=omitRemoteName)

            if rect.left() >= xMax:
                return

        # Draw loose refs
        for refName in refs:
            # Skip refboxes for hidden refs (except tags and special refs)
            if (refName in repoModel.hiddenRefs
                    and refName.startswith("refs/")
                    and not refName.startswith(RefPrefix.TAGS)):
                continue

            # Skip clustered refs we've drawn above
            if refName in nonLooseRefs:
                continue

            self._paintRefbox(painter, rect, toolTips, refName, isHome=refName == homeBranch)

            if rect.left() >= xMax:
                return

    def _paintRefbox(
            self,
            painter: QPainter,
            rect: QRect,
            toolTips: list[CommitToolTipZone],
            refName: str,
            isHome: bool = False,
            clipLeft: bool = False,
            clipRight: bool = False,
            forceOmitName: bool = False,
    ):
        if refName == 'HEAD' and not self.repoModel.headIsDetached:
            return

        refboxDef = next(d for d in REFBOXES if refName.startswith(d.prefix))

        if forceOmitName:
            text = ""
        # elif refName == UC_FAKEREF:
        #     text = _("Working Directory")
        elif not refboxDef.keepPrefix:
            text = refName.removeprefix(refboxDef.prefix)
        else:
            text = refName
        color = refboxDef.color
        bgColor = QColor(color)
        iconName = refboxDef.icon

        # Omit remote name if there's a single remote
        if refboxDef.prefix == RefPrefix.REMOTES and self.repoModel.singleRemote:
            text = text.split('/', 1)[-1]

        dark = painter.pen().color().lightnessF() > .5
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

        rrRadius = 4  # Rounded Rectangle radius
        lPadding = 3  # Left padding
        rPadding = 4  # Right padding
        vMargin = max(0, math.ceil((rect.height() - 16) / 4))  # Vertical margin

        maxWidth = settings.prefs.refBoxMaxWidth
        if text and maxWidth != 0:
            text, fittedFont, textWidth = FittedText.fit(
                font, maxWidth, text, Qt.TextElideMode.ElideMiddle, limit=QFont.Stretch.Condensed)
        else:
            textWidth = -rPadding  # Negate rPadding

        lClip = 0
        rClip = 0
        if clipLeft:
            lPadding = 2 * lPadding
            lClip = rrRadius
        if clipRight:
            rPadding = 2 * rPadding + 2
            rClip = rrRadius

        if iconName:
            iconRect = QRect(rect)
            iconRect.adjust(lPadding, vMargin, 0, -vMargin)
            iconSize = min(16, iconRect.height())
            iconRect.setWidth(iconSize)
            iconPadding = 2
        else:
            iconSize = 0
            iconPadding = 0

        boxRect = QRect(rect)
        boxRect.setWidth(lPadding + iconSize + iconPadding + textWidth + rPadding)

        frameRect = QRectF(boxRect)
        frameRect.adjust(0, vMargin, 0, -vMargin)
        frameRect.adjust(-lClip, 0, 0, 0)
        clipBox = frameRect.adjusted(lClip, 0, -rClip+1, 0)

        if lClip or rClip:
            painter.save()
            painter.setClipRect(clipBox)

        framePath = QPainterPath()
        framePath.addRoundedRect(frameRect.adjusted(.5, .5, .5, -.5),  # Snap to pixel grid
                                 rrRadius, rrRadius)

        painter.drawPath(framePath)
        painter.fillPath(framePath, bgColor)

        if iconName:
            icon = stockIcon(iconName, f"gray={color.name()}")
            icon.paint(painter, iconRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if text and textWidth > 0:
            textRect = QRect(boxRect)
            textRect.adjust(0, 0, -rPadding, 0)
            painter.setFont(fittedFont)
            painter.drawText(textRect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            painter.setFont(font)

        # Reset clip rect
        if lClip or rClip:
            painter.restore()

        # Draw divider line
        if lClip:
            x  =  .5 + clipBox.left()
            yt =  .5 + frameRect.top()
            yb = -.5 + frameRect.bottom()
            ym =  .5 + int((yt+yb)/2)
            if rClip:
                painter.drawLine(QLineF(x, yt, x, yb))
            else:
                painter.drawLines([QLineF(x, yt, x, ym-3),
                                   QLineF(x, ym+3, x, yb),
                                   QLineF(x-2, ym-1, x+2, ym-1),
                                   QLineF(x-2, ym+1, x+2, ym+1)])

        # Append tooltip
        refToolTip = CommitToolTipZone(rect.left(), boxRect.right(), "ref", refName)
        toolTips.append(refToolTip)

        # Advance caller rectangle
        rect.setLeft(round(clipBox.right()) + (6 if not rClip else 0))

    def _paintError(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, exc: BaseException):  # pragma: no cover
        """Last-resort row drawing routine used if _paint raises an exception."""

        # We want this to fail in unit tests.
        if APP_TESTMODE:
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

    def isBold(self, oid: Oid) -> bool:
        """ Can be overridden """
        return oid != NULL_OID and oid == self.repoModel.headCommitId

    def isDim(self, oid: Oid):
        """ Can be overridden """
        return oid != NULL_OID and oid in self.repoModel.foreignCommits

    def uncommittedChangesMessage(self) -> str:
        """ Can be overridden """
        summaryText = _("Working Directory") + " "
        # Append change count if available
        numChanges = self.repoModel.numUncommittedChanges
        if numChanges == 0:
            summaryText += _("(Clean)")
        elif numChanges > 0:
            summaryText += _n("({n} change)", "({n} changes)", numChanges)
        # Append draft message if any
        draftMessage = self.repoModel.prefs.draftCommitMessage
        if draftMessage:
            draftMessage = messageSummary(draftMessage)[0].strip()
            draftIntro = _("Commit draft:")
            summaryText += f" – {draftIntro} {tquo(draftMessage)}"
        return summaryText

    def paintPrivate(
            self,
            painter: QPainter,
            option: QStyleOptionViewItem,
            rect: QRect,
            oid: Oid,
            toolTips: list[CommitToolTipZone]
    ):
        """
        Draw widget-specific information inbetween the commit hash and message.
        By default, draws the graph and refboxes. Can be overridden.
        """

        # ------ Graph
        if oid is not None:
            graphRect = QRect(rect)
            paintGraphFrame(painter, graphRect, oid, self.repoModel.graph, self.repoModel.hiddenCommits)
            rect.setLeft(graphRect.right())

        # ------ Mount icon
        if self.mounts.isMounted(oid):
            painter.save()
            self._paintRefbox(painter, rect, toolTips, "FAKEREF_FUSEMOUNT", forceOmitName=True)
            toolTips[-1].data = _("This commit is currently mounted as a folder.")
            painter.restore()

        # ------ Refboxes
        refsHere = self.repoModel.refsAt.get(oid, None)
        if refsHere:
            painter.save()
            painter.setClipRect(rect)
            self._paintRefboxes(painter, rect, refsHere, toolTips)
            painter.restore()
