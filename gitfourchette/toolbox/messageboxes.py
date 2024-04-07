import html
import logging
import re
import sys
import traceback
from typing import Callable, Literal

from gitfourchette.qt import *
from gitfourchette.toolbox.excutils import shortenTracebackPath
from gitfourchette.toolbox.qtutils import onAppThread, setWindowModal, MakeNonNativeDialog

logger = logging.getLogger(__name__)

MessageBoxIconName = Literal['warning', 'information', 'question', 'critical']

_excMessageBoxQueue = []


def excMessageBox(
        exc,
        title="",
        message="",
        parent=None,
        printExc=True,
        showExcSummary=True,
        icon: MessageBoxIconName = 'critical',
        abortUnitTest=True,
):
    if abortUnitTest:
        from gitfourchette.settings import TEST_MODE
        if TEST_MODE:
            raise exc

    try:
        isCritical = icon == 'critical'

        if printExc:
            traceback.print_exception(exc.__class__, exc, exc.__traceback__)

        # Without a parent, show() won't work. Try to find a QMainWindow to use as the parent.
        if not parent:
            for tlw in QApplication.topLevelWidgets():
                if isinstance(tlw, QMainWindow):
                    parent = tlw
                    break

        # bail out if we're not running on Qt's application thread
        if not onAppThread():
            sys.stderr.write("excMessageBox: not on application thread; bailing out\n")
            return

        if not title:
            title = tr("Unhandled exception")
        if not message:
            message = tr("An exception was raised.")

        if showExcSummary:
            try:
                from gitfourchette.trtables import TrTables
                TrTables.init()
                summary = f"{TrTables.exceptionName(exc)}: {exc}"
            except:
                summary = traceback.format_exception_only(exc.__class__, exc)
                summary = ''.join(summary).strip()

            if len(summary) > 500:
                summary = summary[:500] + "... " + tr("(MESSAGE TRUNCATED)")
            message += "<br><br>" + html.escape(summary)
            if isCritical:
                message += "<p><small>" + tr("If you want to file a bug report, please click “Show Details” "
                                             "and copy the <b>entire</b> message.")

        details = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
        details = [shortenTracebackPath(line) for line in details]
        details = ''.join(details).strip()

        qmb = asyncMessageBox(parent, icon, title, message)
        qmb.setDetailedText(details)

        detailsEdit: QTextEdit = qmb.findChild(QTextEdit)
        if detailsEdit:
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            font.setPointSize(min(font.pointSize(), 8))
            detailsEdit.setFont(font)
            detailsEdit.setMinimumWidth(600)
            detailsEdit.setFixedHeight(300)

        # Keep user from triggering more exceptions by clicking on stuff in the background
        qmb.setWindowModality(Qt.WindowModality.ApplicationModal)

        if isCritical:
            from gitfourchette.settings import DEVDEBUG
            if DEVDEBUG:
                quitButton = qmb.addButton(QMessageBox.StandardButton.Reset)  # Reset button is leftmost in KDE
                quitButton.setText(tr("Quit application"))

        dismissButton = qmb.addButton(QMessageBox.StandardButton.Ok)
        qmb.setDefaultButton(dismissButton)
        qmb.setEscapeButton(dismissButton)

        # Show next error message in queue when finished
        qmb.finished.connect(_popExcMessageBoxQueue)

        # Add the qmb to the queue of error messages
        _excMessageBoxQueue.append(qmb)

        # Only show now if no other excMessageBox is currently being shown
        if len(_excMessageBoxQueue) <= 1:
            _showExcMessageBox(qmb)

    except BaseException as excMessageBoxError:
        sys.stderr.write(f"*********************************************\n")
        sys.stderr.write(f"excMessageBox failed!!!\n")
        sys.stderr.write(f"*********************************************\n")
        traceback.print_exception(excMessageBoxError)


