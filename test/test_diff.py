# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest
import re
import textwrap

from gitfourchette.diffview.diffview import DiffView
from gitfourchette.nav import NavLocator
from .util import *


def writeLongFile(path, numLines, numWordsPerLine) -> str:
    text = ""
    for y in range(numLines):
        text += " ".join(f"y{y}x{x}" for x in range(numWordsPerLine)) + "\n"
    writeFile(path, text)
    return path


def testEmptyDiffEmptyFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    touchFile(F"{wd}/NewEmptyFile.txt")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)

    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert re.search(r"empty file", rw.specialDiffView.toPlainText(), re.I)


@pytest.mark.skipif(WINDOWS, reason="file modes are flaky on Windows")
def testEmptyDiffWithModeChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    os.chmod(f"{wd}/a/a1", 0o755)
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    assert re.search(r"mode change:.+(normal|regular).+executable", rw.specialDiffView.toPlainText(), re.I)


def testEmptyDiffWithNameChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    os.rename(f"{wd}/master.txt", f"{wd}/mastiff.txt")
    with RepoContext(wd) as repo:
        repo.index.remove("master.txt")
        repo.index.add("mastiff.txt")
        repo.index.write()
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.stagedFiles, 0)
    assert re.search(r"renamed:.+master\.txt.+mastiff\.txt", rw.specialDiffView.toPlainText(), re.I)


def testDiffDeletedFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    os.unlink(f"{wd}/master.txt")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.toPlainText().startswith("@@ -1,2 +0,0 @@")


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
@pytest.mark.parametrize("method", ["key", "button", "mmbviewport", "mmbgutter"])
def testDiffViewStageLines(tempDir, mainWindow, method):
    mainWindow.onAcceptPrefsDialog({"middleClickToStage": True})

    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/NewFile.txt", "line A\nline B\nline C\nline D\nline E")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    assert rw.repo.status() == {"NewFile.txt": FileStatus.WT_NEW}

    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)

    assert not rw.diffView.rubberBand.isVisible()
    assert not rw.diffView.rubberBandButtonGroup.isVisible()

    qteClickBlock(rw.diffView, 0)
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)
    assert re.search(r"can.t stage", mainWindow.statusBar().currentMessage(), re.I)
    qteSelectBlocks(rw.diffView, 3, 4)

    assert rw.diffView.rubberBand.isVisible()
    assert rw.diffView.rubberBandButtonGroup.isVisible()
    assert rw.diffView.rubberBandButtonGroup.pos().y() < rw.diffView.rubberBand.pos().y()

    qteSelectBlocks(rw.diffView, 4, 3)
    assert rw.diffView.rubberBandButtonGroup.pos().y() < rw.diffView.rubberBand.pos().y()

    if method == "key":
        QTest.keyPress(rw.diffView, Qt.Key.Key_Return)
    elif method == "button":
        rw.diffView.stageButton.click()
    elif method == "mmbviewport":
        QTest.mouseClick(rw.diffView.viewport(), Qt.MouseButton.MiddleButton)
    elif method == "mmbgutter":
        QTest.mouseClick(rw.diffView.gutter, Qt.MouseButton.MiddleButton)
    else:
        raise NotImplementedError(f"Unknown method {method}")

    assert rw.repo.status() == {"NewFile.txt": FileStatus.INDEX_NEW | FileStatus.WT_MODIFIED}

    stagedId = rw.repo.index["NewFile.txt"].id
    stagedBlob = rw.repo.peel_blob(stagedId)
    assert stagedBlob.data == b"line C\nline D\n"


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
def testDiffViewStageAllLinesThenJumpToNextFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/aaaaa.txt", "line A\nlineB\n")
    writeFile(f"{wd}/master.txt", "\n".join(["On master"]*50))
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("aaaaa.txt"), check=True)

    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    qteSelectBlocks(rw.diffView, 1, 2)
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)

    assert NavLocator.inUnstaged("master.txt").isSimilarEnoughTo(rw.navLocator)
    assert 0 == rw.diffView.textCursor().blockNumber()


