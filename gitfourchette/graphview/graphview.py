# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from contextlib import suppress

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.graph import MockCommit
from gitfourchette.graphview.commitlogdelegate import CommitLogDelegate
from gitfourchette.graphview.commitlogfilter import CommitLogFilter
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, GpgStatus, RepoModel
from gitfourchette.tasks import *
from gitfourchette.toolbox import *


class GraphView(QListView):
    linkActivated = Signal(str)
    statusMessage = Signal(str)

    clModel: CommitLogModel
    clFilter: CommitLogFilter

    class SelectCommitError(KeyError):
        def __init__(self, oid: Oid, foundButHidden: bool, likelyTruncated: bool = False):
            super().__init__()
            self.oid = oid
            self.foundButHidden = foundButHidden
            self.likelyTruncated = likelyTruncated

        def __str__(self):
            if self.foundButHidden:
                m = _("This commit isn’t shown in the graph because it’s part of a hidden branch.")
            elif self.likelyTruncated:
                m = _("This commit isn’t shown in the graph because it isn’t part of the truncated commit history.")
            else:
                m = _("This commit isn’t shown in the graph.")
            return m

    def __init__(self, repoModel: RepoModel, parent):
        super().__init__(parent)

        self.repoModel = repoModel

        # Use tabular numbers (ISO dates look better with Inter, Cantarell, etc.)
        self.setFont(setFontFeature(self.font(), "tnum"))

        self.clModel = CommitLogModel(repoModel, self)
        self.clFilter = CommitLogFilter(repoModel, self)
        self.clFilter.setSourceModel(self.clModel)

        self.setModel(self.clFilter)

        # Massive perf boost when displaying/updating huge commit logs
        self.setUniformItemSizes(True)

        self.repoWidget = parent
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # prevents double-clicking to edit row text

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onContextMenuRequested)

        self.searchBar = SearchBar(self, toLengthVariants(_("Find a commit by hash, message or author|Find commit")))
        self.searchBar.detectHashes = True
        self.searchBar.setUpItemViewBuddy()
        self.searchBar.hide()
        self.clFilter.rowsAboutToBeInserted.connect(self.searchBar.invalidateBadStem)

        self.clDelegate = CommitLogDelegate(self.repoModel, searchBar=self.searchBar, parent=self)
        self.setItemDelegate(self.clDelegate)

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs(invalidateMetrics=False)

        # Shortcut keys
        makeWidgetShortcut(self, self.searchBar.hideOrBeep, "Escape")
        self.checkoutShortcut = makeWidgetShortcut(self, self.onReturnKey, "Return", "Enter")
        self.copyHashShortcut = makeWidgetShortcut(self, self.copyCommitHashToClipboard, QKeySequence.StandardKey.Copy)
        self.copyMessageShortcut = makeWidgetShortcut(self, self.copyCommitMessageToClipboard, "Ctrl+Shift+C")
        self.getInfoShortcut = makeWidgetShortcut(self, self.getInfoOnCurrentCommit, "Space")

    def makeContextMenu(self) -> QMenu:
        kind = self.currentRowKind
        oid = self.currentCommitId
        repoModel = self.repoModel
        repo = repoModel.repo
        mainWindow = GFApplication.instance().mainWindow

        mergeActions = []

        if kind == SpecialRow.UncommittedChanges:
            actions = [
                TaskBook.action(self, NewCommit, accel="C"),
                TaskBook.action(self, AmendCommit, accel="A"),
                ActionDef.SEPARATOR,
                TaskBook.action(self, NewStash, accel="S"),
                TaskBook.action(self, ExportWorkdirAsPatch, accel="X"),
            ]

            if self.repoModel.prefs.hasDraftCommit():
                actions.extend([
                    ActionDef.SEPARATOR,
                    ActionDef(_("Clear Draft Message"), self.repoModel.prefs.clearDraftCommit),
                ])

            actions.extend(mainWindow.contextualUserCommands(UserCommand.Token.Workdir))

        elif kind == SpecialRow.EndOfShallowHistory:
            actions = []

        elif kind == SpecialRow.TruncatedHistory:
            expandSome = makeInternalLink("expandlog")
            expandAll = makeInternalLink("expandlog", n=str(0))
            changePref = makeInternalLink("prefs", "maxCommits")
            actions = [
                ActionDef(_("Load up to {0} commits", QLocale().toString(repoModel.nextTruncationThreshold)),
                          lambda: self.linkActivated.emit(expandSome)),
                ActionDef(_("Load full commit history"),
                          lambda: self.linkActivated.emit(expandAll)),
                ActionDef(_("Change threshold setting"),
                          lambda: self.linkActivated.emit(changePref)),
            ]

        elif kind == SpecialRow.Commit:
            # Merge actions
            if repoModel.homeBranch:
                with suppress(KeyError, StopIteration):
                    refsHere = repoModel.refsAt[oid]
                    target = next(ref for ref in refsHere if ref.startswith((RefPrefix.HEADS, RefPrefix.REMOTES)))
                    mergeCaption = _("&Merge into {0}…", lquo(repoModel.homeBranch))
                    mergeActions = [
                        TaskBook.action(self, MergeBranch, name=mergeCaption, taskArgs=(target,)),
                    ]

            checkoutAction = TaskBook.action(self, CheckoutCommit, _("&Check Out…"), taskArgs=oid)
            checkoutAction.shortcuts = self.checkoutShortcut.key()
            resetLabel = _("&Reset {0} to Here…", lquo(repoModel.homeBranch) if repoModel.homeBranch else "HEAD")

            gpgLookAtCommit = repo.peel_commit(oid)
            gpgStatus, _gpgKeyInfo = repoModel.getCachedGpgStatus(gpgLookAtCommit)
            gpgIcon = gpgStatus.iconName()

            mounts = GFApplication.instance().mountManager
            mountCaption = _("&Mount Commit As Folder")
            if not mounts.supportsMounting():
                mountActions = []
            elif mounts.isMounted(oid):
                mountActions = [ActionDef(mountCaption, icon="git-mount", submenu=mounts.makeMenuItemsForMount(oid, self))]
            else:
                mountActions = [ActionDef(mountCaption, icon="git-mount",
                                          callback=lambda: mounts.mount(repo.path, oid))]

            actions = [
                *mergeActions,
                ActionDef.SEPARATOR,
                TaskBook.action(self, NewBranchFromCommit, _("New &Branch Here…"), taskArgs=oid),
                TaskBook.action(self, NewTag, _("&Tag This Commit…"), taskArgs=oid),
                ActionDef.SEPARATOR,
                checkoutAction,
                TaskBook.action(self, ResetHead, resetLabel, taskArgs=oid),
                ActionDef.SEPARATOR,
                TaskBook.action(self, CherrypickCommit, _("Cherry &Pick…"), taskArgs=oid),
                TaskBook.action(self, RevertCommit, _("Re&vert…"), taskArgs=oid),
                TaskBook.action(self, ExportCommitAsPatch, _("E&xport As Patch…"), taskArgs=oid),
                ActionDef.SEPARATOR,
                ActionDef(_("Copy Commit &Hash"), self.copyCommitHashToClipboard, shortcuts=self.copyHashShortcut.key()),
                ActionDef(_("Copy Commit M&essage"), self.copyCommitMessageToClipboard, shortcuts=self.copyMessageShortcut.key()),
                TaskBook.action(self, VerifyGpgSignature, taskArgs=oid, enabled=gpgStatus != GpgStatus.Unsigned, icon=gpgIcon, accel="G"),
                *mountActions,
                ActionDef(_("Get &Info…"), self.getInfoOnCurrentCommit, "SP_MessageBoxInformation", shortcuts=self.getInfoShortcut.key()),
                *mainWindow.contextualUserCommands(UserCommand.Token.Commit),
            ]

        menu = ActionDef.makeQMenu(self, actions)
        menu.setObjectName("GraphViewCM")

        return menu

    def onContextMenuRequested(self, point: QPoint):
        menu = self.makeContextMenu()
        if menu is not None:
            menu.aboutToHide.connect(menu.deleteLater)
            menu.popup(self.mapToGlobal(point))

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        currentIndex = self.currentIndex()
        if not currentIndex.isValid() or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        event.accept()
        rowKind = currentIndex.data(CommitLogModel.Role.SpecialRow)
        if rowKind == SpecialRow.UncommittedChanges:
            NewCommit.invoke(self)
        elif rowKind == SpecialRow.TruncatedHistory:
            self.linkActivated.emit(makeInternalLink("expandlog"))
        elif rowKind == SpecialRow.Commit:
            oid = self.currentCommitId
            CheckoutCommit.invoke(self, oid)

    def onReturnKey(self):
        oid = self.currentCommitId
        isValidCommit = oid and oid != UC_FAKEID
        if isValidCommit:
            CheckoutCommit.invoke(self, oid)
        else:
            NewCommit.invoke(self)

    @property
    def currentRowKind(self) -> SpecialRow:
        currentIndex = self.currentIndex()
        if not currentIndex.isValid():
            return SpecialRow.Invalid
        return currentIndex.data(CommitLogModel.Role.SpecialRow)

    @property
    def currentCommitId(self) -> Oid | None:
        # TODO: If pygit2 had Oid.__bool__() which returned True if the hash isn't NULL_OID,
        #       we wouldn't have to return None for compatibility with existing code
        #       (pygit2 1.18.0+ has this now)
        currentIndex = self.currentIndex()
        if not currentIndex.isValid():
            return None
        if SpecialRow.Commit != currentIndex.data(CommitLogModel.Role.SpecialRow):
            return None
        oid = currentIndex.data(CommitLogModel.Role.Oid)
        return oid

    def getInfoOnCurrentCommit(self):
        oid = self.currentCommitId
        if not oid:
            return
        withDebugInfo = QGuiApplication.keyboardModifiers() & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
        GetCommitInfo.invoke(self, oid, withDebugInfo)

    def copyCommitHashToClipboard(self):
        oid = self.currentCommitId
        if not oid:  # uncommitted changes
            return
        text = str(oid)
        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def copyCommitMessageToClipboard(self):
        oid = self.currentCommitId
        if not oid:  # uncommitted changes
            return
        commit = self.repoModel.repo[oid].peel(Commit)
        text = commit.message.rstrip()
        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def selectionChanged(self, selected: QItemSelection, deselected: QItemSelection):
        # do standard callback, such as scrolling the viewport if reaching the edges, etc.
        super().selectionChanged(selected, deselected)

        if selected.count() == 0:
            return

        index = selected.indexes()[0]
        self.onSetCurrent(index)

    def onSetCurrent(self, current: QModelIndex):
        if self.signalsBlocked():  # Don't bother with the jump if our signals are blocked
            return

        assert current.isValid()

        special = current.data(CommitLogModel.Role.SpecialRow)
        if special == SpecialRow.UncommittedChanges:
            locator = NavLocator(NavContext.WORKDIR)
        elif special == SpecialRow.Commit:
            oid = current.data(CommitLogModel.Role.Oid)
            locator = NavLocator(NavContext.COMMITTED, commit=oid)
        else:
            locator = NavLocator(NavContext.SPECIAL, path=str(special))

        Jump.invoke(self, locator)

    def selectRowForLocator(self, locator: NavLocator, force=False):
        filterIndex = self.getFilterIndexForLocator(locator)
        if force or filterIndex.row() != self.currentIndex().row():
            self.scrollTo(filterIndex, QAbstractItemView.ScrollHint.EnsureVisible)
            self.setCurrentIndex(filterIndex)
        return filterIndex

    def getFilterIndexForLocator(self, locator: NavLocator):
        if locator.context == NavContext.COMMITTED:
            index = self.getFilterIndexForCommit(locator.commit)
            assert index.data(CommitLogModel.Role.SpecialRow) == SpecialRow.Commit
        elif locator.context.isWorkdir():
            index = self.clFilter.index(0, 0)
            assert index.data(CommitLogModel.Role.SpecialRow) == SpecialRow.UncommittedChanges
        elif locator.context == NavContext.SPECIAL:
            assert self.clModel._extraRow != SpecialRow.Invalid, "no special row!"
            index = self.clFilter.index(self.clFilter.rowCount()-1, 0)
            assert locator.path == str(index.data(CommitLogModel.Role.SpecialRow))
        else:
            raise NotImplementedError(f"unsupported locator context {locator.context}")
        return index

    def getFilterIndexForCommit(self, oid: Oid) -> QModelIndex:
        try:
            rawIndex = self.repoModel.graph.getCommitRow(oid)
        except KeyError as exc:
            raise GraphView.SelectCommitError(oid, foundButHidden=False, likelyTruncated=self.repoModel.truncatedHistory) from exc

        newSourceIndex = self.clModel.index(rawIndex, 0)
        newFilterIndex = self.clFilter.mapFromSource(newSourceIndex)

        if not newFilterIndex.isValid():
            raise GraphView.SelectCommitError(oid, foundButHidden=True)

        return newFilterIndex

    def scrollToRowForLocator(self, locator: NavLocator, scrollHint=QAbstractItemView.ScrollHint.EnsureVisible):
        with suppress(GraphView.SelectCommitError):
            filterIndex = self.getFilterIndexForLocator(locator)
            self.scrollTo(filterIndex, scrollHint)

    def repaintCommit(self, oid: Oid):
        with suppress(GraphView.SelectCommitError):
            filterIndex = self.getFilterIndexForCommit(oid)
            self.update(filterIndex)

    def refreshPrefs(self, invalidateMetrics=True):
        self.setVerticalScrollMode(settings.prefs.listViewScrollMode)
        self.setAlternatingRowColors(settings.prefs.alternatingRowColors)

        # Force redraw to reflect changes in row height, flattening, date format, etc.
        if invalidateMetrics:
            self.itemDelegate().invalidateMetrics()
            self.model().layoutChanged.emit()

    # -------------------------------------------------------------------------
    # Find text in commit message or hash

    def searchRange(self, searchRange: range) -> QModelIndex | None:
        model = self.model()  # to filter out hidden rows, don't use self.clModel directly

        term = self.searchBar.searchTerm
        likelyHash = self.searchBar.searchTermLooksLikeHash
        assert term
        assert term == term.lower(), "search term should have been sanitized"

        for i in searchRange:
            index = model.index(i, 0)
            commit = model.data(index, CommitLogModel.Role.Commit)
            if commit is None or type(commit) is MockCommit:
                continue
            if likelyHash and str(commit.id).startswith(term):
                return index
            if term in commit.message.lower():
                return index
            if term in abbreviatePerson(commit.author, settings.prefs.authorDisplayStyle).lower():
                return index

        return None
