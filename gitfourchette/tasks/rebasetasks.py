# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import logging
from contextlib import suppress
from pathlib import Path

from gitfourchette.forms.rebasedialog import RebaseDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from gitfourchette.localization import _
from gitfourchette.nav import NavLocator, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.ipc.ipcserver import GFIpcServer
from gitfourchette.qt import *
from gitfourchette.rebase.editmsgautofillserver import EditmsgAutoFillServer
from gitfourchette.rebase.rebasemodel import RebaseInfo, RebaseLine, RebaseOp, RebasePlan
from gitfourchette.tasks.repotask import TaskPrereqs, TaskEffects
from gitfourchette.tasks.repotask import RepoTask, AbortTask
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

_StandardRebaseTaskEffects = TaskEffects.Head | TaskEffects.Workdir

# Magic messages passed via git's stderr from the socket callback function to
# the RepoTask's main coroutine.
_AbortMagicOK = "InteractiveRebaseAbortMagicOK"
_AbortMagicNoop = "InteractiveRebaseAbortMagicNoop"
_AbortMagicToctou = "InteractiveRebaseAbortMagicToctou"


class InteractiveRebase(RepoTask):
    def prereqs(self):
        return TaskPrereqs.NoChanges | TaskPrereqs.NoUnborn | TaskPrereqs.NoCherrypick

    def flow(self, ontoCommit: Oid):
        if self.rw.findChild(RebaseDialog):
            raise AbortTask(_("Please conclude the current rebase before starting a new one."))

        headName = self.repo.head_branch_shorthand
        headCommit = self.repo.head_commit_id

        if headCommit == ontoCommit:
            message = paragraphs(_("No rebase is necessary."),
                                 _("{0} already points to {1}.")
                                 ).format(bquo(headName), bquo(shortHash(headCommit)))
            raise AbortTask(message, icon="information")

        sequenceServer = GFIpcServer(self, singleShot=True, startNow=True)
        sequenceServer.clientConnected.connect(self.onClientConnected)

        self.epilog.effects |= _StandardRebaseTaskEffects

        driver = yield from self.flowCallGit(
            "-c", "core.abbrev=no",
            "rebase", "-i", str(ontoCommit),
            env={
                "GIT_SEQUENCE_EDITOR": sequenceServer.clientCommand(),
            },
            autoFail=False)

        # Back from onClientConnected.
        # We expect `rebase -i` to fail with one of our magic strings.
        # If it failed for any other reason, show Git error message.
        stderr = driver.stderrScrollback()

        if _AbortMagicOK in stderr:
            pass
        elif _AbortMagicNoop in stderr:
            yield from self.confirmNoopRebase(headName, headCommit, ontoCommit)
        else:
            raise AbortTask.fromGitError(driver)

    def onClientConnected(self, handshake: GFIpcProtocol.Handshake, socket: QLocalSocket):
        abortPayload = _AbortMagicOK

        try:
            self.hideProcessProgress.emit(True)

            path = handshake.args[0]
            assert Path(path).samefile(self.repo.in_gitdir("rebase-merge/git-rebase-todo"))

            info = RebaseInfo.parse(self.repo.path)

            if not info.todoSeq:
                abortPayload = _AbortMagicNoop
                return

            # Verify lines with "# empty"
            for item in info.todoSeq:
                if item.originalComment.endswith(RebaseLine.EmptyCommitSuffix):
                    with suppress(ValueError, LookupError):
                        commit = self.repo[item.hexHash].peel(Commit)
                        if commit.tree_id == commit.parents[0].tree_id:
                            item.verifiedEmpty = True

            plan = RebasePlan(info.todoSeq, headName=info.headName, origHead=info.origHead, onto=info.onto)

            # Insert fake 'start' line
            ontoCommit = self.repo.peel_commit(plan.onto)
            ontoCommitMessage, _dummy = messageSummary(ontoCommit.message, "")
            start = RebaseLine(RebaseOp.FakeStart, str(plan.onto), ontoCommitMessage)
            sequence = [start] + plan.sequence

            dialog = RebaseDialog(sequence, self.parentWidget())
            dialog.setWindowTitle("[*]" + _("Rebasing {0} onto {1}", tquoe(info.headShorthand), tquo(shortHash(info.onto))))
            dialog.accepted.connect(lambda: self.executeRebase(plan, dialog))
            dialog.exploreCommit.connect(self.rw.jump)
            dialog.show()
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        except Exception as ex:
            # Switch to non-graceful abort
            abortPayload = f"{self.__class__.__name__} failed: {ex.__class__.__name__}: {ex}"

        finally:
            # Bail from `rebase -i` until the dialog is accepted
            # Exit GIT_SEQUENCE_EDITOR with non-0 return code, causing `git rebase` to fail
            GFIpcProtocol.respondAndBail(socket, abort=abortPayload)

    def executeRebase(self, oldPlan: RebasePlan, dialog: RebaseDialog):
        """ Run when RebaseDialog is accepted. """
        newSequence = dialog.ui.sequence.effectiveSequence()
        newPlan = dataclasses.replace(oldPlan, sequence=newSequence)
        ExecuteRebase.invoke(dialog, oldPlan, newPlan, dialog.rebaseExtraArgs())

    def confirmNoopRebase(self, headName: str, headCommit: Oid, ontoCommit: Oid):
        message = paragraphs(
            _("There’s nothing to rebase. All commits from {0} are already in the other branch."),
            _("If you continue, this will amount to resetting {0} to {1}.")
        ).format(bquo(headName), bquo(shortHash(ontoCommit)))
        yield from self.flowConfirm(text=message, verb=_("Continue"))

        # Make sure the head didn't change while user was reading the message
        if self.repo.head_branch_shorthand != headName or self.repo.head_commit_id != headCommit:
            raise AbortTask(_toctouErrorText(headName, headCommit))

        driver = yield from self.flowCallGit("rebase", str(ontoCommit))
        _debriefRebase(self, driver, headName, headCommit, ontoCommit)


