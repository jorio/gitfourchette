# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

from gitfourchette import settings
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.repoprefs import RefSort
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)

BRANCH_FOLDERS = True

UC_FAKEREF = "UC_FAKEREF"  # actual refs are either HEAD or they start with /refs/, so this name is safe
"Fake reference for Uncommitted Changes."


class SidebarItem(enum.IntEnum):
    Root = -1
    Spacer = 0
    WorkdirHeader = enum.auto()
    UncommittedChanges = enum.auto()
    LocalBranchesHeader = enum.auto()
    StashesHeader = enum.auto()
    RemotesHeader = enum.auto()
    TagsHeader = enum.auto()
    SubmodulesHeader = enum.auto()
    LocalBranch = enum.auto()
    DetachedHead = enum.auto()
    UnbornHead = enum.auto()
    Stash = enum.auto()
    Remote = enum.auto()
    RemoteBranch = enum.auto()
    Tag = enum.auto()
    Submodule = enum.auto()
    RefFolder = enum.auto()


class SidebarLayout:
    RootItems = [
        SidebarItem.WorkdirHeader,
        SidebarItem.UncommittedChanges,
        SidebarItem.Spacer,
        SidebarItem.LocalBranchesHeader,
        SidebarItem.Spacer,
        SidebarItem.RemotesHeader,
        SidebarItem.Spacer,
        SidebarItem.TagsHeader,
        SidebarItem.Spacer,
        SidebarItem.StashesHeader,
        SidebarItem.Spacer,
        SidebarItem.SubmodulesHeader,
    ]

    ForceExpand = [
        SidebarItem.WorkdirHeader
    ]

    NonleafItems = sorted([
        SidebarItem.Root,
        SidebarItem.WorkdirHeader,
        SidebarItem.LocalBranchesHeader,
        SidebarItem.RefFolder,
        SidebarItem.Remote,
        SidebarItem.RemotesHeader,
        SidebarItem.StashesHeader,
        SidebarItem.SubmodulesHeader,
        SidebarItem.TagsHeader,
    ])

    UnindentItems = {
        SidebarItem.LocalBranch: -1,
        SidebarItem.UnbornHead: -1,
        SidebarItem.DetachedHead: -1,
        SidebarItem.Stash: -1,
        SidebarItem.Tag: -1,
        SidebarItem.Submodule: -1,
        SidebarItem.Remote: -1,
        SidebarItem.RemoteBranch: -1,
        SidebarItem.RefFolder: -1,
    }

    HideableItems = sorted([
        SidebarItem.LocalBranch,
        SidebarItem.Remote,
        SidebarItem.RemoteBranch,
        SidebarItem.RefFolder,
    ])


class SidebarNode:
    children: list[SidebarNode]
    parent: SidebarNode | None
    row: int
    kind: SidebarItem
    data: str
    warning: str
    displayName: str

    @staticmethod
    def fromIndex(index: QModelIndex) -> SidebarNode:
        if not index.isValid():
            raise NotImplementedError("Can't make a SidebarNode from an invalid QModelIndex!")
        p = index.internalPointer()
        assert isinstance(p, SidebarNode)
        return p

    def __init__(self, kind: SidebarItem, data: str = ""):
        self.children = []
        self.parent = None
        self.row = -1
        self.kind = kind
        self.data = data
        self.warning = ""
        self.displayName = ""

    def appendChild(self, node: SidebarNode):
        assert self.mayHaveChildren()
        assert self is not node
        assert not node.parent
        node.row = len(self.children)
        node.parent = self
        self.children.append(node)

    def findChild(self, kind: SidebarItem, data: str = "") -> SidebarNode:
        """ Warning: this is inefficient - don't use this if there are many children! """
        assert self.mayHaveChildren()
        with suppress(StopIteration):
            return next(c for c in self.children if c.kind == kind and c.data == data)
        raise KeyError("child node not found")

    def createIndex(self, model: QAbstractItemModel) -> QModelIndex:
        return model.createIndex(self.row, 0, self)

    def getCollapseHash(self) -> str:
        assert self.mayHaveChildren(), "it's futile to hash a leaf"
        return f"{self.kind.name}.{self.data}"
        # Warning: it's tempting to replace this with something like "hash(data) << 8 | item",
        # but hash(data) doesn't return stable values across different Python sessions,
        # so it's not suitable for persistent storage (in history.json).

    def mayHaveChildren(self):
        return self.kind in SidebarLayout.NonleafItems

    def wantForceExpand(self):
        return self.kind in SidebarLayout.ForceExpand

    def canBeHidden(self):
        return self.kind in SidebarLayout.HideableItems

    def walk(self):
        # Unit test helper
        frontier = self.children[:]
        while frontier:
            node = frontier.pop(0)
            yield node
            frontier.extend(node.children)

    def isSimilarEnoughTo(self, other: SidebarNode):
        """ Use this to compare SidebarNodes from two different models. """
        return self.kind == other.kind and self.data == other.data

    def __repr__(self):
        return f"SidebarNode({self.kind.name} {self.data})"


