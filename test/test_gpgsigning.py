# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
import shutil
import textwrap

import pytest

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.nav import NavLocator
from .test_remotelink import AskpassShim
from .util import *


aliceFpr = "EB85BB5FA33A75E15E944E63F231550C4F47E38E"
aliceKeyId = aliceFpr[-16:]


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


def copySshKey(tempPath: str, testKeyName: str):
    pubPath = f"{tempPath}/{testKeyName}.pub"
    privPath = f"{tempPath}/{testKeyName}"
    shutil.copyfile(getTestDataPath(f"keys/{testKeyName}.pub"), pubPath)
    shutil.copyfile(getTestDataPath(f"keys/{testKeyName}"), privPath)
    os.chmod(privPath, 0o600)
    return pubPath


def setUpForSshSigning(tempPath: str, repoWorkdir: str, testKeyName: str = "simple"):
    pubKeyCopy = copySshKey(tempPath, testKeyName)
    allowedSigners = f"{tempPath}/allowedSigners"
    writeFile(allowedSigners, "CriquetteRockwell " + readTextFile(pubKeyCopy))

    with RepoContext(repoWorkdir) as repo:
        repo.config["gpg.format"] = "ssh"
        repo.config["commit.gpgSign"] = True
        repo.config["user.signingKey"] = pubKeyCopy
        repo.config["gpg.ssh.allowedSignersFile"] = allowedSigners

    return pubKeyCopy, allowedSigners


@requiresGpg
@pytest.mark.parametrize("amend", [False, True])
def testCommitWithPgpSignature(tempDir, mainWindow, tempGpgHome, amend):
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
    assert re.search("good signature; key trusted", toolTip, re.I)
    assert re.search(aliceKeyId, toolTip, re.I)

    # Look for GPG signing information in GetCommitInfo dialog
    triggerMenuAction(mainWindow.menuBar(), "view/go to head")
    triggerContextMenuAction(rw.graphView.viewport(), "get info")
    findQMessageBox(rw, f"signature:.+good signature; key trusted.+{aliceKeyId}").reject()

    ToolCommands.runSync(settings.prefs.gitPath, "verify-commit", "-v", str(commit.id), directory=wd, strict=True)

    ToolCommands.runSync("gpg", "--batch", "--yes", "--delete-secret-and-public-keys", aliceFpr, directory=wd, strict=True)

    with pytest.raises(ChildProcessError, match=r"process exited with code 1"):
        ToolCommands.runSync(settings.prefs.gitPath, "verify-commit", "-v", str(commit.id), directory=wd, strict=True)


@requiresGpg
@pytest.mark.parametrize("amend", [False, True], ids=["commit", "amend"])
@pytest.mark.parametrize("passphrase", [False, True], ids=["simple", "passphrase"])
def testCommitWithSshSignature(tempDir, mainWindow, tempGpgHome, amend, passphrase):
    wd = unpackRepo(tempDir)

    keyName = "simple" if not passphrase else "pygit2_empty"
    setUpForSshSigning(tempDir.name, wd, keyName)

    rw = mainWindow.openRepo(wd)

    if not amend:
        rw.diffArea.commitButton.click()
        acceptQMessageBox(rw, "empty commit")
    else:
        triggerMenuAction(mainWindow.menuBar(), "repo/amend last commit")

    commitDialog = findQDialog(rw, "commit", CommitDialog)
    commitDialog.ui.summaryEditor.setText("TEST SSH-SIGNED COMMIT")

    signAction = commitDialog.ui.gpg.actions()[0]
    assert findTextInWidget(signAction, r"enable sign")
    assert signAction.isEnabled()
    assert signAction.isChecked()
    keyDisplay = commitDialog.ui.gpg.actions()[1]
    assert keyName in keyDisplay.text()

    with AskpassShim(password="empty") as askpassShim:
        commitDialog.accept()

        if passphrase:
            # Make sure we were prompted to enter the passphrase for the correct key
            assert re.search("Enter passphrase for.+pygit2_empty", askpassShim.dumpFile.read_text())

    commit = rw.repo.head_commit
    assert commit.message.strip() == "TEST SSH-SIGNED COMMIT"

    # The commit we've just created should be auto-trusted.
    # Look for signing information in GraphView tooltip
    toolTip = summonToolTip(rw.graphView.viewport(), QPoint(rw.graphView.viewport().width() - 16, 30))
    assert re.search("good signature; key trusted", toolTip, re.I)

    # Look for signing information in GetCommitInfo dialog
    triggerMenuAction(mainWindow.menuBar(), "view/go to head")
    triggerContextMenuAction(rw.graphView.viewport(), "get info")
    findQMessageBox(rw, "signature:.+good signature; key trusted").reject()


@requiresGpg
def testVerifyGoodPgpSignature(tempDir, mainWindow, tempGpgHome):
    wd = unpackRepo(tempDir)

    output = ToolCommands.runSync(
        settings.prefs.gitPath, "-c", "core.abbrev=no",
        "commit", "--allow-empty", f"-S{aliceFpr}", "-mGPG-Signed Commit",
        directory=wd, strict=True)
    commitHash = re.match(r"^\[.+\s([0-9a-f]+)]", output).group(1)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex=commitHash), ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, f"good signature; key not fully trusted.+{aliceKeyId}")

    # Tell GPG to trust the key, then verify the signature again
    writeFile(f"{tempGpgHome}/gpg.conf", f"trusted-key {aliceFpr}\n")
    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, f"good signature; key trusted.+{aliceKeyId}")


