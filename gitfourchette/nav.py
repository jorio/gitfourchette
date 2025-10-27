# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import enum
import time
from typing import ClassVar

from gitfourchette.localization import *
from gitfourchette.porcelain import NULL_OID, Oid
from gitfourchette.qt import *
from gitfourchette.toolbox import *

PUSH_INTERVAL = 0.5


class NavFlags(enum.IntFlag):
    ForceDiff = enum.auto()
    "Force reloading the pygit2.Diff of the commit or workdir."

    ForceRecreateDocument = enum.auto()
    "Force re-rendering the DiffDocument."

    AllowWriteIndex = enum.auto()
    "Allow writing to the index while loading the diff at this location."

    AllowLargeFiles = enum.auto()
    "Bypass file size and line length limits to display the diff at this location."

    AllowMultiSelect = enum.auto()
    "Don't reset the selection when loading this location."

    ActivateWindow = enum.auto()
    "Bring window to the foreground after jumping to this location."

    DefaultFlags = 0


@enum.unique
class NavContext(enum.IntEnum):
    """
    State of a patch in the staging pipeline
    """

    EMPTY       = 0
    COMMITTED   = 1
    WORKDIR     = 2
    UNTRACKED   = 3
    UNSTAGED    = 4
    STAGED      = 5
    SPECIAL     = 6

    def isWorkdir(self):
        return self == NavContext.WORKDIR or self == NavContext.UNTRACKED or self == NavContext.UNSTAGED or self == NavContext.STAGED

    def isDirty(self):
        return self == NavContext.UNTRACKED or self == NavContext.UNSTAGED

    def translateName(self):
        names = {
            NavContext.EMPTY: _p("NavContext", "Empty"),
            NavContext.UNTRACKED: _p("NavContext", "Untracked"),
            NavContext.UNSTAGED: _p("NavContext", "Unstaged"),
            NavContext.STAGED: _p("NavContext", "Staged"),
            NavContext.COMMITTED: _p("NavContext", "Committed"),
        }
        return names.get(self, _p("NavContext", "Unknown"))