class SidebarModel(QAbstractItemModel):
    repoModel: RepoModel
    rootNode: SidebarNode
    nodesByRef: dict[str, SidebarNode]
    _unbornHead: str

    _checkedOut: str
    "Shorthand of checked-out local branch"

    _checkedOutUpstream: str
    "Shorthand of the checked-out branch's upstream"

    _cachedTooltipIndex: QModelIndex
    _cachedTooltipText: str

    collapseCache: set[str]
    collapseCacheValid: bool

    class Role:
        Ref = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 0)
        IconKey = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)

    @property
    def _parentWidget(self) -> QWidget:
        return QObject.parent(self)

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    def __init__(self, parent=None):
        super().__init__(parent)

        self.collapseCache = set()
        self.collapseCacheValid = False

        self.clear()

        if settings.DEVDEBUG and HAS_QTEST:
            self.modelTester = QAbstractItemModelTester(self)
            if not settings.TEST_MODE:
                logger.warning("Sidebar model tester enabled. This will SIGNIFICANTLY slow down SidebarModel.rebuild!")

    def clear(self, emitSignals=True):
        # IMPORTANT: Do not clear collapseCache in this function!
        # rebuild() calls clear() but we want collapseCache to persist!

        if emitSignals:
            self.beginResetModel()

        self.repoModel = None
        self.rootNode = SidebarNode(SidebarItem.Root)
        self.nodesByRef = {}
        self._checkedOut = ""
        self._checkedOutUpstream = ""

        self._cachedTooltipIndex = QModelIndex_default
        self._cachedTooltipText = ""

        if emitSignals:
            self.endResetModel()

    def isExplicitlyHidden(self, node: SidebarNode) -> bool:
        if node.kind == SidebarItem.LocalBranch or node.kind == SidebarItem.RemoteBranch:
            return node.data in self.repoModel.prefs.hiddenRefPatterns
        elif node.kind == SidebarItem.Remote:
            return f"{RefPrefix.REMOTES}{node.data}/" in self.repoModel.prefs.hiddenRefPatterns
        elif node.kind == SidebarItem.RefFolder:
            return f"{node.data}/" in self.repoModel.prefs.hiddenRefPatterns
        else:
            return False

    def isImplicitlyHidden(self, node: SidebarNode) -> bool:
        if node.kind == SidebarItem.LocalBranch or node.kind == SidebarItem.RemoteBranch:
            return node.data in self.repoModel.hiddenRefs and node.data not in self.repoModel.prefs.hiddenRefPatterns
        else:
            return False

    def isAncestryChainExpanded(self, node: SidebarNode):
        # Assume everything is expanded if collapse cache is missing (see restoreExpandedItems).
        if not self.collapseCacheValid:
            return True

        # My collapsed state doesn't matter here - it only affects my children.
        # So start looking at my parent.
        node = node.parent
        assert node is not None

        # Walk up parent chain until root index (row -1)
        while node.parent is not None:
            h = node.getCollapseHash()
            if h in self.collapseCache:
                return False
            node = node.parent

        return True

    def onIndexExpanded(self, index: QModelIndex):
        node = SidebarNode.fromIndex(index)
        h = node.getCollapseHash()
        self.collapseCache.discard(h)

    def onIndexCollapsed(self, index: QModelIndex):
        node = SidebarNode.fromIndex(index)
        h = node.getCollapseHash()
        self.collapseCache.add(h)

    def refreshRepoName(self):
        if self.rootNode and self.repoModel:
            workdirNode = self.rootNode.findChild(SidebarItem.WorkdirHeader)
            workdirNode.displayName = settings.history.getRepoNickname(self.repo.workdir)

    @benchmark
    def rebuild(self, repoModel: RepoModel):
        self.beginResetModel()

        repo = repoModel.repo

        self.clear(emitSignals=False)
        self.repoModel = repoModel
        self.nodesByRef = {}

        # Pending ref shorthands for _makeRefTreeNodes
        localBranches = []
        remoteBranchesDict: dict[str, list[str]] = {}
        tags = []

        # -----------------------------
        # Set up root nodes
        # -----------------------------
        rootNode = SidebarNode(SidebarItem.Root)
        for eitem in SidebarLayout.RootItems:
            rootNode.appendChild(SidebarNode(eitem))
        uncommittedNode = rootNode.findChild(SidebarItem.UncommittedChanges)
        branchRoot = rootNode.findChild(SidebarItem.LocalBranchesHeader)
        remoteRoot = rootNode.findChild(SidebarItem.RemotesHeader)
        tagRoot = rootNode.findChild(SidebarItem.TagsHeader)
        submoduleRoot = rootNode.findChild(SidebarItem.SubmodulesHeader)
        stashRoot = rootNode.findChild(SidebarItem.StashesHeader)

        self.rootNode = rootNode
        self.nodesByRef[UC_FAKEREF] = uncommittedNode

        self.refreshRepoName()

        # -----------------------------
        # HEAD
        # -----------------------------
        try:
            # Try to get the name of the checked-out branch
            checkedOut = repo.head.name

        except GitError:
            # Unborn HEAD - Get name of unborn branch
            assert repo.head_is_unborn
            target = repo.lookup_reference("HEAD").target
            assert isinstance(target, str), "Unborn HEAD isn't a symbolic reference!"
            target = target.removeprefix(RefPrefix.HEADS)
            node = SidebarNode(SidebarItem.UnbornHead, target)
            branchRoot.appendChild(node)
            self.nodesByRef["HEAD"] = node

        else:
            # It's not unborn
            if checkedOut == 'HEAD':
                # Detached head, leave self._checkedOut blank
                assert repo.head_is_detached
                node = SidebarNode(SidebarItem.DetachedHead, str(repo.head.target))
                branchRoot.appendChild(node)
                self.nodesByRef["HEAD"] = node

            else:
                # We're on a branch
                assert checkedOut.startswith(RefPrefix.HEADS)
                checkedOut = checkedOut.removeprefix(RefPrefix.HEADS)
                self._checkedOut = checkedOut

                # Try to get the upstream (.upstream_name raises KeyError if there isn't one)
                with suppress(KeyError):
                    branch = repo.branches.local[checkedOut]
                    upstream = branch.upstream_name  # This can be a bit expensive
                    upstream = upstream.removeprefix(RefPrefix.REMOTES)  # Convert to shorthand
                    self._checkedOutUpstream = upstream

        # -----------------------------
        # Remotes
        # -----------------------------
        for name in repoModel.remotes:
            remoteBranchesDict[name] = []
            node = SidebarNode(SidebarItem.Remote, name)
            remoteRoot.appendChild(node)

        # -----------------------------
        # Refs
        # -----------------------------
        for name in reversed(repoModel.refs):  # reversed because refCache sorts tips by ASCENDING commit time
            prefix, shorthand = RefPrefix.split(name)

            if prefix == RefPrefix.HEADS:
                localBranches.append(shorthand)
                # We're not caching upstreams because it's very expensive to do

            elif prefix == RefPrefix.REMOTES:
                remote, branchName = split_remote_branch_shorthand(shorthand)
                try:
                    remoteBranchesDict[remote].append(branchName)
                except KeyError:
                    warnings.warn(f"SidebarModel: missing remote: {remote}")

            elif prefix == RefPrefix.TAGS:
                tags.append(shorthand)

            elif name == "HEAD" or name.startswith("stash@{"):
                pass  # handled separately

            else:
                warnings.warn(f"SidebarModel: unsupported ref prefix: {name}")

        # Populate local branch tree
        self.populateRefNodeTree(localBranches, branchRoot, SidebarItem.LocalBranch, RefPrefix.HEADS, repoModel.prefs.sortBranches)

        # Populate tag tree
        self.populateRefNodeTree(tags, tagRoot, SidebarItem.Tag, RefPrefix.TAGS, repoModel.prefs.sortTags)

        # Populate remote tree
        for remote, branches in remoteBranchesDict.items():
            remoteNode = remoteRoot.findChild(SidebarItem.Remote, remote)
            assert remoteNode is not None
            remotePrefix = f"{RefPrefix.REMOTES}{remote}/"
            self.populateRefNodeTree(branches, remoteNode, SidebarItem.RemoteBranch, remotePrefix, repoModel.prefs.sortRemoteBranches)

        # -----------------------------
        # Stashes
        # -----------------------------
        for i, stashCommitId in enumerate(repoModel.stashes):
            message = repo[stashCommitId].message
            message = strip_stash_message(message)
            refName = f"stash@{{{i}}}"
            node = SidebarNode(SidebarItem.Stash, str(stashCommitId))
            node.displayName = message
            stashRoot.appendChild(node)
            self.nodesByRef[refName] = node

        # -----------------------------
        # Submodules
        # -----------------------------
        for submoduleKey in repoModel.submodules:
            node = SidebarNode(SidebarItem.Submodule, submoduleKey)
            submoduleRoot.appendChild(node)

            if submoduleKey not in repoModel.initializedSubmodules:
                node.warning = _("Submodule not initialized.")

        # -----------------------------
        # Commit new model
        # -----------------------------
        self.endResetModel()

    def populateRefNodeTree(self, shorthands: list[str], containerNode: SidebarNode, kind: SidebarItem, refNamePrefix: str, sortMode: RefSort = RefSort.Default):
        pendingFolders: dict[str, SidebarNode] = {}

        shIter: Iterable[str]
        if sortMode == RefSort.TimeAsc:
            shIter = reversed(shorthands)
        elif sortMode == RefSort.AlphaAsc:
            shIter = sorted(shorthands, key=naturalSort)
        elif sortMode == RefSort.AlphaDesc:
            shIter = sorted(shorthands, key=naturalSort, reverse=True)
        else:
            shIter = shorthands

        for sh in shIter:
            if not BRANCH_FOLDERS or "/" not in sh:
                folderNode = containerNode
            else:
                folderName = sh.rsplit("/", 1)[0]
                try:
                    folderNode = pendingFolders[folderName]
                except KeyError:
                    # Create node for folder, but add it to containerNode later
                    # so that all folders are grouped together.
                    folderNode = SidebarNode(SidebarItem.RefFolder, refNamePrefix + folderName)
                    pendingFolders[folderName] = folderNode

            refName = refNamePrefix + sh
            node = SidebarNode(kind, refName)
            folderNode.appendChild(node)
            self.nodesByRef[refName] = node

        for folderName, folderNode in pendingFolders.items():
            parts = folderName.split("/")
            parts.pop()
            while parts:
                parentFolder = "/".join(parts)
                try:
                    parentNode = pendingFolders[parentFolder]
                    parentNode.appendChild(folderNode)
                    folderNode.displayName = folderNode.data.removeprefix(parentNode.data)
                    break
                except KeyError:
                    parts.pop()
            else:
                folderNode.displayName = folderNode.data.removeprefix(refNamePrefix)
                containerNode.appendChild(folderNode)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex_default) -> QModelIndex:
        # Return an index given a parent and a row (i.e. child number within parent)

        assert column == 0
        assert row >= 0

        if not parent.isValid():
            parentNode = self.rootNode
        else:
            parentNode = SidebarNode.fromIndex(parent)

        node = parentNode.children[row]
        assert node.row == row

        return node.createIndex(self)

    def parent(self, index: QModelIndex) -> QModelIndex:
        # Return the parent of the given index

        # No repo or root node: no parent
        if not index.isValid():
            return QModelIndex()

        # Get parent node
        node = SidebarNode.fromIndex(index)
        node = node.parent
        assert node is not None

        # Blank index for children of root node
        if node is self.rootNode:
            return QModelIndex()

        return node.createIndex(self)

    def rowCount(self, parent: QModelIndex = QModelIndex_default) -> int:
        if not parent.isValid():  # root
            node = self.rootNode
        else:
            node = SidebarNode.fromIndex(parent)
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex_default) -> int:
        return 1

    def cacheTooltip(self, index: QModelIndex, text: str):
        self._cachedTooltipIndex = index
        self._cachedTooltipText = text

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        # Tooltips may show information that is expensive to obtain.
        # Try to reuse any tooltip that we may have cached for the same index.
        if role == Qt.ItemDataRole.ToolTipRole and index == self._cachedTooltipIndex:
            return self._cachedTooltipText

        node = SidebarNode.fromIndex(index)
        assert node is not None

        displayRole = role == Qt.ItemDataRole.DisplayRole
        toolTipRole = role == Qt.ItemDataRole.ToolTipRole
        sizeHintRole = role == Qt.ItemDataRole.SizeHintRole
        fontRole = role == Qt.ItemDataRole.FontRole
        refRole = role == SidebarModel.Role.Ref
        iconKeyRole = role == SidebarModel.Role.IconKey

        row = index.row()
        item = node.kind

        if item == SidebarItem.Spacer:
            pass

        elif item == SidebarItem.LocalBranch:
            refName = node.data
            branchName = refName.removeprefix(RefPrefix.HEADS)
            if displayRole:
                if not BRANCH_FOLDERS:
                    return branchName
                return branchName.rsplit("/", 1)[-1]
            elif refRole:
                return refName
            elif toolTipRole:
                text = "<p style='white-space: pre'>"
                text += _("{0} (local branch)", btag(branchName))
                # Try to get the upstream (branch.upstream_name raises KeyError if there isn't one)
                # Warning: branch.upstream_name can be a bit expensive
                with suppress(KeyError):
                    branch = self.repo.branches.local[branchName]
                    upstream = branch.upstream_name.removeprefix(RefPrefix.REMOTES)
                    text += "\n" + _("Upstream: {0}", escape(upstream))
                if branchName == self._checkedOut:
                    text += "\n<img src='assets:icons/git-head' style='vertical-align: bottom;'/> "
                    text += "HEAD " + _("(this is the checked-out branch)")
                self.cacheTooltip(index, text)
                return text
            elif iconKeyRole:
                return "git-branch" if branchName != self._checkedOut else "git-head"

        elif item == SidebarItem.UnbornHead:
            target = node.data
            if displayRole:
                return _("[unborn]") + " " + target
            elif toolTipRole:
                text = ("<p style='white-space: pre'>"
                        + _("Unborn HEAD: does not point to a commit yet.") + "\n"
                        + _("Local branch {0} will be created when you create the initial commit.", bquo(target)))
                self.cacheTooltip(index, text)
                return text

        elif item == SidebarItem.DetachedHead:
            if displayRole:
                return _("Detached HEAD")
            elif toolTipRole:
                oid = Oid(hex=node.data)
                caption = _("Detached HEAD")
                return f"<p style='white-space: pre'>{caption} @ {shortHash(oid)}"
            elif refRole:
                return "HEAD"
            elif iconKeyRole:
                return "git-head-detached"

        elif item == SidebarItem.Remote:
            remoteName = node.data
            if displayRole:
                return remoteName
            elif toolTipRole:
                url = self.repo.remotes[remoteName].url
                return "<p style='white-space: pre'>" + escape(url)
            elif iconKeyRole:
                return "git-remote"

        elif item == SidebarItem.RemoteBranch:
            refName = node.data
            shorthand = refName.removeprefix(RefPrefix.REMOTES)
            remoteName, branchName = split_remote_branch_shorthand(shorthand)
            if displayRole:
                if not BRANCH_FOLDERS:
                    return branchName
                return branchName.rsplit("/", 1)[-1]
            elif refRole:
                return refName
            elif toolTipRole:
                text = "<p style='white-space: pre'>"
                text += _("{0} (remote-tracking branch)", btag(shorthand))
                if self._checkedOutUpstream == shorthand:
                    text += "<br><i>" + _("Upstream for the checked-out branch ({0})", hquoe(self._checkedOut))
                return text
            elif fontRole:
                if self._checkedOutUpstream == shorthand:
                    font = QFont(self._parentWidget.font())
                    font.setItalic(True)
                    return font
                else:
                    return None
            elif iconKeyRole:
                return "git-branch"

        elif item == SidebarItem.RefFolder:
            refName = node.data
            if displayRole:
                return node.displayName
            elif toolTipRole:
                prefix, name = RefPrefix.split(refName)
                text = "<p style='white-space: pre'>"
                text += "<img src='assets:icons/git-folder' style='vertical-align: bottom;'/> "
                if prefix == RefPrefix.REMOTES:
                    text += _("{0} (remote branch folder)", btag(name))
                elif prefix == RefPrefix.TAGS:
                    text += _("{0} (tag folder)", btag(name))
                else:
                    text += _("{0} (local branch folder)", btag(name))
                return text
            elif iconKeyRole:
                return "git-folder"

        elif item == SidebarItem.Tag:
            refName = node.data
            tagName = refName.removeprefix(RefPrefix.TAGS)
            if displayRole:
                if not BRANCH_FOLDERS:
                    return tagName
                return tagName.rsplit("/", 1)[-1]
            elif refRole:
                return refName
            elif toolTipRole:
                text = "<p style='white-space: pre'>"
                text += _("Tag {0}", bquo(tagName))
                return text
            elif iconKeyRole:
                return "git-tag"

        elif item == SidebarItem.Stash:
            if displayRole:
                return node.displayName
            elif refRole:
                return F"stash@{{{row}}}"
            elif toolTipRole:
                oid = Oid(hex=node.data)
                commit = self.repo.peel_commit(oid)
                dateText = signatureDateFormat(commit.committer, settings.prefs.shortTimeFormat)
                text = "<p style='white-space: pre'>"
                text += f"<b>stash@{{{row}}}</b>: {escape(commit.message)}<br/>"
                text += f"<b>{_('date:')}</b> {escape(dateText)}"
                self.cacheTooltip(index, text)
                return text
            elif iconKeyRole:
                return "git-stash"

        elif item == SidebarItem.Submodule:
            if displayRole:
                return node.data.rsplit("/", 1)[-1]
            elif toolTipRole:
                text = "<p style='white-space: pre'>"
                text += _("{0} (submodule)", f"<b>{escape(node.data)}</b>")
                text += "\n" + _("Workdir: {0}", escape(self.repo.listall_submodules_dict()[node.data]))
                url = self.repo.submodules[node.data].url or _("[not set]")
                text += "\n" + _("URL: {0}", escape(url))
                if node.warning:
                    text += "<br>\u26a0 " + node.warning
                return text
            elif iconKeyRole:
                return "achtung" if node.warning else "git-submodule"

        elif item == SidebarItem.UncommittedChanges:
            if displayRole:
                changesText = TrTables.enum(SidebarItem.UncommittedChanges)
                numUncommittedChanges = self.repoModel.numUncommittedChanges
                if numUncommittedChanges >= 0:
                    ucSuffix = f" ({numUncommittedChanges})"
                    changesText = changesText.replace("\x9C", ucSuffix + "\x9C") + ucSuffix
                return changesText
            elif refRole:
                # Return fake ref so we can select Uncommitted Changes from elsewhere
                return UC_FAKEREF
            elif iconKeyRole:
                return "git-workdir"
            elif toolTipRole:
                tip = _("Go to Working Directory")
                tip = appendShortcutToToolTipText(tip, QKeySequence("Ctrl+G"))
                if self.repoModel.numUncommittedChanges >= 0:
                    tip += "\n" + _n("({n} uncommitted change)", "({n} uncommitted changes)",
                                     self.repoModel.numUncommittedChanges)
                return tip

        else:
            if displayRole:
                if item == SidebarItem.WorkdirHeader:
                    return node.displayName
                elif item == SidebarItem.LocalBranchesHeader:
                    return TrTables.enum(item)
                else:
                    name = TrTables.enum(item)
                    if node.getCollapseHash() in self.collapseCache:
                        name += f" ({len(node.children)})"
                    return name
            elif refRole:
                return ""
            elif fontRole:
                font = self._parentWidget.font()
                font.setWeight(QFont.Weight.DemiBold)
                return font

        # fallback
        if sizeHintRole:
            return QSize(-1, int(1.2 * self._parentWidget.fontMetrics().height()))

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        node = SidebarNode.fromIndex(index)

        if node.kind == SidebarItem.Spacer:
            return Qt.ItemFlag.ItemNeverHasChildren

        if node.kind in SidebarLayout.ForceExpand:
            return Qt.ItemFlag.NoItemFlags

        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        if not node.mayHaveChildren():
            assert not node.children
            f |= Qt.ItemFlag.ItemNeverHasChildren

        return f
