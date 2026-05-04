# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.sidebar.sidebarmodel import SidebarNode, SidebarItem


class SidebarProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filterText = ""
        self.setRecursiveFilteringEnabled(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def setFilterText(self, text: str):
        self._filterText = text.strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, sourceRow: int, sourceParent: QModelIndex) -> bool:
        if not self._filterText:
            return True

        sourceModel = self.sourceModel()
        index = sourceModel.index(sourceRow, 0, sourceParent)

        if not index.isValid():
            return True

        node = SidebarNode.fromIndex(index)
        item = node.kind

        if item in [
            SidebarItem.Root,
            SidebarItem.Spacer,
            SidebarItem.WorkdirHeader,
            SidebarItem.UncommittedChanges,
            SidebarItem.LocalBranchesHeader,
            SidebarItem.RemotesHeader,
            SidebarItem.TagsHeader,
            SidebarItem.StashesHeader,
            SidebarItem.SubmodulesHeader,
        ]:
            return True

        if item in [
            SidebarItem.LocalBranch,
            SidebarItem.RemoteBranch,
            SidebarItem.Tag,
            SidebarItem.Stash,
            SidebarItem.Remote,
            SidebarItem.RefFolder,
            SidebarItem.Submodule,
            SidebarItem.DetachedHead,
            SidebarItem.UnbornHead,
        ]:
            displayText = index.data(Qt.ItemDataRole.DisplayRole)
            if not displayText:
                return True

            # For branches and tags, check both display text and full ref path
            # This ensures that branches like "wip/leaf" match when searching for "wip"
            if item in [SidebarItem.LocalBranch, SidebarItem.RemoteBranch, SidebarItem.Tag, SidebarItem.Stash]:
                refName = index.data(sourceModel.Role.Ref)
                if refName and self._filterText.lower() in refName.lower():
                    return True

            return self._filterText.lower() in displayText.lower()

        return True