def testPartialPatchSpacesInFilename(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/file with spaces.txt", "line A\nline B\nline C\n")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    assert rw.repo.status() == {"file with spaces.txt": FileStatus.WT_NEW}

    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    qteClickBlock(rw.diffView, 1)
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)

    assert rw.repo.status() == {"file with spaces.txt": FileStatus.INDEX_NEW | FileStatus.WT_MODIFIED}

    stagedId = rw.repo.index["file with spaces.txt"].id
    stagedBlob = rw.repo.peel_blob(stagedId)
    assert stagedBlob.data == b"line A\n"


@pytest.mark.skipif(WINDOWS, reason="file modes are flaky on Windows")
def testPartialPatchPreservesExecutableFileMode(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        os.chmod(F"{wd}/master.txt", 0o755)
        repo.index.add_all(["master.txt"])
        repo.create_commit_on_head("master.txt +x", TEST_SIGNATURE, TEST_SIGNATURE)

    writeFile(F"{wd}/master.txt", "This file is +x now\nOn master\nOn master\nDon't stage this line\n")

    rw = mainWindow.openRepo(wd)
    assert rw.repo.status() == {"master.txt": FileStatus.WT_MODIFIED}

    # Partial patch of first modified line
    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    QTest.keyPress(rw.diffView, Qt.Key.Key_Down)    # Skip hunk line (@@...@@)
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)  # Stage first modified line
    assert rw.repo.status() == {"master.txt": FileStatus.WT_MODIFIED | FileStatus.INDEX_MODIFIED}

    staged = rw.repo.get_staged_changes()
    delta = next(staged.deltas)
    assert delta.new_file.path == "master.txt"
    assert delta.new_file.mode & 0o777 == 0o755

    unstaged = rw.repo.get_unstaged_changes()
    delta = next(unstaged.deltas)
    assert delta.new_file.path == "master.txt"
    assert delta.new_file.mode & 0o777 == 0o755


def testDiscardHunkNoEOL(tempDir, mainWindow):
    NEW_CONTENTS = "change without eol"

    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/master.txt", NEW_CONTENTS)
    rw = mainWindow.openRepo(wd)

    assert rw.repo.status() == {"master.txt": FileStatus.WT_MODIFIED}

    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.setFocus()
    rw.diffView.discardHunk(0)

    acceptQMessageBox(rw, "discard.+hunk")
    assert NEW_CONTENTS not in readFile(f"{wd}/master.txt").decode('utf-8')


def testSubpatchNoEOL(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        # Commit a file WITHOUT a newline at end
        writeFile(F"{wd}/master.txt", "hello")
        repo.index.add_all(["master.txt"])
        repo.create_commit_on_head("no newline at end of file", TEST_SIGNATURE, TEST_SIGNATURE)

        # Add a newline to the file without committing
        writeFile(F"{wd}/master.txt", "hello\n")

    rw = mainWindow.openRepo(wd)
    assert rw.repo.status() == {"master.txt": FileStatus.WT_MODIFIED}

    # Initiate subpatch by selecting lines and hitting return
    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    rw.diffView.selectAll()
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)
    assert rw.repo.status() == {"master.txt": FileStatus.INDEX_MODIFIED}

    # It must also work in reverse - let's unstage this change via a subpatch
    qlvClickNthRow(rw.stagedFiles, 0)
    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    rw.diffView.selectAll()
    QTest.keyPress(rw.diffView, Qt.Key.Key_Delete)
    assert rw.repo.status() == {"master.txt": FileStatus.WT_MODIFIED}

    # Finally, let's discard this change via a subpatch
    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    rw.diffView.selectAll()
    QTest.keyPress(rw.diffView, Qt.Key.Key_Delete)
    acceptQMessageBox(rw, "discard")
    assert rw.repo.status() == {}


