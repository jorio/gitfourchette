# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import threading

import pytest

from gitfourchette.mainwindow import NoRepoWidgetError
from gitfourchette.toolbox import messageboxes
from gitfourchette.toolbox.messageboxes import excMessageBox
from .util import *


@pytest.fixture(autouse=True)
def cleanExcMessageBoxQueue():
    assert not messageboxes._excMessageBoxQueue, "excMessageBox queue leaked from a previous test"
    yield
    messageboxes._excMessageBoxQueue.clear()


def makeException(excType=ValueError, text="boom"):
    """ Raise and catch an exception so that it has a traceback. """
    def raisingFunctionForTraceback():
        raise excType(text)

    try:
        raisingFunctionForTraceback()
    except excType as exc:
        return exc
    raise AssertionError("unreachable")


def visibleMessageBoxes(parent: QWidget) -> list[QMessageBox]:
    return [qmb for qmb in parent.findChildren(QMessageBox) if qmb.isVisibleTo(parent)]


def testExcMessageBoxContents(mainWindow):
    exc = makeException(ValueError, "something <b>bad</b> happened")
    excMessageBox(exc, title="Custom Title", message="Custom message.", parent=mainWindow,
                  printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "Custom message.+something <b>bad</b> happened")
    assert qmb.windowTitle() == "Custom Title"
    assert qmb.icon() == QMessageBox.Icon.Critical
    assert qmb.windowModality() == Qt.WindowModality.ApplicationModal

    # Exception summary is HTML-escaped; bug report hint for critical errors
    assert "ValueError: something &lt;b&gt;bad&lt;/b&gt; happened" in qmb.text()
    assert "bug report" in qmb.text()

    # Details contain the traceback with shortened paths
    details = qmb.detailedText()
    assert details.startswith("Traceback")
    assert "raisingFunctionForTraceback" in details
    assert "test_messageboxes.py:" in details
    assert "ValueError: something <b>bad</b> happened" in details
    detailsEdit = qmb.findChild(QTextEdit)
    assert detailsEdit is not None
    assert detailsEdit.minimumWidth() == 600

    # Ok is the default/escape button; APP_DEBUG adds a "Quit application" button
    okButton = qmb.button(QMessageBox.StandardButton.Ok)
    assert okButton is not None
    assert qmb.defaultButton() is okButton
    assert qmb.escapeButton() is okButton
    quitButton = qmb.button(QMessageBox.StandardButton.Reset)
    assert APP_DEBUG
    assert quitButton is not None
    assert re.search("quit", quitButton.text(), re.I)
    assert qmb.button(QMessageBox.StandardButton.NoToAll) is None

    assert messageboxes._excMessageBoxQueue == [qmb]
    okButton.click()
    assert not visibleMessageBoxes(mainWindow)
    assert not messageboxes._excMessageBoxQueue


def testExcMessageBoxDefaults(mainWindow):
    exc = makeException(KeyError, "some key")
    # No parent given: excMessageBox should find the main window by itself
    excMessageBox(exc, printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "unhandled exception.+an exception was raised.+KeyError")
    assert qmb.parent() is mainWindow
    assert qmb.icon() == QMessageBox.Icon.Critical
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxPrintsException(mainWindow, capsys):
    exc = makeException(ValueError, "printed to stderr")
    excMessageBox(exc, parent=mainWindow, abortUnitTest=False)
    captured = capsys.readouterr()
    assert "ValueError: printed to stderr" in captured.err
    assert "raisingFunctionForTraceback" in captured.err
    acceptQMessageBox(mainWindow, "printed to stderr", QMessageBox.StandardButton.Ok)


def testExcMessageBoxAbortsUnitTest(mainWindow):
    exc = makeException(ValueError, "abort me")
    with pytest.raises(ValueError, match="abort me"):
        excMessageBox(exc, parent=mainWindow, printExc=False)

    # The box is still shown even though the exception was re-raised
    acceptQMessageBox(mainWindow, "abort me", QMessageBox.StandardButton.Ok)
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxNonCriticalIcon(mainWindow):
    exc = makeException(ValueError, "just a warning")
    excMessageBox(exc, title="Heads up", parent=mainWindow, icon="warning", printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "just a warning")
    assert qmb.icon() == QMessageBox.Icon.Warning
    assert "bug report" not in qmb.text()
    assert qmb.detailedText()
    # The "Quit application" button is only added for critical errors
    assert qmb.button(QMessageBox.StandardButton.Reset) is None
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxWithoutSummary(mainWindow):
    exc = makeException(ValueError, "secret summary")
    excMessageBox(exc, message="Only this message.", parent=mainWindow,
                  showExcSummary=False, printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "Only this message")
    assert "secret summary" not in qmb.text()
    assert not qmb.detailedText()
    assert qmb.findChild(QTextEdit) is None
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxNoRepoWidget(mainWindow):
    exc = makeException(NoRepoWidgetError, "no rw")
    excMessageBox(exc, title="ignored title", message="ignored message", parent=mainWindow,
                  printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "no repository.+please open a repository")
    assert qmb.icon() == QMessageBox.Icon.Information
    assert "ignored" not in qmb.text()
    assert "no rw" not in qmb.text()
    assert not qmb.detailedText()
    assert qmb.button(QMessageBox.StandardButton.Reset) is None
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxTruncatesLongSummary(mainWindow):
    longText = "x" * 2000
    exc = makeException(ValueError, longText)
    excMessageBox(exc, parent=mainWindow, printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "message truncated")
    assert longText not in qmb.text()
    assert "x" * 400 in qmb.text()
    # The full text is still available in the details
    assert longText in qmb.detailedText()
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxSummaryFallback(mainWindow, monkeypatch):
    from gitfourchette import trtables

    def brokenExceptionName(exc):
        raise RuntimeError("translation table unavailable")

    monkeypatch.setattr(trtables, "exceptionName", brokenExceptionName)

    excMessageBox(makeException(ValueError, "fallback summary"), parent=mainWindow,
                  printExc=False, abortUnitTest=False)
    qmb = findQMessageBox(mainWindow, "ValueError: fallback summary")
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxNotOnAppThread(mainWindow, capfd):
    exc = makeException(ValueError, "from another thread")

    thread = threading.Thread(target=lambda: excMessageBox(exc, printExc=False, abortUnitTest=False))
    thread.start()
    thread.join()

    assert "not on application thread" in capfd.readouterr().err
    QTest.qWait(0)
    assert not visibleMessageBoxes(mainWindow)
    assert not messageboxes._excMessageBoxQueue


