# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import base64
import logging
import re
from contextlib import suppress
from pathlib import Path

try:
    from pygit2.remotes import PushUpdate
except ImportError:  # Compatibility with pygit2 1.18.1 and older
    PushUpdate = None

from gitfourchette import settings
from gitfourchette.forms.passphrasedialog import PassphraseDialog
from gitfourchette.gitdriver import VanillaFetchStatusFlag
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repoprefs import RepoPrefs
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

DLRATE_REFRESH_INTERVAL = 500


def getAuthNamesFromFlags(allowedTypes):
    allowedTypeNames = []
    for credential in CredentialType:
        if allowedTypes & credential:
            allowedTypeNames.append(credential.name.lower())
    return ", ".join(allowedTypeNames)


def isPrivateKeyPassphraseProtected(path: str):
    lines = Path(path).read_text("utf-8").splitlines(keepends=False)

    while lines and not re.match("^-+END OPENSSH PRIVATE KEY-+ *$", lines.pop()):
        continue

    while lines and not re.match("^-+BEGIN OPENSSH PRIVATE KEY-+ *$", lines.pop(0)):
        continue

    if not lines:
        return False

    keyContents = base64.b64decode("".join(lines))

    return b"bcrypt" in keyContents


def collectUserKeyFiles():
    if APP_TESTMODE:
        from test.util import getTestDataPath
        sshDirectory = getTestDataPath("keys")
    else:  # pragma: no cover
        sshDirectory = QStandardPaths.locate(QStandardPaths.StandardLocation.HomeLocation, ".ssh", QStandardPaths.LocateOption.LocateDirectory)

    keypairFiles: list[tuple[str, str]] = []

    if not sshDirectory:
        return keypairFiles

    for publicKey in Path(sshDirectory).glob("*.pub"):
        privateKey = publicKey.with_suffix("")
        if publicKey.is_file() and privateKey.is_file():
            logger.debug(f"Discovered key pair {privateKey}")
            keypairFiles.append((str(publicKey), str(privateKey)))

    return keypairFiles


class StaleLeaseError(ConnectionError):
    pass


