# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import gc
import logging
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

# Import as few internal modules as possible here to avoid premature initialization
# from cascading imports before the QApplication has booted.
from gitfourchette.localization import *
from gitfourchette.qt import *

if TYPE_CHECKING:
    from gitfourchette.mainwindow import MainWindow
    from gitfourchette.settings import Session
    from gitfourchette.tasks import RepoTask
    from gitfourchette.porcelain import GitConfig

logger = logging.getLogger(__name__)


class GFApplication(QApplication):
    restyle = Signal()

    mainWindow: MainWindow | None
    initialSession: Session | None
    installedLocale: QLocale | None
    qtbaseTranslator: QTranslator | None
    tempDir: QTemporaryDir
    sessionwideGitConfigPath: str
    sessionwideGitConfig: GitConfig

    @staticmethod
    def instance() -> GFApplication:
        me = QApplication.instance()
        assert isinstance(me, GFApplication)
        return me

    def __init__(self, argv: list[str], bootScriptPath: str = "", ):
        super().__init__(argv)
        self.setObjectName("GFApplication")

        if not bootScriptPath and argv:
            bootScriptPath = argv[0]

        self.mainWindow = None
        self.initialSession = None
        self.installedLocale = None
        self.qtbaseTranslator = QTranslator(self)

        # Don't use app.setOrganizationName because it changes QStandardPaths.
        self.setApplicationName(APP_SYSTEM_NAME)  # used by QStandardPaths
        self.setApplicationDisplayName(APP_DISPLAY_NAME)  # user-friendly name
        self.setApplicationVersion(APP_VERSION)
        self.setDesktopFileName(APP_IDENTIFIER)  # Wayland uses this to resolve window icons

        # Add asset search path relative to boot script
        assetSearchPath = str(Path(bootScriptPath).parent / "assets")
        QDir.addSearchPath("assets", assetSearchPath)

        # Set app icon
        # - Except in macOS app bundles, which automatically use the embedded .icns file
        # - The file extension must be spelled out in some environments (e.g. Windows)
        if not (MACOS and APP_FREEZE_COMMIT):
            self.setWindowIcon(QIcon("assets:icons/gitfourchette.png"))

        # Get system default style name before applying further styling
        self.platformDefaultStyleName = self.style().objectName()

        # Install translators for system language
        # (for command line parser to display localized text)
        self.installTranslators()

        # Process command line
        parser = QCommandLineParser()
        parser.setApplicationDescription(qAppName() + " - " + _("The comfortable Git UI for Linux."))
        parser.addHelpOption()
        parser.addVersionOption()
        parser.addOptions([
            QCommandLineOption(["no-threads", "n"], _("Turn off multithreading (run all tasks on UI thread).")),
            QCommandLineOption(["debug", "d"], _("Enable expensive assertions and development features.")),
            QCommandLineOption(["test-mode"], _("Prevent loading/saving user settings. (implies --no-threads)")),
        ])
        parser.addPositionalArgument("repos", _("Repository paths to open on launch."), "[repos...]")
        parser.process(argv)

        # Schedule cleanup on quit
        self.aboutToQuit.connect(self.endSession)

        self.restyle.connect(self.onRestyle)

        from gitfourchette.globalshortcuts import GlobalShortcuts
        from gitfourchette.tasks import TaskBook, TaskInvoker, RepoTaskRunner
        from gitfourchette import settings

        # Set up global flags from command line
        if parser.isSet("debug"):
            settings.DEVDEBUG = True
        if parser.isSet("no-threads"):
            RepoTaskRunner.ForceSerial = True
        if parser.isSet("test-mode"):
            settings.TEST_MODE = True
            RepoTaskRunner.ForceSerial = True
            self.setApplicationName(APP_SYSTEM_NAME + "_TESTMODE")

        # Prepare session-wide temporary directory
        if FLATPAK:
            # Flatpak guarantees that "/run/user/1000/app/org.gitfourchette.gitfourchette" sits on a tmpfs,
            # and "/tmp" actually resolves to "/run/user/1000/app/org.gitfourchette.gitfourchette/tmp".
            # Use the real path instead of "/tmp" (QDir.tempPath() default value)
            # so that we can pass it to external tools outside our sandbox.
            tempDirPath = Path(os.environ["XDG_RUNTIME_DIR"], "app", os.environ["FLATPAK_ID"])
            assert tempDirPath.exists(), f"Expected to find Flatpak temp dir at: {tempDirPath}"
        else:
            tempDirPath = QDir.tempPath()
        tempDirTemplate = str(Path(tempDirPath, self.applicationName()))
        self.tempDir = QTemporaryDir(tempDirTemplate)
        self.tempDir.setAutoRemove(True)

        # Prime singletons
        GlobalShortcuts.initialize()
        TaskBook.initialize()
        TaskInvoker.instance().invokeSignal.connect(self.onInvokeTask)

        # Get initial session tabs
        self.commandLinePaths = parser.positionalArguments()

    def beginSession(self, bootUi=True):
        from gitfourchette.toolbox.messageboxes import NonCriticalOperation
        from gitfourchette.porcelain import GitConfig
        from gitfourchette import settings
        import pygit2

        # Make sure the temp dir exists
        tempDirPath = Path(self.tempDir.path())
        tempDirPath.mkdir(parents=True, exist_ok=True)

        # In a Flatpak, pygit2's XDG search path resolves to "~/.var/app/org.gitfourchette.gitfourchette/config/git"
        # by default. Users are much more likely to expect "~/.config/git" instead.
        if FLATPAK:
            userXdgGitDir = os.path.expanduser("~/.config/git")
            pygit2.settings.search_path[pygit2.enums.ConfigLevel.XDG] = userXdgGitDir

        # Prepare session-wide git config file
        self.sessionwideGitConfigPath = str(tempDirPath / "session.gitconfig")
        self.sessionwideGitConfig = GitConfig(self.sessionwideGitConfigPath)
        self.initializeSessionwideGitConfig()

        # Load prefs file
        settings.prefs.reset()
        with NonCriticalOperation("Loading prefs"):
            settings.prefs.load()

        # Load history file
        settings.history.reset()
        with NonCriticalOperation("Loading history"):
            settings.history.load()
            settings.history.startups += 1
            settings.history.setDirty()

        # Set logging level from prefs
        self.applyLoggingLevelPref()

        # Set language from prefs
        self.applyLanguagePref()

        # Load session file
        session = settings.Session()
        self.initialSession = session
        with NonCriticalOperation("Loading session"):
            session.load()
        if self.commandLinePaths:
            session.tabs += [str(Path(p).resolve()) for p in self.commandLinePaths]
            session.activeTabIndex = len(session.tabs) - 1

        # Boot main window first thing when event loop starts
        if bootUi:
            QTimer.singleShot(0, self.bootUi)

    def endSession(self, clearTempDir=True):
        from gitfourchette import settings
        from gitfourchette.toolbox.iconbank import clearStockIconCache
        from gitfourchette.syntax import LexJobCache
        from gitfourchette.remotelink import RemoteLink
        if settings.prefs.isDirty():
            settings.prefs.write()
        if settings.history.isDirty():
            settings.history.write()
        LexJobCache.clear()  # don't cache lexed files across sessions (for unit testing)
        RemoteLink.clearSessionPassphrases()  # don't cache passphrases across sessions (for unit testing)
        clearStockIconCache()  # release icon temp files
        gc.collect()  # clean up Repository file handles (for Windows unit tests)
        if clearTempDir:
            self.tempDir.remove()

    def bootUi(self):
        from gitfourchette.mainwindow import MainWindow
        from gitfourchette.toolbox import bquo
        from gitfourchette.settings import QtApiNames
        from gitfourchette.forms.donateprompt import DonatePrompt

        assert self.mainWindow is None, "already have a MainWindow"

        self.applyQtStylePref(forceApplyDefault=False)
        self.onRestyle()
        self.mainWindow = MainWindow()
        self.mainWindow.destroyed.connect(self.onMainWindowDestroyed)

        if self.initialSession is None:
            self.mainWindow.show()
        else:
            # To prevent flashing a window with incorrect dimensions,
            # restore the geometry BEFORE calling show()
            self.mainWindow.restoreGeometry(self.initialSession.windowGeometry)
            self.mainWindow.show()

            self.mainWindow.restoreSession(self.initialSession)
            self.initialSession = None

        if QT_BINDING_BOOTPREF and QT_BINDING_BOOTPREF.lower() != QT_BINDING.lower():  # pragma: no cover
            try:
                QtApiNames(QT_BINDING_BOOTPREF.lower())  # raises ValueError if not recognized
                text = _("Your preferred Qt binding {0} is not available on this machine. Using {1} instead.")
            except ValueError:
                text = _("Your preferred Qt binding {0} is not recognized by {app}. Using {1} instead. (Supported values: {known})")
            text = text.format(bquo(QT_BINDING_BOOTPREF), bquo(QT_BINDING.lower()), app=qAppName(),
                               known=", ".join(e for e in QtApiNames if e))

            QMessageBox.information(self.mainWindow, _("Qt binding unavailable"), text)

        DonatePrompt.onBoot(self.mainWindow)

    def onMainWindowDestroyed(self):
        logger.debug("Main window destroyed")
        self.mainWindow = None

    # -------------------------------------------------------------------------

    def onInvokeTask(self, invoker: QObject, taskType: type[RepoTask], args: tuple, kwargs: dict) -> RepoTask | None:
        from gitfourchette.mainwindow import MainWindow
        from gitfourchette.repowidget import RepoWidget
        from gitfourchette.toolbox import showInformation

        if self.mainWindow is None:
            warnings.warn(f"Ignoring task request {taskType.__name__} because we don't have a window")
            return None

        assert isinstance(invoker, QObject)
        if invoker.signalsBlocked():
            logger.debug(f"Ignoring task request {taskType.__name__} from invoker with blocked signals: " +
                         (invoker.objectName() or invoker.__class__.__name__))
            return None

        # Find parent in hierarchy
        candidate = invoker
        while candidate is not None:
            if isinstance(candidate, RepoWidget | MainWindow):
                break
            candidate = candidate.parent()

        if isinstance(candidate, RepoWidget):
            repoWidget = candidate
        elif isinstance(candidate, MainWindow):
            repoWidget = candidate.currentRepoWidget()
            if repoWidget is None:
                showInformation(candidate, taskType.name(),
                                _("Please open a repository before performing this action."))
                return
        else:
            repoWidget = None

        if repoWidget is None:
            raise AssertionError("RepoTasks must be invoked from a child of RepoWidget or MainWindow")

        return repoWidget.runTask(taskType, *args, **kwargs)

    # -------------------------------------------------------------------------

    def installTranslators(self, preferredLanguage: str = ""):
        from gitfourchette import settings

        if preferredLanguage:
            locale = QLocale(preferredLanguage)
        elif settings.TEST_MODE:
            # Fall back to English in unit tests regardless of the host machine's locale
            # because many unit tests look for pieces of text in dialogs.
            locale = QLocale(QLocale.Language.English)
        else:  # pragma: no cover
            locale = QLocale()  # "Automatic" setting: Get system locale

        # Force English locale for RTL languages. RTL support isn't great for now,
        # and we have no localizations for RTL languages yet anyway.
        if locale.textDirection() != Qt.LayoutDirection.LeftToRight:
            locale = QLocale(QLocale.Language.English)

        # Set default locale
        QLocale.setDefault(locale)
        previousLocale = self.installedLocale
        self.installedLocale = locale

        if previousLocale is not None and locale.name() == previousLocale.name():
            logger.debug(f"Previous locale is similar enough to new locale ({locale.name()}), not reloading translators")
            return

        # Try to load gettext translator for application strings.
        languageCode = locale.name()
        languageCode = languageCode.split("_")[0]  # strip territory (e.g. fr_FR --> fr)
        languageFile = QFile(f"assets:lang/{languageCode}.mo")
        installGettextTranslator(languageFile.fileName())

        # Remove previously installed qtbase translator
        QCoreApplication.removeTranslator(self.qtbaseTranslator)

        # Load qtbase translator
        if not QT5:  # Qt 5 doesn't have QLibraryInfo.path
            qtTranslationsDir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if self.qtbaseTranslator.load(locale, "qtbase", "_", qtTranslationsDir, ".qm"):
                QCoreApplication.installTranslator(self.qtbaseTranslator)

    def applyLanguagePref(self):
        from gitfourchette import settings
        from gitfourchette.trtables import TrTables
        from gitfourchette.tasks.taskbook import TaskBook

        self.installTranslators(settings.prefs.language)

        # Regenerate rosetta stones
        TrTables.retranslate()
        TaskBook.retranslate()

    def applyQtStylePref(self, forceApplyDefault: bool):
        from gitfourchette import settings

        if settings.prefs.qtStyle:
            self.setStyle(settings.prefs.qtStyle)
        elif forceApplyDefault:
            self.setStyle(self.platformDefaultStyleName)

        if MACOS:
            self.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)

    def applyLoggingLevelPref(self):
        from gitfourchette import settings

        logging.root.setLevel(settings.prefs.verbosity.value)

    # -------------------------------------------------------------------------

    def processEventsNoInput(self):
        self.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    # -------------------------------------------------------------------------

    def initializeSessionwideGitConfig(self):
        # On Windows, core.autocrlf is usually set to true in the system config.
        # However, libgit2 cannot find the system config if git wasn't installed
        # with the official installer, e.g. via scoop. If a repo was cloned with
        # autocrlf=true, GF's staging area would be unusable on Windows without
        # setting autocrlf=true in the config.
        if WINDOWS:
            self.sessionwideGitConfig["core.autocrlf"] = "true"

    # -------------------------------------------------------------------------

    def onRestyle(self):
        from gitfourchette.toolbox.qtutils import isDarkTheme
        from gitfourchette.toolbox.iconbank import clearStockIconCache

        styleSheet = Path(QFile("assets:style.qss").fileName()).read_text()
        if isDarkTheme():  # Append dark override
            darkSupplement = Path(QFile("assets:style-dark.qss").fileName()).read_text()
            styleSheet += darkSupplement
        self.setStyleSheet(styleSheet)

        clearStockIconCache()
