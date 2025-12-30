# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import shutil
import textwrap
import pytest

from collections.abc import Generator
from typing import Literal

from gitfourchette.graphview.commitlogmodel import CommitLogModel
from .util import *

from gitfourchette.blameview.blamewindow import BlameWindow
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.repowidget import RepoWidget
from gitfourchette.syntax import syntaxHighlightingAvailable


class BlameFixture:
    path = "hello.txt"

    revs = {
        "workdir": NULL_OID,  # Workdir changes
        "head": Oid(hex="2be5719152d4f82c7302b1c0932d8e5f0a4a0e98"),  # HEAD
        "french": Oid(hex="4ec4389a8068641da2d6578db0419484972284c8"),  # Say hello in French
        "spanish": Oid(hex="6aaa262e655dd54252e5813c8e5acd7780ed097d"),  # Say hello in Spanish
        "initial": Oid(hex="acecd5ea2924a4b900e7e149496e1f4b57976e51"),  # Initial commit
    }

    unrelatedOid = Oid(hex="5470a671a80ac3789f1a6a8cefbcf43ce7af0563")

    history = [
        revs["workdir"],
        revs["head"],
        revs["french"],
        revs["spanish"],
        revs["initial"],
    ]


@pytest.fixture
def blameWindow(tempDir, mainWindow) -> Generator[BlameWindow, None, None]:
    wd = unpackRepo(tempDir, "testrepoformerging")

    # Edit file so we have some uncommitted changes
    headContents = readFile(f"{wd}/{BlameFixture.path}").decode("utf-8")
    newContents = "ciao mondo\n" + headContents
    writeFile(f"{wd}/{BlameFixture.path}", newContents)

    rw = mainWindow.openRepo(wd)

    # Start at Spanish commit
    seedLoc = NavLocator.inCommit(BlameFixture.revs["spanish"], BlameFixture.path)
    rw.jump(seedLoc, check=True)

    # Open blame window
    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    blameWindow = findWindow("blame")
    assert isinstance(blameWindow, BlameWindow)

    assert "Say hello in Spanish" in blameWindow.scrubber.currentText()

    blameWindow._unitTestMainWindow = mainWindow
    blameWindow._unitTestRepoWidget = rw
    yield blameWindow

    blameWindow.close()
    if QT5:  # Qt 5 needs a breather here to actually close window
        QTest.qWait(0)


def testOpenBlameCorrectTrace(blameWindow):
    blameModel = blameWindow.model
    assert blameModel

    # Look at trace
    assert len(blameModel.trace) == len(BlameFixture.history)
    for oid in BlameFixture.history:
        assert blameModel.trace.nodeForCommit(oid)
    with pytest.raises(KeyError):
        blameModel.trace.nodeForCommit(BlameFixture.unrelatedOid)