@pytest.mark.parametrize("closeManually", [True, False])
def testDiffInNewWindow(tempDir, mainWindow, closeManually):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert mainWindow in QApplication.topLevelWidgets()

    oid = Oid(hex='1203b03dc816ccbb67773f28b3c19318654b0bc8')
    rw.jump(NavLocator.inCommit(oid, "c/c2.txt"), check=True)
    qlvClickNthRow(rw.committedFiles, 0)

    rw.committedFiles.openDiffInNewWindow.emit(rw.diffView.currentPatch, rw.navLocator)
    waitUntilTrue(lambda: not mainWindow.isActiveWindow())

    diffWindow = next(w for w in QApplication.topLevelWidgets() if w.objectName() == "DetachedDiffWindow")
    diffWidget: DiffView = diffWindow.findChild(DiffView)
    assert diffWindow is not mainWindow
    assert diffWindow is diffWidget.window()
    assert "c2.txt" in diffWindow.windowTitle()
    assert not mainWindow.isActiveWindow()

    # Initiate search
    QTest.keySequence(diffWidget, QKeySequence.StandardKey.Find)
    assert diffWidget.searchBar.isVisible()

    # Make sure the diff is closed when the repowidget is gone
    if closeManually:
        QTest.keySequence(diffWidget, QKeySequence.StandardKey.Close)  # Note: "Ctrl+W" may not work in offscreen tests!
    else:
        mainWindow.closeAllTabs()

    QTest.qWait(0)  # doesn't get a chance to clean up windows without this...
    assert 1 == len(QGuiApplication.topLevelWindows())


def testSearchDiff(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex='0966a434eb1a025db6b71485ab63a3bfbea520b6')
    rw.jump(NavLocator.inCommit(oid, path="master.txt"))

    diffView = rw.diffView
    searchBar = rw.diffView.searchBar
    searchLine = rw.diffView.searchBar.lineEdit
    searchNext = searchBar.ui.forwardButton
    searchPrev = searchBar.ui.backwardButton

    diffView.setFocus()
    waitUntilTrue(diffView.hasFocus)

    assert not searchBar.isVisible()
    QTest.keySequence(diffView, "Ctrl+F")  # window to be shown for this to work!
    assert searchBar.isVisible()

    QTest.keyClicks(searchLine, "master")
    searchNext.click()
    forward1 = diffView.textCursor()
    assert forward1.selectedText() == "master"

    searchNext.click()
    forward2 = diffView.textCursor()
    assert forward1 != forward2
    assert forward2.selectedText() == "master"
    assert forward2.position() > forward1.position()

    searchNext.click()
    acceptQMessageBox(rw, "no more occurrences")
    forward1Copy = diffView.textCursor()
    assert forward1Copy == forward1  # should have wrapped around

    # Now search in reverse
    searchPrev.click()
    acceptQMessageBox(rw, "no more occurrences")
    reverse1 = diffView.textCursor()
    assert reverse1.selectedText() == "master"
    assert reverse1 == forward2

    searchPrev.click()
    reverse2: QTextCursor = diffView.textCursor()
    assert reverse2 == forward1

    searchPrev.click()
    acceptQMessageBox(rw, "no more occurrences")
    reverse3: QTextCursor = diffView.textCursor()
    assert reverse3 == reverse1

    # Search for nonexistent text
    QTest.keySequence(diffView, "Ctrl+F")  # window to be shown for this to work!
    assert searchBar.isVisible()
    searchBar.lineEdit.setFocus()
    if QT5:  # Qt5 is somehow finicky here (else-branch works perfectly in Qt6) - not important enough to troubleshoot - Qt5 is on the way out
        searchBar.lineEdit.setText("MadeUpGarbage")
        assert searchBar.isRed()
        searchBar.ui.forwardButton.click()
    else:
        assert searchBar.lineEdit.hasSelectedText()  # hitting ctrl+f should reselect text
        QTest.keyClicks(searchLine, "MadeUpGarbage")
        assert searchBar.lineEdit.text() == "MadeUpGarbage"
        assert searchBar.isRed()
        QTest.keyPress(searchLine, Qt.Key.Key_Return)
    # Reject last message box to prevent wrapping again
    rejectQMessageBox(rw, "no.+occurrence.+of.+MadeUpGarbage.+found")


