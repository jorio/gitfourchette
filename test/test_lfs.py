# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re

from gitfourchette.nav import NavLocator
from .util import *


def testLfsImageDiffInCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    addCommit = Oid(hex="0b0ff287d62e3ed6ea2725f078ab67b4d2a70f77")
    rw.jump(NavLocator.inCommit(addCommit, "image1.png"), check=True)

    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer added")

    # If SpecialDiffView is able to display details about the image,
    # then the LFS pointer was correctly parsed.
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "new image.+6.+6 pixels.+79 bytes")


def testLfsTextDiffInCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    commitId = Oid(hex="74ff36893e8e528c18cd59d9603b54f9a00210da")
    rw.jump(NavLocator.inCommit(commitId, "textfile.c"), check=True)

    assert findTextInWidget(rw.diffView, r"int hello\(void\)")  # deleted line
    assert findTextInWidget(rw.diffView, r"int foobar\(void\)")  # added line


def testLfsToggleRawPointersInImageFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    addCommit = Oid(hex="0b0ff287d62e3ed6ea2725f078ab67b4d2a70f77")
    rw.jump(NavLocator.inCommit(addCommit, "image1.png"), check=True)

    mainWindow.onAcceptPrefsDialog({"rawLfsPointers": True})
    assert rw.diffView.isVisible()
    assert findTextInWidget(rw.diffView, "git-lfs.github.com.spec.v1")

    mainWindow.onAcceptPrefsDialog({"rawLfsPointers": False})
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "new image.+6.+6 pixels.+79 bytes")


def testLfsToggleRawPointersInTextFile(tempDir, mainWindow):
    mainWindow.onAcceptPrefsDialog({"rawLfsPointers": True})

    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    commitId = Oid(hex="74ff36893e8e528c18cd59d9603b54f9a00210da")
    rw.jump(NavLocator.inCommit(commitId, "textfile.c"), check=True)
    assert findTextInWidget(rw.diffView, "git-lfs.github.com.spec.v1")

    mainWindow.onAcceptPrefsDialog({"rawLfsPointers": False})
    assert findTextInWidget(rw.diffView, "foobar")


def testLfsFileToolTip(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    addCommit = Oid(hex="0b0ff287d62e3ed6ea2725f078ab67b4d2a70f77")
    rw.jump(NavLocator.inCommit(addCommit, "image1.png"), check=True)

    tip = qlvSummonToolTip(rw.committedFiles, 0)
    tip = stripHtml(tip)
    assert re.search(r"size:.+79 bytes \(lfs\)", tip, re.I | re.S)
    assert re.search(r"lfs object hash:.+4b8c427", tip, re.I | re.S)


def testLfsAddImageInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    image2 = getTestDataPath("image2.png")
    shutil.copy(image2, wd)

    sha = "87e67dacec52083d0f50ec8ac7aa8564f7ff9d8a41403ee0fec0b40d5417a9c2"  # sha256 image2.png
    lfsObjectPath = Path(wd, ".git", "lfs", "objects", sha[:2], sha[2:4], sha)
    assert not lfsObjectPath.exists()

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("image2.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer added")

    rw.diffArea.stageButton.click()
    assert lfsObjectPath.exists()
    rw.jump(NavLocator.inStaged("image2.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer added")

    tip = qlvSummonToolTip(rw.diffArea.stagedFiles, 0)
    tip = stripHtml(tip)
    assert re.search(r"lfs object hash:.+" + sha[:7], tip, re.I | re.S)


def testLfsChangeImageInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    image2 = getTestDataPath("image2.png")
    shutil.copy(image2, f"{wd}/image1.png")

    lfsObjectPath = Path(wd, ".git", "lfs", "objects", "87", "e6", "87e67dacec52083d0f50ec8ac7aa8564f7ff9d8a41403ee0fec0b40d5417a9c2")
    assert not lfsObjectPath.exists()

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("image1.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer changed")

    rw.diffArea.stageButton.click()
    assert lfsObjectPath.exists()
    rw.jump(NavLocator.inStaged("image1.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer changed")

    tip = qlvSummonToolTip(rw.diffArea.stagedFiles, 0)
    tip = stripHtml(tip)
    assert re.search(r"lfs object hash:.+4b8c427.+87e67da", tip, re.I | re.S)


def testLfsRemoveImageInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    os.remove(f"{wd}/image1.png")

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("image1.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer removed")
    assert findTextInWidget(rw.diffArea.specialDiffView, "deleted image")

    tip = qlvSummonToolTip(rw.diffArea.dirtyFiles, 0)
    tip = stripHtml(tip)
    assert re.search(r"lfs object hash:.+4b8c427", tip, re.I | re.S)

    rw.diffArea.stageButton.click()
    rw.jump(NavLocator.inStaged("image1.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer removed")


def testLfsChangeTextInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    writeFile(f"{wd}/textfile.c", "// Still an LFS file\nint bogus = 0;\n")

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("textfile.c"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer changed")
    assert findTextInWidget(rw.diffView, "Still an LFS file")

    rw.diffArea.stageButton.click()
    rw.jump(NavLocator.inStaged("textfile.c"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer changed")
    assert findTextInWidget(rw.diffView, "Still an LFS file")