def _popExcMessageBoxQueue(result = QMessageBox.StandardButton.Ok):
    if result == QMessageBox.StandardButton.Reset:
        logger.warning("Application aborted from message box.")
        QApplication.exit(1)
        return

    if result != QMessageBox.StandardButton.Ok:
        for qmb in _excMessageBoxQueue:
            qmb.deleteLater()
        _excMessageBoxQueue.clear()
        return

    _excMessageBoxQueue.pop(0)
    if not _excMessageBoxQueue:
        # No more messages to show
        return

    qmb = _excMessageBoxQueue[0]

    numRemaining = len(_excMessageBoxQueue) - 1
    if numRemaining >= 1:
        dismissAllButton = qmb.addButton(QMessageBox.StandardButton.NoToAll)
        dismissAllButton.setText(tr("Skip %n more errors", "", numRemaining))

    _showExcMessageBox(qmb)


def _showExcMessageBox(qmb):
    qmb.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog

    if qmb.parent():
        qmb.show()
    else:
        # Without a parent, show() won't work. So, use exec() as the very last resort.
        # (Calling exec() may crash on macOS if another modal dialog is active.)
        qmb.exec()


def asyncMessageBox(
        parent: QWidget,
        icon: MessageBoxIconName,
        title: str,
        text: str,
        buttons=QMessageBox.StandardButton.NoButton,
        macShowTitle=True,
        deleteOnClose=True,
) -> QMessageBox:

    assert onAppThread()
    assert parent is None or isinstance(parent, QWidget)

    loggedMessage = F"[{title}] " + html.unescape(re.sub(r"<[^<]+?>", " ", text))
    if icon in ['information', 'question']:
        logger.debug(loggedMessage)
    else:
        logger.warning(loggedMessage)

    icons = {
        'warning': QMessageBox.Icon.Warning,
        'information': QMessageBox.Icon.Information,
        'question': QMessageBox.Icon.Question,
        'critical': QMessageBox.Icon.Critical,
    }

    # macOS doesn't have a titlebar for message boxes, so put the title in the text
    if macShowTitle and MACOS:
        text = "<p><b>" + title + "</b></p>" + text

    qmb = QMessageBox(
        icons.get(icon, QMessageBox.Icon.NoIcon),
        title,
        text,
        buttons,
        parent=parent
    )

    if parent:
        setWindowModal(qmb)

    if deleteOnClose:
        qmb.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    # macOS hacks to remove "modern" styling
    if MACOS:
        qmb.setStyleSheet("QMessageBox QLabel { font-weight: normal; }")
        MakeNonNativeDialog(qmb)

    return qmb


def showWarning(parent: QWidget, title: str, text: str) -> QMessageBox:
    """
    Shows a warning message box asynchronously.
    """
    qmb = asyncMessageBox(parent, 'warning', title, text)
    qmb.show()
    return qmb


def showInformation(parent: QWidget, title: str, text: str) -> QMessageBox:
    """
    Shows an information message box asynchronously.
    """
    qmb = asyncMessageBox(parent, 'information', title, text)
    qmb.show()
    return qmb


def askConfirmation(
        parent: QWidget,
        title: str,
        text: str,
        callback: Callable | Slot | None = None,
        buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        okButtonText: str = "",
        okButtonIcon: QIcon | None = None,
        show=True,
        messageBoxIcon: MessageBoxIconName = "question",
) -> QMessageBox:
    """
    Shows a confirmation message box asynchronously.

    If you override `buttons`, be careful with your choice of StandardButton values;
    some of them won't emit the `accepted` signal which is connected to the callback.
    """

    qmb = asyncMessageBox(parent, messageBoxIcon, title, text, buttons)

    okButton = qmb.button(QMessageBox.StandardButton.Ok)
    if okButton:
        if okButtonText:
            okButton.setText(okButtonText)
        if okButtonIcon:
            okButton.setIcon(okButtonIcon)

    if callback:
        qmb.accepted.connect(callback)

    if show:
        qmb.show()

    return qmb


class NonCriticalOperation:
    def __init__(self, operation: str):
        self.operation = operation

    def __enter__(self):
        pass

    def __exit__(self, excType, excValue, excTraceback):
        if excValue:
            excMessageBox(excValue, message=tr("Operation failed: {0}.").format(html.escape(self.operation)))
            return True  # don't propagate