class ExecuteRebase(RepoTask):
    def prereqs(self):
        # TODO: need clean workdir, too
        return TaskPrereqs.NoConflicts | TaskPrereqs.NoUnborn | TaskPrereqs.NoCherrypick

    def flow(self, oldPlan: RebasePlan, newPlan: RebasePlan, extraArgs: set[str]):
        self.oldPlan = oldPlan
        self.newPlan = newPlan

        sequenceServer = GFIpcServer(self, singleShot=True, startNow=True)
        sequenceServer.clientConnected.connect(self.onClientConnected)

        self.epilog.effects |= _StandardRebaseTaskEffects
        driver = yield from self.flowCallGit(
            "-c", "core.abbrev=no",
            "rebase", "-i", str(newPlan.onto),
            *extraArgs,
            env={
                "GIT_SEQUENCE_EDITOR": sequenceServer.clientCommand(),
                "GIT_EDITOR": EditmsgAutoFillServer(self).clientCommand(),
            },
            autoFail=False,
        )

        _debriefRebase(self, driver, oldPlan.headShorthand, oldPlan.origHead, oldPlan.onto)

    def onClientConnected(self, handshake: GFIpcProtocol.Handshake, socket: QLocalSocket):
        path = handshake.args[0]
        abortPayload = "Aborting Rebase"

        try:
            self.epilog.effects |= TaskEffects.Head

            assert Path(path).samefile(self.repo.in_gitdir("rebase-merge/git-rebase-todo"))

            info = RebaseInfo.parse(self.repo.path)
            oldPlan2 = RebasePlan(info.todoSeq, headName=info.headName, origHead=info.origHead, onto=info.onto)
            if oldPlan2 != self.oldPlan:
                abortPayload = _AbortMagicToctou
                return

            # Dump new todo
            sequenceText = self.newPlan.serializeSequence()
            Path(path).write_text(sequenceText, encoding="utf-8")
            abortPayload = ""  # success
        finally:
            # Close socket, causing rebase to start executing our sequence
            GFIpcProtocol.respondAndBail(socket, abort=abortPayload)