def testCopyFromDiffWithoutU2029(tempDir, mainWindow):
    """
    At some point, Qt 6 used to replace line breaks with U+2029 (PARAGRAPH
    SEPARATOR) when copying text from a QPlainTextEdit. We used to have a
    workaround that scrubbed this character from the clipboard.

    As of 2/2024, I haven't noticed this behavior in over a year, so I nuked
    the workaround. This test ensures that the clipboard is still clean.

    This behavior is still documented in the Qt docs, though...
    https://doc.qt.io/qt-6/qtextcursor.html#selectedText
    "If the selection obtained from an editor spans a line break, the text
    will contain a Unicode U+2029 paragraph separator character instead of
    a newline \n character. Use QString::replace() to replace these
    characters with newlines."
    """

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex='0966a434eb1a025db6b71485ab63a3bfbea520b6')
    rw.jump(NavLocator.inCommit(oid, path="master.txt"), check=True)

    diffView = rw.diffView
    diffView.setFocus()
    waitUntilTrue(diffView.hasFocus)
    diffView.selectAll()
    diffView.copy()
    QTest.qWait(1)

    clipped = QApplication.clipboard().text()
    assert "\u2029" not in clipped
    assert clipped == (
        "@@ -1 +1,2 @@\n"
        "On master\n"
        "On master"
    )


def testDiffStrayLineEndings(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/crlf.txt", "hi\r\nhow you doin\r\nbye")
    writeFile(f"{wd}/cr.txt", "ancient mac file\r")

    if WINDOWS:
        with RepoContext(wd) as repo:
            repo.config['core.autocrlf'] = False

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged(path="crlf.txt"), check=True)
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().lower() == (
        "@@ -0,0 +1,3 @@\n"
        "hi<crlf>\n"
        "how you doin<crlf>\n"
        "bye<no newline at end of file>"
    )

    # We're kinda cheating here - cr.txt consists of a single line because
    # libgit2 doesn't consider CR to be a linebreak when creating a Diff.
    # Even then, what we have is still better than nothing for the rare use
    # case of importing an ancient Mac file from the 80s/90s into a Git repo.
    rw.jump(NavLocator.inUnstaged(path="cr.txt"), check=True)
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().lower() == (
        "@@ -0,0 +1 @@\n"
        "ancient mac file<cr>"
    )


def testDiffBinaryWarning(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with open(f"{wd}/binary.whatever", "wb") as f:
        f.write(b"\x00\x00\x00\x00")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="binary.whatever"), check=True)
    assert rw.specialDiffView.isVisible()
    assert "binary" in rw.specialDiffView.toPlainText().lower()


def testDiffVeryLongLines(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    contents = " ".join(f"foo{i}" for i in range(5000)) + "\n"
    writeFile(f"{wd}/longlines.txt", contents)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="longlines.txt"))
    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert "long lines" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().rstrip() == "@@ -0,0 +1 @@\n" + contents.rstrip()


def testDiffLargeFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # About one megabyte
    contents = "\n".join(f"{i:08x}." for i in range(100_000)) + "\n"
    writeFile(f"{wd}/bigfile.txt", contents)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="bigfile.txt"), check=True)
    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert "diff is very large" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().rstrip() == "@@ -0,0 +1,100000 @@\n" + contents.rstrip()


def testDiffLargeFilesWithVeryLongLines(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    numLines = 50
    longLine = " ".join(f"foo{i}" for i in range(5_000)) + "\n"
    contents = longLine * numLines
    assert len(contents) > 1_000_000
    writeFile(f"{wd}/longlines.txt", contents)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="longlines.txt"), check=True)
    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert "diff is very large" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().rstrip() == f"@@ -0,0 +1,{numLines} @@\n{contents.rstrip()}"


def testDiffImage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shutil.copyfile(getTestDataPath("image1.png"), f"{wd}/image.png")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("image.png"), check=True)
    assert rw.specialDiffView.isVisible()
    assert re.search("6.6 pixels", rw.specialDiffView.toPlainText())
    rw.diffArea.dirtyFiles.stage()
    rw.diffArea.commitButton.click()
    findQDialog(rw, "commit").ui.summaryEditor.setText("commit an image")
    findQDialog(rw, "commit").accept()

    shutil.copyfile(getTestDataPath("image2.png"), f"{wd}/image.png")
    rw.refreshRepo()
    rw.jump(NavLocator.inUnstaged("image.png"), check=True)
    assert rw.specialDiffView.isVisible()
    assert re.search("6.6 pixels", rw.specialDiffView.toPlainText())
    assert re.search("4.4 pixels", rw.specialDiffView.toPlainText())

    os.unlink(f"{wd}/image.png")
    rw.refreshRepo()
    rw.jump(NavLocator.inUnstaged("image.png"), check=True)
    assert rw.specialDiffView.isVisible()
    assert re.search("6.6 pixels", rw.specialDiffView.toPlainText())


