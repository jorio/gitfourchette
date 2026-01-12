# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import gc
import logging
import os
import sys
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
    from gitfourchette.tasks import RepoTask, TaskInvocation
    from gitfourchette.mount.mountmanager import MountManager
    from gitfourchette.porcelain import GitConfig
    from gitfourchette.sshagent import SshAgent

logger = logging.getLogger(__name__)


class GFApplication(QApplication):
    restyle = Signal()
    prefsChanged = Signal(list)
    regainForeground = Signal()
    fileDraggedToDockIcon = Signal(str)
    mouseSideButtonPressed = Signal(bool)

    # Lightweight state
    installedLocale: QLocale | None
    qtbaseTranslator: QTranslator
    tempDir: QTemporaryDir
    platformDefaultStyleName: str

    # Heavyweight state
    mainWindow: MainWindow | None
    initialSession: Session | None
    commandLinePaths: list
    sessionwideGitConfigPath: str
    sessionwideGitConfig: GitConfig
    sshAgent: SshAgent | None
    mountManager: MountManager | None

    @classmethod
    def instance(cls) -> GFApplication:
        me = QApplication.instance()
        assert isinstance(me, cls)
        return me

    @classmethod
    def main(cls):
        app = cls(sys.argv)
        app.beginSession()
        returnCode = app.exec()
        sys.exit(returnCode)

    def __init__(self, argv: list[str], barebones=False):
        super().__init__(argv)
        self.setObjectName("GFApplication")

        self.mainWindow = None
        self.initialSession = None
        self.commandLinePaths = []
        self.installedLocale = None
        self.qtbaseTranslator = QTranslator(self)
        self.sshAgent = None

        # Show an error dialog in case of unhandled exceptions.
        # Note that debuggers may override the exception hook.
        self.injectExceptHook()

        # Don't use app.setOrganizationName because it changes QStandardPaths.
        self.setApplicationName(APP_SYSTEM_NAME)  # used by QStandardPaths
        self.setApplicationDisplayName(APP_DISPLAY_NAME)  # user-friendly name
        self.setApplicationVersion(APP_VERSION)
        self.setDesktopFileName(APP_IDENTIFIER)  # Wayland uses this to resolve window icons

        # Add assets search path
        if PYINSTALLER_MEIPASS:
            # PyInstaller, e.g. GitFourchette.app/Contents/Frameworks
            assetsParentPath = Path(PYINSTALLER_MEIPASS)
        else:
            # Relative to boot script
            assetsParentPath = Path(__file__ or sys.argv[0]).parent
        assetsSearchPath = str(assetsParentPath / "assets")
        QDir.addSearchPath("assets", assetsSearchPath)

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

        self.createTempDir()

        self.installSigintHandler()

        # ---------------------------------------------------------------------
        # End of barebones initialization
        if barebones:
            return

        # Process command line
        parser = QCommandLineParser()
        parser.setApplicationDescription(qAppName() + " - " + _("The comfortable Git UI for Linux."))
        parser.addHelpOption()
        parser.addVersionOption()
        parser.addPositionalArgument("repos", _("Repository paths to open on launch."), "[repos...]")
        parser.process(argv)

        # Schedule cleanup on quit
        self.aboutToQuit.connect(self.endSession)

        # Listen for palette change events
        self.restyle.connect(self.onRestyle)

        from gitfourchette.globalshortcuts import GlobalShortcuts
        from gitfourchette.tasks import TaskBook, TaskInvocation

        # Prime singletons
        GlobalShortcuts.initialize()
        TaskBook.initialize()
        TaskInvocation.initializeGlobalSignal().connect(self.onInvokeTask)

        # Get initial session tabs
        commandLinePaths = parser.positionalArguments()
        commandLinePaths = [str(Path(p).resolve()) for p in commandLinePaths]
        self.commandLinePaths = commandLinePaths

    # -------------------------------------------------------------------------

    def createTempDir(self):
        tempDirPath = os.environ.get("GITFOURCHETTE_TEMPDIR", "")
        if tempDirPath:
            pass
        elif FLATPAK:
            # Flatpak guarantees that "/run/user/1000/app/org.gitfourchette.gitfourchette" sits on a tmpfs,
            # and "/tmp" actually resolves to "/run/user/1000/app/org.gitfourchette.gitfourchette/tmp".
            # Use the real path instead of "/tmp" (QDir.tempPath() default value)
            # so that we can pass it to external tools outside our sandbox.
            tempDirPath = Path(XDG_RUNTIME_DIR, "app", FLATPAK_ID)
            assert tempDirPath.exists(), f"Expected to find Flatpak temp dir at: {tempDirPath}"
        else:
            tempDirPath = QDir.tempPath()
        tempDirTemplate = str(Path(tempDirPath, self.applicationName()))
        self.tempDir = QTemporaryDir(tempDirTemplate)
        self.tempDir.setAutoRemove(True)

    def injectExceptHook(self):
        # Show an error dialog in case of unhandled exceptions.
        # Note that debuggers may override the exception hook.
        sys.excepthook = self.customExceptHook

    @staticmethod
    def customExceptHook(exctype, value, tb):
        # Run default excepthook first
        sys.__excepthook__(exctype, value, tb)

        from gitfourchette.toolbox import excMessageBox
        excMessageBox(value, printExc=False)

    def installSigintHandler(self):
        import signal
        signal.signal(signal.SIGINT, self.onSigint)

        # Force Python interpreter to run every now and then so it can run the
        # Ctrl+C signal handler. Without this, the app won't actually die until
        # the window regains focus (https://stackoverflow.com/q/4938723).
        if __debug__:
            timer = QTimer(self)
            timer.start(300)
            timer.timeout.connect(lambda: None)

    def onSigint(self, *_dummy):
        # Deferring the quit to the next event loop gives the application some
        # time to wrap up the session.
        QTimer.singleShot(0, self.quit)
        # TODO: Actually return SIGINT from main

    # -------------------------------------------------------------------------

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
            session.tabs += self.commandLinePaths
            session.activeTabIndex = len(session.tabs) - 1

        # Boot main window
        if bootUi:
            self.bootUi()

    def endSession(self, clearTempDir=True):
        from gitfourchette import settings
        from gitfourchette.syntax import LexJobCache
        if settings.prefs.isDirty():
            settings.prefs.write()
        if settings.history.isDirty():
            settings.history.write()
        self.stopSshAgent()

        assert not self.mountManager.mountedCommits, "mount points remaining"
        self.mountManager.deleteLater()
        self.mountManager = None

        LexJobCache.clear()  # don't cache lexed files across sessions (for unit testing)
        # RemoteLink.clearSessionPassphrases()  # don't cache passphrases across sessions (for unit testing)
        gc.collect()  # clean up Repository file handles (for Windows unit tests)
        if clearTempDir:
            self.tempDir.remove()

    def bootUi(self):
        from gitfourchette.mainwindow import MainWindow
        from gitfourchette.toolbox import bquo
        from gitfourchette.settings import QtApiNames
        from gitfourchette.forms.donateprompt import DonatePrompt
        from gitfourchette.mount.mountmanager import MountManager

        assert self.mainWindow is None, "already have a MainWindow"
        assert self.initialSession is not None, "initial session should have been prepared before bootUi"

        # Initialize mountpoint manager
        self.mountManager = MountManager(self)

        self.applyQtStylePref(forceApplyDefault=False)
        self.onRestyle()
        self.mainWindow = MainWindow()

        # Bind window signals
        self.regainForeground.connect(self.mountManager.checkAliveProcesses)
        self.regainForeground.connect(self.mainWindow.onRegainForeground)
        self.mainWindow.destroyed.connect(self.onMainWindowDestroyed)
        self.mouseSideButtonPressed.connect(self.mainWindow.onMouseSideButtonPressed)
        self.fileDraggedToDockIcon.connect(self.mainWindow.onFileDraggedToDockIcon)
        self.mountManager.mountPointsChanged.connect(self.mainWindow.fillGlobalMenuBar)
        self.mountManager.mountPointsChanged.connect(self.mainWindow.update)  # redraw GraphView
        self.mountManager.statusMessage.connect(self.mainWindow.statusBar2.showMessage)

        # To prevent flashing a window with incorrect dimensions,
        # restore the geometry BEFORE calling show()
        if not GNOME:  # Skip this on GNOME (issue #50)
            self.mainWindow.restoreGeometry(self.initialSession.windowGeometry)
        self.mainWindow.show()

        # Initialize SSH agent
        self.applySshAgentPref()

        # Restore session then consume it
        self.mainWindow.restoreSession(self.initialSession, self.commandLinePaths)
        self.initialSession = None
        self.commandLinePaths = []

        # Warn about incorrect Qt bindings
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

        self.installEventFilter(self)

    def onMainWindowDestroyed(self):
        logger.debug("Main window destroyed")
        self.mainWindow = None

    # -------------------------------------------------------------------------

    def onInvokeTask(self, call: TaskInvocation) -> RepoTask | None:
        from gitfourchette.mainwindow import MainWindow
        from gitfourchette.repowidget import RepoWidget
        from gitfourchette.blameview.blamewindow import BlameWindow
        from gitfourchette.toolbox import showInformation

        if self.mainWindow is None:
            warnings.warn(f"Ignoring {repr(call)} because we don't have a window")
            return None

        assert isinstance(call.invoker, QObject)
        if call.invoker.signalsBlocked():
            logger.debug(f"Ignoring {repr(call)} from invoker with blocked signals: " +
                         (call.invoker.objectName() or call.invoker.__class__.__name__))
            return None

        # Find parent in hierarchy
        candidate = call.invoker
        while candidate is not None:
            if isinstance(candidate, RepoWidget | BlameWindow | MainWindow):
                break
            candidate = candidate.parent()

        if isinstance(candidate, RepoWidget | BlameWindow):
            repoWidget = candidate
        elif isinstance(candidate, MainWindow):
            repoWidget = candidate.currentRepoWidget()
            if repoWidget is None:
                showInformation(candidate, call.taskClass.name(),
                                _("Please open a repository before performing this action."))
                return None
        else:
            repoWidget = None

        if repoWidget is None:
            raise AssertionError("RepoTasks must be invoked from a child of RepoWidget or MainWindow")

        return repoWidget.taskRunner.put(call)

    # -------------------------------------------------------------------------

    def installTranslators(self, preferredLanguage: str = ""):
        if preferredLanguage:
            locale = QLocale(preferredLanguage)
        elif APP_TESTMODE:
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
        self._installGettextTranslator(locale)

        # Remove previously installed qtbase translator
        QCoreApplication.removeTranslator(self.qtbaseTranslator)

        # Load qtbase translator
        if not QT5:  # Qt 5 doesn't have QLibraryInfo.path
            qtTranslationsDir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if self.qtbaseTranslator.load(locale, "qtbase", "_", qtTranslationsDir, ".qm"):
                QCoreApplication.installTranslator(self.qtbaseTranslator)

    @staticmethod
    def _installGettextTranslator(locale: QLocale):
        # We'll be resolving the path to an '.mo' file that best matches the given locale.
        moFilePath = ""

        # Match Qt language code with .mo files exported from Weblate.
        # The codes for most languages already match, but Chinese is a notable exception.
        qtLocaleToWeblate = {
            "zh_CN": "zh_Hans",
        }

        languageCode = locale.name()
        languageCode = qtLocaleToWeblate.get(languageCode, languageCode)

        # Look for a territory-specific file first, then fall back to a
        # generic language file (e.g. 'fr_CA' then 'fr').
        try:
            genericLanguageCode = QLocale.languageToCode(locale.language())
        except AttributeError:  # pragma: no cover - Compatibility with Qt 5 and pre-Qt 6.3
            genericLanguageCode = languageCode.split("_")[0]

        for stem in languageCode, genericLanguageCode:
            languageFile = QFile(f"assets:lang/{stem}.mo")
            if languageFile.exists():
                moFilePath = languageFile.fileName()
                break

        # Install translations from the '.mo' file.
        # If we couldn't find a file, this will fall back to American English.
        installGettextTranslator(moFilePath)

    # -------------------------------------------------------------------------

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
            self.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, settings.qtIsNativeMacosStyle())

    def applyLoggingLevelPref(self):
        from gitfourchette import settings

        logging.root.setLevel(settings.prefs.verbosity.value)

    def applySshAgentPref(self):
        from gitfourchette import settings
        from gitfourchette.sshagent import SshAgent
        from gitfourchette.toolbox import showWarning, paragraphs

        wantAgent = settings.prefs.ownSshAgent
        sandbox = settings.prefs.isGitSandboxed()

        if not wantAgent:
            self.stopSshAgent()
            return

        if self.sshAgent and sandbox != self.sshAgent.isSandboxed():
            # Sandboxed state of the current agent isn't what we want, restart it
            self.stopSshAgent()

        if self.sshAgent:
            # Already have an agent
            return

        try:
            self.sshAgent = SshAgent(self, sandbox=sandbox)
        except Exception as exc:
            message = paragraphs(
                _("Couldn’t start {0} ({1}).", "ssh-agent", str(exc)),
                _("Please make sure OpenSSH is installed on your system."))
            showWarning(self.mainWindow, _("SSH agent"), message)

    def stopSshAgent(self):
        if self.sshAgent:
            self.sshAgent.stopAndWait()
            self.sshAgent.deleteLater()
            self.sshAgent = None

    # -------------------------------------------------------------------------

    def processEventsNoInput(self):
        self.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def eventFilter(self, watched, event: QEvent):
        eventType = event.type()
        isPress = eventType == QEvent.Type.MouseButtonPress

        if eventType == QEvent.Type.FileOpen:
            # Called if dragging something to dock icon on macOS.
            # Ignore in test mode - the test runner may send a bogus FileOpen before we're ready to process it.
            assert isinstance(event, QFileOpenEvent)
            path = event.file()
            if not APP_TESTMODE:
                self.fileDraggedToDockIcon.emit(path)

        elif eventType == QEvent.Type.ApplicationStateChange:
            # Refresh current RepoWidget when the app regains the active state (foreground)
            if QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
                QTimer.singleShot(0, self.regainForeground)

        elif isPress or eventType == QEvent.Type.MouseButtonDblClick:
            # As of PyQt6 6.8, QContextMenuEvent sometimes pretends that its event type is a MouseButtonDblClick
            if PYQT6 and not isinstance(event, QMouseEvent):
                logger.warning(f"QContextMenuEvent pretends it's a double click: {event}")
                return False

            # Intercept back/forward mouse clicks
            assert isinstance(event, QMouseEvent)
            button = event.button()
            isBack = button == Qt.MouseButton.BackButton
            isForward = button == Qt.MouseButton.ForwardButton
            if isBack or isForward:
                if isPress:
                    self.mouseSideButtonPressed.emit(isForward)
                # Eat clicks or double-clicks of back and forward mouse buttons
                return True

        elif eventType == QEvent.Type.PaletteChange and watched is self.mainWindow:
            # Recolor some widgets when palette changes (light to dark or vice-versa).
            # Tested in KDE Plasma 6 and macOS 15.
            self.restyle.emit()

        elif eventType == QEvent.Type.StatusTip:
            # Eat QStatusTipEvent. The menubar emits those when a menu is hovered;
            # but since we don't use status tips, the status bar is cleared for no reason.
            if APP_DEBUG:
                assert not event.tip(), "assuming QStatusTipEvent is always empty"
            return True

        return False

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
        from gitfourchette.syntax.colorscheme import ColorScheme

        QPixmapCache.clear()

        styleSheet = Path(QFile("assets:style.qss").fileName()).read_text()
        if isDarkTheme():  # Append dark override
            darkSupplement = Path(QFile("assets:style-dark.qss").fileName()).read_text()
            styleSheet += darkSupplement
        self.setStyleSheet(styleSheet)

        ColorScheme.refreshFallbackScheme()

    # -------------------------------------------------------------------------
    # Utilities

    def openPrefsDialog(self, prefKey: str):
        self.mainWindow.openPrefsDialog(prefKey)