@dataclasses.dataclass(frozen=True)
class NavLocator:
    """
    Resource locator within a repository.
    Used to navigate the UI to a specific area of a repository.
    """

    Empty: ClassVar[NavLocator]

    context: NavContext = NavContext.EMPTY
    commit: Oid = NULL_OID
    path: str = ""
    ref: str = ""

    cursorChar: int = 0
    """
    Character position of the text cursor.
    """

    cursorLine: int = 0
    """
    Line number of the text cursor. CodeView will attempt to keep the cursor on
    this line in case of a mismatch with `cursorChar` (which may occur when file
    contents change in the workdir).
    """

    scrollChar: int = 0
    """
    Character position of the top-left corner in the scrollable viewport.
    """

    flags: NavFlags = NavFlags.DefaultFlags  # WARNING: Those are not saved in history

    URL_AUTHORITY: ClassVar[str] = "jump"

    if APP_DEBUG:
        def __post_init__(self):
            assert not self.path.endswith("/")
            assert isinstance(self.context, NavContext)
            assert isinstance(self.commit, Oid)
            assert isinstance(self.path, str)
            assert isinstance(self.ref, str)
            hasCommit = self.commit != NULL_OID
            hasRef = bool(self.ref)
            if self.context == NavContext.COMMITTED:
                assert hasCommit or hasRef
                assert hasCommit ^ hasRef
                assert not hasRef or self.ref == "HEAD" or self.ref.startswith("refs/")
            else:
                assert not hasCommit
                assert not hasRef

    def __bool__(self):
        """
        Return True if the locator's context is anything but EMPTY.

        The locator is NOT considered empty when the path is empty but the context isn't
        (e.g. in the STAGED context, with no files selected.)
        """
        return self.context.value != NavContext.EMPTY

    def __repr__(self) -> str:
        return F"{self.__class__.__name__}({self.contextKey:.8} {self.path})"

    @staticmethod
    def inCommit(oid: Oid, path: str = ""):
        return NavLocator(context=NavContext.COMMITTED, commit=oid, path=path)

    @staticmethod
    def inRef(ref: str, path: str = ""):
        return NavLocator(context=NavContext.COMMITTED, ref=ref, path=path)

    @staticmethod
    def inUnstaged(path: str = ""):
        return NavLocator(context=NavContext.UNSTAGED, path=path)

    @staticmethod
    def inStaged(path: str = ""):
        return NavLocator(context=NavContext.STAGED, path=path)

    @staticmethod
    def inWorkdir():
        return NavLocator(context=NavContext.WORKDIR)

    def isSimilarEnoughTo(self, other: NavLocator):
        """Coarse equality - Compare context, commit & path (ignores flags & position in diff)"""
        return (self.context == other.context
                and self.commit == other.commit
                and self.path == other.path)

    def hasFlags(self, flags: NavFlags):
        return flags == (self.flags & flags)

    def asTitle(self):
        header = self.path
        if self.context == NavContext.COMMITTED:
            header += " @ " + shortHash(self.commit)
        elif self.context.isWorkdir():
            header += " [" + self.context.translateName() + "]"
        return header

    def url(self):
        if self.context == NavContext.COMMITTED:
            fragment = str(self.commit)
        else:
            fragment = self.context.name

        query = {}
        if self.flags != NavFlags.DefaultFlags:
            query["flags"] = str(self.flags.value)

        return makeInternalLink(NavLocator.URL_AUTHORITY, self.path, fragment, **query)

    def replace(self, **kwargs) -> NavLocator:
        return dataclasses.replace(self, **kwargs)

    def coarse(self, keepFlags=False):
        flags = NavFlags.DefaultFlags if not keepFlags else self.flags
        return NavLocator(context=self.context, commit=self.commit, path=self.path, ref=self.ref, flags=flags)

    def withExtraFlags(self, flags: NavFlags) -> NavLocator:
        return self.replace(flags=self.flags | flags)

    def withoutFlags(self, flags: NavFlags) -> NavLocator:
        return self.replace(flags=self.flags & ~flags)

    @staticmethod
    def parseUrl(url: QUrl):
        assert url.authority() == NavLocator.URL_AUTHORITY
        assert url.hasFragment()

        frag = url.fragment()
        path = url.path()

        if path:  # fix up non-empty path
            assert path.startswith("/")
            path = path.removeprefix("/")

        try:
            context = NavContext[frag]
            commit = NULL_OID
        except KeyError:
            context = NavContext.COMMITTED
            commit = Oid(hex=frag)

        flags = NavFlags.DefaultFlags
        query = QUrlQuery(url.query())
        if not query.isEmpty():
            strFlags = query.queryItemValue("flags")
            flags = NavFlags(int(strFlags))

        return NavLocator(context, commit, path, flags=flags)

    @property
    def contextKey(self):
        if self.context == NavContext.SPECIAL:
            return f"@special@{self.path}"
        elif self.context != NavContext.COMMITTED:
            return self.context.name
        elif self.ref:
            return self.ref
        else:
            return str(self.commit)

    @property
    def fileKey(self):
        """ For NavHistory.recallFileInContext(). """
        return f"{self.contextKey}:{self.path}"

    @property
    def hash7(self):
        """ Return the first seven hex digits of the commit hash (unit testing helper) """
        return str(self.commit)[:7]

NavLocator.Empty = NavLocator()