def testDiffLargeImage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shutil.copyfile(getTestDataPath("image1.png"), f"{wd}/image.png")
    with open(f"{wd}/image.png", "ab") as binfile:
        binfile.write(b"\x00" * 6_000_000)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("image.png"), check=True)
    assert rw.specialDiffView.isVisible()
    assert "image is very large" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.specialDiffView.isVisible()
    assert "image is very large" not in rw.specialDiffView.toPlainText().lower()


def testDiffSvgImage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shutil.copyfile(getTestDataPath("image3.svg"), f"{wd}/image.svg")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("image.svg"), check=True)
    assert rw.diffView.isVisible()
    assert "<svg xmlns=" in rw.diffView.toPlainText()

    mainWindow.onAcceptPrefsDialog({"renderSvg": True})
    assert rw.specialDiffView.isVisible()
    assert re.search("16.16 pixels", rw.specialDiffView.toPlainText())


def testDiffTypeChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    Path(f"{wd}/a/a1").unlink()
    Path(f"{wd}/a/a1").symlink_to(f"{wd}/master.txt")

    rw = mainWindow.openRepo(wd)
    assert rw.specialDiffView.isVisible()
    text = rw.specialDiffView.toPlainText()
    assert re.search(r"type has changed", text, re.I)
    assert re.search(r"old type.+regular file.+new type.+symbolic link", text, re.I | re.S)


def testDiffViewSelectionStableAfterRefresh(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "please don't nuke my selection\n")

    rw = mainWindow.openRepo(wd)
    diffView = rw.diffView

    rw.jump(NavLocator.inUnstaged("master.txt"), check=True)
    assert not diffView.textCursor().hasSelection()

    # Select some text
    diffView.selectAll()
    assert diffView.textCursor().hasSelection()
    assert (0, 3) == diffView.getSelectedLineExtents()

    # Selection must be stable if file didn't change
    rw.refreshRepo()
    assert diffView.textCursor().hasSelection()
    assert (0, 3) == diffView.getSelectedLineExtents()

    # Selection cleared if file did change
    writeFile(f"{wd}/master.txt", "please DO!!! nuke my selection\n")
    rw.refreshRepo()
    assert not diffView.textCursor().hasSelection()


