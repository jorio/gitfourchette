# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import enum
import logging
import os
import sys
from contextlib import suppress

import pygments.style
import pygments.styles
import pygments.util

from gitfourchette import pycompat  # noqa: F401 - StrEnum for Python 3.10
from gitfourchette.localization import *
from gitfourchette.prefsfile import PrefsFile
from gitfourchette.qt import *
from gitfourchette.toolbox.benchmark import BENCHMARK_LOGGING_LEVEL
from gitfourchette.toolbox.gitutils import AuthorDisplayStyle
from gitfourchette.toolbox.pathutils import PathDisplayStyle
from gitfourchette.toolbox.qtutils import isDarkTheme
from gitfourchette.toolbox.textutils import englishTitleCase
from gitfourchette.toolcommands import ToolCommands

logger = logging.getLogger(__name__)

TEST_MODE = "pytest" in sys.modules
"""
Unit testing mode (don't touch real user prefs, etc.).
Can be forced with command-line switch "--test-mode".
"""

DEVDEBUG = TEST_MODE
"""
Enable expensive assertions and debugging features.
Can be forced with command-line switch "--debug".
"""

SHORT_DATE_PRESETS = {
    "ISO": "yyyy-MM-dd HH:mm",
    "Universal 1": "dd MMM yyyy HH:mm",
    "Universal 2": "ddd dd MMM yyyy HH:mm",
    "European 1": "dd/MM/yy HH:mm",
    "European 2": "dd.MM.yy HH:mm",
    "American": "M/d/yy h:mm ap",
}


class GraphRowHeight(enum.IntEnum):
    CRAMPED = 80
    TIGHT = 100
    RELAXED = 130
    ROOMY = 150
    SPACIOUS = 175


class GraphRefBoxWidth(enum.IntEnum):
    ICONS_ONLY = 0
    STANDARD = 120
    WIDE = 1000


class QtApiNames(enum.StrEnum):
    QTAPI_AUTOMATIC = ""
    QTAPI_PYQT6 = "pyqt6"
    QTAPI_PYSIDE6 = "pyside6"
    QTAPI_PYQT5 = "pyqt5"


class LoggingLevel(enum.IntEnum):
    BENCHMARK = BENCHMARK_LOGGING_LEVEL
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING


class PygmentsPresets:
    Automatic = ""
    Off = "off"
    Light = "stata-light"
    Dark = "stata-dark"


@dataclasses.dataclass
class Prefs(PrefsFile):
    _filename = "prefs.json"

    _category_general           : int                   = 0
    language                    : str                   = ""
    qtStyle                     : str                   = ""
    pathDisplayStyle            : PathDisplayStyle      = PathDisplayStyle.FULL_PATHS
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

    _category_imageDiff         : int                   = 0
    imageFileThresholdKB        : int                   = 5000
    renderSvg                   : bool                  = False

    _category_graph             : int                   = 0
    chronologicalOrder          : bool                  = True
    graphRowHeight              : GraphRowHeight        = GraphRowHeight.RELAXED
    refBoxMaxWidth              : GraphRefBoxWidth      = GraphRefBoxWidth.STANDARD
    authorDisplayStyle          : AuthorDisplayStyle    = AuthorDisplayStyle.FULL_NAME
    shortTimeFormat             : str                   = list(SHORT_DATE_PRESETS.values())[0]
    maxCommits                  : int                   = 10000
    authorDiffAsterisk          : bool                  = True
    alternatingRowColors        : bool                  = False

    _category_external          : int                   = 0
    externalEditor              : str                   = ""
    externalDiff                : str                   = ToolCommands.DiffPresets[ToolCommands.DefaultDiffPreset]
    externalMerge               : str                   = ToolCommands.MergePresets[ToolCommands.DefaultMergePreset]

    _category_tabs              : int                   = 0
    tabCloseButton              : bool                  = True
    expandingTabs               : bool                  = True
    autoHideTabs                : bool                  = False
    doubleClickTabOpensFolder   : bool                  = True

    _category_trash             : int                   = 0
    maxTrashFiles               : int                   = 250
    maxTrashFileKB              : int                   = 1000

    _category_advanced          : int                   = 0
    maxRecentRepos              : int                   = 20
    shortHashChars              : int                   = 7
    autoRefresh                 : bool                  = True
    middleClickToStage          : bool                  = False
    flattenLanes                : bool                  = True
    animations                  : bool                  = True
    condensedFonts              : bool                  = True
    pygmentsPlugins             : bool                  = False
    verbosity                   : LoggingLevel          = LoggingLevel.WARNING
    forceQtApi                  : QtApiNames            = QtApiNames.QTAPI_AUTOMATIC

    _category_hidden            : int                   = 0
    smoothScroll                : bool                  = True
    toolBarButtonStyle          : Qt.ToolButtonStyle    = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    toolBarIconSize             : int                   = 16
    defaultCloneLocation        : str                   = ""
    dontShowAgain               : list[str]             = dataclasses.field(default_factory=list)
    resetDontShowAgain          : bool                  = False
    donatePrompt                : int                   = 0

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

    def isSyntaxHighlightingEnabled(self):
        return self.syntaxHighlighting != PygmentsPresets.Off

    def resolvePygmentsStyle(self) -> pygments.style.Style | None:
        styleName = self.syntaxHighlighting
        if styleName == PygmentsPresets.Automatic:
            styleName = PygmentsPresets.Dark if isDarkTheme() else PygmentsPresets.Light
        if styleName == PygmentsPresets.Off:
            return None
        try:
            return pygments.styles.get_style_by_name(styleName)
        except pygments.util.ClassNotFound:
            return None

    def isDarkPygmentsStyle(self) -> bool:
        style = self.resolvePygmentsStyle()
        if style is None:
            return isDarkTheme()
        bgColor = QColor(style.background_color)
        return bgColor.lightnessF() < .5

    def basicQssForPygmentsStyle(self, qobject):
        pygmentsStyle = self.resolvePygmentsStyle()
        if pygmentsStyle is None:
            return "/* no Pygments style */"
        bgColor = pygmentsStyle.background_color
        fgColor = "black"
        with suppress(TypeError):
            fgColor = '#' + pygmentsStyle.style_for_token(pygments.token.Token.Text)['color']
        return f"{type(qobject).__name__} {{ background-color: {bgColor}; color: {fgColor}; }}"


