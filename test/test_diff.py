# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.diffview.diffview import DiffView
from gitfourchette.nav import NavLocator
from .util import *


def testEmptyDiffEmptyFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    touchFile(F"{wd}/NewEmptyFile.txt")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)

    assert not rw.diffView.isVisibleTo(rw)
    assert rw.specialDiffView.isVisibleTo(rw)
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
@pytest.mark.parametrize("method", ["key", "button"])
def testDiffViewStageLines(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/NewFile.txt", "line A\nline B\nline C\nline D\nline E")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    assert rw.repo.status() == {"NewFile.txt": FileStatus.WT_NEW}

    rw.diffView.setFocus()

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

    rw.jump(NavLocator.inUnstaged("aaaaa.txt"))
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
    rw.diffView.selectAll()
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)
    assert rw.repo.status() == {"master.txt": FileStatus.INDEX_MODIFIED}

    # It must also work in reverse - let's unstage this change via a subpatch
    qlvClickNthRow(rw.stagedFiles, 0)
    rw.diffView.setFocus()
    rw.diffView.selectAll()
    QTest.keyPress(rw.diffView, Qt.Key.Key_Delete)
    assert rw.repo.status() == {"master.txt": FileStatus.WT_MODIFIED}

    # Finally, let's discard this change via a subpatch
    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.setFocus()
    rw.diffView.selectAll()
    QTest.keyPress(rw.diffView, Qt.Key.Key_Delete)
    acceptQMessageBox(rw, "discard")
    assert rw.repo.status() == {}


def testDiffInNewWindow(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert mainWindow in QApplication.topLevelWidgets()

    oid = Oid(hex='1203b03dc816ccbb67773f28b3c19318654b0bc8')
    rw.jump(NavLocator.inCommit(oid))
    qlvClickNthRow(rw.committedFiles, 0)
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inCommit(oid, "c/c2.txt"))

    rw.committedFiles.openDiffInNewWindow.emit(rw.diffView.currentPatch, rw.navLocator)

    diffWindow = next(w for w in QApplication.topLevelWidgets() if w.objectName() == DiffView.DetachedWindowObjectName)
    diffWidget: DiffView = diffWindow.findChild(DiffView)
    assert diffWidget.window() is not mainWindow
    assert "c2.txt" in diffWindow.windowTitle()

    # Initiate search
    QTest.qWait(1)
    QTest.keySequence(diffWidget, "Ctrl+F")
    assert diffWidget.searchBar.isVisibleTo(diffWidget.window())

    # Make sure the diff is closed when the repowidget is gone
    mainWindow.closeAllTabs()
    QTest.qWait(0)  # doesn't get a chance to clean up windows without this...
    assert 1 == len(QGuiApplication.topLevelWindows())


def testSearchInDiff(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex='0966a434eb1a025db6b71485ab63a3bfbea520b6')
    rw.jump(NavLocator.inCommit(oid, path="master.txt"))

    diffView = rw.diffView
    searchBar = rw.diffView.searchBar
    searchLine = rw.diffView.searchBar.lineEdit
    searchNext = searchBar.ui.forwardButton
    searchPrev = searchBar.ui.backwardButton

    assert not searchBar.isVisibleTo(rw)
    diffView.setFocus()
    # Give it two event loop iterations to react...
    QTest.qWait(1)
    QTest.qWait(1)
    QTest.keySequence(diffView, "Ctrl+F")  # window to be shown for this to work!
    assert searchBar.isVisibleTo(rw)

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
    assert searchBar.isVisibleTo(rw)
    searchBar.lineEdit.setFocus()
    if QT5:  # Qt5 is somehow finicky here (else-branch works perfectly in Qt6) - not important enough to troubleshoot - Qt5 is on the way out
        searchBar.lineEdit.setText("MadeUpGarbage")
        searchBar.ui.forwardButton.click()
    else:
        assert searchBar.lineEdit.hasSelectedText()  # hitting ctrl+f should reselect text
        QTest.keyClicks(searchLine, "MadeUpGarbage")
        assert searchBar.lineEdit.text() == "MadeUpGarbage"
        QTest.keyPress(searchLine, Qt.Key.Key_Return)
    # Reject last message box to prevent wrapping again
    rejectQMessageBox(rw, "no.+occurrence.+of.+MadeUpGarbage.+found")


