# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import enum
import shlex
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from gitfourchette import pycompat  # noqa: F401 - StrEnum for Python 3.10
from gitfourchette import settings
from gitfourchette.exttools import openTerminal
from gitfourchette.localization import _, _p
from gitfourchette.nav import NavContext, NavLocator
from gitfourchette.porcelain import Repo, RefPrefix, split_remote_branch_shorthand
from gitfourchette.sidebar.sidebarmodel import SidebarNode, SidebarItem
from gitfourchette.toolbox import askConfirmation, escape, showWarning
from gitfourchette.toolbox.textutils import ulify
from gitfourchette.toolcommands import ToolCommands

if TYPE_CHECKING:
    from gitfourchette.repowidget import RepoWidget


class UserCommand:
    class Token(enum.StrEnum):
        Commit          = "$COMMIT"
        File            = "$FILE"
        FileAbs         = "$FILEABS"
        FileDir         = "$FILEDIR"
        FileDirAbs      = "$FILEDIRABS"
        Head            = "$HEAD"
        HeadBranch      = "$HEADBRANCH"
        HeadUpstream    = "$HEADUPSTREAM"
        Ref             = "$REF"
        Remote          = "$REMOTE"
        Workdir         = "$WORKDIR"

    def __init__(self, rw: RepoWidget, command: str):
        self.rw = rw

        title = _("Run Command")
        tokens = ToolCommands.splitCommandTokens(command)

        placeholders = set(ToolCommands.findPlaceholderTokens(tokens))
        replacements = {}
        errors = []
        for token in placeholders:
            assert token.startswith("$")
            try:
                try:
                    internalIdentifier = UserCommand.Token(token)
                except ValueError as unknownTokenError:
                    raise KeyError(_("Unknown placeholder token")) from unknownTokenError
                callback = getattr(self, f"eval{internalIdentifier.name}")
                replacements[token] = callback()
            except Exception as exc:
                errors.append(f"{escape(str(exc))} (<b>{escape(token)}</b>)")
                traceback.print_exc()

        if errors:
            showWarning(rw, title,
                        f"<p><tt>{escape(command)}</tt></p>" +
                        _("The prerequisites for your command are not met:") + ulify(errors))
            return

        tokens = ToolCommands.injectReplacements(tokens, replacements)
        command = shlex.join(tokens)

        def run():
            openTerminal(rw, self.repo.workdir, command)

        if settings.prefs.confirmRunCommand:
            question = _("Do you want to run this command in a terminal?") + f"<p><tt>{escape(command)}</tt></p>"
            askConfirmation(rw, title, question, callback=run)
        else:
            run()

    @property
    def repo(self) -> Repo:
        return self.rw.repoModel.repo

    @property
    def locator(self) -> NavLocator:
        return self.rw.navLocator

    @property
    def sidebarNode(self) -> SidebarNode:
        sidebarIndex = self.rw.sidebar.currentIndex()
        return SidebarNode.fromIndex(sidebarIndex)

    def evalWorkdir(self):
        return self.repo.workdir

    def evalCommit(self) -> str:
        locator = self.locator
        if locator.context != NavContext.COMMITTED:
            raise ValueError(_("A commit must be selected in the history"))
        commit = self.repo[locator.commit]
        return str(commit.short_id)

    def evalHead(self) -> str:
        if self.repo.head_is_unborn:
            raise ValueError(_("HEAD cannot be unborn"))
        commit = self.repo.head_commit
        return str(commit.short_id)

    def evalRef(self) -> str:
        refKinds = {
            SidebarItem.LocalBranch,
            SidebarItem.RemoteBranch,
            SidebarItem.Tag,
        }

        sidebarNode = self.sidebarNode
        if sidebarNode.kind not in refKinds:
            raise ValueError(_("A ref (local branch, remote branch, or tag) must be selected in the sidebar"))
        return sidebarNode.data

    def evalHeadBranch(self) -> str:
        repo = self.repo
        if repo.head_is_unborn or repo.head_is_detached:
            raise ValueError(_("HEAD cannot be unborn or detached"))
        return repo.head_branch_fullname

    def evalHeadUpstream(self) -> str:
        repo = self.repo
        if repo.head_is_unborn or repo.head_is_detached:
            raise ValueError(_("HEAD cannot be unborn or detached"))
        branch = repo.branches.local[repo.head_branch_shorthand]
        try:
            return branch.upstream_name
        except KeyError as exc:
            raise ValueError(_("Current branch has no upstream")) from exc

    def evalFile(self) -> str:
        locator = self.locator
        if not locator.path:
            raise ValueError(_("A file must be selected"))
        return locator.path

    def evalFileAbs(self) -> str:
        return self.repo.in_workdir(self.evalFile())

    def evalFileDir(self) -> str:
        path = Path(self.evalFile())
        return str(path.parent)

    def evalFileDirAbs(self) -> str:
        path = Path(self.evalFileAbs())
        return str(path.parent)

    def evalRemote(self) -> str:
        node = self.sidebarNode
        if node.kind == SidebarItem.Remote:
            return node.data
        elif node.kind == SidebarItem.RemoteBranch:
            _prefix, shorthand = RefPrefix.split(node.data)
            remoteName, _branch = split_remote_branch_shorthand(shorthand)
            return remoteName
        raise ValueError(_("A remote or a remote branch must be selected"))

    @staticmethod
    def tokenHelpTable():
        Token = UserCommand.Token
        relSuffix = " " + _p("relative path", "(relative)")
        absSuffix = " " + _p("absolute path", "(absolute)")
        return {
            Token.Commit        : _("Hash of the selected commit in the history"),
            Token.File          : _("Path to the selected file") + relSuffix,
            Token.FileAbs       : _("Path to the selected file") + absSuffix,
            Token.FileDir       : _("Path to the selected file’s parent directory") + relSuffix,
            Token.FileDirAbs    : _("Path to the selected file’s parent directory") + absSuffix,
            Token.Head          : _("Hash of the HEAD commit"),
            Token.HeadBranch    : _("Ref name of the HEAD branch"),
            Token.HeadUpstream  : _("Ref name of the HEAD branch’s upstream"),
            Token.Ref           : _("Name of the selected ref in the sidebar (local branches, remote branches, tags)"),
            Token.Remote        : _("Name of the selected remote in the sidebar"),
            Token.Workdir       : _("Path to the repository’s working directory") + absSuffix,
        }

    @staticmethod
    def parseCommandBlock(commands: str):
        for line in commands.splitlines(keepends=False):
            split = line.split("#", 1)

            if len(split) == 1:
                command = line
                comment = command
            else:
                command, comment = split

            command = command.strip()
            comment = comment.strip() or command

            if not command:
                continue

            # Find placeholder tokens
            tokens = ToolCommands.splitCommandTokens(command)
            placeholders = set(ToolCommands.findPlaceholderTokens(tokens))

            yield command, comment, placeholders
