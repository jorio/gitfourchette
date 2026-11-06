# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import enum
import logging
import os
from collections.abc import Iterator
from contextlib import suppress
from typing import ClassVar

from gitfourchette import colors
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.exttools.toolpresets import ToolPresets
from gitfourchette.localization import *
from gitfourchette.prefsfile import PrefsFile
from gitfourchette.qt import *
from gitfourchette.syntax import PygmentsPresets, ColorScheme
from gitfourchette.toolbox.benchmark import BENCHMARK_LOGGING_LEVEL
from gitfourchette.toolbox.gitutils import AuthorDisplayStyle
from gitfourchette.toolbox.pathutils import PathDisplayStyle
from gitfourchette.toolbox.textutils import englishTitleCase

logger = logging.getLogger(__name__)


SHORT_DATE_PRESETS = {
    "ISO": "yyyy-MM-dd HH:mm",
    "Universal 1": "dd MMM yyyy HH:mm",
    "Universal 2": "ddd dd MMM yyyy HH:mm",
    "European 1": "dd/MM/yy HH:mm",
    "European 2": "dd.MM.yy HH:mm",
    "American": "M/d/yy h:mm ap",
}

SHORT_DATE_DEFAULT_PRESET = next(iter(SHORT_DATE_PRESETS.values()))


class RefSort(enum.IntEnum):
    TimeDesc = 0
    TimeAsc = 1
    AlphaAsc = 2
    AlphaDesc = 3
    UseGlobalPref = -1


class GraphRowHeight(enum.IntEnum):
    Cramped = 80
    Tight = 100
    Relaxed = 130
    Roomy = 150
    Spacious = 175


class GraphRefBoxWidth(enum.IntEnum):
    IconsOnly = 0
    Standard = 120
    Wide = 1000


class QtApiNames(enum.StrEnum):
    Automatic = ""
    PyQt6 = "pyqt6"
    PySide6 = "pyside6"
    PyQt5 = "pyqt5"


class LoggingLevel(enum.IntEnum):
    Benchmark = BENCHMARK_LOGGING_LEVEL
    Debug = logging.DEBUG
    Info = logging.INFO
    Warning = logging.WARNING


class FileListClick(enum.StrEnum):
    Nothing = ""
    Stage = "stage"
    Blame = "blame"
    Edit = "edit"
    DiffTool = "difftool"
    Folder = "folder"


class TabBarClick(enum.StrEnum):
    Nothing = ""
    Close = "close"
    Folder = "folder"
    Terminal = "terminal"


class WhitespaceMode(enum.StrEnum):
    """How `git diff` treats line endings and whitespace when showing patches."""

    Strict = ""
    IgnoreAll = "ignore-all-space"
    IgnoreChange = "ignore-space-change"
    IgnoreCrAtEol = "ignore-cr-at-eol"


