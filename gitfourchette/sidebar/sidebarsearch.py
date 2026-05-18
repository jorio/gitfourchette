# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

from typing import TYPE_CHECKING

from gitfourchette.search.searchprovider import SearchProvider

if TYPE_CHECKING:
    from gitfourchette.sidebar.sidebar import Sidebar


class SidebarSearch(SearchProvider):
    sidebar: Sidebar

    def __init__(self, sidebar: Sidebar):
        super().__init__(sidebar)
        self.sidebar = sidebar

    def invalidate(self):
        super().invalidate()

        # Wipe term from filter, return to permanent collapse state
        self.setTerm("")

        # After returning to the permanent collapse state, force expand the node
        # that the user selected while the filter was active
        node = self.sidebar.selectedNode()
        if node is not None and not self.sidebar.sidebarModel.isAncestryChainExpanded(node):
            self.sidebar.selectionModel().clear()
            self.sidebar.selectNode(node)

    def _termChanged(self):
        term = self.term()
        self.sidebar.filterModel.setFilterText(term)

        if term:
            self.sidebar.setCollapseStateLayer(transient=True)
            self.sidebar.expandAll()
        else:
            self.sidebar.setCollapseStateLayer(transient=False)
