# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from tarfile import TarFile

from gitfourchette.gitdriver import GitDriver
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

    # Init subtrees
    # (with empty template so that hook sample files don't trip largeFileThreshold)
    GitDriver.runSync("init", "--template=", "SmallTree", directory=wd, strict=True)
    GitDriver.runSync("init", "--template=", "LargeTree", directory=wd, strict=True)

    Path(f"{wd}/a/a2.txt").unlink()
    writeFile(f"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")
    writeFile(f"{wd}/SomeNewFile.txt", "this file is untracked")
    writeFile(f"{wd}/MassiveFile.txt", "." * largeFileThreshold)
    writeFile(f"{wd}/SmallTree/hello.txt", "this untracked tree should end up in a tarball")
    writeFile(f"{wd}/LargeTree/hello.txt", "." * largeFileThreshold)

    if not WINDOWS:
        Path(f"{wd}/symlink").symlink_to(f"{wd}/this/path/does/not/exist")

    setOfDirtyFiles = {
        "a/a1.txt",
        "a/a2.txt",
        "MassiveFile.txt",
        "SomeNewFile.txt",
        "[link] symlink",
        "[new subtree] LargeTree",
        "[new subtree] SmallTree",
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

    assert findInTrash("a1.txt")
    assert findInTrash("SomeNewFile.txt")
    assert findInTrash("SmallTree.tar")
    assert not findInTrash("a2.txt")  # file deletions shouldn't be backed up
    assert not findInTrash("MassiveFile.txt")  # file is too large to be backed up
    assert not findInTrash("LargeTree")  # tree is too large to be backed up

    # Find symlink
    if not WINDOWS:
        assert findInTrash("symlink")
        assert Path(findInTrash("symlink")).is_symlink()

    # Make sure tree.tar contains our repo
    tarballFiles = TarFile(findInTrash("SmallTree.tar")).getnames()
    assert "SmallTree" in tarballFiles
    assert "SmallTree/.git/config" in tarballFiles
    assert "SmallTree/hello.txt" in tarballFiles


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
