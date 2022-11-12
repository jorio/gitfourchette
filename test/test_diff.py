from . import reposcenario
from .fixtures import *
from .util import *
from gitfourchette.widgets.commitdialog import CommitDialog
import pygit2


def testSensibleMessageShownForUnstagedEmptyFile(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    touchFile(F"{wd}/NewEmptyFile.txt")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)

    assert not rw.diffView.isVisibleTo(rw)
    assert rw.richDiffView.isVisibleTo(rw)
    assert "is empty" in rw.richDiffView.toPlainText().lower()


def testStagePartialPatchInUntrackedFile(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/NewFile.txt", "line A\nline B\nline C\n")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    assert rw.repo.status() == {"NewFile.txt": pygit2.GIT_STATUS_WT_NEW}

    rw.diffView.setFocus()
    QTest.keyPress(rw.diffView, Qt.Key_Return)

    assert rw.repo.status() == {"NewFile.txt": pygit2.GIT_STATUS_INDEX_NEW | pygit2.GIT_STATUS_WT_MODIFIED}

    stagedId = rw.repo.index["NewFile.txt"].id
    stagedBlob: pygit2.Blob = rw.repo[stagedId].peel(pygit2.Blob)
    assert stagedBlob.data == b"line A\n"


def testPartialPatchSpacesInFilename(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/file with spaces.txt", "line A\nline B\nline C\n")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    assert rw.repo.status() == {"file with spaces.txt": pygit2.GIT_STATUS_WT_NEW}

    rw.diffView.setFocus()
    QTest.keyPress(rw.diffView, Qt.Key_Return)

    assert rw.repo.status() == {"file with spaces.txt": pygit2.GIT_STATUS_INDEX_NEW | pygit2.GIT_STATUS_WT_MODIFIED}

    stagedId = rw.repo.index["file with spaces.txt"].id
    stagedBlob: pygit2.Blob = rw.repo[stagedId].peel(pygit2.Blob)
    assert stagedBlob.data == b"line A\n"


def testDiscardHunkNoEOL(qtbot, tempDir, mainWindow):
    NEW_CONTENTS = "change without eol"

    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/master.txt", NEW_CONTENTS)
    rw = mainWindow.openRepo(wd)

    assert rw.repo.status() == {"master.txt": pygit2.GIT_STATUS_WT_MODIFIED}

    qlvClickNthRow(rw.dirtyFiles, 0)
    rw.diffView.setFocus()
    rw.diffView.discardHunk(0)

    acceptQMessageBox(rw, "discard.+hunk")
    assert NEW_CONTENTS not in readFile(f"{wd}/master.txt").decode('utf-8')
