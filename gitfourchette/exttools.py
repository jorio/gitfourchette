# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import shlex
from contextlib import suppress
from signal import SIGINT

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.settings import prefs, TEST_MODE
from gitfourchette.toolbox import *
from gitfourchette.toolcommands import ToolCommands
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)

PREFKEY_EDITOR = "externalEditor"
PREFKEY_DIFFTOOL = "externalDiff"
PREFKEY_MERGETOOL = "externalMerge"


def openPrefsDialog(parent: QWidget, prefKey: str):
    from gitfourchette.mainwindow import MainWindow
    while parent:
        if isinstance(parent, MainWindow):
            parent.openPrefsDialog(prefKey)
            break
        else:
            parent = parent.parentWidget()


def onLocateTool(prefKey: str, newPath: str):
    command = getattr(prefs, prefKey)
    newCommand = ToolCommands.replaceProgramTokenInCommand(command, newPath)
    setattr(prefs, prefKey, newCommand)
    prefs.write()


def onExternalToolProcessError(parent: QWidget, prefKey: str,
                               isKnownFlatpak=False,
                               compileError: Exception | None = None):
    assert isinstance(parent, QWidget)

    commandString = getattr(prefs, prefKey)
    programName = ToolCommands.getCommandName(commandString, "", {})

    translatedPrefKey = TrTables.prefKey(prefKey)

    title = _("Failed to start {tool}", tool=translatedPrefKey)

    if compileError:
        message = _("There is an issue with the {tool} command template in your settings:").format(tool=tquo(translatedPrefKey))
        message += f"<pre>{escape(commandString)}</pre>"
        message += "&rarr; " + str(compileError)
    else:
        if isKnownFlatpak:
            message = _("Couldn’t start Flatpak {command} ({tool}).")
        else:
            message = _("Couldn’t start {command} ({tool}).")
        message = message.format(tool=translatedPrefKey, command=bquo(programName))
        message += " " + _("It might not be installed on your machine.")

    configureButtonID = QMessageBox.StandardButton.Ok
    browseButtonID = QMessageBox.StandardButton.Open

    qmb = asyncMessageBox(parent, 'warning', title, message,
                          configureButtonID | browseButtonID | QMessageBox.StandardButton.Cancel)

    configureButton = qmb.button(configureButtonID)
    configureButton.setText(_("Edit Command…"))
    configureButton.setIcon(stockIcon("configure"))

    browseButton = qmb.button(browseButtonID)
    browseButton.setText(_("Locate {tool}…", tool=lquo(programName)))

    removeBrowseButton = bool(compileError)
    if FREEDESKTOP:
        tokens = ToolCommands.splitCommandTokens(commandString)
        if ToolCommands.isFlatpakRunCommand(tokens):
            removeBrowseButton = True
    if removeBrowseButton:
        qmb.removeButton(browseButton)

    def onQMBFinished(result):
        if result == configureButtonID:
            openPrefsDialog(parent, prefKey)
        elif result == browseButtonID:
            qfd = QFileDialog(parent, _("Where is {tool}?", tool=lquo(programName)))
            qfd.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
            qfd.setFileMode(QFileDialog.FileMode.AnyFile)
            qfd.setWindowModality(Qt.WindowModality.WindowModal)
            qfd.setOption(QFileDialog.Option.DontUseNativeDialog, TEST_MODE)
            qfd.show()
            qfd.fileSelected.connect(lambda newPath: onLocateTool(prefKey, newPath))
            return qfd

    qmb.finished.connect(onQMBFinished)
    qmb.show()