def testExcMessageBoxQueue(mainWindow):
    for i in range(1, 4):
        excMessageBox(makeException(ValueError, f"error #{i}"), parent=mainWindow,
                      printExc=False, abortUnitTest=False)

    # Only the first error is shown; the others are queued
    assert len(messageboxes._excMessageBoxQueue) == 3
    boxes = visibleMessageBoxes(mainWindow)
    assert len(boxes) == 1
    qmb1 = findQMessageBox(mainWindow, "error #1")
    assert qmb1.button(QMessageBox.StandardButton.NoToAll) is None
    with pytest.raises(KeyError):
        findQMessageBox(mainWindow, "error #2")

    # Dismiss the first one: the second one shows up, offering to skip the remaining one
    qmb1.button(QMessageBox.StandardButton.Ok).click()
    assert len(messageboxes._excMessageBoxQueue) == 2
    assert len(visibleMessageBoxes(mainWindow)) == 1
    qmb2 = findQMessageBox(mainWindow, "error #2")
    skipButton = qmb2.button(QMessageBox.StandardButton.NoToAll)
    assert skipButton is not None
    assert re.search(r"skip 1 more error\b", skipButton.text(), re.I)

    # Dismiss the second one: the third (last) one shows up, without a skip button
    qmb2.button(QMessageBox.StandardButton.Ok).click()
    assert len(messageboxes._excMessageBoxQueue) == 1
    assert len(visibleMessageBoxes(mainWindow)) == 1
    qmb3 = findQMessageBox(mainWindow, "error #3")
    assert qmb3.button(QMessageBox.StandardButton.NoToAll) is None

    # Dismiss the last one: nothing left
    qmb3.button(QMessageBox.StandardButton.Ok).click()
    assert not messageboxes._excMessageBoxQueue
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxQueueSkipAll(mainWindow):
    for i in range(1, 5):
        excMessageBox(makeException(ValueError, f"error #{i}"), parent=mainWindow,
                      printExc=False, abortUnitTest=False)
    assert len(messageboxes._excMessageBoxQueue) == 4

    findQMessageBox(mainWindow, "error #1").button(QMessageBox.StandardButton.Ok).click()

    qmb2 = findQMessageBox(mainWindow, "error #2")
    skipButton = qmb2.button(QMessageBox.StandardButton.NoToAll)
    assert re.search(r"skip 2 more errors", skipButton.text(), re.I)

    # Skipping discards all remaining errors
    skipButton.click()
    assert not messageboxes._excMessageBoxQueue
    QTest.qWait(0)
    assert not visibleMessageBoxes(mainWindow)

    # A new error after skipping is shown immediately
    excMessageBox(makeException(ValueError, "fresh error"), parent=mainWindow,
                  printExc=False, abortUnitTest=False)
    qmb = findQMessageBox(mainWindow, "fresh error")
    assert qmb.button(QMessageBox.StandardButton.NoToAll) is None
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not messageboxes._excMessageBoxQueue
    assert not visibleMessageBoxes(mainWindow)


def testExcMessageBoxQuitApplication(mainWindow, monkeypatch):
    exitCodes = []
    monkeypatch.setattr(QApplication, "exit", lambda code=0: exitCodes.append(code))

    excMessageBox(makeException(ValueError, "fatal"), parent=mainWindow, printExc=False, abortUnitTest=False)
    excMessageBox(makeException(ValueError, "queued"), parent=mainWindow, printExc=False, abortUnitTest=False)

    qmb = findQMessageBox(mainWindow, "fatal")
    qmb.button(QMessageBox.StandardButton.Reset).click()
    assert exitCodes == [1]

    # The queue isn't processed any further after asking to quit
    with pytest.raises(KeyError):
        findQMessageBox(mainWindow, "queued")
    assert not visibleMessageBoxes(mainWindow)

    # Clean up the queued box that was never shown
    for leftover in messageboxes._excMessageBoxQueue:
        leftover.deleteLater()


def testShowExcMessageBoxWithoutParent(mainWindow):
    # Without a parent, _showExcMessageBox falls back to exec()
    qmb = QMessageBox(QMessageBox.Icon.Critical, "Orphan", "orphan box", QMessageBox.StandardButton.Ok)
    shown = []
    destroyed = []
    qmb.destroyed.connect(lambda: destroyed.append(True))

    def dismiss():
        shown.append(qmb.isVisible())
        qmb.button(QMessageBox.StandardButton.Ok).click()

    QTimer.singleShot(0, dismiss)
    messageboxes._showExcMessageBox(qmb)  # blocks until dismissed
    assert shown == [True]
    # WA_DeleteOnClose was set, so the box doesn't leak
    waitUntilTrue(lambda: destroyed)
