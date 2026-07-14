# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
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
    # The mainWindow fixture ensures proper setup/teardown of the trash
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

    GFApplication.applyPrefs(maxTrashFileKB=largeFileThreshold // 1024)
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

    def findInTrash(partialFileName: str) -> Path | None:
        return next((f for f in trash.trashFiles if partialFileName in f.name), None)

    assert findInTrash("a1.txt")
    assert findInTrash("SomeNewFile.txt")
    assert findInTrash("SmallTree.tar")
    assert not findInTrash("a2.txt")  # file deletions shouldn't be backed up
    assert not findInTrash("MassiveFile.txt")  # file is too large to be backed up
    assert not findInTrash("LargeTree")  # tree is too large to be backed up

    # Find symlink
    if not WINDOWS:
        assert findInTrash("symlink")
        assert findInTrash("symlink").is_symlink()

    # Make sure tree.tar contains our repo
    tarballFiles = TarFile(findInTrash("SmallTree.tar")).getnames()
    assert "SmallTree" in tarballFiles
    assert "SmallTree/.git/config" in tarballFiles
    assert "SmallTree/hello.txt" in tarballFiles


def testTrashFull(tempDir, mainWindow):
    # The mainWindow fixture ensures proper setup/teardown of the trash
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
    trashInstance = Trash.instance()
    assert len(trashInstance.trashFiles) == settings.prefs.maxTrashFiles
    assert "a1.txt" in trashInstance.trashFiles[0].name


def testClearTrash(mainWindow):
    assert Trash.instance().count() == 0

    mainWindow.clearRescueFolder()
    acceptQMessageBox(mainWindow, "no discarded (patches|changes) to delete")

    _fillTrashWithJunk(40)
    assert Trash.instance().count() == 40
    mainWindow.clearRescueFolder()
    acceptQMessageBox(mainWindow, "delete.+40.+discarded (patches|changes)")
    assert Trash.instance().count() == 0


def testOpenTrashFolder(mainWindow):
    # Attempt to open trash without any files in it
    triggerMenuAction(mainWindow.menuBar(), "help/open trash")
    rejectQMessageBox(mainWindow, "there.s no trash folder")

    # Open trash with some files
    _fillTrashWithJunk(40)
    with MockDesktopServicesContext(mainWindow) as services:
        triggerMenuAction(mainWindow.menuBar(), "help/open trash")
        openedPath = services.lastUrlAsLocalFile()
        assert Trash.instance().trashDir.samefile(openedPath)


def testTrashSymlinkNameConflicts(mainWindow, tempDir):
    wd = tempDir.name
    trash = Trash.instance()

    from gitfourchette import settings
    settings.prefs.maxTrashFiles = max(300, settings.prefs.maxTrashFiles)

    assert trash.maxFileCount() >= 300
    assert trash.MaxUniqueSuffix < trash.maxFileCount()

    Path(wd, "trashed_symlink").symlink_to(Path(wd, "nowhere"))

    # Saturate trash with symlinks
    while trash.count() < trash.maxFileCount():
        trash.backupFile(wd, "trashed_symlink")