class RemoteLink(QObject, RemoteCallbacks):
    sessionPassphrases = {}

    userAbort = Signal()
    message = Signal(str)
    progress = Signal(int, int)
    beginRemote = Signal(str, str)

    # Pass messages between network thread and UI thread for passphrase prompt
    requestPassphrase = Signal(str, object)

    updatedTips: dict[str, tuple[Oid, Oid]]

    @staticmethod
    def mayAbortNetworkOperation(f):
        def wrapper(*args):
            x: RemoteLink = args[0]
            if x._aborting:
                raise InterruptedError(_("Remote operation interrupted by user."))
            return f(*args)
        return wrapper

    @classmethod
    def clearSessionPassphrases(cls):
        cls.sessionPassphrases.clear()

    def __init__(self, parent: QObject):
        QObject.__init__(self, parent)
        RemoteCallbacks.__init__(self)

        assert findParentWidget(self)

        self.setObjectName("RemoteLink")
        self.transferRateTimer = QElapsedTimer()

        self.resetLoginState()
        self._aborting = False
        self._busy = False
        self.updatedTips = {}

        self.userAbort.connect(self._onAbort)
        self.requestPassphrase.connect(self.showPassphraseDialog)

    def resetLoginState(self):
        self.attempts = 0

        self.keypairFiles = []
        self.usingCustomKeyFile = ""
        self.moreDetailsOnCustomKeyFileFail = True
        self.anyKeyIsUnreadable = False

        self.lastAttemptKey = ""
        self.lastAttemptUrl = ""
        self.lastAttemptPassphrase = None
        self.usingKnownKeyFirst = False  # for informative purposes only

        self.transferRate = 0
        self.transferredBytesAtTimerStart = 0
        self.transferCompleteAtTimerStart = False
        self.transferRateTimer.invalidate()

        self._sidebandProgressBuffer = ""

        self.pushLease = None
        self.pushLeaseRemote = None

    def forceCustomKeyFile(self, privKeyPath):
        self.usingCustomKeyFile = privKeyPath
        self.moreDetailsOnCustomKeyFileFail = False

    def discoverKeyFiles(self, remote: Remote | str = ""):
        # Find remote-specific key files
        if isinstance(remote, Remote) and not self.usingCustomKeyFile:
            assert isinstance(remote._repo, Repo)
            self.usingCustomKeyFile = RepoPrefs.getRemoteKeyFileForRepo(remote._repo, remote.name)

        if self.usingCustomKeyFile:
            privkey = self.usingCustomKeyFile
            pubkey = privkey + ".pub"

            if not Path(pubkey).is_file():
                raise FileNotFoundError(_("Remote-specific public key file not found:") + " " + compactPath(pubkey))

            if not Path(privkey).is_file():
                raise FileNotFoundError(_("Remote-specific private key file not found:") + " " + compactPath(privkey))

            logger.info(f"Using remote-specific key pair {privkey}")

            self.keypairFiles.append((pubkey, privkey))

        # Find user key files
        else:
            self.keypairFiles.extend(collectUserKeyFiles())

            # If we've already connected to this host before,
            # give higher priority to the key that we used last
            if remote:
                url = remote.url if isinstance(remote, Remote) else remote
                assert type(url) is str
                strippedUrl = stripRemoteUrlPath(url)
                if strippedUrl and strippedUrl in settings.history.workingKeys:
                    workingKey = settings.history.workingKeys[strippedUrl]
                    self.keypairFiles.sort(key=lambda tup: tup[1] != workingKey)
                    logger.debug(f"Will try key '{workingKey}' first because it has been used in the past to access '{strippedUrl}'")
                    self.usingKnownKeyFirst = True

        # See if any of the keys are unreadable
        for _pubkey, privkey in self.keypairFiles:
            try:
                # Just some dummy read
                isPrivateKeyPassphraseProtected(privkey)
            except OSError:
                self.anyKeyIsUnreadable = True
                break

    def isAborting(self):
        return self._aborting

    def isBusy(self):
        return self._busy

    def raiseAbortFlag(self):
        self.message.emit(_("Aborting remote operation…"))
        self.progress.emit(0, 0)
        self.userAbort.emit()

    def _onAbort(self):
        self._aborting = True
        logger.info("Abort flag set.")

    @mayAbortNetworkOperation
    def sideband_progress(self, string):
        # The remote sends a stream of characters intended to be printed
        # progressively. So, the string we receive may be incomplete.
        string = self._sidebandProgressBuffer + string

        # \r refreshes the current status line, and \n starts a new one.
        # Send the last complete line we have.
        split = string.replace("\r", "\n").rsplit("\n", 2)
        with suppress(IndexError):
            logger.info(f"[sideband] {split[-2]}")

        # Buffer partial message for next time.
        self._sidebandProgressBuffer = split[-1]

    # def certificate_check(self, certificate, valid, host):
    #     gflog("RemoteLink", "Certificate Check", certificate, valid, host)
    #     return 1

    @mayAbortNetworkOperation
    def credentials(self, url, username_from_url, allowed_types):
        self.attempts += 1
        self.lastAttemptKey = ""
        self.lastAttemptPassphrase = None

        if self.attempts > 10:
            raise ConnectionRefusedError(_("Too many credential retries."))

        if self.attempts == 1:
            logger.info(f"Auths accepted by server: {getAuthNamesFromFlags(allowed_types)}")

        if self.keypairFiles and (allowed_types & CredentialType.SSH_KEY):
            pubkey, privkey = self.keypairFiles.pop(0)
            logger.info(f"Logging in with: {compactPath(pubkey)}")
            self.message.emit(_("Logging in with key:") + " " + compactPath(pubkey))
            passphrase = self.getPassphraseFromNetworkThread(privkey)
            self.lastAttemptKey = privkey
            self.lastAttemptUrl = url
            self.lastAttemptPassphrase = passphrase
            return Keypair(username_from_url, pubkey, privkey, passphrase)
        elif self.attempts == 0:
            raise NotImplementedError(
                _("Unsupported authentication type.") + " " +
                _("The remote claims to accept: {0}.", getAuthNamesFromFlags(allowed_types)))
        elif self.anyKeyIsUnreadable:
            raise ConnectionRefusedError(
                _("Could not find suitable key files for this remote.") + " " +
                _("The key files couldn’t be opened (permission issues?)."))
        elif self.usingCustomKeyFile:
            message = _("The remote has rejected your custom key file ({0}).", compactPath(self.usingCustomKeyFile))
            if self.moreDetailsOnCustomKeyFileFail:
                message += " "
                message += _("To change key file settings for this remote, "
                             "right-click on the remote in the sidebar and pick “Edit Remote”.")
            raise ConnectionRefusedError(message)
        else:
            raise ConnectionRefusedError(_("Credentials rejected by remote."))

    @mayAbortNetworkOperation
    def transfer_progress(self, stats: TransferProgress):
        self._genericTransferProgress(
            stats.received_objects,
            stats.total_objects,
            stats.received_bytes,
            _("Downloading…"),
            _("Download complete ({0})."))

    @mayAbortNetworkOperation
    def push_transfer_progress(self, objects_pushed: int, total_objects: int, bytes_pushed: int):
        self._genericTransferProgress(
            objects_pushed,
            total_objects,
            bytes_pushed,
            _("Uploading…"),
            _("Upload complete ({0})."),
            showIndexingProgress=False)

    @staticmethod
    def supportsLease(fatal=False) -> bool:
        if settings.prefs.vanillaGit:
            return True
        return pygit2_version_at_least("1.18.2", raise_error=fatal, feature_name="Force Push With Lease")

    def setLease(self, remote: Remote, simpleName: str):
        # The push_negotiation callback (required for lease check) is only effective in pygit2 1.18.2+
        RemoteLink.supportsLease(fatal=True)

        if self.pushLease is None:
            self.pushLease = {}
            self.pushLeaseRemote = remote
        else:
            assert self.pushLeaseRemote is remote, "lease can only be set for one remote at a time"

        repo = remote._repo
        rbName = remote.name + "/" + simpleName
        branch = repo.branches.remote[rbName]
        target = branch.target
        remoteRefName = RefPrefix.HEADS + simpleName
        self.pushLease[remoteRefName] = target

        logger.debug(f"Setting lease on {remoteRefName} ({id7(target)})")

    def clearLease(self):
        self.pushLease = None
        self.pushLeaseRemote = None

    # Only effective with pygit2 1.18.2+
    @mayAbortNetworkOperation
    def push_negotiation(self, updates: list[PushUpdate]):
        if self.pushLease is None:
            return

        remoteHeadInfo = self.pushLeaseRemote.list_heads(connect=False)

        for update in updates:
            refName = update.dst_refname

            try:
                actualHead = next(rh.oid for rh in remoteHeadInfo if rh.name == refName)
            except StopIteration:
                logger.debug(f"push_negotiation: no advertised head for {refName}")
                actualHead = NULL_OID

            try:
                knownHead = self.pushLease[refName]
            except KeyError:
                logger.debug(f"push_negotiation: no lease for {refName}")
                knownHead = NULL_OID

            if knownHead != actualHead:
                remoteName = self.pushLeaseRemote.name
                displayShorthand = remoteName + "/" + RefPrefix.split(refName)[1]
                raise StaleLeaseError(
                    _("Your repository’s knowledge of remote branch {branch} is out of date. "
                      "The force-push was rejected to prevent data loss. "
                      "Please fetch remote {remote} before pushing again. "
                      "(Expected commit at tip: {known}; actually on the remote: {actual}.)",
                      branch=tquo(displayShorthand),
                      known=tquo(shortHash(knownHead)),
                      actual=tquo(shortHash(actualHead)),
                      remote=tquo(remoteName)))

            logger.info(f"push_negotiation: lease check pass ({refName} {id7(knownHead)})")

    def _genericTransferProgress(self, objectsTransferred: int, totalObjects: int, bytesTransferred: int,
                                 transferingMessage: str, completeMessage: str, showIndexingProgress=True):
        obj = min(objectsTransferred, totalObjects)
        transferComplete = obj == totalObjects

        if not self.transferRateTimer.isValid():
            # Prime timer
            self.transferRateTimer.start()
            self.transferredBytesAtTimerStart = bytesTransferred
        elif self.transferRateTimer.elapsed() > DLRATE_REFRESH_INTERVAL:
            # Schedule next timer tick
            intervalBytes = bytesTransferred - self.transferredBytesAtTimerStart
            self.transferRate = int(intervalBytes * 1000 / self.transferRateTimer.elapsed())
            self.transferRateTimer.restart()
            self.transferredBytesAtTimerStart = bytesTransferred
        elif transferComplete != self.transferCompleteAtTimerStart:
            # When the transfer completes, force UI update regardless of timer
            pass
        else:
            # Don't update UI too frequently (ease CPU load)
            return

        self.transferCompleteAtTimerStart = transferComplete

        locale = QLocale()
        sizeText = locale.formattedDataSize(bytesTransferred, 1)

        if not transferComplete:
            self.progress.emit(obj, totalObjects)
            message = transferingMessage + " "
            # Hide transfer size until it's large enough, so we don't flash an
            # irrelevant number for small transfers (e.g. "Uploading 12 bytes").
            if bytesTransferred >= 1024:
                message += sizeText + " "
            if self.transferRate != 0:
                rateText = locale.formattedDataSize(self.transferRate, 0 if self.transferRate < 1e6 else 1)
                message += _p("download speed", "({0}/s)", rateText)
        else:
            self.progress.emit(0, 0)
            message = completeMessage.format(sizeText) + " "
            if showIndexingProgress:
                message += _("Indexing {0} objects…", locale.toString(totalObjects))

        self.message.emit(message)

    def update_tips(self, refname: str, old: Oid, new: Oid):
        logger.info(f"Update tip {refname}: {old} ---> {new}")
        self.updatedTips[refname] = (old, new)

    def push_update_reference(self, refname: str, message: str | None):
        if not message:
            message = ""
        self.message.emit(_("Push update reference:") + f"\n{refname} {message}")

    def rememberSuccessfulKeyFile(self):
        if self.lastAttemptKey and self.lastAttemptUrl and not self.usingCustomKeyFile:
            strippedUrl = stripRemoteUrlPath(self.lastAttemptUrl)
            settings.history.setRemoteWorkingKey(strippedUrl, self.lastAttemptKey)
            logger.debug(f"Remembering key '{self.lastAttemptKey}' for host '{strippedUrl}'")

        if (self.lastAttemptKey
                and self.lastAttemptUrl
                and self.lastAttemptPassphrase is not None
                and settings.prefs.rememberPassphrases):
            RemoteLink.sessionPassphrases[self.lastAttemptKey] = self.lastAttemptPassphrase
        self.lastAttemptPassphrase = None

    def remoteContext(self, remote: Remote | str, resetParams=True) -> RemoteContext:
        return RemoteLink.RemoteContext(self, remote, resetParams)

    def getPassphraseFromNetworkThread(self, keyfile: str) -> str | None:
        assert not onAppThread()

        if not isPrivateKeyPassphraseProtected(keyfile):
            return None

        try:
            return RemoteLink.sessionPassphrases[keyfile]
        except KeyError:
            pass

        loop = QEventLoop()
        result = []

        def onPassphraseReady(theKeyfile, thePassphrase):
            result.append((theKeyfile, thePassphrase))
            loop.quit()

        self.requestPassphrase.emit(keyfile, onPassphraseReady)
        loop.exec()

        resultKeyfile, resultPassphrase = result.pop()
        if resultKeyfile != keyfile:
            assert not resultKeyfile, "passphrase entered for unexpected keyfile"
            raise InterruptedError(_("Passphrase entry canceled."))

        return resultPassphrase

    def showPassphraseDialog(self, keyfile: str, callback):
        assert onAppThread()
        passphraseDialog = PassphraseDialog(findParentWidget(self), keyfile)
        passphraseDialog.passphraseReady.connect(callback)
        passphraseDialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        passphraseDialog.show()

    def formatUpdatedTipsMessage(self, header, noNewCommits=""):
        messages = [header]
        for ref in self.updatedTips:
            rb = RefPrefix.split(ref)[1]
            oldTip, newTip = self.updatedTips[ref]
            if oldTip == newTip:  # for pushing
                ps = _("{0} is already up to date with {1}.", tquo(rb), tquo(shortHash(oldTip)))
            elif oldTip == NULL_OID:
                ps = _("{0} created: {1}.", tquo(rb), shortHash(newTip))
            elif newTip == NULL_OID:
                ps = _("{0} deleted, was {1}.", tquo(rb), shortHash(oldTip))
            else:
                ps = _("{0}: {1} → {2}.", tquo(rb), shortHash(oldTip), shortHash(newTip))
            messages.append(ps)
        if not self.updatedTips:
            messages.append(noNewCommits or _("No new commits."))
        return " ".join(messages)

    @staticmethod
    def formatUpdatedTipsMessageFromGitOutput(
            updatedTips: dict[str, tuple[str, Oid, Oid]],
            header: str,
            noNewCommits="",
            skipUpToDate=False,
    ) -> str:
        messages = []
        for ref in updatedTips:
            rp, rb = RefPrefix.split(ref)
            if not rp:  # no "refs/" prefix, e.g. FETCH_HEAD, etc.
                continue
            flag, oldTip, newTip = updatedTips[ref]
            if flag == VanillaFetchStatusFlag.UpToDate:
                if skipUpToDate:
                    continue
                ps = _("{0} is already up to date with {1}.", tquo(rb), tquo(shortHash(oldTip)))
            elif flag == VanillaFetchStatusFlag.NewRef:
                ps = _("{0} created: {1}.", tquo(rb), shortHash(newTip))
            elif flag == VanillaFetchStatusFlag.PrunedRef:
                ps = _("{0} deleted, was {1}.", tquo(rb), shortHash(oldTip))
            else:  # ' ' (fast forward), '+' (forced update), '!' (error)
                ps = _("{0}: {1} → {2}.", tquo(rb), shortHash(oldTip), shortHash(newTip))
            messages.append(ps)
        if not messages:
            messages.append(noNewCommits or _("No new commits."))
        return " ".join([header] + messages)

    class RemoteContext:
        def __init__(self, remoteLink: RemoteLink, remote: Remote | str, resetParams=True):
            self.remoteLink = remoteLink
            self.remote = remote
            self.resetParams = resetParams

        def __enter__(self):
            # Reset login state before each remote (unless caller explicitly wants to keep initial parameters)
            if self.resetParams:
                self.remoteLink.resetLoginState()

            if isinstance(self.remote, Remote):
                self.remoteLink.beginRemote.emit(self.remote.name, self.remote.url)
            else:
                self.remoteLink.beginRemote.emit("", self.remote)

            # Discover key files to use for this remote
            self.remoteLink.discoverKeyFiles(self.remote)

            self.remoteLink._busy = True

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.remoteLink._busy = False
            if exc_type is None:
                self.remoteLink.rememberSuccessfulKeyFile()