def testDiffContextLinesSetting(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        writeFile(f"{wd}/context.txt", "\n".join(f"line {i}" for i in range(1, 50)))
        repo.index.add("context.txt")
        repo.create_commit_on_head("context", TEST_SIGNATURE, TEST_SIGNATURE)
        writeFile(f"{wd}/context.txt", "\n".join(f"line {i}" if i != 25 else f"LINE {i}" for i in range(1, 50)))

    rw = mainWindow.openRepo(wd)
    assert NavLocator.inUnstaged("context.txt").isSimilarEnoughTo(rw.navLocator)

    # 1 hunk line, 3 context lines above change, 2 changed lines (- then +), 3 context lines below change
    assert 1+3+2+3 == len(rw.diffView.toPlainText().splitlines())

    prefsDialog = mainWindow.openPrefsDialog("contextLines")
    waitUntilTrue(lambda: QApplication.focusWidget() is not None
                  and QApplication.focusWidget().objectName() == "prefctl_contextLines")
    QTest.keyClicks(QApplication.focusWidget(), "8")
    prefsDialog.accept()

    # 1 hunk line, 8 context lines above change, 2 changed lines (- then +), 8 context lines below change
    assert 1+8+2+8 == len(rw.diffView.toPlainText().splitlines())


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
def testDiffGutterMouseInputs(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/manylines.txt", "\n".join(f"line {i}" for i in range(1, 1001)))
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView
    LMB = Qt.MouseButton.LeftButton

    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"), check=True)

    def selection():
        text = dv.textCursor().selectedText()
        return text.replace("\u2029", "\n")

    def clearSelection():
        cursor = dv.textCursor()
        cursor.clearSelection()
        dv.setTextCursor(cursor)

    assert not selection()

    line1 = qteBlockPoint(dv, 0)
    line2 = qteBlockPoint(dv, 1)
    line3 = qteBlockPoint(dv, 2)

    # Click on first line
    clearSelection()
    QTest.mouseClick(dv.gutter, LMB, pos=line1)
    assert "@@ -1 +1,2 @@" == selection()

    # Shift-click on second line
    clearSelection()
    QTest.mouseClick(dv.gutter, LMB, Qt.KeyboardModifier.ShiftModifier, pos=line2)
    assert "@@ -1 +1,2 @@\nc1" == selection()

    # Click on first line, hold button and move to second line
    clearSelection()
    QTest.mousePress(dv.gutter, LMB, pos=line1)
    QTest.mouseMove(dv.gutter, pos=line2)
    QTest.mouseRelease(dv.gutter, LMB, pos=line2)
    assert "@@ -1 +1,2 @@\nc1" == selection()

    # Click on second line, then shift-click on first line
    clearSelection()
    QTest.mouseClick(dv.gutter, LMB, pos=line2)
    QTest.mouseClick(dv.gutter, LMB, Qt.KeyboardModifier.ShiftModifier, pos=line1)
    assert "@@ -1 +1,2 @@\nc1" == selection()

    # Double-click on first line: Select entire hunk
    clearSelection()
    QTest.mouseDClick(dv.gutter, LMB, pos=line1)
    assert "@@ -1 +1,2 @@\nc1\nc1" == selection()

    # Double-click on context line: Nothing happens
    clearSelection()
    QTest.mouseDClick(dv.gutter, LMB, pos=line2)
    assert not selection()

    # Double-click on green/red line: Select clump
    clearSelection()
    QTest.mouseDClick(dv.gutter, LMB, pos=line3)
    assert "c1" == selection()

    rw.jump(NavLocator.inUnstaged("manylines.txt"), check=True)
    assert dv.firstVisibleBlock().blockNumber() == 0
    postMouseWheelEvent(dv.gutter, -120)
    QTest.qWait(1)
    assert dv.firstVisibleBlock().blockNumber() == 3


def testDiffViewStageBlankLines(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/hello.txt", "Hello1\n\nHello2\n\n")
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView
    LMB = Qt.MouseButton.LeftButton

    rw.jump(NavLocator.inUnstaged("hello.txt"), check=True)

    dv.setFocus()
    waitUntilTrue(dv.hasFocus)

    line1 = qteBlockPoint(dv, 1)  # Hello1
    line2 = qteBlockPoint(dv, 2)  # (blank)
    # line3 = qteBlockPoint(dv, 3)  # Hello2
    line4 = qteBlockPoint(dv, 4)  # (blank)

    # Stage "Hello1\n\n"
    QTest.mouseClick(dv.gutter, LMB, pos=line1)
    QTest.mouseClick(dv.gutter, LMB, Qt.KeyboardModifier.ShiftModifier, pos=line2)
    QTest.keyPress(dv, Qt.Key.Key_Return)
    assert b"Hello1\n\n" == rw.repo.peel_blob(rw.repo.index["hello.txt"].id).data

    # Stage blank line before Hello2
    QTest.mouseClick(dv.gutter, LMB, pos=line4)
    QTest.keyPress(dv, Qt.Key.Key_Return)
    assert b"Hello1\n\n\n" == rw.repo.peel_blob(rw.repo.index["hello.txt"].id).data


def testDiffViewMouseWheelZoom(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/manylines.txt", "\n".join(f"line {i}" for i in range(1, 1001)))
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    initialFont = dv.font()
    initialPointSize = initialFont.pointSize()

    def scroll(delta: int):
        postMouseWheelEvent(dv.gutter, delta, modifiers=Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(0)
        return dv.font().pointSize()

    assert scroll(120) > initialPointSize
    assert scroll(-120) == initialPointSize
    assert scroll(-120) < initialPointSize

    # Test size floor
    for _i in range(50):
        minPointSize = scroll(-120)
    assert scroll(-120) == minPointSize


def testToggleWordWrap(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    mainWindow.resize(999, 400)

    writeLongFile(f"{wd}/longfile.txt", 50, 200)

    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    rw.jump(NavLocator.inUnstaged("longfile.txt"), check=True)
    assert dv.horizontalScrollBar().isVisible()

    # Scroll down a bit and look at the first visible word
    dv.verticalScrollBar().setValue(5)
    assert dv.firstVisibleBlock().text().startswith("y4x0")

    for enableWrap in [True, False]:
        # Toggle word wrap
        triggerContextMenuAction(dv.viewport(), "word wrap")
        QTest.qWait(0)

        # Horizontal scroll bar should only be visible without wrap
        assert dv.horizontalScrollBar().isVisible() == (not enableWrap)

        # Scroll position should be stable after toggling word wrap
        assert dv.firstVisibleBlock().text().startswith("y4x0")


def testRestoreScrollPositionWithWordWrap(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(f"{wd}/dontcare.txt", "whatever")
    writeLongFile(f"{wd}/longfile.txt", 50, 200)

    # Enable word wrap and make window narrow enough for the lines to wrap significantly
    mainWindow.onAcceptPrefsDialog({"wordWrap": True})
    mainWindow.resize(999, 600)

    rw = mainWindow.openRepo(wd)
    dv = rw.diffView
    scrollBar = dv.verticalScrollBar()

    rw.jump(NavLocator.inUnstaged("longfile.txt"), check=True)
    assert not dv.horizontalScrollBar().isVisible()
    assert scrollBar.isVisible()

    def getTopLeftWord():
        cursor = dv.topLeftCornerCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfWord, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText()

    # Scroll down to 100th+ word on 25th line
    while not re.match(r"y25x1\d\d", getTopLeftWord()):
        value = scrollBar.value() + 1
        scrollBar.setValue(value)
        assert value == scrollBar.value(), "scrolled too far"

    # Remember which exact word it is (it's unlikely to be exactly y25x100 - 'x' may be a bit above 100)
    expectedRestoreScrollToWord = getTopLeftWord()

    # Jump to another file so that we back up the current position on longline.txt
    rw.jump(NavLocator.inUnstaged("dontcare.txt"), check=True)
    assert getTopLeftWord() == "@@"

    # Jump back to longline.txt and make sure we've restored the correct scroll position
    rw.jump(NavLocator.inUnstaged("longfile.txt"), check=True)
    assert getTopLeftWord() == expectedRestoreScrollToWord


@pytest.mark.parametrize("fromGutter", [False, True])
def testExportPatchFromHunk(tempDir, mainWindow, fromGutter):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"))

    triggerContextMenuAction(dv.gutter if fromGutter else dv.viewport(), "export hunk.+as patch")
    exportedPath = acceptQFileDialog(rw, "export", f"{tempDir.name}", useSuggestedName=True)
    assert exportedPath.endswith("c1.txt[partial].patch")
    assert readTextFile(exportedPath).endswith(
        "--- a/c/c1.txt\n"
        "+++ b/c/c1.txt\n"
        "@@ -1,1 +1,2 @@\n"
        " c1\n"
        "+c1\n")


@pytest.mark.parametrize("fromGutter", [False, True])
def testRevertHunk(tempDir, mainWindow, fromGutter):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    assert readTextFile(f"{wd}/c/c1.txt") == "c1\nc1\n"

    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"))

    triggerContextMenuAction(dv.gutter if fromGutter else dv.viewport(), "revert hunk")
    acceptQMessageBox(rw, "do you want to revert this hunk")

    assert NavLocator.inUnstaged("c/c1.txt").isSimilarEnoughTo(rw.navLocator)
    assert readTextFile(f"{wd}/c/c1.txt") == "c1\n"


@pytest.mark.parametrize(
    ["commitHex", "path", "line1", "line2", "expectedResult"],
    [
        ("c070ad8", "a/a1.txt", 1, 1, "a1\n"),
        ("c070ad8", "a/a1.txt", 1, 2, ""),
        ("58be465", "master.txt", 1, 2, "On master\n"),
        ("c9ed7bf", "c/c2-2.txt", 1, 1, "c2\n"),  # Revert deleted lines in deleted file
    ])
def testRevertLineSelection(tempDir, mainWindow,
                            commitHex, path, line1, line2, expectedResult):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    oid = rw.repo[commitHex].peel(Commit).id
    rw.jump(NavLocator.inCommit(oid, path), check=True)
    qteSelectBlocks(rw.diffArea.diffView, line1, line2)
    triggerContextMenuAction(rw.diffArea.diffView.gutter, "revert lines")
    acceptQMessageBox(rw, "do you want to revert the selected lines")
    assert readTextFile(f"{wd}/{path}") == expectedResult


def testRevertLineSelectionDontUseTooMuchContext(tempDir, mainWindow):
    rev1 = textwrap.dedent("""\
        1
        2
        3
        4
        5
        6
        7
    """)

    rev2 = textwrap.dedent("""\
        1 Unrelated change in rev2
        2 Unrelated change in rev2
        3
        4
        5
        6 Let's reverse this from rev2
        7
    """)

    rev3 = textwrap.dedent("""\
        1 Unrelated change in rev2
        2 Another change in rev3 to throw off 'git apply' with too much context
        3
        4
        5
        6 Let's reverse this from rev2
        7
    """)

    expectedResult = textwrap.dedent("""\
        1 Unrelated change in rev2
        2 Another change in rev3 to throw off 'git apply' with too much context
        3
        4
        5
        6
        7
    """)

    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        def createCommit(text):
            writeFile(f"{wd}/master.txt", text)
            repo.index.add_all()
            return repo.create_commit_on_head("test permissive revert")
        createCommit(rev1)
        commit2 = createCommit(rev2)
        createCommit(rev3)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(commit2, "master.txt"), check=True)

    qteSelectBlocks(rw.diffArea.diffView, 8, 9)
    assert rw.diffArea.diffView.textCursor().selectedText() == "6\u20296 Let's reverse this from rev2"

    triggerContextMenuAction(rw.diffArea.diffView.gutter, "revert lines")
    acceptQMessageBox(rw, "do you want to revert the selected lines")
    assert readTextFile(f"{wd}/master.txt") == expectedResult


@pytest.mark.parametrize("sampleText", [
    # Sample text is Python comments to ensure that syntax highlighting
    # applies to the entire line.

    # Complex CJK glyph encoded as two UTF-16 surrogates.
    # The glyph must be kept whole!
    ("#Hello W\U00030EDErld",
     "#Hello W\U00030EDDrld"),

    # Blue heart emoji
    ("#Hello World",
     "#Hello W\U0001F499rld"),

    # Simple emoji --> complex emoji (single glyph made of many codepoints)
    ("#Hello W\U0001f504rld",
     "#Hello W\U0001f486\U0001f3fd\u200d\u2642\ufe0frld"),

    # Skin tone modifier diff. Ideally, this shouldn't be broken into 3 glyphs,
    # but it's acceptable as long as no U+FFFD placeholders appear.
    ("#Hello W\U0001f486\U0001f3fd\u200d\u2642\ufe0frld",
     "#Hello W\U0001f486\U0001f3ff\u200d\u2642\ufe0frld"),
])
def testCharacterLevelDiffInUnicodeSurrogatePairs(tempDir, mainWindow, sampleText):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        writeFile(f"{wd}/surrogatepairs.py", f"{sampleText[0]}\n# bogus context\n")
        repo.index.add_all()
        repo.create_commit_on_head("TEST SURROGATE PAIRS", TEST_SIGNATURE, TEST_SIGNATURE)
        writeFile(f"{wd}/surrogatepairs.py", f"{sampleText[1]}\n# bogus context\n")

    rw = mainWindow.openRepo(wd)
    document: QTextDocument = rw.diffView.document()

    # Let syntax highlighting settle
    QTest.qWait(0)
    assert all(job.lexingComplete for job in rw.diffView.highlighter.lexJobs)

    def reconstructLine(lineNumber: int):
        block = document.findBlockByNumber(lineNumber)
        text16 = document.toRawText().encode('utf_16_le')
        slices = []
        fragment: QTextFragment
        for fragment in block.fragments():  # this iterator is a qt.py extension
            start16 = 2 * fragment.position()  # fragment pos is relative to entire text
            end16 = 2 * (fragment.position() + fragment.length())
            slice16 = text16[start16: end16]
            slices.append(slice16.decode('utf_16_le', 'replace'))
        return "".join(slices)

    assert "\uFFFD" not in reconstructLine(1), "placeholder char - incorrect split?"
    assert "\uFFFD" not in reconstructLine(2), "placeholder char - incorrect split?"
    assert reconstructLine(1) == sampleText[0]
    assert reconstructLine(2) == sampleText[1]
