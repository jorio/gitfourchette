# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from dataclasses import dataclass
from typing import Literal

from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, RepoModel, GpgStatus
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables


@dataclass
class CommitToolTipZone:
    left: int
    right: int
    kind: Literal['ref', 'author', 'message', 'pinSource', 'pinTarget']
    data: str = ""


class SpecialRow(enum.IntEnum):
    Invalid = 0
    UncommittedChanges = enum.auto()
    Commit = enum.auto()
    TruncatedHistory = enum.auto()
    EndOfShallowHistory = enum.auto()


class CommitLogModel(QAbstractListModel):
    ToolTipCacheSize = 150
    """ Number of rows to keep track of for ToolTipZones """

    class Role:
        Commit          = Qt.ItemDataRole.UserRole + 0
        Oid             = Qt.ItemDataRole.UserRole + 1
        ToolTipZones    = Qt.ItemDataRole.UserRole + 2
        AuthorColumnX   = Qt.ItemDataRole.UserRole + 3
        SpecialRow      = Qt.ItemDataRole.UserRole + 4
        BlameRevision   = Qt.ItemDataRole.UserRole + 5  # for BlameScrubber

    repoModel: RepoModel
    _extraRow: SpecialRow
    _authorColumnX: int
    _toolTipZones: dict[int, list[CommitToolTipZone]]

    def __init__(self, repoModel: RepoModel, parent: QWidget):
        super().__init__(parent)

        self.repoModel = repoModel
        self._authorColumnX = -1
        self._toolTipZones = {}

        if repoModel.truncatedHistory:
            self._extraRow = SpecialRow.TruncatedHistory
        elif repoModel.repo.is_shallow:
            self._extraRow = SpecialRow.EndOfShallowHistory
        else:
            self._extraRow = SpecialRow.Invalid

    def resetCommitSequence(self, nRemovedRows: int = -1, nAddedRows: int = 0):
        if nRemovedRows < 0:
            # Replace log wholesale
            self.beginResetModel()
            self.endResetModel()
            return

        parent = QModelIndex_default  # it's not a tree model so there's no parent

        # DON'T interleave beginRemoveRows/beginInsertRows!
        # It'll crash with QSortFilterProxyModel!
        if nRemovedRows != 0:
            self.beginRemoveRows(parent, 0, nRemovedRows)
            self.endRemoveRows()

        if nAddedRows != 0:
            self.beginInsertRows(parent, 0, nAddedRows)
            self.endInsertRows()

    def rowCount(self, *args, **kwargs) -> int:
        n = len(self.repoModel.commitSequence)
        if self._extraRow != SpecialRow.Invalid:
            n += 1
        return n

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        row = index.row()

        if role == Qt.ItemDataRole.DisplayRole:
            return None

        elif role == CommitLogModel.Role.Commit:
            try:
                return self.repoModel.commitSequence[row]
            except IndexError:
                pass

        elif role == CommitLogModel.Role.Oid:
            try:
                commit = self.repoModel.commitSequence[row]
                if commit is not None:
                    return commit.id
            except IndexError:
                pass

        elif role == CommitLogModel.Role.SpecialRow:
            if row == 0:
                return SpecialRow.UncommittedChanges
            elif row < len(self.repoModel.commitSequence):
                return SpecialRow.Commit
            else:
                return self._extraRow

        elif role == Qt.ItemDataRole.ToolTipRole:
            tip = ""

            try:
                commit = self.repoModel.commitSequence[row]
                zones = self._toolTipZones[row]
            except (IndexError, KeyError):
                return tip
            if commit is None or commit.id == UC_FAKEID:
                return tip

            x = self.parent().mapFromGlobal(QCursor.pos()).x()
            for zone in zones:
                if not (zone.left <= x <= zone.right):
                    continue
                if zone.kind == "ref":
                    tip = zone.data
                elif zone.kind == "message":
                    tip = commitMessageTooltip(commit)
                elif zone.kind == "author":
                    tip = commitAuthorTooltip(commit, *self.repoModel.getCachedGpgStatus(commit))
                elif zone.kind == "pin":
                    tip = commitAuthorTooltip(commit)
                elif zone.kind == "pinSource":
                    tip = _("Commit {0} is pinned for comparison", shortHash(commit.id))
                elif zone.kind == "pinTarget":
                    tip = _("This commit is being compared to the pinned commit")
                break

            if self._authorColumnX <= 0:  # author hidden in narrow window
                tip += commitAuthorTooltip(commit, *self.repoModel.getCachedGpgStatus(commit))

            return tip

        return None

    def setData(self, index, value, role=None):
        if role == CommitLogModel.Role.AuthorColumnX:
            self._authorColumnX = value
            return True

        elif role == CommitLogModel.Role.ToolTipZones:
            row = index.row()

            # Bump row to end of keys
            # (dicts keep key insertion order in Python 3.7+)
            self._toolTipZones.pop(row, None)
            self._toolTipZones[row] = value

            # Nuke old entries if the dict grew beyond the threshold
            trimCacheDict(self._toolTipZones, CommitLogModel.ToolTipCacheSize)

            return True

        return False


def commitAuthorTooltip(commit: Commit, gpgStatus: GpgStatus, gpgKeyInfo: str) -> str:
    def formatTime(sig: Signature):
        return escape(signatureDateFormat(sig))

    def formatPerson(sig: Signature):
        return f"<b>{escape(sig.name)}</b> &lt;{escape(sig.email)}&gt;"

    author = commit.author
    committer = commit.committer

    markup = "<p style='white-space: pre'>"
    markup += formatPerson(author)

    if author == committer:
        markup += f"<small><br>{formatTime(author)}"
    elif author.name == committer.name and author.email == committer.email:
        suffixA = _p("CommitTooltip", "(authored)")
        suffixC = _p("CommitTooltip", "(committed)")
        markup += (f"<small><br>{formatTime(author)} {suffixA}"
                   f"<br>{formatTime(committer)} *{suffixC}")
    else:
        committedBy = _p("CommitTooltip", "Committed by {0}", formatPerson(committer))
        markup += (f"<small><br>{formatTime(author)}"
                   f"<br><br>* {committedBy}"
                   f"<br><small>{formatTime(committer)}")
    markup += "</p>"

    if gpgStatus == GpgStatus.Unsigned:
        pass
    elif gpgKeyInfo:
        markup += f"<p>{gpgStatus.iconHtml()} {TrTables.enum(gpgStatus)}<br><small>{escape(gpgKeyInfo)}</small></p>"
    else:
        markup += f"<p>{gpgStatus.iconHtml()} {TrTables.enum(gpgStatus)}</p>"

    return markup


def commitMessageTooltip(commit: Commit) -> str:
    message = commit.message.rstrip()
    maxLength = max(len(line) for line in message.splitlines())
    message = escape(message)

    if maxLength <= 80:
        # Keep Qt from wrapping tooltip text when the message is made up of short lines
        return "<p style='white-space: pre'>" + message
    else:
        return "<p>" + message.replace('\n', '<br>')


def trimCacheDict(d: dict, trimToSize: int):
    maxCapacity = trimToSize * 2
    size = len(d)
    if size <= maxCapacity:
        return
    numOldKeys = size - trimToSize
    oldKeys = list(d)[:numOldKeys]
    for k in oldKeys:
        del d[k]
