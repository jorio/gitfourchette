# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from contextlib import suppress
from collections.abc import Iterable

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.forms.commitfilesearchbar import CommitFileSearchBar
from gitfourchette.forms.searchbar import SearchBar, SearchResultsNotReady
from gitfourchette.graph import MockCommit
from gitfourchette.graphview.commitlogdelegate import CommitLogDelegate
from gitfourchette.graphview.commitlogfilter import CommitLogFilter
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, GpgStatus, RepoModel
from gitfourchette.tasks import *
from gitfourchette.tasks.exporttasks import ExportABDiffAsPatch
from gitfourchette.toolbox import *


class GraphView(QListView):
    SearchPathspecPrefix = "/f"

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
        self.navLocator = NavLocator.Empty

        # Use tabular numbers (ISO dates look better with Inter, Cantarell, etc.)
        self.setFont(setFontFeature(self.font(), "tnum"))

        self.clModel = CommitLogModel(repoModel, self)
        self.clFilter = CommitLogFilter(repoModel, self)
        self.clFilter.setSourceModel(self.clModel)

        self.setModel(self.clFilter)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Massive perf boost when displaying/updating huge commit logs
        self.setUniformItemSizes(True)

        self.repoWidget = parent
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # prevents double-clicking to edit row text

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onContextMenuRequested)

        # --------------
        # SearchBar

        searchPlaceholder = "|".join([
            _("Find commit hash, message or author. Type {f} to find commits touching files."),
            _("Find commit ({f} to find files in commits)"),
            _("Find commit")])
        searchPlaceholder = searchPlaceholder.format(f=tquo(self.SearchPathspecPrefix))
        searchPlaceholder = toLengthVariants(searchPlaceholder)

        self.searchBar = SearchBar(self, searchPlaceholder)
        self.searchBar.detectHashes = True

        self.searchBar.searchTermChanged.connect(self.onSearchBarTermChanged)
        self.searchBar.searchPulse.connect(self.onSearchBarPulse)

        self.searchBar.setUpItemViewBuddy()

        self.searchBar.hide()
        self.clFilter.rowsAboutToBeInserted.connect(self.searchBar.invalidateBadStem)

        self.commitFileSearchBar = CommitFileSearchBar(self)
        self.commitFileSearchBar.hide()

        # --------------

        self.clDelegate = CommitLogDelegate(
            self.repoModel,
            searchBar=self.searchBar,
            parent=self,
        )
        self.setItemDelegate(self.clDelegate)

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs(invalidateMetrics=False)

        # Shortcut keys (commit-file bar takes precedence when visible)
        makeWidgetShortcut(self, self._escapeSearchBars, "Escape")
        self.checkoutShortcut = makeWidgetShortcut(self, self.onReturnKey, "Return", "Enter")
        self.copyHashShortcut = makeWidgetShortcut(self, self.copyCommitHashToClipboard, QKeySequence.StandardKey.Copy)
        self.copyMessageShortcut = makeWidgetShortcut(self, self.copyCommitMessageToClipboard, "Ctrl+Shift+C")
        self.getInfoShortcut = makeWidgetShortcut(self, self.getInfoOnCurrentCommit, "Space")

    def _escapeSearchBars(self):
        if self.commitFileSearchBar.isVisible():
            self.commitFileSearchBar.bail()
        else:
            self.searchBar.hideOrBeep()

    def mouseMoveEvent(self, event: QMouseEvent):
        """
        By default, ExtendedSelection lets the user select multiple items by
        holding down LMB and dragging. This event handler enforces single-item
        selection unless the user holds down Shift or Ctrl.
        """
        isLMB = bool(event.buttons() & Qt.MouseButton.LeftButton)
        isShift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        isCtrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if isLMB and not isShift and not isCtrl:
            self.mousePressEvent(event)  # re-route event as if it were a click event
            self.scrollTo(self.indexAt(event.pos()))  # mousePressEvent won't scroll to the item on its own
        else:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        currentIndex = self.currentIndex()
        if (not currentIndex.isValid()
                or event.button() != Qt.MouseButton.LeftButton
                or event.modifiers() != Qt.KeyboardModifier.NoModifier):
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
        # TODO: The only remaining uses of this function are in unit tests. Remove?
        if self.navLocator.context == NavContext.COMMITTED:
            return SpecialRow.Commit
        elif self.navLocator.context.isWorkdir():
            return SpecialRow.UncommittedChanges
        elif self.navLocator.context == NavContext.SPECIAL:
            return SpecialRow.fromString(self.navLocator.path)
        else:
            return SpecialRow.Invalid

    @property
    def currentCommitId(self) -> Oid | None:
        # TODO: If pygit2 had Oid.__bool__() which returned True if the hash isn't NULL_OID,
        #       we wouldn't have to return None for compatibility with existing code
        #       (pygit2 1.18.0+ has this now)
        if self.navLocator.context == NavContext.COMMITTED:
            return self.navLocator.commit
        else:
            return None

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

        # Don't bother with the jump if our signals are blocked
        if self.signalsBlocked():
            return

        locator = self.locatorFromSelection()
        if not locator:
            return

        locator = locator.withExtraFlags(NavFlags.BypassCommitSelect)
        Jump.invoke(self, locator)

    def locatorFromSelection(self):
        # Warning: selection not sorted!
        indexes = self.selectedIndexes()
        if not indexes:
            return NavLocator.Empty

        # Get the "last" selected index.
        # Note that currentIndex() may return an index outside the selection!
        current = self.currentIndex()
        if not current.isValid() or current not in indexes:
            current = indexes[-1]
        assert current.isValid()

        special = current.data(CommitLogModel.Role.SpecialRow)
        if special == SpecialRow.UncommittedChanges:
            locator = NavLocator.inWorkdir()
        elif special == SpecialRow.Commit:
            oid = current.data(CommitLogModel.Role.Oid)
            locator = NavLocator.inCommit(oid)
        else:
            locator = NavLocator.inSpecial(special)

        # Handle multiple selected rows
        if len(indexes) > 1:
            originalCommit = locator.commit

            # A/B diffing only allowed if exactly two commits are selected
            twoSelected = len(indexes) == 2

            # When initiating an A/B diff, ensure the "B" side comes out on top
            # regardless of the order in which the selection was made.
            if twoSelected:
                indexes.sort(key=lambda i: i.row(), reverse=True)

            # Get commit oids
            oids = tuple(i.data(CommitLogModel.Role.Oid) for i in indexes)

            if not twoSelected:
                locator = NavLocator.inSpecial(SpecialRow.TooManyRowsSelected)
            elif any(o in (UC_FAKEID, None) for o in oids):
                # Both oids must be valid commit oids
                locator = NavLocator.inSpecial(SpecialRow.CannotCompareRows)

            # Keep track of selected/current rows
            locator = locator.replace(selectedCommits=oids, commit=originalCommit)

        return locator

    def selectRowForLocator(self, locator: NavLocator):
        # Keep scroll position if we're re-selecting the same row
        same = locator.isSimilarEnoughTo(self.navLocator, considerPaths=False)
        vpos = self.verticalScrollBar().sliderPosition()

        # Save locator as current
        self.navLocator = locator

        # Update A/B commits in model
        commitDiffAB = locator.commitDiffAB()
        if commitDiffAB != self.clModel.commitDiffAB:
            self.clModel.commitDiffAB = commitDiffAB
            self.viewport().update()  # Redraw A/B icons (or lack thereof)

        # Bail if this call originates from a user click (selection already correct)
        if locator.hasFlags(NavFlags.BypassCommitSelect):
            return

        # Get index for main selected row
        filterIndex = self.getFilterIndexForLocator(locator)

        # Update selection model
        with QSignalBlockerContext(self):  # DON'T emit jump signal
            sm = self.selectionModel()
            sm.clear()

            # Multiple selected commits
            for sc in locator.selectedCommits:
                fi = self.getFilterIndexForCommit(sc)
                sm.select(fi, QItemSelectionModel.SelectionFlag.Select)

            # Set current index (i.e. keyboard focus) on main selected row.
            # This automatically scrolls the row into view.
            sm.setCurrentIndex(filterIndex, QItemSelectionModel.SelectionFlag.Select)

        if same:
            self.verticalScrollBar().setSliderPosition(vpos)

    def getFilterIndexForLocator(self, locator: NavLocator) -> QModelIndex:
        if locator.context == NavContext.COMMITTED:
            index = self.getFilterIndexForCommit(locator.commit)
            assert index.data(CommitLogModel.Role.SpecialRow) == SpecialRow.Commit
            return index

        if locator.context.isWorkdir():
            index = self.clFilter.index(0, 0)
            if index.data(CommitLogModel.Role.SpecialRow) != SpecialRow.UncommittedChanges:
                # Workdir row is being filtered out
                raise self.SelectCommitError(None, True, False)
            return index

        if locator.context == NavContext.SPECIAL:
            special = SpecialRow.fromString(locator.path)

            # Multi-selection error pages: use main commit row
            if special in (SpecialRow.CannotCompareRows, SpecialRow.TooManyRowsSelected):
                return self.getFilterIndexForCommit(locator.commit)

            # Last row
            if self.clModel._extraRow != special:
                raise GraphView.SelectCommitError(None, False, False)
            index = self.clFilter.index(self.clFilter.rowCount()-1, 0)
            assert index.data(CommitLogModel.Role.SpecialRow) == special
            return index

        raise NotImplementedError(f"unsupported locator context {locator.context}")

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

    def isLocatorVisible(self, locator: NavLocator) -> bool:
        try:
            self.getFilterIndexForLocator(locator)
            return True
        except GraphView.SelectCommitError:
            return False

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

    def onSearchBarTermChanged(self, term: str):
        if term.startswith(self.SearchPathspecPrefix):
            self.searchBar.invalidateBadStem()  # HACK: Always invalidate badStem when changing file searches
            self.repoModel.commitPathspecFilter.clear()

    def onSearchBarPulse(self):
        term = self.searchBar.searchTerm

        if term.startswith(self.SearchPathspecPrefix):
            pathspec = term.removeprefix(self.SearchPathspecPrefix).strip()

            # Don't issue empty query if user isn't done typing
            if not pathspec:
                return

            QueryCommitsTouchingPath.invoke(self, pathspec, self.onFileSearchComplete)

    def onFileSearchComplete(self):
        self.viewport().update()
        if self.searchBar.isVisible():
            self.searchBar.pulseItemView()

    # Called from SearchBar
    def searchRows(self, rows: Iterable[int]) -> QModelIndex | None:
        term = self.searchBar.searchTerm
        assert term
        assert term == term.lower(), "search term should have been sanitized"

        if term.startswith(self.SearchPathspecPrefix):
            return self.searchRowsPathspec(rows)
        else:
            return self.searchRowsMessageHashAuthor(rows)

    def searchRowsMessageHashAuthor(self, rows: Iterable[int]):
        model = self.model()  # to filter out hidden rows, don't use self.clModel directly
        term = self.searchBar.searchTerm
        likelyHash = self.searchBar.searchTermLooksLikeHash

        for i in rows:
            index = model.index(i, 0)
            commit = model.data(index, CommitLogModel.Role.Commit)
            if commit is None or isinstance(commit, MockCommit):
                continue
            if likelyHash and str(commit.id).startswith(term):
                return index
            if term in commit.message.lower():
                return index
            if term in abbreviatePerson(commit.author, settings.prefs.authorDisplayStyle).lower():
                return index

        return None

    def searchRowsPathspec(self, rows: Iterable[int]):
        model = self.model()  # to filter out hidden rows, don't use self.clModel directly
        term = self.searchBar.searchTerm
        cpf = self.repoModel.commitPathspecFilter

        # User hasn't entered their term yet
        if not term.removeprefix(self.SearchPathspecPrefix).strip():
            return None

        # Query ongoing
        if not cpf.isReady():
            raise SearchResultsNotReady()

        for i in rows:
            index = model.index(i, 0)
            match = model.data(index, CommitLogModel.Role.PathspecMatch)
            if match:
                return index

        return None

    # -------------------------------------------------------------------------
    # Context menus

    def onContextMenuRequested(self, point: QPoint):
        actions = None
        locator = self.navLocator

        if locator.context.isWorkdir():
            actions = self._contextMenuActionsUncommittedChanges()

        elif locator.context == NavContext.COMMITTED:
            if locator.commitDiffAB():
                actions = self._contextMenuActions2Commits(locator)
            else:
                actions = self._contextMenuActions1Commit()

        elif locator.context == NavContext.SPECIAL:
            special = SpecialRow.fromString(locator.path)
            if special == SpecialRow.TruncatedHistory:
                actions = self._contextMenuActionsTruncatedHistory()

        # Fall back to no-op menu
        if actions is None:
            actions = [
                ActionDef(_("No actions available for this selection"), enabled=False)
            ]

        menu = ActionDef.makeQMenu(self, actions)
        menu.setObjectName("GraphViewCM")
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.mapToGlobal(point))

    def _contextMenuActionsUncommittedChanges(self):
        mainWindow = GFApplication.instance().mainWindow

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
        return actions

    def _contextMenuActionsTruncatedHistory(self):
        locale = self.locale()
        expandSome = makeInternalLink("expandlog")
        expandAll = makeInternalLink("expandlog", n=str(0))
        changePref = makeInternalLink("prefs", "maxCommits")
        actions = [
            ActionDef(_("Load up to {0} commits", locale.toString(self.repoModel.nextTruncationThreshold)),
                      lambda: self.linkActivated.emit(expandSome)),

            ActionDef(_("Load full commit history"),
                      lambda: self.linkActivated.emit(expandAll)),

            ActionDef(_("Change threshold setting"),
                      lambda: self.linkActivated.emit(changePref)),
        ]
        return actions

    def _contextMenuActions1Commit(self):
        mainWindow = GFApplication.instance().mainWindow
        repoModel = self.repoModel
        repo = repoModel.repo
        oid = self.currentCommitId

        myRef = lquo(repoModel.homeBranch) if repoModel.homeBranch else "HEAD"

        # Figure out a nice ref name to initiate a merge, or fall back to commit id
        try:
            refsHere = repoModel.refsAt[oid]
            mergeWhat = next(ref for ref in refsHere if ref.startswith((RefPrefix.HEADS, RefPrefix.REMOTES)))
        except (KeyError, StopIteration):
            mergeWhat = oid

        checkoutAction = TaskBook.action(self, CheckoutCommit, _("&Check Out…"), taskArgs=oid)
        checkoutAction.shortcuts = self.checkoutShortcut.key()

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
            mountActions = [ActionDef(mountCaption, icon="git-mount", callback=lambda: mounts.mount(repo.workdir, oid))]

        actions = [
            TaskBook.action(self, NewBranchFromCommit, _("New &Branch Here…"), taskArgs=oid),
            TaskBook.action(self, NewTag, _("&Tag This Commit…"), taskArgs=oid),
            ActionDef.SEPARATOR,
            checkoutAction,
            TaskBook.action(self, MergeBranch, _("&Merge into {0}…", myRef), taskArgs=(mergeWhat,)),
            TaskBook.action(self, ResetHead, _("&Reset {0} to Here…", myRef), taskArgs=oid),
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
        return actions

    def _contextMenuActions2Commits(self, locator: NavLocator):
        diffAB = locator.commitDiffAB()

        actions = [
            ActionDef(_("&Swap A/B"),
                      lambda: Jump.invoke(self, locator.swapABCommits())),

            ActionDef(_("E&xport A/B Diff As Patch…"),
                      lambda: ExportABDiffAsPatch.invoke(self, diffAB))
        ]
        return actions
