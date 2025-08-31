# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
import textwrap

import pytest

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.nav import NavLocator
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
    assert findTextInWidget(signAction, r"enable sign")
    assert signAction.isEnabled()
    assert signAction.isChecked()
    keyDisplay = commitDialog.ui.gpg.actions()[1]
    assert re.search(rf"key:\s+{aliceFpr}", keyDisplay.text())

    commitDialog.accept()

    commit = rw.repo.head_commit
    assert commit.message.strip() == "TEST GPG-SIGNED COMMIT"

    # The commit we've just created should be auto-trusted.
    # Look for GPG signing information in GraphView tooltip
    toolTip = summonToolTip(rw.graphView.viewport(), QPoint(rw.graphView.viewport().width() - 16, 30))
    assert "good signature; key trusted" in toolTip.lower()

    # Look for GPG signing information in GetCommitInfo dialog
    triggerMenuAction(mainWindow.menuBar(), "view/go to head")
    triggerContextMenuAction(rw.graphView.viewport(), "get info")
    findQMessageBox(rw, "signature:.+good signature; key trusted").reject()

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

    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "good signature; key not fully trusted")

    # Tell GPG to trust the key, then verify the signature again
    writeFile(f"{tempGpgHome}/gpg.conf", f"trusted-key {aliceFpr}\n")
    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "good signature; key trusted")


@requiresGpg
def testCommitGpgBadSignature(tempDir, mainWindow, tempGpgHome):
    # This signature was made by Alice. We have her key in the test
    # environment's keyring, so we're able to verify it. However, it was made
    # for an unrelated commit, so gpg should say BADSIG.
    aliceRandomSignature = textwrap.dedent("""\
        -----BEGIN PGP SIGNATURE-----

        iHUEABYKAB0WIQTrhbtfozp14V6UTmPyMVUMT0fjjgUCaKzZTwAKCRDyMVUMT0fj
        jl9SAQD9jP2eAIgs1hHyFPCzKsMvMFl4dWfcbv8WEqBreyaxkwD+OBMDvlL5dR2G
        e9tA1G0KHSPP2wgayb6rVUFmNFLD1Qo=
        =Lfmm
        -----END PGP SIGNATURE-----
        """)

    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        commitString = repo.create_commit_string(
            TEST_SIGNATURE, TEST_SIGNATURE, "BAD GPG SIGNATURE!",
            repo.head_tree.id, [repo.head_commit_id])
        oid = repo.create_commit_with_signature(commitString, aliceRandomSignature)
        repo.create_branch_from_commit("BadGPG", oid)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid, ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "bad signature")
