# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path

import pytest

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.nav import NavLocator
from gitfourchette.toolbox import stripAccelerators
from .util import *


aliceFpr = "EB85BB5FA33A75E15E944E63F231550C4F47E38E"


@pytest.fixture
def tempGpgHome():
    """
    Create an ephemeral GNUPGHOME so we don't touch the host's keyring.
    """

    environBackup = os.environ.copy()

    # On macOS, gpg doesn't seem to like when GNUPGHOME exceeds 82 characters.
    # The base temp path already uses 57+ characters (/private/var/folders/xx/.../T/).
    # Create a temp dir with as short a path as possible.
    tempHome = QTemporaryDir(f"{QDir.tempPath()}/GFTestGPG")
    path = tempHome.path()
    assert not MACOS or len(path) <= 82, "this path might be too long for GNUPGHOME"

    os.environ["GNUPGHOME"] = path

    stdout = ToolCommands.runSync("gpg", "--batch", "--list-keys", directory=path, strict=True)
    assert stdout.strip() == "", "gpg already found some keys! home not sealed off?"

    ToolCommands.runSync("gpg", "--batch", "--import", getTestDataPath("gpgkeys/alice.key"), directory=path, strict=True)

    stdout = ToolCommands.runSync("gpg", "--batch", "--list-keys", directory=path, strict=True)
    assert aliceFpr in stdout

    yield path

    os.environ.clear()
    os.environ.update(environBackup)


@requiresGpg
@pytest.mark.parametrize("amend", [False, True])
def testCommitGpg(tempDir, mainWindow, tempGpgHome, amend):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.config["commit.gpgSign"] = "true"
        repo.config["user.signingKey"] = aliceFpr

    rw = mainWindow.openRepo(wd)

    if not amend:
        rw.diffArea.commitButton.click()
        acceptQMessageBox(rw, "empty commit")
    else:
        triggerMenuAction(mainWindow.menuBar(), "repo/amend last commit")

    commitDialog: CommitDialog = findQDialog(rw, "commit")
    commitDialog.ui.summaryEditor.setText("TEST GPG-SIGNED COMMIT")

    signAction = commitDialog.ui.gpg.actions()[0]
    assert re.search(r"enable gpg", stripAccelerators(signAction.text()), re.I)
    assert signAction.isEnabled()
    assert signAction.isChecked()
    keyDisplay = commitDialog.ui.gpg.actions()[1]
    assert re.search(rf"key:\s+{aliceFpr}", keyDisplay.text())

    commitDialog.accept()

    commit = rw.repo.head_commit
    assert commit.message.strip() == "TEST GPG-SIGNED COMMIT"

    ToolCommands.runSync(settings.prefs.gitPath, "verify-commit", "-v", str(commit.id), directory=wd, strict=True)

    ToolCommands.runSync("gpg", "--batch", "--yes", "--delete-secret-and-public-keys", aliceFpr, directory=wd, strict=True)

    with pytest.raises(ChildProcessError, match=r"process exited with code 1"):
        ToolCommands.runSync(settings.prefs.gitPath, "verify-commit", "-v", str(commit.id), directory=wd, strict=True)


@requiresGpg
def testVerifyGpgSignature(tempDir, mainWindow, tempGpgHome):
    wd = unpackRepo(tempDir)

    output = ToolCommands.runSync(
        settings.prefs.gitPath, "-c", "core.abbrev=no",
        "commit", "--allow-empty", f"-S{aliceFpr}", "-mGPG-Signed Commit",
        directory=wd, strict=True)
    commitHash = re.match(r"^\[.+\s([0-9a-f]+)]", output).group(1)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex=commitHash), ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "verify gpg")
    acceptQMessageBox(rw, "verified successfully.+alice lovelace")