@dataclasses.dataclass
class Prefs(PrefsFile):
    _filename = "prefs.json"

    _category_general           : int                   = 0
    language                    : str                   = ""
    qtStyle                     : str                   = ""
    pathDisplayStyle            : PathDisplayStyle      = PathDisplayStyle.FullPaths
    refSort                     : RefSort               = RefSort.TimeDesc
    showToolBar                 : bool                  = True
    showStatusBar               : bool                  = True
    showMenuBar                 : bool                  = True

    _category_diff              : int                   = 0
    font                        : str                   = ""
    fontSize                    : int                   = 0
    syntaxHighlighting          : str                   = PygmentsPresets.Automatic
    colorblind                  : bool                  = False
    contextLines                : int                   = 3
    tabSpaces                   : int                   = 4
    largeFileThresholdKB        : int                   = 500
    wordWrap                    : bool                  = False
    showStrayCRs                : bool                  = True
    showWhitespace              : bool                  = False
    whitespaceMode              : WhitespaceMode        = WhitespaceMode.Strict

    _category_imageDiff         : int                   = 0
    imageFileThresholdKB        : int                   = 5000
    renderSvg                   : bool                  = False

    _category_graph             : int                   = 0
    chronologicalOrder          : bool                  = True
    graphRowHeight              : GraphRowHeight        = GraphRowHeight.Relaxed
    refBoxMaxWidth              : GraphRefBoxWidth      = GraphRefBoxWidth.Standard
    authorDisplayStyle          : AuthorDisplayStyle    = AuthorDisplayStyle.FullName
    shortTimeFormat             : str                   = SHORT_DATE_DEFAULT_PRESET
    maxCommits                  : int                   = 10000
    hashesBesideGraph           : bool                  = True
    authorDiffAsterisk          : bool                  = True
    verifyGpgOnTheFly           : bool                  = False
    alternatingRowColors        : bool                  = False

    _category_git               : int                   = 0
    gitPath                     : str                   = ToolPresets.defaultGit()
    ownSshAgent                 : bool                  = False
    ownAskpass                  : bool                  = True
    lfsAware                    : bool                  = True

    _category_external          : int                   = 0
    externalEditor              : str                   = ""
    terminal                    : str                   = ToolPresets.DefaultTerminalCommand
    _spacer0                    : int                   = 0
    externalDiff                : str                   = ToolPresets.DefaultDiffCommand
    externalMerge               : str                   = ToolPresets.DefaultMergeCommand

    _category_userCommands      : int                   = 0
    commands                    : str                   = ""
    confirmCommands             : bool                  = True

    _category_tabs              : int                   = 0
    tabCloseButton              : bool                  = True
    expandingTabs               : bool                  = True
    autoHideTabs                : bool                  = False

    _category_mouseShortcuts    : int                   = 0
    _label_tabBarClicks         : int                   = 0
    doubleClickTabBar           : TabBarClick           = TabBarClick.Folder
    middleClickTabBar           : TabBarClick           = TabBarClick.Close
    _label_fileListClicks       : int                   = 0
    doubleClickFileList         : FileListClick         = FileListClick.Nothing
    middleClickFileList         : FileListClick         = FileListClick.Stage
    _label_diffViewClicks       : int                   = 0
    middleClickStageLines       : bool                  = True

    _category_trash             : int                   = 0
    maxTrashFiles               : int                   = 250
    maxTrashFileKB              : int                   = 1000

    _category_advanced          : int                   = 0
    maxRecentRepos              : int                   = 20
    shortHashChars              : int                   = 7
    autoRefresh                 : bool                  = True
    autoFetchMinutes            : int                   = 5
    flattenLanes                : bool                  = True
    animations                  : bool                  = True
    condensedFonts              : bool                  = True
    pygmentsPlugins             : bool                  = False
    verbosity                   : LoggingLevel          = LoggingLevel.Debug if APP_TESTMODE else LoggingLevel.Warning
    forceQtApi                  : QtApiNames            = QtApiNames.Automatic

    _category_hidden            : int                   = 0
    # Hide autoFetch from PrefsDialog because autoFetchMinutes's control includes a checkbox
    autoFetch                   : bool                  = False
    rememberPassphrases         : bool                  = True
    smoothScroll                : bool                  = True
    toolBarButtonStyle          : Qt.ToolButtonStyle    = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    toolBarIconSize             : int                   = 16
    defaultCloneLocation        : str                   = ""
    dontShowAgain               : list[str]             = dataclasses.field(default_factory=list)
    resetDontShowAgain          : bool                  = False
    donatePrompt                : int                   = 0
    refSortClearTimestamp       : int                   = 0
    rebaseBottomUp              : bool                  = True
    rebaseDateArg               : str                   = ""

    @property
    def listViewScrollMode(self) -> QAbstractItemView.ScrollMode:
        if self.smoothScroll:
            return QAbstractItemView.ScrollMode.ScrollPerPixel
        else:
            return QAbstractItemView.ScrollMode.ScrollPerItem

    def resolveDefaultCloneLocation(self):
        if self.defaultCloneLocation:
            return self.defaultCloneLocation

        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if path:
            return os.path.normpath(path)
        return os.path.expanduser("~")

    def monoFont(self):
        monoFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if self.font:
            monoFont.fromString(self.font)
        if self.fontSize > 0:
            monoFont.setPointSize(self.fontSize)
        return monoFont

    def calcRowHeight(self, fontMetrics: QFontMetrics):
        return fontMetrics.height() * self.graphRowHeight // 100

    def isSyntaxHighlightingEnabled(self):
        return self.syntaxHighlighting != PygmentsPresets.Off

    def syntaxHighlightingScheme(self):
        return ColorScheme.resolve(self.syntaxHighlighting)

    def addDelColors(self):
        if self.colorblind:
            return colors.teal, colors.orange
        else:
            return colors.olive, colors.red

    def addDelColorsStyleTag(self):
        green, red = self.addDelColors()
        return ("<style>"
                f"del {{ color: {red.name()}; text-decoration: none; }} "
                f"add {{ color: {green.name()}; }}"
                "</style>")

    def isGitSandboxed(self):
        return self.gitPath.startswith(ToolCommands.FlatpakSandboxedCommandPrefix)


