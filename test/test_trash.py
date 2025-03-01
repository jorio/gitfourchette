# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from tarfile import TarFile

from gitfourchette.trash import Trash
from .util import *


def _fillTrashWithJunk(n):
    trash = Trash.instance()
    trash.refreshFiles()
    trash.clear()
    os.makedirs(trash.trashDir, exist_ok=True)
    for i in range(n):
        with open(F"{trash.trashDir}/19991231T235900-test{i}.txt", "w") as junk:
            junk.write(F"test{i}")
    trash.refreshFiles()


def testBackupDiscardedPatches(tempDir, mainWindow):
    largeFileThreshold = 1024 + 1

    wd = unpackRepo(tempDir)
    os.unlink(F"{wd}/a/a2.txt")
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")
    writeFile(F"{wd}/SomeNewFile.txt", "this file is untracked")
    writeFile(F"{wd}/MassiveFile.txt", "." * largeFileThreshold)
    writeFile(F"{wd}/tree/.git/config", "")
    writeFile(F"{wd}/tree/hello.txt", "this untracked tree should end up in a tarball")
    writeFile(F"{wd}/MassiveTree/.git/config", "")
    writeFile(F"{wd}/MassiveTree/hello.txt", "." * largeFileThreshold)
    if not WINDOWS:
        os.symlink(f"{wd}/this/path/does/not/exist", f"{wd}/symlink")

    setOfDirtyFiles = {
        "a/a1.txt",
        "a/a2.txt",
        "MassiveFile.txt",
        "SomeNewFile.txt",
        "[link] symlink",
        "[tree] tree",
        "[tree] MassiveTree"
    }

    mainWindow.onAcceptPrefsDialog({"maxTrashFileKB": largeFileThreshold // 1024})
    rw = mainWindow.openRepo(wd)

    if WINDOWS:
        setOfDirtyFiles.remove("[link] symlink")
    assert set(qlvGetRowData(rw.dirtyFiles)) == setOfDirtyFiles
    assert qlvGetRowData(rw.stagedFiles) == []

    trash = Trash.instance()
    trash.refreshFiles()
    assert len(trash.trashFiles) == 0

    rw.dirtyFiles.setFocus()
    QTest.keySequence(rw.dirtyFiles, QKeySequence("Ctrl+A,Del"))
    acceptQMessageBox(rw, "really discard changes")

    def findInTrash(partialFileName: str):
        try:
            return next(f for f in trash.trashFiles if partialFileName in f)
        except StopIteration:
            return None

    assert len(trash.trashFiles) == 4 if not WINDOWS else 3

    assert findInTrash("a1.txt")
    assert findInTrash("SomeNewFile.txt")

    if not WINDOWS:
        assert findInTrash("symlink")
        assert os.path.islink(findInTrash("symlink"))

    assert not findInTrash("a2.txt")  # file deletions shouldn't be backed up
    assert not findInTrash("MassiveFile.txt")  # file is too large to be backed up
    assert not findInTrash("MassiveTree")  # tree is too large to be backed up

    assert findInTrash("tree.tar")
    assert set(TarFile(findInTrash("tree.tar")).getnames()) == {
        "tree", "tree/.git", "tree/.git/config", "tree/hello.txt"}


def testTrashFull(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    from gitfourchette import settings

    # Create N junk files in trash
    _fillTrashWithJunk(settings.prefs.maxTrashFiles * 2)

    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Delete)
    acceptQMessageBox(rw, "really discard changes")

    # Trash should have been purged to make room for new patch
    assert len(Trash.instance().trashFiles) == settings.prefs.maxTrashFiles
    assert "a1.txt" in Trash.instance().trashFiles[0]


def testClearTrash(mainWindow):
    assert Trash.instance().size()[1] == 0

    mainWindow.clearRescueFolder()
    acceptQMessageBox(mainWindow, "no discarded (patches|changes) to delete")

    _fillTrashWithJunk(40)
    assert Trash.instance().size()[1] == 40
    mainWindow.clearRescueFolder()
    acceptQMessageBox(mainWindow, "delete.+40.+discarded (patches|changes)")
    assert Trash.instance().size()[1] == 0
