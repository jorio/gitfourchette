# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re

from gitfourchette.forms.commitdialog import CommitDialog
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


@requiresLfs
def testLfsAddImageInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    image2 = getTestDataPath("image2.png")
    shutil.copy(image2, wd)

    sha = "87e67dacec52083d0f50ec8ac7aa8564f7ff9d8a41403ee0fec0b40d5417a9c2"  # sha256 image2.png
    lfsObjectPath = Path(wd, ".git", "lfs", "objects", sha[:2], sha[2:4], sha)
    assert not lfsObjectPath.exists()

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("image2.png"), check=True)
    # Not an LFS object until it's staged
    assert not findTextInWidget(rw.diffArea.diffHeader, "LFS")

    rw.diffArea.stageButton.click()
    assert lfsObjectPath.exists()
    rw.jump(NavLocator.inStaged("image2.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer added")

    tip = qlvSummonToolTip(rw.diffArea.stagedFiles, 0)
    tip = stripHtml(tip)
    assert re.search(r"lfs object hash:.+" + sha[:7], tip, re.I | re.S)


@requiresLfs
def testLfsChangeImageInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    image2 = getTestDataPath("image2.png")
    shutil.copy(image2, f"{wd}/image1.png")

    lfsObjectPath = Path(wd, ".git", "lfs", "objects", "87", "e6", "87e67dacec52083d0f50ec8ac7aa8564f7ff9d8a41403ee0fec0b40d5417a9c2")
    assert not lfsObjectPath.exists()

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("image1.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "unstaged changes to LFS object")

    rw.diffArea.stageButton.click()
    assert lfsObjectPath.exists()
    rw.jump(NavLocator.inStaged("image1.png"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer changed")

    tip = qlvSummonToolTip(rw.diffArea.stagedFiles, 0)
    tip = stripHtml(tip)
    assert re.search(r"lfs object hash:.+4b8c427.+87e67da", tip, re.I | re.S)


@requiresLfs
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


@requiresLfs
def testLfsChangeTextInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    writeFile(f"{wd}/textfile.c", "// Still an LFS file\nint bogus = 0;\n")

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("textfile.c"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "unstaged changes to LFS object")
    assert findTextInWidget(rw.diffView, "Still an LFS file")

    rw.diffArea.stageButton.click()
    rw.jump(NavLocator.inStaged("textfile.c"), check=True)
    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer changed")
    assert findTextInWidget(rw.diffView, "Still an LFS file")


def testLfsStopTrackingImageInCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    commitId = Oid(hex="8bee978d3eeecdd9e271a5ff8c7cd25ff29d37ad")
    rw.jump(NavLocator.inCommit(commitId, "image1.png"), check=True)

    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer removed")
    assert findTextInWidget(rw.diffArea.specialDiffView, "old image, lfs")
    assert findTextInWidget(rw.diffArea.specialDiffView, "new image, not lfs")


def testLfsStopTrackingTextInCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    commitId = Oid(hex="3fb301f7e37f712d11b575103d0c2eabb3d6e514")
    rw.jump(NavLocator.inCommit(commitId, "textfile.c"), check=True)

    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer removed")

    diffLines = rw.diffView.lineData
    # LFS pointer: red lines
    assert diffLines[1].text.startswith("version https://git-lfs.github.com/spec/v1")
    assert diffLines[1].origin == "-"
    # Vanilla blob: green lines
    assert diffLines[5].text.startswith(" * This is a text file")
    assert diffLines[5].origin == "+"


def testLfsStopTrackingTextInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    # Remove LFS filter on '*.c' files
    attributes = readTextFile(f"{wd}/.gitattributes")
    lines = attributes.splitlines(keepends=True)
    lines = [line for line in lines if "*.c" not in line]
    attributes = "".join(lines)
    writeFile(f"{wd}/.gitattributes", attributes)

    rw = mainWindow.openRepo(wd)

    def checkLfsPointerRemoved():
        assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer removed")
        diffLines = rw.diffView.lineData
        # LFS pointer: red lines
        assert diffLines[1].text.startswith("version https://git-lfs.github.com/spec/v1")
        assert diffLines[1].origin == "-"
        # Vanilla blob: green lines
        assert diffLines[5].text.startswith(" * This is a text file")
        assert diffLines[5].origin == "+"

    # Unstaged
    rw.jump(NavLocator.inUnstaged("textfile.c"), check=True)
    checkLfsPointerRemoved()

    # Staged (Note: we're not staging .gitattributes together with the file
    # here, but the LFS pointer should still be recognized as being removed)
    rw.diffArea.stageButton.click()
    rw.jump(NavLocator.inStaged("textfile.c"), check=True)
    checkLfsPointerRemoved()

    # Make commit then look at the file inside the commit
    rw.diffArea.commitButton.click()
    commitDialog = findQDialog(rw, "Commit", CommitDialog)
    commitDialog.ui.summaryEditor.setText("Untrack text file")
    commitDialog.accept()
    rw.jump(NavLocator.inCommit(rw.repo.head_commit_id, "textfile.c"), check=True)
    checkLfsPointerRemoved()


def testLfsConvertTextToLfsInCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")
    rw = mainWindow.openRepo(wd)

    commitId = Oid(hex="227336fd324c065828168c2e9000a7ceee1ce9dc")
    rw.jump(NavLocator.inCommit(commitId, "textfilemigrate.c"), check=True)

    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer added")

    diffLines = rw.diffView.lineData
    # Vanilla blob: red lines
    assert diffLines[1].text.startswith("/* This is another text file")
    assert diffLines[1].origin == "-"
    # LFS pointer: red lines
    assert diffLines[3].text.startswith("version https://git-lfs.github.com/spec/v1")
    assert diffLines[3].origin == "+"


@requiresLfs
def testLfsConvertTextToLfsInWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    with RepoContext(wd) as repo:
        repo.checkout_commit(Oid(hex="748c251f524c4448370bcd4f3a11c7e128aba8c5"))

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("textfilemigrate.c"), check=True)
    rw.diffArea.stageButton.click()
    rw.jump(NavLocator.inStaged("textfilemigrate.c"), check=True)

    assert findTextInWidget(rw.diffArea.diffHeader, "LFS pointer added")

    diffLines = rw.diffView.lineData
    # Vanilla blob: red lines
    assert diffLines[1].text.startswith("/* This is another text file")
    assert diffLines[1].origin == "-"
    # LFS pointer: red lines
    assert diffLines[3].text.startswith("version https://git-lfs.github.com/spec/v1")
    assert diffLines[3].origin == "+"


def testLfsObjectCacheMissing(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "lfsrepo")

    path1 = Path(wd, ".git", "lfs")
    path1.rename(path1.with_name("lfs-yanked"))

    with RepoContext(wd) as repo:
        repo.reset(Oid(hex="e17a94b1a3dbabdb1371b961e7d7bf3f0fefcd8b"), ResetMode.HARD)

    rw = mainWindow.openRepo(wd)

    # Untrack LFS image
    rw.jump(NavLocator.inCommit(Oid(hex="8bee978d3eeecdd9e271a5ff8c7cd25ff29d37ad"), "image1.png"), check=True)
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "objects? missing from local lfs cache.+4b8c427.+79 bytes")

    # Modify LFS text file
    rw.jump(NavLocator.inCommit(Oid(hex="74ff36893e8e528c18cd59d9603b54f9a00210da"), "textfile.c"), check=True)
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "objects? missing from local lfs cache.+2f065e4.+86 bytes.+d9ad1fb.+87 bytes")

    # Add LFS text file
    rw.jump(NavLocator.inCommit(Oid(hex="5d74f8e6ac1271eb706807e2cbfe67eef5e1e8a8"), "textfile.c"), check=True)
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "objects? missing from local lfs cache.+2f065e4.+86 bytes")

    # Add LFS image
    rw.jump(NavLocator.inCommit(Oid(hex="0b0ff287d62e3ed6ea2725f078ab67b4d2a70f77"), "image1.png"), check=True)
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "objects? missing from local lfs cache.+4b8c427.+79 bytes")