def testCopyFromDiffWithoutU2029(tempDir, mainWindow):
    """
    WARNING: THIS TEST MODIFIES THE SYSTEM'S CLIPBOARD.
    (No worries if you're running the tests offscreen.)

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
    rw.jump(NavLocator.inCommit(oid, path="master.txt"))

    # Make sure the clipboard is clean before we begin
    clipboard = QApplication.clipboard()
    clipboard.clear()
    assert not clipboard.text()

    diffView = rw.diffView
    diffView.setFocus()
    diffView.selectAll()
    diffView.copy()
    QTest.qWait(1)

    clipped = clipboard.text()
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

    rw.jump(NavLocator.inUnstaged(path="crlf.txt"))
    assert rw.diffView.isVisibleTo(rw)
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
    rw.jump(NavLocator.inUnstaged(path="cr.txt"))
    assert rw.diffView.isVisibleTo(rw)
    assert rw.diffView.toPlainText().lower() == (
        "@@ -0,0 +1 @@\n"
        "ancient mac file<cr>"
    )


def testDiffBinaryWarning(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with open(f"{wd}/binary.whatever", "wb") as f:
        f.write(b"\x00\x00\x00\x00")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="binary.whatever"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert "binary" in rw.specialDiffView.toPlainText().lower()


def testDiffVeryLongLines(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    contents = " ".join(f"foo{i}" for i in range(5000)) + "\n"
    writeFile(f"{wd}/longlines.txt", contents)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="longlines.txt"))
    assert not rw.diffView.isVisibleTo(rw)
    assert rw.specialDiffView.isVisibleTo(rw)
    assert "long lines" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.diffView.isVisibleTo(rw)
    assert rw.diffView.toPlainText().rstrip() == "@@ -0,0 +1 @@\n" + contents.rstrip()


def testDiffLargeFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # About one megabyte
    contents = "\n".join(f"{i:08x}." for i in range(100_000)) + "\n"
    writeFile(f"{wd}/bigfile.txt", contents)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(path="bigfile.txt"))
    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert "too large to be previewed" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().rstrip() == "@@ -0,0 +1,100000 @@\n" + contents.rstrip()


def testDiffImage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shutil.copyfile(getTestDataPath("image1.png"), f"{wd}/image.png")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("image.png"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert re.search("6.6 pixels", rw.specialDiffView.toPlainText())
    rw.diffArea.dirtyFiles.stage()
    rw.diffArea.commitButton.click()
    findQDialog(rw, "commit").ui.summaryEditor.setText("commit an image")
    findQDialog(rw, "commit").accept()

    shutil.copyfile(getTestDataPath("image2.png"), f"{wd}/image.png")
    rw.refreshRepo()
    rw.jump(NavLocator.inUnstaged("image.png"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert re.search("6.6 pixels", rw.specialDiffView.toPlainText())
    assert re.search("4.4 pixels", rw.specialDiffView.toPlainText())

    os.unlink(f"{wd}/image.png")
    rw.refreshRepo()
    rw.jump(NavLocator.inUnstaged("image.png"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert re.search("6.6 pixels", rw.specialDiffView.toPlainText())


def testDiffLargeImage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shutil.copyfile(getTestDataPath("image1.png"), f"{wd}/image.png")
    with open(f"{wd}/image.png", "ab") as binfile:
        binfile.write(b"\x00" * 6_000_000)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("image.png"))
    assert rw.specialDiffView.isVisible()
    assert "too large to be previewed" in rw.specialDiffView.toPlainText().lower()

    qteClickLink(rw.specialDiffView, "load.+anyway")
    assert rw.specialDiffView.isVisible()
    assert "too large" not in rw.specialDiffView.toPlainText().lower()


def testDiffViewSelectionStableAfterRefresh(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "please don't nuke my selection\n")

    rw = mainWindow.openRepo(wd)
    diffView = rw.diffView

    rw.jump(NavLocator.inUnstaged("master.txt"))
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
    QTest.qWait(0)
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
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"))

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

    rw.jump(NavLocator.inUnstaged("manylines.txt"))
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

    rw.jump(NavLocator.inUnstaged("hello.txt"))

    line1 = qteBlockPoint(dv, 1)  # Hello1
    line2 = qteBlockPoint(dv, 2)  # (blank)
    # line3 = qteBlockPoint(dv, 3)  # Hello2
    line4 = qteBlockPoint(dv, 4)  # (blank)

    # Stage "Hello1\n\n"
    QTest.mouseClick(dv.gutter, LMB, pos=line1)
    QTest.mouseClick(dv.gutter, LMB, Qt.KeyboardModifier.ShiftModifier, pos=line2)
    QTest.keyPress(dv, Qt.Key.Key_Enter)
    assert b"Hello1\n\n" == rw.repo.peel_blob(rw.repo.index["hello.txt"].id).data

    # Stage blank line before Hello2
    QTest.mouseClick(dv.gutter, LMB, pos=line4)
    QTest.keyPress(dv, Qt.Key.Key_Enter)
    assert b"Hello1\n\n\n" == rw.repo.peel_blob(rw.repo.index["hello.txt"].id).data


def testDiffViewMouseWheelZoom(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/manylines.txt", "\n".join(f"line {i}" for i in range(1, 1001)))
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    initialFont = dv.font()

    postMouseWheelEvent(dv.gutter, 120, modifiers=Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(1)
    assert dv.font().pointSize() > initialFont.pointSize()

    postMouseWheelEvent(dv.gutter, -120, modifiers=Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(1)
    assert dv.font().pointSize() == initialFont.pointSize()

    postMouseWheelEvent(dv.gutter, -120, modifiers=Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(1)
    assert dv.font().pointSize() < initialFont.pointSize()


def testToggleWordWrap(tempDir, mainWindow):
    text = ("pen pineapple apple pen " * 250) + "\n"
    text *= 12

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/longline.txt", text)
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView
    assert NavLocator.inUnstaged("longline.txt").isSimilarEnoughTo(rw.navLocator)
    assert dv.horizontalScrollBar().isVisible()

    menu = dv.contextMenu(QPoint(0, 0))
    triggerMenuAction(menu, "word wrap")
    QTest.qWait(0)
    assert not dv.horizontalScrollBar().isVisible()


def testExportPatchFromHunk(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"))

    menu = dv.contextMenu(dv.viewport().mapToGlobal(qteBlockPoint(dv, 0)))
    triggerMenuAction(menu, "export hunk.+as patch")
    exportedPath = acceptQFileDialog(rw, "export", f"{tempDir.name}", useSuggestedName=True)
    assert exportedPath.endswith("c1.txt[partial].patch")
    assert readFile(exportedPath).decode("utf-8").endswith(
        "--- a/c/c1.txt\n"
        "+++ b/c/c1.txt\n"
        "@@ -1,1 +1,2 @@\n"
        " c1\n"
        "+c1\n")


def testRevertHunk(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dv = rw.diffView

    assert readFile(f"{wd}/c/c1.txt") == b"c1\nc1\n"

    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"))

    cr = dv.cursorRect(dv.textCursor())
    menu = dv.contextMenu(dv.mapToGlobal(QPoint(cr.x(), cr.y())))
    triggerMenuAction(menu, "revert hunk")

    assert NavLocator.inUnstaged("c/c1.txt").isSimilarEnoughTo(rw.navLocator)
    assert readFile(f"{wd}/c/c1.txt") == b"c1\n"
