# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from collections.abc import Iterable
from typing import Any

from gitfourchette import settings
from gitfourchette.gitdriver import GitDelta
from gitfourchette.localization import *
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)

STATUS_ICON_LETTERS = "xadmrxxatxu"
"""
Table of status_*.svg icons for each enum entry
in pygit2.enums.DeltaStatus.
"""


def deltaModeText(om: FileMode, nm: FileMode) -> str:
    if om != 0 and nm != 0 and om != nm:
        # Mode change
        if nm == FileMode.BLOB_EXECUTABLE:
            return "+x"
        elif om == FileMode.BLOB_EXECUTABLE:
            return "-x"
        elif nm != FileMode.BLOB:
            return TrTables.shortFileModes(nm)
        else:
            return ""
    elif om == 0:
        # New file
        return TrTables.shortFileModes(nm)
    return ""


def fileTooltip(repo: Repo, delta: GitDelta, navContext: NavContext, isCounterpart: bool = False):
    locale = QLocale()
    of = delta.old
    nf = delta.new
    sc = delta.status

    text = "<table style='white-space: pre'>"

    def newLine(heading, caption):
        colon = _(':')
        color = mutedToolTipColorHex()
        return f"<tr><td style='color:{color}; text-align: right;'>{heading}{colon} </td><td>{caption}</td>"

    if sc == 'R':
        text += newLine(_("old name"), escape(of.path))
        text += newLine(_("new name"), escape(nf.path))
    else:
        text += newLine(_("name"), escape(nf.path))

    # Status caption
    statusCaption = TrTables.diffStatusChar(sc)
    if sc not in '?U':  # show status char except for untracked and conflict
        statusCaption += f" ({sc})"
    if sc == 'U':  # conflict sides
        assert delta.conflict is not None
        postfix = TrTables.enum(delta.conflict.sides)
        statusCaption += f" ({postfix})"
    text += newLine(_("status"), statusCaption)

    # Similarity + Old name
    if sc == 'R':
        text += newLine(_("similarity"), f"{delta.similarity}%")

    # File Mode
    if sc in 'DU':
        pass
    elif sc in 'A?':
        text += newLine(_("file mode"), TrTables.enum(nf.mode))
    elif of.mode != nf.mode:
        text += newLine(_("file mode"), f"{TrTables.enum(of.mode)} \u2192 {TrTables.enum(nf.mode)}")

    mTimeNS, size = -1, -1
    sizeIsAccurate = False
    if nf.isBlob() and not nf.isId0():
        # Stat workdir file (get size on disk, modification time)
        if navContext.isWorkdir():
            mTimeNS, size = nf.stat(repo)

        # Get accurate size in index if it's not an unstaged file
        if navContext in (NavContext.STAGED, NavContext.COMMITTED):
            assert nf.isIdValid()
            size = repo.peel_blob(nf.id).size
            sizeIsAccurate = True

    # Size (if applicable)
    if size != -1:
        sizeText = locale.formattedDataSize(size, 1)
        if not sizeIsAccurate:
            sizeText = _("{size} on disk", size=sizeText)
        text += newLine(_("size"), sizeText)

    # Modified time
    if mTimeNS != -1:
        timeSecs = int(mTimeNS * 1e-9)  # Convert from nanoseconds
        timeQdt = QDateTime.fromSecsSinceEpoch(timeSecs)
        timeText = locale.toString(timeQdt, settings.prefs.shortTimeFormat)
        text += newLine(_("modified"), timeText)

    # Blob/Commit IDs
    # (Not for unmerged conflicts)
    # (Not for untracked trees - those never have a valid ID)
    if sc != 'U' and nf.mode != FileMode.TREE:
        oldId = shortHash(of.id) if of.isIdValid() else _("(not computed)")
        newId = shortHash(nf.id) if nf.isIdValid() else _("(not computed)")
        idLegend = _("commit hash") if nf.mode == FileMode.COMMIT else _("blob hash")
        text += newLine(idLegend, f"{oldId} \u2192 {newId}")

    if isCounterpart:
        if navContext == NavContext.UNSTAGED:
            counterpartText = _("Currently viewing diff of staged changes in this file; "
                                "it also has <u>unstaged</u> changes.")
        else:
            counterpartText = _("Currently viewing diff of unstaged changes in this file; "
                                "it also has <u>staged</u> changes.")
        text += f"<p>{counterpartText}</p>"

    return text


class FileListModel(QAbstractListModel):
    class Role:
        Delta = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 0)
        FilePath = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)

    deltas: list[GitDelta]
    fileRows: dict[str, int]
    highlightedCounterpartRow: int
    navContext: NavContext

    def __init__(self, parent: QWidget, navContext: NavContext):
        super().__init__(parent)
        self.navContext = navContext
        self.clear()

    @property
    def repo(self) -> Repo:
        return self.parent().repo

    @property
    def parentWidget(self) -> QWidget:
        parentWidget = self.parent()
        assert isinstance(parentWidget, QWidget)
        return parentWidget

    def clear(self):
        self.deltas = []
        self.fileRows = {}
        self.highlightedCounterpartRow = -1
        self.modelReset.emit()

    def setContents(self, deltas: Iterable[GitDelta]):
        self.beginResetModel()

        self.deltas.clear()
        self.fileRows.clear()

        sortedDeltas = sorted(deltas, key=lambda d: naturalSort(d.new.path))

        for delta in sortedDeltas:
            self.fileRows[delta.new.path] = len(self.deltas)
            self.deltas.append(delta)

        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex_default) -> int:
        return len(self.deltas)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole) -> Any:
        row = index.row()
        try:
            delta = self.deltas[row]
        except IndexError:
            delta = None

        if role == FileListModel.Role.Delta:
            return delta

        elif role == FileListModel.Role.FilePath:
            # TODO: Canonical path for submodules?
            return delta.new.path

        elif role == Qt.ItemDataRole.DisplayRole:
            # TODO: Canonical path for submodules?
            text = abbreviatePath(delta.new.path, settings.prefs.pathDisplayStyle)

            # Show important mode info in brackets
            modeInfo = deltaModeText(delta.old.mode, delta.new.mode)
            if modeInfo:
                text = f"[{modeInfo}] {text}"

            return text

        elif role == Qt.ItemDataRole.DecorationRole:
            letter = delta.status
            if letter == "?":  # untracked, fake A
                letter = "A"
            letter = letter.lower()
            return stockIcon(f"status_{letter}")

        elif role == Qt.ItemDataRole.ToolTipRole:
            isCounterpart = row == self.highlightedCounterpartRow
            return fileTooltip(self.repo, delta, self.navContext, isCounterpart)

        elif role == Qt.ItemDataRole.SizeHintRole:
            return QSize(-1, self.parentWidget.fontMetrics().height())

        elif role == Qt.ItemDataRole.FontRole:
            if row == self.highlightedCounterpartRow:
                font = self.parentWidget.font()
                font.setUnderline(True)
                return font

        return None

    def getRowForFile(self, path: str) -> int:
        """
        Get the row number for the given path.
        Raise KeyError if the path is absent from this model.
        """
        return self.fileRows[path]

    def getFileAtRow(self, row: int) -> str:
        """
        Get the path corresponding to the given row number.
        Return an empty string if the row number is invalid.
        """
        if row < 0 or row >= self.rowCount():
            return ""
        return self.data(self.index(row), FileListModel.Role.FilePath)

    def hasFile(self, path: str) -> bool:
        """
        Return True if the given path is present in this model.
        """
        return path in self.fileRows
