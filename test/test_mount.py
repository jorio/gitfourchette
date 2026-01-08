# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.nav import NavLocator
from .util import *


@requiresFuse
def testMountCommitFileListing(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    loc = NavLocator.inCommit(Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322"), "b/b1.txt")
    rw.jump(loc, check=True)

    with MockDesktopServicesContext() as services:
        triggerContextMenuAction(rw.graphView.viewport(), "mount commit as folder")
        mountPoint = Path(services.urls[-1].toLocalFile())

    # Give the process a second to boot up
    waitUntilTrue(lambda: (mountPoint / "master.txt").exists())

    allFiles = []
    for root, _dirs, files in os.walk(mountPoint):  # TODO: Switch to Path.walk once we can drop Python 3.11 and older
        allFiles.extend(Path(root, f).relative_to(mountPoint) for f in files)
    assert {str(p) for p in allFiles} == {
        "master.txt", "a/a1.txt", "a/a2.txt",
        "b/b1.txt", "b/b2.txt", "c/c1.txt", "c/c2.txt"
    }

    assert (mountPoint / "master.txt").read_bytes() == b"On master\nOn master\n"
    assert (mountPoint / "a/a1.txt").read_bytes() == b"a1\na1\n"

    timestamp = (mountPoint / "master.txt").lstat().st_mtime
    date = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    assert date.year() == 2005
    assert date.month() == 4
    assert date.day() in [7, 8]  # allow some wiggle room depending on timezone (commit was made at 15:29 UTC-7)

    triggerMenuAction(mainWindow.menuBar(), "mount/unmount")
    assert not mountPoint.exists()


@requiresFuse
def testConfirmUnmountBeforeClosing(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    loc = NavLocator.inCommit(Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322"), "b/b1.txt")
    rw.jump(loc, check=True)

    with MockDesktopServicesContext() as services:
        triggerContextMenuAction(rw.graphView.viewport(), "mount commit as folder")
        mountPoint = Path(services.urls[-1].toLocalFile())

    # Give the process a second to boot up
    waitUntilTrue(lambda: (mountPoint / "master.txt").exists())

    mainWindow.close()
    rejectQMessageBox(mainWindow, "unmount")
    assert mainWindow.isVisible()
    assert Path(mountPoint).exists()

    mainWindow.close()
    qmb = findQMessageBox(mainWindow, "unmount.+before quitting")
    qmb.button(QMessageBox.StandardButton.Ok).click()
    assert not mainWindow.isVisible()
    assert not Path(mountPoint).exists()


@requiresFuse
def testMountMultipleUnmountAll(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    locs = [
        NavLocator.inCommit(Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322"), "b/b1.txt"),
        NavLocator.inCommit(Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"), "c/c1.txt"),
        NavLocator.inCommit(Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6"), "master.txt"),
    ]

    mountPoints = []

    for loc in locs:
        rw.jump(loc, check=True)

        with MockDesktopServicesContext() as services:
            triggerContextMenuAction(rw.graphView.viewport(), "mount commit as folder")
            path = Path(services.urls[-1].toLocalFile())
            mountPoints.append(path)

    # Give the processes a second to boot up
    waitUntilTrue(lambda: all((path / loc.path).exists()
                              for loc, path in zip(locs, mountPoints, strict=True)))

    triggerMenuAction(mainWindow.menuBar(), "mount/unmount all")
    assert all(not (path / loc.path).exists()
               for loc, path in zip(locs, mountPoints, strict=True))
