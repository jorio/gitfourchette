# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import textwrap

from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.rebasedialog import RebaseDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.nav import NavLocator
from gitfourchette.rebase.rebasemodel import RebaseOp, RebaseOpLetters
from gitfourchette.rebase.rebasesequencedropindicator import RebaseSequenceDropIndicator
from gitfourchette.rebase.rebasesequencemodel import RebaseSequenceModel
from gitfourchette.rebase.rebasesequenceview import RebaseSequenceView
from gitfourchette.toolbox import QRichTextMenu, QModelIndex_default
from .util import *
from . import reposcenario


@dataclasses.dataclass
class _Todo:
    row: int
    op: RebaseOp
    message: str | None = None


def _driveRebaseDialog(rw, onto: Oid, todoList: list[_Todo]):
    rw.jump(NavLocator.inCommit(onto, ""))

    # Bring up RebaseDialog
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    rebaseDialog = waitForQDialog(rw, "rebase|rebasing", t=RebaseDialog)
    sequenceView = rebaseDialog.ui.sequence

    assert sequenceView.sequenceModel.sequence[0].op == RebaseOp.FakeStart
    assert sequenceView.sequenceModel.sequence[0].oid == onto

    # Apply all operations
    for todo in todoList:
        # Select row
        bottomUpRow = sequenceView.model().rowCount() - 1 - todo.row
        bottomUpRow -= 1  # account for fake start row
        qlvClickNthRow(sequenceView, bottomUpRow)

        # In the unit testing environment, Jump may hand focus back to GraphView.
        # This doesn't occur in the real world (RebaseDialog still has focus).
        # Make sure RebaseDialog still has focus.
        rebaseDialog.activateWindow()
        waitUntilTrue(rebaseDialog.isActiveWindow)
        sequenceView.setFocus()
        waitUntilTrue(sequenceView.hasFocus)

        # Press keyboard shortcut for desired operation
        QTest.keyClicks(sequenceView.viewport(), RebaseOpLetters[todo.op])

        itemsSoFar = sequenceView.effectiveSequence()
        assert itemsSoFar[todo.row].op == todo.op

        # Apply reworded message, if any
        if todo.message is not None:
            assert todo.op.isEditable(), "need editable op to change message"

            # QLineEdit should have been brought up by hotkey
            lineEdit: QLineEdit = sequenceView.findChild(QLineEdit)
            assert lineEdit is not None
            assert lineEdit.isVisible()
            waitUntilTrue(lineEdit.hasFocus)

            # Fill it in
            lineEdit.setText(todo.message)
            assert lineEdit.text() == todo.message

            # Warning: in real life, Return commits the current text in the
            # QLineEdit, but in offscreen mode, this accepts the entire dialog.
            lineEdit.clearFocus()
            QTest.qWait(0)

            assert itemsSoFar[todo.row].payload.strip() == todo.message.strip()

        # Give delegate time to repaint (for coverage)
        QTest.qWait(0)

    return rebaseDialog


@pytest.mark.parametrize("withChanges", [False, True], ids=["no changes", "with changes"])
def testCancelRebaseDialog(tempDir, mainWindow, withChanges):
    wd = unpackRepo(tempDir)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1"), check=True)

    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [_Todo(0, RebaseOp.Edit)] if withChanges else []

    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    rebaseDialog.reject()

    if withChanges:
        assert rebaseDialog.isVisible()
        qmb = findQMessageBox(rebaseDialog, "really discard this rebase plan")
        findWidgetWithText(qmb.buttons(), "discard").click()

    assert rw.repo.state() == RepositoryState.NONE


def testAbortRebase(tempDir, mainWindow):
    head = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    edit = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    todo = [_Todo(0, RebaseOp.Edit)]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE
    assert rw.repo.head_commit_id == edit
    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "rebasing.+master.+onto.+" + str(onto)[:7])
    assert findTextInWidget(rw.mergeBanner.label, "stopped at.+" + str(edit)[:7])

    # Abort the rebase
    findWidgetWithText(rw.mergeBanner.buttons, "abort rebase").click()
    acceptQMessageBox(rw, "abort rebase")

    assert rw.repo.state() == RepositoryState.NONE
    assert not rw.mergeBanner.isVisible()
    assert rw.repo.head_commit_id == head