@requiresGpg
def testVerifyGoodPgpSignatureWithMissingKey(tempDir, mainWindow, tempGpgHome):
    wd = unpackRepo(tempDir)

    # Create signed commit with Alice's key
    output = ToolCommands.runSync(
        settings.prefs.gitPath, "-c", "core.abbrev=no",
        "commit", "--allow-empty", f"-S{aliceFpr}", "-mGPG-Signed Commit",
        directory=wd, strict=True)
    commitHash = re.match(r"^\[.+\s([0-9a-f]+)]", output).group(1)

    # Nuke gnupg home so it won't find Alice's key
    shutil.rmtree(tempGpgHome)
    os.makedirs(tempGpgHome)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex=commitHash), ""), check=True)

    # Verify signature; key not in keyring
    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    qmb = findQMessageBox(rw, f"not in your keyring.+{aliceKeyId}")

    # Copy key ID to clipboard
    copyButton = next(b for b in qmb.buttons() if findTextInWidget(b, "Copy Key ID"))
    copyButton.click()
    assert QApplication.clipboard().text() == aliceKeyId

    # Close qmb with escape key. Adding the Copy Key ID button may cause
    # qmb to stop responding to the Esc key - this tests the workaround.
    qmb.setFocus()
    waitUntilTrue(qmb.hasFocus)
    QTest.keyClick(qmb, Qt.Key.Key_Escape)

    # Import key and verify again
    ToolCommands.runSync("gpg", "--batch", "--import", getTestDataPath("gpgkeys/alice.key"),
                         directory=wd, strict=True)
    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, f"good signature; key not fully trusted.+{aliceKeyId}")


@requiresGpg
def testVerifyGoodSshSignature(tempDir, mainWindow, tempGpgHome):
    wd = unpackRepo(tempDir)
    _pubKey, allowedSigners = setUpForSshSigning(tempDir.name, wd)

    output = ToolCommands.runSync(
        settings.prefs.gitPath, "-c", "core.abbrev=no",
        "commit", "--allow-empty", "-S", "-mSSH-Signed Commit",
        directory=wd, strict=True)
    commitHash = re.match(r"^\[.+\s([0-9a-f]+)]", output).group(1)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex=commitHash), ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "good signature; key trusted.+CriquetteRockwell")

    # Clear allowed signers, then verify the signature again
    writeFile(allowedSigners, "")
    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "good signature; key not fully trusted")


@requiresGpg
def testVerifyBadPgpSignature(tempDir, mainWindow, tempGpgHome):
    # This signature was made by Alice. We have her key in the test
    # environment's keyring, so we're able to verify it. However, it was made
    # for an unrelated commit, so gpg should say BADSIG.
    aliceRandomSignature = textwrap.dedent("""\
        -----BEGIN PGP SIGNATURE-----
        iHUEABYKAB0WIQTrhbtfozp14V6UTmPyMVUMT0fjjgUCaKzZTwAKCRDyMVUMT0fj
        jl9SAQD9jP2eAIgs1hHyFPCzKsMvMFl4dWfcbv8WEqBreyaxkwD+OBMDvlL5dR2G
        e9tA1G0KHSPP2wgayb6rVUFmNFLD1Qo=
        =Lfmm
        -----END PGP SIGNATURE-----""")

    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        commitString = repo.create_commit_string(
            TEST_SIGNATURE, TEST_SIGNATURE, "BAD PGP SIGNATURE!",
            repo.head_tree.id, [repo.head_commit_id])
        oid = repo.create_commit_with_signature(commitString, aliceRandomSignature)
        repo.create_branch_from_commit("BadSignature", oid)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid, ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "bad signature")


@requiresGpg
def testVerifyBadSshSignature(tempDir, mainWindow, tempGpgHome):
    # An allowed signers file is required to verify ssh signatures
    allowedSigners = tempDir.name + "/allowedSigners"
    touchFile(allowedSigners)

    # This signature was made with the 'simple.pub' key for an unrelated commit.
    randomSignature = textwrap.dedent("""\
        -----BEGIN SSH SIGNATURE-----
        U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAg/QvOXnIKrnSR0vQJxwG/mMfRJs
        eCjePKmBu0cl8qZZUAAAADZ2l0AAAAAAAAAAZzaGE1MTIAAABTAAAAC3NzaC1lZDI1NTE5
        AAAAQMrBf44N5jZsvbUFNPGYYlf7Yw5tFDkAqnRNPjtieWCv1QtW7pgIOzXK6wDVfgwGQT
        QDVVtGG7Hw6M9M7ga9MQA=
        -----END SSH SIGNATURE-----""")

    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        # Verification won't work without this file
        repo.config["gpg.ssh.allowedSignersFile"] = allowedSigners

        commitString = repo.create_commit_string(
            TEST_SIGNATURE, TEST_SIGNATURE, "BAD SSH SIGNATURE!",
            repo.head_tree.id, [repo.head_commit_id])
        oid = repo.create_commit_with_signature(commitString, randomSignature)
        repo.create_branch_from_commit("BadSignature", oid)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid, ""), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "verify signature")
    acceptQMessageBox(rw, "bad signature")
