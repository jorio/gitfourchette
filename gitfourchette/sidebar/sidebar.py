# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import time
import warnings
from collections.abc import Callable, Iterable
from contextlib import suppress

from gitfourchette import porcelain
from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import Oid, RefPrefix
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.repoprefs import RefSort
from gitfourchette.sidebar.sidebardelegate import SidebarDelegate, SidebarClickZone
from gitfourchette.sidebar.sidebarmodel import SidebarModel, SidebarNode, SidebarItem, UC_FAKEREF
from gitfourchette.tasks import *
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables
from gitfourchette.webhost import WebHost

INVALID_MOUSEPRESS = (-1, SidebarClickZone.Invalid)


class Sidebar(QTreeView):
    toggleHideRefPattern = Signal(str, bool)

    openSubmoduleRepo = Signal(str)
    openSubmoduleFolder = Signal(str)

    statusMessage = Signal(str)

    @property
    def sidebarModel(self) -> SidebarModel:
        model = self.model()
        assert isinstance(model, SidebarModel)
        return model

    def __init__(self, parent):
        super().__init__(parent)
        self.repoWidget = parent

        self.setObjectName("Sidebar")
        self.setMouseTracking(True)  # for eye icons
        self.setMinimumWidth(128)
        self.setIndentation(16)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)  # large sidebars update twice as fast with this, but we can't have thinner spacers
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.customContextMenuRequested.connect(self.onCustomContextMenuRequested)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        sidebarModel = SidebarModel(self)
        self.setModel(sidebarModel)

        self.setItemDelegate(SidebarDelegate(self))

        self.expanded.connect(sidebarModel.onIndexExpanded)
        self.collapsed.connect(sidebarModel.onIndexCollapsed)
        self.selectionBackup = None

        # When clicking on a row, information about the clicked row and "zone"
        # is kept until mouseReleaseEvent.
        self.mousePressCache = INVALID_MOUSEPRESS

        self.refreshPrefs()

        makeWidgetShortcut(self, self.onReturnShortcut, "Return", "Enter")
        makeWidgetShortcut(self, self.onDeleteShortcut, "Delete")
        makeWidgetShortcut(self, self.onRenameShortcut, "F2")

    def drawBranches(self, painter, rect, index):
        """
        (overridden function)
        Prevent drawing the default "branches" and expand/collapse indicators.
        We draw the expand/collapse indicator ourselves in SidebarDelegate.
        """
        # Overriding this function has the same effect as adding this line in the QSS:
        # Sidebar::branch { image: none; border-image: none; }
        return

    def visualRect(self, index: QModelIndex) -> QRect:
        """
        Required so the theme can properly draw unindented rows.
        """

        vr = super().visualRect(index)

        if index.isValid():
            node = SidebarNode.fromIndex(index)
            SidebarDelegate.unindentRect(node.kind, vr, self.indentation())

        return vr

    def refSortMenu(self, prefKey: str) -> list[ActionDef]:
        repoModel = self.sidebarModel.repoModel
        repoPrefs = repoModel.prefs

        defaultMode = settings.prefs.refSort
        currentMode = getattr(repoPrefs, prefKey)
        assert isinstance(currentMode, RefSort)
        if currentMode == RefSort.UseGlobalPref:
            currentMode = defaultMode

        def setSortMode(newMode: RefSort):
            if currentMode == newMode:
                return
            setattr(repoPrefs, prefKey, newMode)
            repoPrefs.refSortClearTimestamp = int(time.time())
            repoPrefs.setDirty()
            self.backUpSelection()
            self.refresh(repoModel)
            self.restoreSelectionBackup()

        submenu = []
        for sortMode, caption in TrTables._enums[RefSort].items():
            if not caption:  # Skip UseGlobalPref
                continue
            action = ActionDef(
                caption,
                lambda m=sortMode: setSortMode(m),
                radioGroup=f"sortBy-{prefKey}",
                checkState=1 if currentMode == sortMode else -1)
            submenu.append(action)

        return submenu

    def makeNodeMenu(self, node: SidebarNode, menu: QMenu | None = None):
        if menu is None:
            menu = QMenu(self)
            menu.setObjectName("SidebarContextMenu")
        menu.setToolTipsVisible(True)

        actions = []

        model = self.sidebarModel
        repo = model.repo
        item = node.kind
        data = node.data
        isExplicitlyShown = model.isExplicitlyShown(node)
        isExplicitlyHidden = model.isExplicitlyHidden(node)
        mainWindow = GFApplication.instance().mainWindow

        if item == SidebarItem.WorkdirHeader:
            actions += self.repoWidget.contextMenuItems()

        elif item == SidebarItem.UncommittedChanges:
            actions += [
                TaskBook.action(self, NewCommit, accel="C"),
                TaskBook.action(self, AmendCommit, accel="A"),
                ActionDef.SEPARATOR,
                TaskBook.action(self, NewStash, accel="S"),
                TaskBook.action(self, ExportWorkdirAsPatch, accel="X"),
                *mainWindow.contextualUserCommands(UserCommand.Token.Workdir),
            ]

        elif item == SidebarItem.LocalBranchesHeader:
            actions += [
                TaskBook.action(self, NewBranchFromHead, _("&New Branch…")),
                ActionDef.SEPARATOR,
                ActionDef(_("Sort By"), submenu=self.refSortMenu("sortBranches")),
            ]

        elif item == SidebarItem.LocalBranch:
            refName = data
            prefix, branchName = RefPrefix.split(data)
            assert prefix == RefPrefix.HEADS
            branch = repo.branches.local[branchName]

            activeBranchName = model.repoModel.homeBranch
            isCurrentBranch = branch and branch.is_checked_out()
            hasUpstream = bool(branch.upstream)
            upstreamBranchName = "" if not hasUpstream else branch.upstream.shorthand

            thisBranchDisplay = lquoe(branchName)
            activeBranchDisplay = lquoe(activeBranchName)
            upstreamBranchDisplay = lquoe(upstreamBranchName)

            userCommandTokens = [UserCommand.Token.Commit, UserCommand.Token.Ref]
            if isCurrentBranch:
                userCommandTokens.extend([
                    UserCommand.Token.Head,
                    UserCommand.Token.HeadBranch,
                    UserCommand.Token.HeadUpstream
                ])

            actions += [
                TaskBook.action(
                    self,
                    SwitchBranch,
                    _("&Switch to {0}…", thisBranchDisplay),
                    taskArgs=branchName,
                ).replace(enabled=not isCurrentBranch),

                ActionDef.SEPARATOR,

                TaskBook.action(
                    self,
                    MergeBranch,
                    _("&Merge into {0}…", activeBranchDisplay),
                    taskArgs=refName,
                ).replace(enabled=not isCurrentBranch and activeBranchName),

                ActionDef.SEPARATOR,

                TaskBook.action(
                    self,
                    FetchRemoteBranch,
                    _("&Fetch {0}", upstreamBranchDisplay) if hasUpstream else _("Fetch"),
                    taskArgs=branch.upstream.shorthand if hasUpstream else None,
                ).replace(enabled=hasUpstream),

                TaskBook.action(
                    self,
                    PullBranch,
                    _("Pu&ll from {0}…", upstreamBranchDisplay) if hasUpstream else _("Pull…"),
                ).replace(enabled=hasUpstream and isCurrentBranch),

                TaskBook.action(
                    self,
                    FastForwardBranch,
                    _("Fast-Forward to {0}…", upstreamBranchDisplay) if hasUpstream else _("Fast-Forward…"),
                    taskArgs=branchName,
                ).replace(enabled=hasUpstream),

                TaskBook.action(
                    self,
                    PushBranch,
                    _("&Push to {0}…", upstreamBranchDisplay) if hasUpstream else _("Push…"),
                    taskArgs=branchName,
                ),

                ActionDef(
                    _("&Upstream Branch"),
                    submenu=self.makeUpstreamSubmenu(repo, branchName, upstreamBranchName)),

                ActionDef.SEPARATOR,

                TaskBook.action(self, RenameBranch, _("Re&name…"), taskArgs=branchName),

                TaskBook.action(self, DeleteBranch, _("&Delete…"), taskArgs=branchName),

                ActionDef.SEPARATOR,

                TaskBook.action(self, NewBranchFromRef, _("New &Branch Here…"), taskArgs=refName),

                ActionDef.SEPARATOR,

                ActionDef(_("&Hide in Graph"),
                          lambda: self.wantHideNode(node),
                          checkState=[-1, 1][isExplicitlyHidden],
                          tip=_("Hide this branch from the graph (effective if no other branches/tags point here)"),
                          icon="view-hidden"),

                ActionDef(_("Hide &All But This"),
                          lambda: self.wantHideNode(node, True),
                          checkState=[-1, 1][isExplicitlyShown],
                          icon="view-exclusive"),

                *mainWindow.contextualUserCommands(*userCommandTokens),
            ]

        elif item == SidebarItem.DetachedHead:
            actions += [TaskBook.action(self, NewBranchFromHead, _("New &Branch Here…")), ]

        elif item == SidebarItem.RemoteBranch:
            activeBranchName = model.repoModel.homeBranch
            activeBranchDisplay = lquoe(activeBranchName) if activeBranchName else _("(no current branch)")

            refName = data
            prefix, shorthand = RefPrefix.split(refName)
            assert prefix == RefPrefix.REMOTES

            remoteName, remoteBranchName = porcelain.split_remote_branch_shorthand(shorthand)
            remoteUrl = self.sidebarModel.repo.remotes[remoteName].url
            webUrl, webHost = WebHost.makeLink(remoteUrl, remoteBranchName)
            webActions = []
            if webUrl:
                webActions = [
                    ActionDef(
                        _("Visit Web Page on {0}", escamp(webHost)),
                        lambda: QDesktopServices.openUrl(QUrl(webUrl)),
                        icon="internet-web-browser",
                        tip=f"<p style='white-space: pre'>{escape(webUrl)}</p>",
                    ),
                    ActionDef.SEPARATOR,
                ]

            actions += [
                TaskBook.action(self, NewBranchFromRef, _("New Local &Branch Here…"), taskArgs=refName),

                TaskBook.action(self, FetchRemoteBranch, _("&Fetch New Commits"), taskArgs=shorthand),

                ActionDef.SEPARATOR,

                TaskBook.action(self, MergeBranch, _("&Merge into {0}…", activeBranchDisplay),
                                taskArgs=refName, enabled=bool(activeBranchName)),

                ActionDef.SEPARATOR,

                TaskBook.action(self, RenameRemoteBranch, taskArgs=shorthand),

                TaskBook.action(self, DeleteRemoteBranch, taskArgs=shorthand),

                ActionDef.SEPARATOR,

                *webActions,

                ActionDef(_("&Hide in Graph"),
                          lambda: self.wantHideNode(node),
                          checkState=[-1, 1][isExplicitlyHidden],
                          icon="view-hidden"),

                ActionDef(_("Hide &All But This"),
                          lambda: self.wantHideNode(node, True),
                          checkState=[-1, 1][isExplicitlyShown],
                          icon="view-exclusive"),

                *mainWindow.contextualUserCommands(UserCommand.Token.Commit, UserCommand.Token.Ref, UserCommand.Token.Remote),
            ]

        elif item == SidebarItem.Remote:
            remoteUrl = model.repo.remotes[data].url
            webUrl, webHost = WebHost.makeLink(remoteUrl)

            collapseActions = []
            if any(n.kind == SidebarItem.RefFolder for n in node.children):
                collapseActions = [
                    ActionDef(
                        _("Collapse All Folders"),
                        lambda: self.collapseChildFolders(node),
                    ),
                    ActionDef(
                        _("Expand All Folders"),
                        lambda: self.expandChildFolders(node),
                    ),
                ]

            webActions = []
            if webUrl:
                webActions = [
                    ActionDef(
                        _("Visit Web Page on {0}", escamp(webHost)),
                        lambda: QDesktopServices.openUrl(QUrl(webUrl)),
                        icon="internet-web-browser",
                        tip=f"<p style='white-space: pre'>{escape(webUrl)}</p>",
                    ),
                ]

            actions += [
                TaskBook.action(self, EditRemote, accel="E", taskArgs=data),

                TaskBook.action(self, FetchRemotes, accel="F", taskArgs=data),

                ActionDef.SEPARATOR,

                TaskBook.action(self, DeleteRemote, accel="R", taskArgs=data),

                ActionDef.SEPARATOR,

                *webActions,

                ActionDef(_("Copy Remote &URL"),
                          lambda: self.copyToClipboard(remoteUrl)),

                ActionDef.SEPARATOR,

                *collapseActions,

                ActionDef(_("&Hide in Graph"),
                          lambda: self.wantHideNode(node),
                          checkState=[-1, 1][isExplicitlyHidden],
                          icon="view-hidden"),

                ActionDef(_("Hide &All But This"),
                          lambda: self.wantHideNode(node, True),
                          checkState=[-1, 1][isExplicitlyShown],
                          icon="view-exclusive"),

                *mainWindow.contextualUserCommands(UserCommand.Token.Remote),
            ]

        elif item == SidebarItem.RemotesHeader:
            actions += [
                TaskBook.action(self, NewRemote, accel="A"),
                TaskBook.action(self, FetchRemotes, accel="F"),
                ActionDef.SEPARATOR,
                ActionDef(_("Sort Remote Branches By"), submenu=self.refSortMenu("sortRemoteBranches")),
            ]

        elif item == SidebarItem.RefFolder:
            if node.data.startswith(RefPrefix.HEADS):
                actions += [
                    ActionDef(_("Re&name Folder…"), lambda: self.wantRenameNode(node)),
                    ActionDef(_("&Delete Folder…"), lambda: self.wantDeleteNode(node)),
                    ActionDef.SEPARATOR,
                ]

            actions += [
                ActionDef(_("&Hide in Graph"),
                          lambda: self.wantHideNode(node),
                          checkState=[-1, 1][isExplicitlyHidden],
                          icon="view-hidden"),

                ActionDef(_("Hide &All But This"),
                          lambda: self.wantHideNode(node, True),
                          checkState=[-1, 1][isExplicitlyShown],
                          icon="view-exclusive"),
            ]

        elif item == SidebarItem.StashesHeader:
            actions += [
                TaskBook.action(self, NewStash, accel="S"),
            ]

        elif item == SidebarItem.Stash:
            oid = Oid(hex=data)

            actions += [
                TaskBook.action(self, ApplyStash, accel="A", taskArgs=oid),

                TaskBook.action(self, ExportStashAsPatch, accel="X", taskArgs=oid),

                ActionDef.SEPARATOR,

                TaskBook.action(self, DropStash, accel="D", taskArgs=oid),

                ActionDef.SEPARATOR,

                ActionDef(_("Reveal &Parent Commit"), lambda: self.revealStashParent(oid)),
            ]

        elif item == SidebarItem.TagsHeader:
            refspecs = [ref for ref in self.sidebarModel.repoModel.refs.keys()
                        if ref.startswith(RefPrefix.TAGS)]

            actions += [
                TaskBook.action(self, NewTag, _("&New Tag on HEAD Commit…")),
                ActionDef(_("&Push All Tags To"), submenu=self.pushRefspecMenu(refspecs), enabled=bool(refspecs)),
                ActionDef.SEPARATOR,
                ActionDef(_("Sort By"), submenu=self.refSortMenu("sortTags")),
            ]

        elif item == SidebarItem.Tag:
            prefix, shorthand = RefPrefix.split(data)
            assert prefix == RefPrefix.TAGS
            refspecs = [data]

            target = self.sidebarModel.repoModel.refs[data]

            actions += [
                TaskBook.action(self, CheckoutCommit, _("&Check Out Tagged Commit…"), taskArgs=target),
                TaskBook.action(self, DeleteTag, _("&Delete Tag…"), taskArgs=shorthand),
                ActionDef.SEPARATOR,
                ActionDef(_("Push To"), submenu=self.pushRefspecMenu(refspecs)),
            ]

        elif item == SidebarItem.SubmodulesHeader:
            submodules = self.sidebarModel.repoModel.submodules

            actions += [
                TaskBook.action(self, UpdateSubmodulesRecursive, enabled=bool(submodules)),
            ]

        elif item == SidebarItem.Submodule:
            model = self.sidebarModel
            repo = model.repo

            actions += [
                ActionDef(_("&Open Submodule in New Tab"),
                          lambda: self.openSubmoduleRepo.emit(data)),

                ActionDef(_("Open Submodule &Folder"),
                          lambda: self.openSubmoduleFolder.emit(data)),

                ActionDef(_("Copy &Path"),
                          lambda: self.copyToClipboard(repo.in_workdir(data))),

                ActionDef.SEPARATOR,

                TaskBook.action(self, UpdateSubmodule, taskArgs=data),

                ActionDef.SEPARATOR,

                TaskBook.action(self, RemoveSubmodule, taskArgs=data),
            ]

        # --------------------

        ActionDef.addToQMenu(menu, *actions)

        return menu

    def onCustomContextMenuRequested(self, localPoint: QPoint):
        globalPoint = self.mapToGlobal(localPoint)
        index: QModelIndex = self.indexAt(localPoint)
        if not index.isValid():
            return
        node = SidebarNode.fromIndex(index)
        menu = self.makeNodeMenu(node)
        if menu.actions():
            menu.exec(globalPoint)
        menu.deleteLater()

    def refresh(self, repoModel: RepoModel):
        self.sidebarModel.rebuild(repoModel)
        self.restoreExpandedItems()

    def backUpSelection(self):
        try:
            self.selectionBackup = SidebarNode.fromIndex(self.selectedIndexes()[0])
        except IndexError:
            self.clearSelectionBackup()

    def clearSelectionBackup(self):
        self.selectionBackup = None

    def restoreSelectionBackup(self):
        if self.selectionBackup is None:
            return
        with suppress(StopIteration), QSignalBlockerContext(self):
            newNode = self.findNode(self.selectionBackup.isSimilarEnoughTo)
            restoreIndex = newNode.createIndex(self.sidebarModel)
            self.setCurrentIndex(restoreIndex)
        self.clearSelectionBackup()

    def refreshPrefs(self):
        self.setVerticalScrollMode(settings.prefs.listViewScrollMode)
        self.setAnimated(settings.prefs.animations)

    def repaintUncommittedChanges(self):
        model = self.sidebarModel
        index = model.nodesByRef[UC_FAKEREF].createIndex(model)
        self.update(index)

    def wantSelectNode(self, node: SidebarNode):
        if self.signalsBlocked():  # Don't bother with the jump if our signals are blocked
            return

        if node is None:
            return

        assert isinstance(node, SidebarNode)

        item = node.kind

        if item == SidebarItem.UncommittedChanges:
            locator = NavLocator.inWorkdir()
        elif item == SidebarItem.UnbornHead:
            locator = NavLocator.inWorkdir()
        elif item == SidebarItem.DetachedHead:
            locator = NavLocator.inRef("HEAD")
        elif item == SidebarItem.LocalBranch:
            locator = NavLocator.inRef(node.data)
        elif item == SidebarItem.RemoteBranch:
            locator = NavLocator.inRef(node.data)
        elif item == SidebarItem.Tag:
            locator = NavLocator.inRef(node.data)
        elif item == SidebarItem.Stash:
            locator = NavLocator.inCommit(Oid(hex=node.data))
        else:
            return None

        Jump.invoke(self, locator)

    def wantEnterNode(self, node: SidebarNode):
        if node is None:
            QApplication.beep()
            return
        assert isinstance(node, SidebarNode)

        item = node.kind

        if item == SidebarItem.Spacer:
            pass

        elif item == SidebarItem.LocalBranch:
            SwitchBranch.invoke(self, node.data.removeprefix(RefPrefix.HEADS))

        elif item == SidebarItem.Remote:
            EditRemote.invoke(self, node.data)

        elif item == SidebarItem.RemotesHeader:
            NewRemote.invoke(self)

        elif item == SidebarItem.LocalBranchesHeader:
            NewBranchFromHead.invoke(self)

        elif item == SidebarItem.UncommittedChanges:
            NewCommit.invoke(self)

        elif item == SidebarItem.Submodule:
            self.openSubmoduleRepo.emit(node.data)

        elif item == SidebarItem.StashesHeader:
            NewStash.invoke(self)

        elif item == SidebarItem.Stash:
            oid = Oid(hex=node.data)
            ApplyStash.invoke(self, oid)

        elif item == SidebarItem.RemoteBranch:
            NewBranchFromRef.invoke(self, node.data)

        elif item == SidebarItem.DetachedHead:
            NewBranchFromHead.invoke(self)

        elif item == SidebarItem.TagsHeader:
            NewTag.invoke(self)

        elif item == SidebarItem.Tag:
            target = self.sidebarModel.repoModel.refs[node.data]
            CheckoutCommit.invoke(self, target)

        else:
            QApplication.beep()

    def wantDeleteNode(self, node: SidebarNode):
        if node is None:
            QApplication.beep()
            return

        item = node.kind
        data = node.data

        if item == SidebarItem.Spacer:
            pass

        elif item == SidebarItem.LocalBranch:
            assert data.startswith(RefPrefix.HEADS)
            DeleteBranch.invoke(self, data.removeprefix(RefPrefix.HEADS))

        elif item == SidebarItem.Remote:
            DeleteRemote.invoke(self, data)

        elif item == SidebarItem.Stash:
            oid = Oid(hex=data)
            DropStash.invoke(self, oid)

        elif item == SidebarItem.RemoteBranch:
            assert data.startswith(RefPrefix.REMOTES)
            DeleteRemoteBranch.invoke(self, data.removeprefix(RefPrefix.REMOTES))

        elif item == SidebarItem.Tag:
            assert data.startswith(RefPrefix.TAGS)
            DeleteTag.invoke(self, data.removeprefix(RefPrefix.TAGS))

        elif item == SidebarItem.RefFolder:
            prefix, name = RefPrefix.split(data)
            if prefix == RefPrefix.HEADS:
                DeleteBranchFolder.invoke(self, data)
            else:
                QApplication.beep()

        else:
            QApplication.beep()

    def wantRenameNode(self, node: SidebarNode):
        if node is None:
            QApplication.beep()
            return

        item = node.kind
        data = node.data

        if item == SidebarItem.Spacer:
            pass

        elif item == SidebarItem.LocalBranch:
            prefix, name = RefPrefix.split(data)
            assert prefix == RefPrefix.HEADS
            RenameBranch.invoke(self, name)

        elif item == SidebarItem.Remote:
            EditRemote.invoke(self, data)

        elif item == SidebarItem.RemoteBranch:
            RenameRemoteBranch.invoke(self, data)

        elif item == SidebarItem.RefFolder:
            prefix, name = RefPrefix.split(data)
            if prefix == RefPrefix.HEADS:
                RenameBranchFolder.invoke(self, data)
            else:
                QApplication.beep()

        else:
            QApplication.beep()

    def wantHideNode(self, node: SidebarNode, allButThis: bool = False):
        pattern = node.refMatchingPattern()
        if not pattern:
            return
        self.toggleHideRefPattern.emit(pattern, allButThis)
        self.repaint()

    def getValidNode(self):
        try:
            index: QModelIndex = self.selectedIndexes()[0]
            return SidebarNode.fromIndex(index)
        except IndexError:
            return None

    def onReturnShortcut(self):
        self.wantEnterNode(self.getValidNode())

    def onDeleteShortcut(self):
        self.wantDeleteNode(self.getValidNode())

    def onRenameShortcut(self):
        self.wantRenameNode(self.getValidNode())

    def selectionChanged(self, selected: QItemSelection, deselected: QItemSelection):
        super().selectionChanged(selected, deselected)

        if selected.count() == 0:
            return

        current = selected.indexes()[0]
        if not current.isValid():
            return

        self.wantSelectNode(SidebarNode.fromIndex(current))

    def resolveClick(self, pos: QPoint) -> tuple[QModelIndex, SidebarNode | None, SidebarClickZone]:
        index = self.indexAt(pos)
        if index.isValid():
            rect = self.visualRect(index)
            node = SidebarNode.fromIndex(index)
            zone = SidebarDelegate.getClickZone(node, rect, pos.x())
        else:
            node = None
            zone = SidebarClickZone.Invalid
        return index, node, zone

    def mouseMoveEvent(self, event):
        """
        Bypass QTreeView's mouseMoveEvent to prevent the original branch
        expand indicator from taking over mouse input.
        """
        QAbstractItemView.mouseMoveEvent(self, event)

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        index, node, zone = self.resolveClick(pos)

        # Save click info for mouseReleaseEvent
        self.mousePressCache = (index.row(), zone)

        if zone == SidebarClickZone.Invalid:
            super().mousePressEvent(event)
            return

        if zone == SidebarClickZone.Select:
            self.setCurrentIndex(index)

        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        index, node, zone = self.resolveClick(pos)

        # Only perform special actions (hide, expand) if mouse was released
        # on same row/zone as mousePressEvent
        match = (index.row(), zone) == self.mousePressCache

        # Clear mouse press info on release
        self.mousePressCache = INVALID_MOUSEPRESS

        if (not match
                or node is None
                or zone in [SidebarClickZone.Invalid, SidebarClickZone.Select]):
            super().mouseReleaseEvent(event)
            return

        if zone == SidebarClickZone.Hide:
            allButThis = event.button() == Qt.MouseButton.MiddleButton or self.sidebarModel.isHideAllButThisMode()
            self.wantHideNode(node, allButThis)
            event.accept()
        elif zone == SidebarClickZone.Expand:
            # Toggle expanded state
            if node.mayHaveChildren():
                if self.isExpanded(index):
                    self.collapse(index)
                else:
                    self.expand(index)
            event.accept()
        else:
            warnings.warn(f"Unknown click zone {zone}")

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # NOT calling "super().mouseDoubleClickEvent(event)" on purpose.

        pos = event.position().toPoint()
        index, node, zone = self.resolveClick(pos)

        # Let user collapse/expand/hide a single node in quick succession
        # without triggering a double click
        if zone not in [SidebarClickZone.Invalid, SidebarClickZone.Select]:
            self.mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton and node is not None:
            self.wantEnterNode(node)

    def revealStashParent(self, oid: Oid):
        commit = self.sidebarModel.repo.peel_commit(oid)
        parent = commit.parent_ids[0]
        Jump.invoke(self, NavLocator.inCommit(parent))

    def walk(self):
        return self.sidebarModel.rootNode.walk()

    def findNode(self, predicate: Callable[[SidebarNode], bool]) -> SidebarNode:
        return next(node for node in self.walk() if predicate(node))

    def findNodeByRef(self, ref: str) -> SidebarNode:
        return self.sidebarModel.nodesByRef[ref]

    def findNodesByKind(self, kind: SidebarItem) -> list[SidebarNode]:
        """ Unit test helper """
        return [node for node in self.walk() if node.kind == kind]

    def findNodeByKind(self, kind: SidebarItem) -> SidebarNode:
        """ Unit test helper """
        nodes = self.findNodesByKind(kind)
        if len(nodes) == 0:
            raise KeyError(str(kind))
        if len(nodes) != 1:
            raise ValueError(f"{kind} is not unique")
        return nodes[0]

    def countNodesByKind(self, kind: SidebarItem):
        """ Unit test helper """
        return len(self.findNodesByKind(kind))

    def indexForRef(self, ref: str) -> QModelIndex | None:
        model = self.sidebarModel
        try:
            node = model.nodesByRef[ref]
            return node.createIndex(model)
        except KeyError:
            return None

    def selectNode(self, node: SidebarNode) -> QModelIndex:
        index = node.createIndex(self.sidebarModel)
        self.setCurrentIndex(index)
        return index

    def selectAnyRef(self, *refs: str) -> QModelIndex | None:
        # Early out if any candidate ref is already selected
        with suppress(IndexError):
            index = self.selectedIndexes()[0]
            if index and index.data(SidebarModel.Role.Ref) in refs:
                return index

        # If several refs point to the same commit, attempt to select
        # the checked-out branch first (or its upstream, if any)
        model = self.sidebarModel
        refCandidates: Iterable[str]
        if model._checkedOut:
            favorRefs = [RefPrefix.HEADS + model._checkedOut,
                         RefPrefix.REMOTES + model._checkedOutUpstream]
            refCandidates = sorted(refs, key=favorRefs.__contains__, reverse=True)
        else:
            refCandidates = refs

        # Find a visible index that matches any of the candidates
        for ref in refCandidates:
            index = self.indexForRef(ref)
            if not index:
                continue
            # Don't force-expand any collapsed indexes
            node = SidebarNode.fromIndex(index)
            if model.isAncestryChainExpanded(node):
                self.setCurrentIndex(index)
                return index

        # There are no indices that match the candidates, so select nothing
        self.clearSelection()
        return None

    @benchmark
    def restoreExpandedItems(self):
        model = self.sidebarModel

        # If we don't have a valid collapse cache (typically upon opening the repo), expand everything.
        # This can be pretty expensive, so cache collapsed items for next time.
        if not model.collapseCacheValid:
            self.expandAll()
            model.collapseCache.clear()
            model.collapseCacheValid = True
            return

        assert model.collapseCacheValid

        frontier = model.rootNode.children[:]
        while frontier:
            node = frontier.pop()

            if not node.mayHaveChildren():
                continue

            if node.wantForceExpand() or node.getCollapseHash() not in model.collapseCache:
                index = node.createIndex(model)
                self.expand(index)

            frontier.extend(node.children)

    def collapseChildFolders(self, node: SidebarNode):
        for n in node.children:
            if n.kind == SidebarItem.RefFolder:
                index = n.createIndex(self.sidebarModel)
                self.collapse(index)

    def expandChildFolders(self, node: SidebarNode):
        for n in node.children:
            if n.kind == SidebarItem.RefFolder:
                index = n.createIndex(self.sidebarModel)
                self.expand(index)

    def copyToClipboard(self, text: str):
        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def makeUpstreamSubmenu(self, repo, lbName, ubName) -> list:
        RADIO_GROUP = "UpstreamSelection"

        menu = [
            ActionDef(
                _("Stop tracking upstream branch") if ubName else _("Not tracking any upstream branch"),
                lambda: EditUpstreamBranch.invoke(self, lbName, ""),
                checkState=1 if not ubName else -1,
                radioGroup=RADIO_GROUP),
        ]

        for remoteBranches in repo.listall_remote_branches(value_style="shorthand").values():
            if not remoteBranches:
                continue
            menu.append(ActionDef.SEPARATOR)
            for rbShorthand in remoteBranches:
                menu.append(ActionDef(
                    escamp(rbShorthand),
                    lambda rb=rbShorthand: EditUpstreamBranch.invoke(self, lbName, rb),
                    checkState=1 if ubName == rbShorthand else -1,
                    radioGroup=RADIO_GROUP))

        if len(menu) <= 1:
            if not repo.remotes:
                explainer = _("No remotes.")
            else:
                explainer = _("No remote branches found. Try fetching the remotes.")
            menu.append(ActionDef.SEPARATOR)
            menu.append(ActionDef(explainer, enabled=False))

        return menu

    def pushRefspecMenu(self, refspecs):
        remotes = self.sidebarModel.repoModel.remotes
        menu = []

        if remotes:
            menu.append(TaskBook.action(self, PushRefspecs, _("&All Remotes"), taskArgs=("*", refspecs)))
            menu.append(ActionDef.SEPARATOR)
            for remote in remotes:
                menu.append(TaskBook.action(self, PushRefspecs, escamp(remote), taskArgs=(remote, refspecs)))
        else:
            menu.append(ActionDef(_("No Remotes"), enabled=False))

        return menu