class PrefEffects:
    RebuildMenu: ClassVar = {
        "language",
        "commands",
        "confirmCommands",
        "externalEditor"
    }
    "Pref keys that trigger a rebuild of the main menu."

    ReloadDiff: ClassVar = {
        "showStrayCRs",
        "colorblind",
        "largeFileThresholdKB",
        "imageFileThresholdKB",
        "contextLines",
        "whitespaceMode",
        "maxCommits",
        "renderSvg",
        "lfsAware",
        "syntaxHighlighting",
        "qtStyle",
    }
    "Pref keys that trigger a reload of the current diff."

    ReloadRepo: ClassVar = {
        "chronologicalOrder",
        "maxCommits",
        "refSort",
    }
    "Pref keys that fully take effect after a repo reload."

    RestartApp: ClassVar = {
        "language",
        "forceQtApi",
        "pygmentsPlugins",
    }
    "Pref keys that fully take effect after an app restart."


@dataclasses.dataclass
class History(PrefsFile):
    _filename = "history.json"

    @dataclasses.dataclass
    class JsonRepo:
        seq: int = -1
        length: int = 0
        nickname: str = ""
        superproject: str = ""

    repos: dict[str, JsonRepo] = dataclasses.field(default_factory=dict)
    cloneHistory: list[str] = dataclasses.field(default_factory=list)
    fileDialogPaths: dict[str, str] = dataclasses.field(default_factory=dict)
    startups: int = 0

    _maxSeq = -1

    @staticmethod
    def normalizeRepoPath(path: str):
        return os.path.normpath(path)

    def addRepo(self, path: str) -> JsonRepo:
        repo = self.getRepo(path)
        repo.seq = self.drawSequenceNumber()
        return repo

    def getRepo(self, path: str) -> JsonRepo:
        path = self.normalizeRepoPath(path)
        try:
            repo = self.repos[path]
        except KeyError:
            repo = History.JsonRepo()
            self.repos[path] = repo
        return repo

    def getRepoNickname(self, path: str, strict: bool = False) -> str:
        repo = self.getRepo(path)
        name = repo.nickname
        if not name and not strict:
            path = self.normalizeRepoPath(path)
            name = os.path.basename(path)
        return name

    def getRepoTabName(self, path: str) -> str:
        name = self.getRepoNickname(path)

        seen = {path}
        while path:
            path = self.getRepo(path).superproject
            if path:
                if path in seen:
                    logger.warning(f"Circular superproject in {self._filename}! {path}")
                    return name
                seen.add(path)
                superprojectName = self.getRepoNickname(path)
                name = f"{superprojectName}: {name}"

        return name

    def clearRepoHistory(self):
        self.repos.clear()
        self.invalidateSequenceNumber()
        self.setDirty()

    def getRecentRepoPaths(self, n: int, newestFirst=True) -> Iterator[str]:
        sortedPaths = (path for path, _ in
                       sorted(self.repos.items(), key=lambda i: i[1].seq, reverse=newestFirst))

        return (path for path, _ in zip(sortedPaths, range(n), strict=False))

    def write(self, force=False):
        self.trim()
        super().write(force)

    def trim(self):
        n = prefs.maxRecentRepos

        if len(self.repos) > n:
            # Recreate self.repos with only the n most recent paths
            topPaths = self.getRecentRepoPaths(n)
            self.repos = {path: self.repos[path] for path in topPaths}

        if len(self.cloneHistory) > n:
            self.cloneHistory = self.cloneHistory[-n:]

    def addCloneUrl(self, url):
        with suppress(ValueError):
            self.cloneHistory.remove(url)
        # Insert most recent cloned URL first
        self.cloneHistory.insert(0, url)

    def clearCloneHistory(self):
        self.cloneHistory.clear()

    def drawSequenceNumber(self, increment=1):
        if self._maxSeq < 0 and self.repos:
            self._maxSeq = max(r.seq for r in self.repos.values())
        self._maxSeq += increment
        return self._maxSeq

    def invalidateSequenceNumber(self):
        self._maxSeq = -1


@dataclasses.dataclass
class Session(PrefsFile):
    _filename = "session.json"

    tabs                        : list[str]             = dataclasses.field(default_factory=list)
    activeTabIndex              : int                   = -1
    windowGeometry              : bytes                 = b""
    rebaseDialogGeometry        : bytes                 = b""
    splitterSizes               : dict[str, list[int]]  = dataclasses.field(default_factory=dict)


# Initialize default prefs and history.
# The app should load the user's prefs with prefs.load() and history.load().
prefs = Prefs()
history = History()


def getExternalEditorName():
    genericName = englishTitleCase(_("External editor"))
    return ToolPresets.getCommandName(prefs.externalEditor, genericName, ToolPresets.Editors)


def getDiffToolName():
    genericName = englishTitleCase(_("Diff tool"))
    return ToolPresets.getCommandName(prefs.externalDiff, genericName, ToolPresets.DiffTools)


def getMergeToolName():
    genericName = englishTitleCase(_("Merge tool"))
    return ToolPresets.getCommandName(prefs.externalMerge, genericName, ToolPresets.MergeTools)