class AbortRebase(RepoTask):
    def flow(self):
        assert self.repo.state() in [
            RepositoryState.REBASE,
            RepositoryState.REBASE_INTERACTIVE,
            RepositoryState.REBASE_MERGE,
        ], f"attempting to abort non-rebase state {self.repo.state()}"

        info = RebaseInfo.parse(self.repo.path)

        yield from self.flowConfirm(
            text=paragraphs(
                _("Do you want to abort the ongoing rebase of {0} onto {1}?",
                  tquoe(info.headShorthand),
                  tquoe(shortHash(info.onto, maybe=True)),
                  ),

                _("Aborting will <b>clear all changes in the working directory</b>, and branch {0} will move back to {1}.",
                  tquoe(info.headShorthand),
                  tquoe(shortHash(info.origHead, maybe=True)),
                  ),
            ),
        )

        self.epilog.effects |= _StandardRebaseTaskEffects
        yield from self.flowCallGit("rebase", "--abort")

        self.epilog.status = _("Rebase aborted.")


class ContinueRebase(RepoTask):
    def flow(self):
        assert self.repo.state() == RepositoryState.REBASE_INTERACTIVE, \
            f"attempting to continue from state {self.repo.state()}"

        rebaseInfoAtStart = RebaseInfo.parse(self.repo.path)

        self.epilog.effects |= _StandardRebaseTaskEffects

        # We need GIT_EDITOR to confirm the commit message:
        # - for commits marked 'reword' (fill in message from the payload we
        #   added to the todo file)
        # - after fixing conflicts (just leave message intact)
        driver = yield from self.flowCallGit(
            "rebase", "--continue",
            env={
                "GIT_EDITOR": EditmsgAutoFillServer(self).clientCommand(),
            },
            autoFail=False,
        )

        _debriefRebase(self, driver, rebaseInfoAtStart.headShorthand, rebaseInfoAtStart.origHead, rebaseInfoAtStart.onto)


def _toctouErrorText(headName: str, headCommit: Oid):
    return paragraphs(
        _("Cannot apply this rebase plan."),
        _("The repository isn’t on the same branch/commit as when you started rebasing."),
        _("The plan was made when branch {0} was checked out, and its head was at commit {1}.",
          bquo(headName),
          bquo(shortHash(headCommit)),
          ),
    )


def _debriefRebase(task: RepoTask, driver: GitDriver, headName: str, headCommit: Oid, ontoCommit: Oid):
    exitCode = driver.exitCode()
    unknownFailure = exitCode not in [0, 1]

    if exitCode == 1:
        stderr = driver.stderrScrollback().strip()

        if stderr == "error: nothing to do":
            # Canceled from dialog, bail quietly
            raise AbortTask()

        if _AbortMagicToctou in stderr:
            raise AbortTask(_toctouErrorText(headName, headCommit))

        stdout = driver.stdoutScrollback()
        logger.debug(f"git rebase stdout: {stdout}")

        if "CONFLICT" in stdout:
            task.epilog.jumpTo = NavLocator.inUnstaged().withExtraFlags(NavFlags.SelectAnyConflict)
        else:
            unknownFailure = True

    if unknownFailure:
        # Bail loudly
        raise AbortTask.fromGitError(driver)

    state = task.repo.state()

    if state == RepositoryState.NONE:
        status = _("Finished rebasing {0} onto {1}.", tquoe(headName), tquo(shortHash(ontoCommit)))
    else:
        status = _("Rebase stopped. Your input is needed to continue.")

    task.epilog.status = status