def testContinueRebase(tempDir, mainWindow):
    head = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    edit = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    todo = [_Todo(0, RebaseOp.Edit)]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE
    assert rw.repo.head_commit_id == edit
    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "rebasing.+master.+onto.+" + str(onto)[:7])
    assert findTextInWidget(rw.mergeBanner.label, "stopped at.+" + str(edit)[:7])

    # Make some changes to the commit we're stopped at
    triggerMenuAction(mainWindow.menuBar(), "repo/amend")
    commitDialog = findQDialog(rw, "amend", t=CommitDialog)
    commitDialog.ui.summaryEditor.setText("Amended from Rebase")
    commitDialog.accept()

    # Continue rebasing
    continueButton = rw.mergeBanner.findButton("continue rebase")
    assert continueButton.isEnabled()
    continueButton.click()

    assert rw.repo.state() == RepositoryState.NONE
    assert not rw.mergeBanner.isVisible()
    assert rw.repo.head_commit_id != head, "new head must be different after making changes"


def testRebaseReword(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Reword, "  rewording older commit  "),  # some extra whitespace
        _Todo(1, RebaseOp.Reword, "rewording newer commit: Café, привет, 你好, 🦊"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.head_commit.message.strip() == "rewording newer commit: Café, привет, 你好, 🦊"
    assert rw.repo.head_commit.parents[0].message.strip() == "rewording older commit"


def testRebaseRewordEditorFailureDoesntHang(tempDir, mainWindow, monkeypatch):
    # If filling in COMMIT_EDITMSG fails, git must get an answer and stop instead of waiting forever
    from gitfourchette.rebase import editmsgautofillserver

    class BrokenRebaseInfo:
        @staticmethod
        def parse(_path):
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(editmsgautofillserver, "RebaseInfo", BrokenRebaseInfo)

    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    _driveRebaseDialog(rw, onto, [_Todo(0, RebaseOp.Reword, "new message")]).accept()
    acceptQMessageBox(rw, "EditmsgAutoFillServer failed: RuntimeError: simulated failure")
    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE  # git stopped, the user can carry on


def testRebaseRewordDisplayMessage(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Reword, "hello rewording"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    dialog = _driveRebaseDialog(rw, onto, todo)

    def getSelectedMessage():
        return dialog.ui.sequence.selectedRebaseLines()[0].displayMessage()

    # Switching from 'reword' to 'pick' should revert the old name
    qlvClickNthRow(dialog.ui.sequence, 1)
    assert "hello rewording" == getSelectedMessage()
    QTest.keyClicks(dialog.ui.sequence.viewport(), RebaseOpLetters[RebaseOp.Pick])
    assert "Rename c/c2.txt => c/c2-2.txt" == getSelectedMessage()

    # Switching back to 'reword' should have saved the message that we entered originally
    QTest.keyClicks(dialog.ui.sequence.viewport(), RebaseOpLetters[RebaseOp.Reword])
    assert "hello rewording" == getSelectedMessage()

    dialog.accept()


def testRebaseRewordAfterContinue(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Edit),
        _Todo(1, RebaseOp.Reword, "rewording still works after continue"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE
    assert rw.mergeBanner.isVisible()
    continueButton = rw.mergeBanner.findButton("continue rebase")
    assert continueButton.isEnabled()
    continueButton.click()

    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.head_commit.message.strip() == "rewording still works after continue"


def testRebaseRewordNoop(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Pick),
        _Todo(1, RebaseOp.Reword, ""),  # Reword to empty message
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    rebaseDialog.accept()

    head = rw.repo.head_commit
    assert head.message.strip() == "Delete c/c2-2.txt"
    assert head.author.name == "A U Thor"
    assert head.committer.name == "Test Person"


def testRebaseCausesConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git rm master.txt
        git commit -am 'deleting master.txt'

        git branch hello2 49322bb17d3acc9146f98c97d078513228bbf3c0
        git checkout hello2

        echo 'bump' > c/c2.txt
        git commit -am 'modifying c/c2.txt'

        echo 'bump' > master.txt
        git commit -am 'modifying master.txt'
    """, wd)

    onto = Oid(hex="653b7d48ae91074764e7ae41449c8d0942e640a6")
    todo = []

    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE
    assert rw.mergeBanner.isVisible()

    # Rebase blocked by conflict
    for stoppedAt, conflictFile in [
        ("f044e03", "c/c2.txt"),   # first iteration: task InteractiveRebase gets stopped
        ("5aba9ee", "master.txt"),  # second iteration: task ContinueRebase gets stopped
    ]:
        assert findTextInWidget(rw.mergeBanner.label, "stopped at.+" + stoppedAt)
        assert findTextInWidget(rw.mergeBanner.label, "fix conflicts to continue")

        # Continue button should be grayed out
        continueButton = rw.mergeBanner.findButton("continue rebase")
        assert not continueButton.isEnabled()

        # Task should auto-jump to 1st conflict
        assert NavLocator.inUnstaged(conflictFile).isSimilarEnoughTo(rw.navLocator)

        # Resolve the conflict
        assert rw.conflictView.isVisible()
        assert rw.conflictView.ui.oursButton.isVisible()
        assert rw.conflictView.ui.theirsButton.isVisible()
        assert findTextInWidget(rw.conflictView.ui.oursButton, "keep our deletion")
        assert findTextInWidget(rw.conflictView.ui.theirsButton, "accept their version")
        rw.conflictView.ui.theirsButton.click()
        acceptQMessageBox(rw, "accept their")

        # Continue rebase
        continueButton = rw.mergeBanner.findButton("continue rebase")
        assert continueButton.isEnabled()
        continueButton.click()

    assert not rw.mergeBanner.isVisible()
    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.head_commit.message.startswith("modifying master.txt")
    assert rw.repo.head_commit.parents[0].message.startswith("modifying c/c2.txt")


def testRebaseNoopDud(tempDir, mainWindow):
    shell("""
        git init repo -b master
        cd repo
        git commit --allow-empty -m 'root commit'
    """, tempDir.name)

    wd = f"{tempDir.name}/repo"
    onto = readOidFile(f"{wd}/.git/refs/heads/master")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(onto, ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    acceptQMessageBox(rw, "no rebase is necessary")
    assert rw.repo.branches.local["master"].target == onto


def testRebaseNoopReset(tempDir, mainWindow):
    shell("""
        git init -b master repo
        cd repo
        touch hello.txt
        git add hello.txt
        git commit -m 'root commit'
        echo 'hello' > hello.txt
        git commit -am 'add some text'
        git branch rebase-onto-here
        git commit --amend -m 'add exact same text with a different commit message'
    """, tempDir.name)

    wd = f"{tempDir.name}/repo"
    onto = readOidFile(f"{wd}/.git/refs/heads/rebase-onto-here")
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(onto, "hello.txt"), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    acceptQMessageBox(rw, "all commits from.+master.+are already in the other branch")
    visualPause()
    assert rw.repo.branches.local["master"].target == onto


def testRebasePlanOutOfSync(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = []

    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)

    shell("git checkout ce112d0", wd)
    rw.refreshRepo()

    rebaseDialog.accept()
    rejectQMessageBox(rw, "cannot apply this rebase plan")


def testRebaseVerifyEmptyCommitsInTodo(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git commit --allow-empty -m 'some dummy commit'

        echo 'yoink' > master.txt
        git commit -am 'gotcha # empty'
    """, wd)

    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = []

    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    seq = rebaseDialog.initialSequence

    assert seq[-2].originalComment == "some dummy commit # empty"
    assert seq[-2].displayMessage() == "some dummy commit"
    assert seq[-2].verifiedEmpty

    assert seq[-1].originalComment == "gotcha # empty"
    assert seq[-1].displayMessage() == "gotcha # empty"
    assert not seq[-1].verifiedEmpty

    rebaseDialog.reject()


def testRebaseBannerCantContinueWithUnstagedChanges(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [_Todo(0, RebaseOp.Edit)]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    banner = rw.mergeBanner
    _driveRebaseDialog(rw, onto, todo).accept()

    assert findTextInWidget(banner.label, "you can continue")
    assert banner.isVisible()
    assert banner.property("heeded") == "true"
    assert banner.findButton("continue rebase").isEnabled()

    writeFile(f"{wd}/master.txt", "hello")
    rw.refreshRepo()
    assert findTextInWidget(banner.label, "stage.+your changes to continue")
    assert banner.property("heeded") != "true"
    assert not banner.findButton("continue rebase").isEnabled()

    rw.jump(NavLocator.inUnstaged("master.txt"), check=True)
    rw.diffArea.stageButton.click()
    assert findTextInWidget(banner.label, "you can continue")
    assert banner.property("heeded") == "true"
    assert banner.findButton("continue rebase").isEnabled()
    banner.findButton("continue rebase").click()


def testRebaseDanglingFixup(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [_Todo(0, RebaseOp.Fixup)]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)

    okButton: QPushButton = rebaseDialog.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
    assert not okButton.isEnabled()
    assert rebaseDialog.warningHint.isVisible()

    rebaseDialog.ui.sequence.setFocus()
    QTest.keySequence(rebaseDialog, QKeySequence.StandardKey.Undo)
    assert okButton.isEnabled()
    assert not rebaseDialog.warningHint.isVisible()

    rebaseDialog.accept()


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
def testRebaseSequenceDropIndicator(tempDir, mainWindow, monkeypatch):
    """
    Coverage test for RebaseSequenceDropIndicator's painting code.

    QDragEnterEvent/QDragMoveEvent/QDropEvent work with MIME data, but Qt won't
    preserve our custom data via MIME drag-and-drop. To avoid corrupting the
    list, we don't actually complete the drop in this coverage test
    (QDragLeaveEvent instead of QDropEvent).
    """

    callSpy = CallSpy(monkeypatch, RebaseSequenceDropIndicator, "paintEvent")

    wd = unpackRepo(tempDir)
    onto = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    rw = mainWindow.openRepo(wd)

    # Bring up RebaseDialog
    rw.jump(NavLocator.inCommit(onto, ""))
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    rebaseDialog = waitForQDialog(rw, "rebase|rebasing", t=RebaseDialog)

    view: RebaseSequenceView = rebaseDialog.ui.sequence
    LMB = Qt.MouseButton.LeftButton
    MOD = Qt.KeyboardModifier.NoModifier
    ps = QPointF(qlvVisualRect(view, 4).center())
    pd = QPointF(qlvVisualRect(view, 0).center())

    qlvClickNthRow(view, 4)
    mime = view.model().mimeData(view.selectedIndexes())

    events = [
        QDragEnterEvent(ps, Qt.DropAction.MoveAction, mime, LMB, MOD),
        QDragMoveEvent(pd, Qt.DropAction.MoveAction, mime, LMB, MOD),
        QDragLeaveEvent(),  # leave instead of drop to avoid corrupting the list (see docstring)
    ]
    for e in events:
        QApplication.sendEvent(view.viewport(), e)
        QTest.qWait(0)
        assert e.isAccepted()
        visualPause(.5)

    assert callSpy.completeCalls >= 1

    rebaseDialog.reject()


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
@pytest.mark.skipif(QT6 and QT_BINDING_VERSION_TUPLE < (6, 7), reason="TODO: Qt 6.6?")
def testRebaseSequenceViewQDrag(tempDir, mainWindow, monkeypatch):
    """
    Coverage test for the custom QDrag in RebaseSequenceView.
    NOTE: Flaky on Wayland in non-offscreen mode.
    """

    callSpyMakeQDrag = CallSpy(monkeypatch, RebaseSequenceView, "makeQDrag")
    callSpyStartDrag = CallSpy(monkeypatch, RebaseSequenceView, "startDrag")

    wd = unpackRepo(tempDir)
    onto = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    rw = mainWindow.openRepo(wd)

    # Bring up RebaseDialog
    rw.jump(NavLocator.inCommit(onto, ""))
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    rebaseDialog = waitForQDialog(rw, "rebase|rebasing", t=RebaseDialog)

    view = rebaseDialog.ui.sequence
    LMB = Qt.MouseButton.LeftButton
    ps = qlvVisualRect(view, 4).center()  # "On master again"

    # In offscreen mode, startDrag() returns immediately, so we can't actually
    # complete a move this way.
    allowActualMove = not OFFSCREEN
    if allowActualMove:
        pd = QPoint(ps.x(), 2)  # move to the top
    else:
        pd = ps + QPoint(100, 0)  # stay on same row

    clickTarget = view.viewport()

    QCursor.setPos(clickTarget.mapToGlobal(ps))
    QTest.mousePress(clickTarget, LMB, pos=ps)
    QCursor.setPos(clickTarget.mapToGlobal(pd))
    # In non-offscreen mode, startDrag() blocks the event loop, so schedule move
    # and release for later.
    QTimer.singleShot(0, lambda: QTest.mouseMove(clickTarget, pos=pd))
    QTimer.singleShot(500, lambda: QTest.mouseRelease(clickTarget, LMB, pos=pd))

    pause(1)
    assert callSpyMakeQDrag.completeCalls == 1
    assert callSpyStartDrag.completeCalls == 1

    rebaseDialog.reject()

    # If we did complete the move, RebaseDialog wants us to confirm closing a
    # modified rebase plan.
    if allowActualMove:
        assert rebaseDialog.ui.sequence.effectiveSequence()[0].displayMessage() == "On master again"
        qmb = findQMessageBox(rebaseDialog, "really discard this rebase plan")
        findWidgetWithText(qmb.buttons(), "discard").click()


def testRebaseRichTextMenu(tempDir, mainWindow, monkeypatch):
    """
    Coverage test for RebaseMenuStyle (colored labels).
    """

    callSpy = CallSpy(monkeypatch, QRichTextMenu, "paintEvent")

    wd = unpackRepo(tempDir)
    onto = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    rw = mainWindow.openRepo(wd)

    # Bring up RebaseDialog
    rw.jump(NavLocator.inCommit(onto, ""))
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    rebaseDialog = waitForQDialog(rw, "rebase|rebasing", t=RebaseDialog)

    rebaseDialog.ui.sequence.setFocus()
    qlvClickNthRow(rebaseDialog.ui.sequence, 1)
    menu = summonContextMenu(rebaseDialog.ui.sequence.viewport(), QPoint(8, 8))
    visualPause()
    menu.close()

    assert callSpy.completeCalls > 0

    rebaseDialog.close()


def testRebaseJumpToCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    onto = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")
    head = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    rw = mainWindow.openRepo(wd)

    # Bring up RebaseDialog
    rw.jump(NavLocator.inCommit(onto, ""))
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    rebaseDialog = waitForQDialog(rw, "rebase|rebasing", t=RebaseDialog)

    rebaseDialog.ui.sequence.setFocus()
    qlvClickNthRow(rebaseDialog.ui.sequence, 0)

    assert NavLocator.inCommit(head, "c/c2-2.txt").isSimilarEnoughTo(rw.navLocator)

    rebaseDialog.close()


def testRebaseCorruptInfo(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Edit),
        _Todo(1, RebaseOp.Reword, "rewording still works after continue"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.repo.state() == RepositoryState.REBASE_INTERACTIVE
    assert rw.mergeBanner.isVisible()
    continueButton = rw.mergeBanner.findButton("continue rebase")
    assert continueButton.isEnabled()

    writeFile(f"{wd}/.git/rebase-merge/git-rebase-todo", "yikes-this-will-not-parse")
    rw.refreshRepo()

    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "failed to collect information")


def testRebaseBannerCommitLinks(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Edit),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    assert rw.mergeBanner.isVisible()

    qlabelClickLink(rw.mergeBanner.label, id7(onto))
    assert NavLocator.inCommit(onto, "a/a1").isSimilarEnoughTo(rw.navLocator)

    stop = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    qlabelClickLink(rw.mergeBanner.label, id7(stop))
    assert NavLocator.inCommit(stop, "c/c2-2.txt").isSimilarEnoughTo(rw.navLocator)

    shell("rm master.txt", wd)
    rw.refreshRepo()
    qlabelClickLink(rw.mergeBanner.label, "Go to Working Directory")
    assert NavLocator.inUnstaged("master.txt").isSimilarEnoughTo(rw.navLocator)


def testRebaseDateOptions(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Pick),
        _Todo(1, RebaseOp.Reword, "reworded head commit"),
    ]

    wd = unpackRepo(tempDir)
    shell("git branch starting-point", wd)

    rw = mainWindow.openRepo(wd)
    currentSecs = QDateTime.currentSecsSinceEpoch()

    # Nothing

    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    menu = rebaseDialog.ui.optionsButton.menu()
    assert findMenuAction(menu, "separate author.committer dates").isChecked()  # default option pre-checked
    rebaseDialog.accept()

    head = rw.repo.head_commit
    assert head.author.name == "A U Thor"
    assert head.committer.name == "Test Person"
    assert head.committer.time != head.author.time
    assert QDateTime.fromSecsSinceEpoch(head.author.time).toString("yyyy-MM-dd") == "2022-01-16"
    assert head.committer.time - currentSecs <= 60

    # --committer-date-is-author-date

    shell("git reset --hard starting-point", wd)
    rw.refreshRepo()

    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    menu = rebaseDialog.ui.optionsButton.menu()
    assert findMenuAction(menu, "separate author.committer dates").isChecked()  # last option was saved
    findMenuAction(menu, "set committer date to author date").setChecked(True)  # check --committer-date-is-author-date
    rebaseDialog.accept()

    head = rw.repo.head_commit
    assert head.author.name == "A U Thor"
    assert head.committer.name == "Test Person"
    assert head.committer.time == head.author.time
    assert QDateTime.fromSecsSinceEpoch(head.committer.time).toString("yyyy-MM-dd") == "2022-01-16"

    # --reset-author-date

    shell("git reset --hard starting-point", wd)
    rw.refreshRepo()
    assert rw.repo.head_commit.message.strip() != "reworded head commit"

    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    menu = rebaseDialog.ui.optionsButton.menu()
    assert findMenuAction(menu, "set committer date").isChecked()  # last option was saved
    findMenuAction(menu, "set author date").setChecked(True)  # check --reset-author-date
    rebaseDialog.accept()

    head = rw.repo.head_commit
    assert head.message.strip() == "reworded head commit"
    assert head.author.name == "A U Thor"
    assert head.committer.name == "Test Person"

    # With --reset-author-date, Git resets the author date to the current
    # time as it replays the commit, then it reads the clock again as it
    # records the new commit (committer date). These 2 timestamps are
    # typically identical, but sometimes the commit may land a bit later.
    # Committer date should never precede author date, though.
    assert head.committer.time - head.author.time >= 0
    assert head.committer.time - head.author.time <= 3
    assert head.committer.time - currentSecs <= 60


def testRebaseUndoRedo(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Edit),
        _Todo(1, RebaseOp.Reword, "reworded head commit"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    rebaseDialog.ui.sequence.setFocus()

    for _dummy in range(3):
        QTest.keySequence(rebaseDialog, QKeySequence.StandardKey.Undo)

    assert rebaseDialog.serializeSequence().strip() == textwrap.dedent("""\
        pick ce112d052bcf42442aa8563f1e2b7a8aabbf4d17 # Rename c/c2.txt => c/c2-2.txt
        pick c9ed7bf12c73de26422b7c5a44d74cfce5a8993b # Delete c/c2-2.txt
    """).strip()

    for _dummy in range(3):
        QTest.keySequence(rebaseDialog, QKeySequence.StandardKey.Redo)

    assert rebaseDialog.serializeSequence().strip() == textwrap.dedent("""\
        edit ce112d052bcf42442aa8563f1e2b7a8aabbf4d17 # Rename c/c2.txt => c/c2-2.txt
        reword c9ed7bf12c73de26422b7c5a44d74cfce5a8993b #GITFOURCHETTE_REBASE_PAYLOAD=cmV3b3JkZWQgaGVhZCBjb21taXQ=
    """).strip()

    rebaseDialog.reject()
    qmb = findQMessageBox(rebaseDialog, "really discard this rebase plan")
    findWidgetWithText(qmb.buttons(), "discard").click()


def testRebaseSequenceDelegatePaintCoverage(tempDir, mainWindow):
    """ Coverage test for RebaseSequenceDelegate.paint """

    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(7, RebaseOp.Edit),
        _Todo(6, RebaseOp.Fixup),
        _Todo(4, RebaseOp.Fixup),
        _Todo(3, RebaseOp.Reword, "hello2"),
        _Todo(2, RebaseOp.Fixup),
        _Todo(1, RebaseOp.Drop),
        _Todo(0, RebaseOp.Edit),
    ]

    wd = unpackRepo(tempDir)

    # Insert junk commits that we'll rewrite
    shell("""
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
        git commit --allow-empty -mhello
    """, wd)

    # Grow window so all rebased commits show up in the graph
    mainWindow.resize(1600, 1600)

    # Do the rebase
    rw = mainWindow.openRepo(wd)
    _driveRebaseDialog(rw, onto, todo).accept()

    # First stop in rebase (let it paint pending fixups)
    QTest.qWait(0)  # let delegate repaint
    assert rw.mergeBanner.isVisible()
    findWidgetWithText(rw.mergeBanner.buttons, "continue rebase").click()

    # Second stop in rebase (let it paint 'done' commits)
    QTest.qWait(0)  # let delegate repaint

    # Conclude the rebase
    assert rw.mergeBanner.isVisible()
    findWidgetWithText(rw.mergeBanner.buttons, "continue rebase").click()
    assert not rw.mergeBanner.isVisible()


def testRebaseUndoRedoCommandCompression(tempDir, mainWindow):
    """ Dragging and dropping multiple rows should come out to a single undo
    command. """

    onto = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    s1 = ["c9ed7bf", "ce112d0", "d0114ab", "f73b956", "7f82283", "59706a1", "d31f5a6", "83d2f04", "1203b03", "bab66b4"]
    s2 = ["7f82283", "59706a1", "d31f5a6", "83d2f04", "c9ed7bf", "ce112d0", "d0114ab", "f73b956", "1203b03", "bab66b4"]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, [])

    def getHashes():
        hashes = []
        for row in range(rebaseDialog.sequenceModel.rowCount()):
            index = rebaseDialog.sequenceModel.index(row)
            line = index.data(RebaseSequenceModel.RebaseLineRole)
            hashes.append(id7(line.hexHash))
        return hashes

    assert getHashes() == s1

    # Move rows. Drag-and-drop is tricky in a unit testing environment, so
    # simulate many calls to moveRows, just like a real drag-and-drop does.
    qlvClickNthRow(rebaseDialog.ui.sequence, 4)
    qlvClickNthRow(rebaseDialog.ui.sequence, 8-1, Qt.KeyboardModifier.ShiftModifier)
    for i in range(4):
        rebaseDialog.sequenceModel.moveRow(QModelIndex_default, 4+i, QModelIndex_default, 0+i)
    assert getHashes() == s2

    # Make sure RebaseDialog has focus after Jump (offscreen tests quirk)
    rebaseDialog.activateWindow()
    waitUntilTrue(rebaseDialog.isActiveWindow)

    # Undo - must return to sequence 1 thanks to command compression (mergeWith)
    QTest.keySequence(rebaseDialog, QKeySequence.StandardKey.Undo)
    assert getHashes() == s1

    # Make sure RebaseDialog has focus after Jump (offscreen tests quirk)
    rebaseDialog.activateWindow()
    waitUntilTrue(rebaseDialog.isActiveWindow)

    # Redo - must return to sequence 2
    QTest.keySequence(rebaseDialog, QKeySequence.StandardKey.Redo)
    assert getHashes() == s2

    rebaseDialog.reject()
    qmb = findQMessageBox(rebaseDialog, "really discard this rebase plan")
    findWidgetWithText(qmb.buttons(), "discard").click()


def testRebaseCommitDialogInfoMessage(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Edit),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    rebaseDialog.accept()

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    commitDialog = findQDialog(rw, "commit", t=CommitDialog)
    assert findTextInWidget(commitDialog.ui.infoText, "rebasing.+inserting an empty commit")
    commitDialog.reject()

    shell("git rm master.txt", wd)
    rw.refreshRepo()
    rw.diffArea.commitButton.click()
    commitDialog = findQDialog(rw, "commit", t=CommitDialog)
    assert findTextInWidget(commitDialog.ui.infoText, "rebasing.+inserting a new commit")
    commitDialog.reject()


def testRebaseUncommittedChangesYellowBannerAtBoot(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    todo = [
        _Todo(0, RebaseOp.Edit),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rebaseDialog = _driveRebaseDialog(rw, onto, todo)
    rebaseDialog.accept()
    assert rw.mergeBanner.property("heeded")  # green

    shell("rm master.txt", wd)  # uncommitted change
    rw.refreshRepo()
    assert not rw.mergeBanner.property("heeded")  # yellow

    # Reopen the repo
    mainWindow.closeAllTabs()
    rw = mainWindow.openRepo(wd)
    assert not rw.mergeBanner.property("heeded")  # yellow


def testRebaseSingleDialog(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rebaseDialog = _driveRebaseDialog(rw, onto, [])

    # Attempt to start a second rebase; denied
    rw.jump(NavLocator.inCommit(onto, ""))
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    acceptQMessageBox(rw, "conclude the current rebase")

    # After closing the rebase dialog, we should be able to start a new one
    rebaseDialog.close()
    rebaseDialog = _driveRebaseDialog(rw, onto, [])
    rebaseDialog.close()


def testRebaseFromSidebar(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    node = sb.findNode(lambda n: n.data == "refs/heads/master")
    menu = sb.makeNodeMenu(node)
    assert not findMenuAction(menu, "rebase.+master.+onto here").isEnabled()

    node = sb.findNode(lambda n: n.data == "refs/heads/no-parent")
    menu = sb.makeNodeMenu(node)
    triggerMenuAction(menu, "rebase.+master.+onto here")
    findQDialog(rw, "(rebase|rebasing).+master.+onto.+42e4e7c", t=RebaseDialog).reject()
    QTest.qWait(0)  # let the dialog be destroyed

    node = sb.findNode(lambda n: n.data == "refs/remotes/origin/master")
    menu = sb.makeNodeMenu(node)
    triggerMenuAction(menu, "rebase.+master.+onto here")
    findQDialog(rw, "(rebase|rebasing).+master.+onto.+49322bb", t=RebaseDialog).reject()


def testRebaseWithChangesInWorkingDirectory(tempDir, mainWindow):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(onto, ""))
    triggerContextMenuAction(rw.graphView.viewport(), "rebase")
    acceptQMessageBox(rw, "working directory contains changes")


def testRebaseStartedOutsideApp(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    pausedTextFilePath = f"{wd}/rebase_paused.txt"

    # Start interactive rebase and pause it on the editor
    driver = GitDriver("rebase", "-i", "master")
    ToolCommands.setQProcessEnvironment(driver, {
        "GIT_SEQUENCE_EDITOR": f"{shlex.quote(getTestDataPath('pause.py'))} {shlex.quote(pausedTextFilePath)}",
    })
    ToolCommands.wrapFlatpakCommand(driver)
    driver.setWorkingDirectory(wd)
    driver.start()
    waitUntilTrue(lambda: Path(pausedTextFilePath).is_file())
    rw.refreshRepo()

    banner = rw.mergeBanner
    assert banner.isVisible()
    assert findTextInWidget(banner.label, "you are editing a rebase plan outside")
    assert findChildWithText(banner, "abort rebase", t=QAbstractButton).isEnabled()
    assert not findChildWithText(banner, "continue rebase", t=QAbstractButton).isEnabled()

    ToolCommands.terminatePlus(driver)


def testRebaseHoverAndLeftClickPill(tempDir, mainWindow, qtbot):
    onto = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(onto, ""))
    rebaseDialog = _driveRebaseDialog(rw, onto, [])

    view = rebaseDialog.ui.sequence
    viewport = view.viewport()

    viewport.grabMouse()  # offscreen quirk: need this for mouseMove to be picked up

    assert not view.delegate.hoverPill

    rect0 = qlvVisualRect(view, 0)  # "pick" first commit
    pillPos0 = rect0.topLeft() + QPoint(4, 4)
    rect2 = qlvVisualRect(view, 2)  # "start" commit
    pillPos2 = rect2.topLeft() + QPoint(4, 4)

    # Start commit tooltip
    tip = summonToolTip(viewport, pillPos2)
    assert re.search(r"starting commit cannot be modified", tip, re.IGNORECASE)

    # Hover over the pill in the first row
    QTest.mouseMove(viewport, pos=pillPos0)
    waitUntilTrue(lambda: view.delegate.hoverPill)
    assert viewport.cursor().shape() == Qt.CursorShape.PointingHandCursor

    # Left-clicking the first row should pop up the context menu
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=pillPos0)
    menu = next(tlw for tlw in QApplication.topLevelWidgets()
                if isinstance(tlw, QMenu) and tlw.isVisible())
    assert findMenuAction(menu, "stop for amending")
    menu.close()
    menu.deleteLater()

    viewport.releaseMouse()
    rebaseDialog.reject()