@dataclasses.dataclass
class History(PrefsFile):
    _filename = "history.json"

    repos: dict = dataclasses.field(default_factory=dict)
    cloneHistory: list = dataclasses.field(default_factory=list)
    fileDialogPaths: dict = dataclasses.field(default_factory=dict)
    workingKeys: dict = dataclasses.field(default_factory=dict)
    startups: int = 0

    _maxSeq = -1

    def addRepo(self, path: str):
        path = os.path.normpath(path)
        repo = self.getRepo(path)
        repo['seq'] = self.drawSequenceNumber()
        return repo

    def getRepo(self, path: str) -> dict:
        path = os.path.normpath(path)
        try:
            repo = self.repos[path]
        except KeyError:
            repo = {}
            self.repos[path] = repo
        return repo

    def getRepoNickname(self, path: str, strict: bool = False) -> str:
        repo = self.getRepo(path)
        path = os.path.normpath(path)
        return repo.get("nickname", "" if strict else os.path.basename(path))

    def setRepoNickname(self, path: str, nickname: str):
        repo = self.getRepo(path)
        nickname = nickname.strip()
        if nickname:
            repo['nickname'] = nickname
        else:
            repo.pop('nickname', None)

    def getRepoNumCommits(self, path: str):
        repo = self.getRepo(path)
        return repo.get('length', 0)

    def setRepoNumCommits(self, path: str, commitCount: int):
        repo = self.getRepo(path)
        if commitCount > 0:
            repo['length'] = commitCount
        else:
            repo.pop('length', None)

    def getRepoSuperproject(self, path: str):
        repo = self.getRepo(path)
        return repo.get('superproject', "")

    def setRepoSuperproject(self, path: str, superprojectPath: str):
        repo = self.getRepo(path)
        if superprojectPath:
            repo['superproject'] = superprojectPath
        else:
            repo.pop('superproject', None)

    def getRepoTabName(self, path: str):
        name = self.getRepoNickname(path)

        seen = {path}
        while path:
            path = self.getRepoSuperproject(path)
            if path:
                if path in seen:
                    logger.warning(f"Circular superproject in {self._filename}! {path}")
                    return name
                seen.add(path)
                superprojectName = self.getRepoNickname(path)
                name = f"{superprojectName}: {name}"

        return name

    def removeRepo(self, path: str):
        path = os.path.normpath(path)
        self.repos.pop(path, None)
        self.invalidateSequenceNumber()

    def clearRepoHistory(self):
        self.repos.clear()
        self.invalidateSequenceNumber()

    def getRecentRepoPaths(self, n: int, newestFirst=True):
        sortedPaths = (path for path, _ in
                       sorted(self.repos.items(), key=lambda i: i[1].get('seq', -1), reverse=newestFirst))

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
            self._maxSeq = max(r.get('seq', -1) for r in self.repos.values())
        self._maxSeq += increment
        return self._maxSeq

    def invalidateSequenceNumber(self):
        self._maxSeq = -1

    def setRemoteWorkingKey(self, url: str, keyPath: str):
        if not url:
            return
        if keyPath:
            self.workingKeys[url] = keyPath
        else:
            self.workingKeys.pop(url, None)
        self.setDirty()


@dataclasses.dataclass
class Session(PrefsFile):
    _filename = "session.json"

    tabs                        : list          = dataclasses.field(default_factory=list)
    activeTabIndex              : int           = -1
    windowGeometry              : bytes         = b""
    splitterSizes               : dict          = dataclasses.field(default_factory=dict)


# Initialize default prefs and history.
# The app should load the user's prefs with prefs.load() and history.load().
prefs = Prefs()
history = History()


def qtIsNativeMacosStyle():  # pragma: no cover
    if not MACOS:
        return False
    return (not prefs.qtStyle) or (prefs.qtStyle.lower() == "macos")


def getExternalEditorName():
    genericName = englishTitleCase(_("External editor"))
    return ToolCommands.getCommandName(prefs.externalEditor, genericName, ToolCommands.EditorPresets)


def getDiffToolName():
    genericName = englishTitleCase(_("Diff tool"))
    return ToolCommands.getCommandName(prefs.externalDiff, genericName, ToolCommands.DiffPresets)


def getMergeToolName():
    genericName = englishTitleCase(_("Merge tool"))
    return ToolCommands.getCommandName(prefs.externalMerge, genericName, ToolCommands.MergePresets)