class NavHistory:
    """
    History of the files that the user has viewed in a repository's commit log and workdir.
    """

    class WriteLock:
        def __init__(self):
            self.locked = False

        def __enter__(self):
            if self.locked:
                raise NotImplementedError("do not nest NavHistory.WriteLock")
            self.locked = True

        def __exit__(self, exc_type=None, exc_value=None, traceback=None):
            self.locked = False

    history: list[NavLocator]
    "Stack of position snapshots."

    current: int
    "Current position in the history stack. Hitting next/forward moves this index."

    recent: dict[str, NavLocator]
    "Most recent NavPos by context key"

    lastPushTime: float
    """Timestamp of the last modification to the history,
    to avoid pushing a million entries when dragging the mouse, etc."""

    writeLock: WriteLock
    "Context manager that prevents any changes to the history"

    def __init__(self):
        self.history = []
        self.recent = {}
        self.current = 0
        self.lastPushTime = 0.0
        self.ignoreDelay = False
        self.writeLock = NavHistory.WriteLock()

        # In a real use case, locators are dropped from the history if push()
        # calls occur in quick succession. This avoids polluting the history
        # with unimportant entries when the user drags the mouse across
        # GraphView, for instance. However, in unit tests, navigation occurs
        # blazingly quickly, but we want each location to be recorded in the
        # history.
        self.ignoreDelay |= APP_TESTMODE

    def isWriteLocked(self):
        return self.writeLock.locked

    def checkWriteLock(self):
        if self.isWriteLocked():
            raise PermissionError("history is locked")

    def push(self, pos: NavLocator):
        self.checkWriteLock()

        if not pos:
            return

        # Clear volatile flags
        if pos.flags != NavFlags.DefaultFlags:
            pos = pos.replace(flags=NavFlags.DefaultFlags)

        self.recent[pos.contextKey] = pos
        self.recent[pos.fileKey] = pos

        if pos.context in [NavContext.STAGED, NavContext.UNSTAGED]:
            # This is a "concrete" workdir locator. Redirect to it when jumping to the
            # "abstract" workdir locator (e.g. by clicking on Uncommitted Changes).
            self.recent[NavContext.WORKDIR.name] = pos

        now = time.time()
        if self.ignoreDelay:
            recentPush = False
        else:
            recentPush = (now - self.lastPushTime) < PUSH_INTERVAL

        if len(self.history) > 0 and \
                (recentPush or self.history[self.current].isSimilarEnoughTo(pos)):
            # Update in-place; don't update lastPush timestamp
            self.history[self.current] = pos
        else:
            if self.current < len(self.history) - 1:
                self.trimFuture()
            self.history.append(pos)
            self.current = len(self.history) - 1
            self.lastPushTime = now

    def trimFuture(self):
        self.checkWriteLock()
        self.history = self.history[: self.current + 1]
        assert not self.canGoForward()

    def refine(self, locator: NavLocator):
        """
        Attempt to make a locator more precise by looking up the most recent
        matching locator in the history.

        For example, given a locator with context=UNSTAGED but without a path,
        refine() will return the locator for an unstaged file that was most
        recently saved to the history.

        In addition, diff cursor/scroll positions will be filled in if the
        history contains them.

        If refining isn't possible, this function returns the same locator as
        the input.
        """

        originalLocator = locator

        # If no path is specified, attempt to recall any path in the same context
        if not locator.path:
            locator = self.recent.get(locator.contextKey, NavLocator.Empty)
            if not locator:
                locator = originalLocator

        locator = self.recent.get(locator.fileKey, NavLocator.Empty) or locator

        # Restore volatile flags
        if originalLocator.flags != locator.flags:
            locator = locator.replace(flags=originalLocator.flags)

        return locator

    def canGoForward(self):
        count = len(self.history)
        return count > 0 and self.current < count - 1

    def canGoBack(self):
        count = len(self.history)
        return count > 0 and self.current > 0

    def canGoDelta(self, delta: int):
        assert delta == -1 or delta == 1
        if delta > 0:
            return self.canGoForward()
        else:
            return self.canGoBack()

    def navigateBack(self):
        self.checkWriteLock()
        if not self.canGoBack():
            return None
        self.current -= 1
        return self.history[self.current]

    def navigateForward(self):
        self.checkWriteLock()
        if not self.canGoForward():
            return None
        self.current += 1
        return self.history[self.current]

    def navigateDelta(self, delta: int):
        assert delta == -1 or delta == 1
        if delta > 0:
            return self.navigateForward()
        else:
            return self.navigateBack()

    def popCurrent(self):
        self.checkWriteLock()
        if self.current < len(self.history):
            return self.history.pop(self.current)
        else:
            return None

    def getTextLog(self):  # pragma: no cover
        s = "------------ NAV LOG ------------"
        i = len(self.history) - 1
        for h in reversed(self.history):
            s += "\n"
            if i == self.current:
                s += "---> "
            else:
                s += "     "
            s += f"{h.contextKey[:7]} {h.path:32} {h.scrollChar} {h.cursorChar}"
            i -= 1
        return s
