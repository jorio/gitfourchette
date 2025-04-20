# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import enum
import shlex
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from gitfourchette import pycompat  # noqa: F401 - StrEnum for Python 3.10
from gitfourchette import settings
from gitfourchette.localization import _, _p
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import RefPrefix, split_remote_branch_shorthand
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.toolbox import escamp
from gitfourchette.toolcommands import ToolCommands

if TYPE_CHECKING:
    from gitfourchette.repowidget import RepoWidget


@dataclasses.dataclass
class UserCommand:
    SeparatorDash = "-"
    AlwaysConfirmPrefix = "?"

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

    class MultiTokenError(ValueError):
        tokenErrors: dict[str, Exception]

        def __init__(self, errors):
            self.tokenErrors = errors

    command: str
    userTitle: str = ""
    placeholderTokens: set[str] = dataclasses.field(default_factory=set)
    isSeparator: bool = False
    shortcut: str = ""
    alwaysConfirm: bool = False

    def menuTitle(self) -> str:
        if not self.userTitle:
            title = escamp(self.command)
        else:
            # Don't escamp the user-defined title!
            # Let them define their own accelerator keys.
            title = self.userTitle

        # Qt interprets tabs as separators for keyboard shortcuts.
        # QTextEdit may insert tabs in commands, so override those.
        title = title.replace('\t', ' ')

        if self.alwaysConfirm or settings.prefs.confirmCommands:
            title += "\u2026"  # Add ellipsis character

        return title

    def menuToolTip(self) -> str:
        return self.command if not self.userTitle else ""

    def matchesContext(self, tokenSet: set[str]):
        if self.isSeparator:
            return False
        return any(t in tokenSet for t in self.placeholderTokens)

    def compile(self, context: RepoWidget) -> str:
        tokens = ToolCommands.splitCommandTokens(self.command)
        placeholders = set(ToolCommands.findPlaceholderTokens(tokens))

        replacements = {}
        errors = {}
        for token in placeholders:
            assert token.startswith("$")
            try:
                try:
                    internalIdentifier = UserCommand.Token(token)
                except ValueError as unknownTokenError:
                    raise KeyError(_("Unknown placeholder token")) from unknownTokenError
                callback = getattr(self, f"eval{internalIdentifier.name}")
                replacements[token] = callback(context)
            except Exception as exc:
                errors[token] = exc
                traceback.print_exc()

        if errors:
            raise UserCommand.MultiTokenError(errors)

        tokens = ToolCommands.injectReplacements(tokens, replacements)
        command = shlex.join(tokens)
        return command

    @classmethod
    def evalWorkdir(cls, context: RepoWidget):
        repo = context.repo
        return repo.workdir

    @classmethod
    def evalCommit(cls, context: RepoWidget) -> str:
        repo = context.repo
        locator = context.navLocator

        if locator.context != NavContext.COMMITTED:
            raise ValueError(_("A commit must be selected in the history"))
        commit = repo[locator.commit]
        return str(commit.short_id)

    @classmethod
    def evalHead(cls, context: RepoWidget) -> str:
        repo = context.repo

        if repo.head_is_unborn:
            raise ValueError(_("HEAD cannot be unborn"))
        commit = repo.head_commit
        return str(commit.short_id)

    @classmethod
    def evalRef(cls, context: RepoWidget) -> str:
        sidebarNode = context.sidebar.getValidNode()

        refKinds = {
            SidebarItem.LocalBranch,
            SidebarItem.RemoteBranch,
            SidebarItem.Tag,
        }

        if sidebarNode.kind not in refKinds:
            raise ValueError(_("A ref (local branch, remote branch, or tag) must be selected in the sidebar"))
        return sidebarNode.data

    @classmethod
    def evalHeadBranch(cls, context: RepoWidget) -> str:
        repo = context.repo
        if repo.head_is_unborn or repo.head_is_detached:
            raise ValueError(_("HEAD cannot be unborn or detached"))
        return repo.head_branch_fullname

    @classmethod
    def evalHeadUpstream(cls, context: RepoWidget) -> str:
        repo = context.repo
        if repo.head_is_unborn or repo.head_is_detached:
            raise ValueError(_("HEAD cannot be unborn or detached"))
        branch = repo.branches.local[repo.head_branch_shorthand]
        try:
            return branch.upstream_name
        except KeyError as exc:
            raise ValueError(_("Current branch has no upstream")) from exc

    @classmethod
    def evalFile(cls, context: RepoWidget) -> str:
        locator = context.navLocator
        if not locator.path:
            raise ValueError(_("A file must be selected"))
        return locator.path

    @classmethod
    def evalFileAbs(cls, context: RepoWidget) -> str:
        repo = context.repo
        return repo.in_workdir(cls.evalFile(context))

    @classmethod
    def evalFileDir(cls, context: RepoWidget) -> str:
        path = Path(cls.evalFile(context))
        return str(path.parent)

    @classmethod
    def evalFileDirAbs(cls, context: RepoWidget) -> str:
        path = Path(cls.evalFileAbs(context))
        return str(path.parent)

    @classmethod
    def evalRemote(cls, context: RepoWidget) -> str:
        node = context.sidebar.getValidNode()
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

    @classmethod
    def parseCommandBlock(cls, commandBlock: str):
        fKey = 6

        for line in commandBlock.splitlines(keepends=False):
            split = line.split("#", 1)

            if len(split) == 1:
                command = line
                comment = ""
            else:
                command, comment = split

            command = command.strip()
            comment = comment.strip()

            if not command:
                # If the comment is all dashes, that's a separator
                if comment and comment == cls.SeparatorDash * len(comment):
                    yield UserCommand("", isSeparator=True)
                continue

            # Force confirmation prompt?
            alwaysConfirm = command.startswith(cls.AlwaysConfirmPrefix)
            if alwaysConfirm:
                command = command.removeprefix(cls.AlwaysConfirmPrefix).strip()

            # Find placeholder tokens
            tokens = ToolCommands.splitCommandTokens(command)
            placeholders = set(ToolCommands.findPlaceholderTokens(tokens))

            # Find shortcut
            shortcut = f"F{fKey}" if fKey <= 12 else ""
            fKey += 1

            yield UserCommand(
                command=command,
                userTitle=comment,
                placeholderTokens=placeholders,
                shortcut=shortcut,
                alwaysConfirm=alwaysConfirm)