def testOpenBlameFromFileListContextMenu(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    rw = mainWindow.openRepo(wd)

    seedLoc = NavLocator.inCommit(BlameFixture.revs["spanish"], BlameFixture.path)
    rw.jump(seedLoc, check=True)

    triggerContextMenuAction(rw.committedFiles.viewport(), "blame")

    blameWindow = findWindow("blame")
    assert isinstance(blameWindow, BlameWindow)
    blameWindow.close()
    if QT5:  # Qt 5 needs a breather here to actually close window
        QTest.qWait(0)


def testOpenBlameJumpAround(blameWindow):
    blameModel = blameWindow.model
    assert blameModel
    assert blameWindow.scrubber.model().blameModel

    assert NavLocator.inCommit(BlameFixture.revs["spanish"], BlameFixture.path).isSimilarEnoughTo(blameModel.currentLocator)

    # Jump to French commit (4ec4)
    gotoOid = BlameFixture.revs["french"]
    gotoNode = blameModel.trace.nodeForCommit(gotoOid)
    assert BlameFixture.history.index(gotoOid) == blameWindow.scrubber.findData(gotoNode, CommitLogModel.Role.TraceNode)
    qcbSetIndex(blameWindow.scrubber, "say hello in french")
    assert NavLocator.inCommit(gotoOid, BlameFixture.path).isSimilarEnoughTo(blameModel.currentLocator)
    assert blameWindow.textEdit.toPlainText().strip() == "hello world\nhola mundo\nbonjour le monde"

    # Jump to uncommitted changes
    gotoOid = BlameFixture.revs["workdir"]
    gotoNode = blameModel.trace.nodeForCommit(gotoOid)
    assert BlameFixture.history.index(gotoOid) == blameWindow.scrubber.findData(gotoNode, CommitLogModel.Role.TraceNode)
    qcbSetIndex(blameWindow.scrubber, "uncommitted")
    assert NavLocator(context=NavContext.WORKDIR, path=BlameFixture.path).isSimilarEnoughTo(blameModel.currentLocator)
    assert blameWindow.textEdit.toPlainText().strip() == "ciao mondo\nhello world\nhola mundo\nbonjour le monde"


@pytest.mark.parametrize("method", ["button", "click"])
def testOpenBlameNavigateBackForward(blameWindow, method):
    scrubber = blameWindow.scrubber
    backButton = blameWindow.backButton
    forwardButton = blameWindow.forwardButton

    blameWindow.textEdit.setFocus()
    waitUntilTrue(blameWindow.textEdit.hasFocus)

    def go(backOrForward: Literal["back", "forward"]):
        back = backOrForward == "back"
        if method == "button":
            (backButton if back else forwardButton).click()
        elif method == "click":
            QTest.mouseClick(blameWindow.textEdit, Qt.MouseButton.BackButton if back else Qt.MouseButton.ForwardButton)
        else:
            raise NotImplementedError("unknown method")

    # Prime history with some items
    qcbSetIndex(scrubber, "Say hello in French")
    qcbSetIndex(scrubber, "Uncommitted")

    # Uncommitted --> back --> French
    assert (True, False) == (backButton.isEnabled(), forwardButton.isEnabled())
    go("back")
    assert "Say hello in French" in scrubber.currentText()

    # French --> back --> Spanish
    assert (True, True) == (backButton.isEnabled(), forwardButton.isEnabled())
    go("back")
    assert "Say hello in Spanish" in scrubber.currentText()

    # Spanish --> can't go further back
    go("back")
    assert "Say hello in Spanish" in scrubber.currentText()

    # Spanish --> forward --> French
    assert (False, True) == (backButton.isEnabled(), forwardButton.isEnabled())
    go("forward")
    assert "Say hello in French" in scrubber.currentText()


def testOpenBlameNavigateUpDown(blameWindow):
    scrubber = blameWindow.scrubber
    olderButton = blameWindow.olderButton
    newerButton = blameWindow.newerButton

    # Spanish --> older --> Initial commit
    assert (True, True) == (olderButton.isEnabled(), newerButton.isEnabled())
    olderButton.click()
    assert "First commit" in scrubber.currentText()

    # Initial commit --> click newer button until Uncommitted Changes
    assert (False, True) == (olderButton.isEnabled(), newerButton.isEnabled())
    for _i in range(len(BlameFixture.history)-1):
        assert newerButton.isEnabled()
        newerButton.click()
    assert (True, False) == (olderButton.isEnabled(), newerButton.isEnabled())
    assert "uncommitted" in scrubber.currentText().lower()

    # Uncommitted Changes --> Shift+Click --> Initial commit
    QTest.mouseClick(olderButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    assert (False, True) == (olderButton.isEnabled(), newerButton.isEnabled())
    assert "First commit" in scrubber.currentText()

    # Initial commit --> Shift+Click --> Uncommitted Changes
    QTest.mouseClick(newerButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    assert (True, False) == (olderButton.isEnabled(), newerButton.isEnabled())
    assert "Uncommitted" in scrubber.currentText()

    # Weird issue with PyQt6 6.9.1? The shift-clicking in this test may cause
    # later tests to fail unless we perform a no-modifier click now.
    QTest.mouseClick(newerButton, Qt.MouseButton.LeftButton)


def testBlameJumpToCommit(blameWindow):
    rw = blameWindow._unitTestRepoWidget
    assert rw.navLocator.commit == BlameFixture.revs["spanish"]

    # Create some extra files in the workdir to ensure that jumping to the workdir
    # also selects hello.txt (not just any random file in the workdir)
    writeFile(rw.repo.in_workdir("aaa_before_hello.txt"), "hello")
    writeFile(rw.repo.in_workdir("zzz_after_hello.txt"), "hello")

    qcbSetIndex(blameWindow.scrubber, "say hello in french")
    blameWindow.jumpButton.click()
    assert NavLocator.inCommit(BlameFixture.revs["french"], "hello.txt").isSimilarEnoughTo(rw.navLocator)

    qcbSetIndex(blameWindow.scrubber, "working directory")
    blameWindow.jumpButton.click()
    assert NavLocator.inUnstaged("hello.txt").isSimilarEnoughTo(rw.navLocator)


def testBlameBinaryBlob(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    shutil.copyfile(getTestDataPath("image1.png"), f"{wd}/hello.txt")
    mainWindow.openRepo(wd)
    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    QTest.qWait(0)
    blameWindow: BlameWindow = findWindow("blame")
    qcbSetIndex(blameWindow.scrubber, "working directory")
    text = blameWindow.textEdit.toPlainText().lower()
    assert "binary blob" in text
    assert "79 bytes" in text
    blameWindow.close()


def testBlameStartTraceOnDeletion(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "TestGitRepository")
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b"), "c/c2-2.txt"), check=True)

    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    blameWindow: BlameWindow = findWindow("blame")

    text = blameWindow.textEdit.toPlainText().lower()
    assert "file deleted in commit c9ed7bf" in text

    # Traverse to bottom of history
    for _i in range(3):
        blameWindow.olderButton.click()
    assert blameWindow.model.currentTraceNode.commitId == Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4")

    blameWindow.close()


def testBlameContextMenu(blameWindow):
    scrubber = blameWindow.scrubber
    viewport = blameWindow.textEdit.viewport()
    rw: RepoWidget = blameWindow._unitTestRepoWidget

    triggerContextMenuAction(viewport, "blame file at.+acecd5e")
    assert "First commit" in scrubber.currentText()

    triggerContextMenuAction(viewport, "show.+acecd5e.+in repo")
    assert NavLocator.inCommit(BlameFixture.revs["initial"], "hello.txt").isSimilarEnoughTo(rw.navLocator)

    triggerContextMenuAction(viewport, "commit info")
    acceptQMessageBox(blameWindow, r"first commit.+acecd5e.+j\. david")

    qcbSetIndex(scrubber, "uncommitted")
    triggerContextMenuAction(viewport, "show diff in working directory")
    assert NavLocator.inUnstaged("hello.txt").isSimilarEnoughTo(rw.navLocator)


def testBlameGutterToolTips(blameWindow):
    # Jump to uncommitted changes
    qcbSetIndex(blameWindow.scrubber, "uncommitted")

    blameWindow.textEdit.setFocus()
    waitUntilTrue(blameWindow.textEdit.hasFocus)

    toolTipFragments = [
        ["not committed yet", "hello.txt"],
        ["acecd5e", "j. david", "2011-02-08", "hello.txt", "first commit"],
        ["6aaa262", "j. david", "2011-02-14", "hello.txt", "say hello in spanish"],
        ["4ec4389", "j. david", "2011-02-14", "hello.txt", "say hello in french"],
    ]

    for i, fragments in enumerate(toolTipFragments):
        linePos = qteBlockPoint(blameWindow.textEdit, i)
        text = summonToolTip(blameWindow.textEdit.gutter, linePos)
        assert all(frag in text.lower() for frag in fragments)

    # Ensure no tooltip beyond last line
    beyondLastLine = linePos + QPoint(0, 50)
    with pytest.raises(TimeoutError):
        summonToolTip(blameWindow.textEdit.gutter, beyondLastLine)


def testBlameNewFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(f"{wd}/SomeNewFile.txt", "hello")
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("SomeNewFile.txt"), check=True)
    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    acceptQMessageBox(mainWindow, "no history")

    rw.diffArea.stageButton.click()
    rw.jump(NavLocator.inStaged("SomeNewFile.txt"), check=True)
    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    acceptQMessageBox(mainWindow, "no history")


def testBlameUnborn(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "TestEmptyRepository")

    writeFile(f"{wd}/SomeNewFile.txt", "hello")
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("SomeNewFile.txt"), check=True)

    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    acceptQMessageBox(mainWindow, "no commits in this repository")


@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
def testBlameSyntaxHighlighting(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Using YAML to also exercise the code path that calls ColorScheme.fillInFallback
    # in codehighlighter.py. See testSyntaxHighlightingFillInFallbackTokenTypes for details
    # (that other test exercises the equivalent code path in diffhighlighter.py).
    text1 = "# initial commit"
    text2 = textwrap.dedent("""\
        hello: world
        stuff:
          - name: "goodbye"
          - scalar: 1234
        """)
    oids = []

    with RepoContext(wd) as repo:
        for i, revision in enumerate([text1, text2], start=1):
            writeFile(f"{wd}/SomeNewFile.yml", revision)
            repo.index.add_all()
            oid = repo.create_commit_on_head(f"syntaxtest{i}", TEST_SIGNATURE, TEST_SIGNATURE)
            oids.append(oid)

    # Open blame window on the commit that produced text1
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oids[0], "SomeNewFile.yml"), check=True)
    triggerMenuAction(mainWindow.menuBar(), "view/blame")
    blameWindow: BlameWindow = findWindow("blame")
    assert "syntaxtest1" in blameWindow.scrubber.currentText()

    # Look at the color of the first character
    color1 = qteSyntaxColor(blameWindow.textEdit, 0)
    assert color1 != QColor(Qt.GlobalColor.black)

    # Jump to another commit from BlameWindow.
    # This will force BlameWindow to create a new LexJob instead of recycling
    # the existing one from RepoWidget's DiffView (for code coverage).
    qcbSetIndex(blameWindow.scrubber, "syntaxtest2")
    color2 = qteSyntaxColor(blameWindow.textEdit, 0)
    assert color2 != QColor(Qt.GlobalColor.black)
    assert color2 != color1  # different token types should be different colors

    blameWindow.close()


def testBlameTransposeScrollPositionsAcrossRevisions(tempDir, mainWindow):
    numPaddingLines = 250
    padding = "/* " + "\n".join(f"padding {i}" for i in range(1, numPaddingLines + 1)) + " */\n"
    fileHistory = [
        f"{padding}int foo=1;\nint bar=2;\nint baz=3;\n{padding}",
        f"{padding}int foo=1;\nint bar=2;\nint baz=3000;\n{padding}",
        f"{padding}int gotcha=0;\nint foo=1;\nint bar=2;\nint baz=3000;\n{padding}",
        f"{padding}int gotcha=0;\nint bar=2;\nint baz=3000;\n{padding}",
    ]

    wd = unpackRepo(tempDir)
    oids = []
    with RepoContext(wd) as repo:
        for i, snapshot in enumerate(fileHistory):
            writeFile(f"{wd}/hello.c", snapshot)
            repo.index.add_all()
            oid = repo.create_commit_on_head(f"revision {i}", TEST_SIGNATURE, TEST_SIGNATURE)
            oids.append(oid)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oids[0], "hello.c"), check=True)
    triggerMenuAction(mainWindow.menuBar(), "view/blame")

    blameWindow: BlameWindow = findWindow("blame")
    vsb = blameWindow.textEdit.verticalScrollBar()
    assert vsb.isVisible()
    vsb.setValue(numPaddingLines)
    assert blameWindow.textEdit.firstVisibleBlock().text() == "int foo=1;"

    # Go up 1 revision - Line numbers identical. Exact 'foo' line should be found.
    blameWindow.newerButton.click()
    assert blameWindow.textEdit.firstVisibleBlock().text() == "int foo=1;"

    # Go up 1 revision - One new line was added above 'foo' line. Exact 'foo' line should still be found.
    blameWindow.newerButton.click()
    assert blameWindow.textEdit.firstVisibleBlock().text() == "int foo=1;"

    # Go up 1 revision - 'foo' line was deleted, so rely on raw line numbers.
    blameWindow.newerButton.click()
    assert blameWindow.textEdit.firstVisibleBlock().text() == "int bar=2;"