def setUpToolCommand(parent: QWidget, prefKey: str):
    translatedPrefKey = TrTables.prefKey(prefKey)

    title = translatedPrefKey

    message = _("{tool} isn’t configured in your settings yet.", tool=bquo(translatedPrefKey))

    qmb = asyncMessageBox(parent, 'warning', title, message,
                          QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

    configureButton = qmb.button(QMessageBox.StandardButton.Ok)
    configureButton.setText(_("Set up {tool}", tool=lquo(translatedPrefKey)))

    qmb.accepted.connect(lambda: openPrefsDialog(parent, prefKey))
    qmb.show()


class ExternalToolProcess(QProcess):
    def __init__(self, parent: QWidget, tokens: list[str], directory: str, detached: bool, prefKey: str):
        super().__init__(parent)

        self.detached = detached
        self.prefKey = prefKey

        self.setProgram(tokens[0])
        self.setArguments(tokens[1:])
        if not FLATPAK:  # In Flatpaks, workdir was set via flatpak-spawn
            self.setWorkingDirectory(directory)
        self.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)

        # Listen for process completion.
        self.finished.connect(self.onFinished)
        # Listen for errors (typically FailedToStart).
        self.errorOccurred.connect(self.onErrorOccurred)
        # When the parent dies, don't let callbacks hit zombie objects.
        parent.destroyed.connect(self.onParentDestroyedWhileProcessRunning)

        logger.info("Process starting: " + shlex.join(tokens))
        if detached and not FLATPAK:  # Flatpaks detach from process via ToolCommands.compileCommand
            self.startDetached()
        else:
            self.start()
            logger.info(f"(PID {self.processId()})")

    def onFinished(self, code, status):
        logger.info(f"Process done: {code} {status}")
        self.disconnectFromParent()
        if not WINDOWS and code == 127:
            # The Flatpak distribution runs non-Flatpak commands through `env`,
            # which returns 127 if the command isn't found.
            onExternalToolProcessError(self.parent(), self.prefKey)

    def onErrorOccurred(self, processError):
        logger.info(f"Process error: {processError}")
        self.disconnectFromParent()
        onExternalToolProcessError(self.parent(), self.prefKey)

    def onParentDestroyedWhileProcessRunning(self):
        # Disconnect signals
        self.disconnectFromParent()
        self.finished.disconnect(self.onFinished)
        self.errorOccurred.disconnect(self.onErrorOccurred)

        if not self.detached:
            pid = self.processId()
            if pid > 0:
                # SIGINT works better with non-Flatpak Meld
                os.kill(pid, SIGINT)
            else:
                self.terminate()

        self.setParent(None)
        self.deleteLater()

    def disconnectFromParent(self):
        # Disconnect from the parent so that future signals won't touch a parent
        # that might have been destroyed.
        # Ignore TypeError, raised by PyQt6 if the connection has already been
        # undone (may occur when SIGKILLing the process - both onFinished and
        # onErrorOccurred will fire).
        with suppress(TypeError):
            self.parent().destroyed.disconnect(self.onParentDestroyedWhileProcessRunning)


def openInExternalTool(
        parent: QWidget,
        prefKey: str,
        replacements: dict[str, str],
        positional: list[str],
        allowQDesktopFallback: bool = False,
        directory: str = "",
        detached: bool = False,
) -> QProcess | None:

    assert isinstance(parent, QWidget)

    command = getattr(prefs, prefKey, "").strip()

    if not command and allowQDesktopFallback:
        for argument in positional:
            QDesktopServices.openUrl(QUrl.fromLocalFile(argument))
        return None

    if not command:
        setUpToolCommand(parent, prefKey)
        return None

    try:
        tokens, directory = ToolCommands.compileCommand(command, replacements, positional, directory)
    except ValueError as exc:
        onExternalToolProcessError(parent, prefKey, compileError=exc)
        return None

    # Check if the Flatpak is installed
    if FREEDESKTOP:
        # Check 'isFlatpakRunCommand' on unfiltered tokens (compileCommand may have added a wrapper)
        unfilteredTokens = ToolCommands.splitCommandTokens(command)
        flatpakRefTokenIndex = ToolCommands.isFlatpakRunCommand(unfilteredTokens)
        if flatpakRefTokenIndex and not ToolCommands.isFlatpakInstalled(unfilteredTokens[flatpakRefTokenIndex], parent):
            onExternalToolProcessError(parent, prefKey, isKnownFlatpak=True)
            return None

    process = ExternalToolProcess(parent=parent, tokens=tokens, directory=directory, detached=detached, prefKey=prefKey)
    return process


def openInTextEditor(parent: QWidget, path: str):
    return openInExternalTool(parent, PREFKEY_EDITOR, positional=[path], replacements={},
                              allowQDesktopFallback=True)


def openInDiffTool(parent: QWidget, a: str, b: str):
    return openInExternalTool(parent, PREFKEY_DIFFTOOL, positional=[],
                              replacements={"$L": a, "$R": b})


def openTerminal(parent: QWidget, workdir: str, command: str = ""):
    launcherScriptPath = ToolCommands.makeTerminalScript(workdir, command)

    return openInExternalTool(
        parent=parent,
        prefKey="terminal",
        replacements={"$COMMAND": launcherScriptPath},
        positional=[],
        directory=workdir, detached=True)
