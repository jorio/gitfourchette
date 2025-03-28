# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from gitfourchette.exttools import openTerminal
from gitfourchette.localization import _
from gitfourchette.nav import NavContext, NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarNode, SidebarItem
from gitfourchette.toolbox import askConfirmation, escape, showWarning
from gitfourchette.toolbox.textutils import ulify
from gitfourchette.toolcommands import ToolCommands

if TYPE_CHECKING:
    from gitfourchette.porcelain import Repo
    from gitfourchette.repowidget import RepoWidget


class UserCommand:
    def __init__(self, rw: RepoWidget, command: str):
        self.rw = rw

        title = _("Run Command")
        tokens = ToolCommands.splitCommandTokens(command)

        replacements = {}
        errors = []
        for token in tokens:
            if not token.startswith("$"):
                continue
            try:
                callback = getattr(self, f"_token_{token[1:]}", None)
                if callback is None:
                    raise KeyError(_("Unknown placeholder token"))
                replacements[token] = callback()
            except Exception as exc:
                errors.append(f"{escape(str(exc))} (<b>{escape(token)}</b>)")

        if errors:
            showWarning(rw, title,
                        f"<p><tt>{escape(command)}</tt></p>" +
                        _("The prerequisites for your command are not met:") + ulify(errors))
            return

        tokens = ToolCommands.injectReplacements(tokens, replacements)
        command = shlex.join(tokens)

        question = _("Do you want to run this command in a terminal?") + f"<p><tt>{escape(command)}</tt></p>"
        askConfirmation(rw, title, question,
                        callback=lambda: openTerminal(rw, self.repo.workdir, command))

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

    def _token_WORKDIR(self):
        return self.repo.workdir

    def _token_COMMIT(self) -> str:
        locator = self.locator
        if locator.context != NavContext.COMMITTED:
            raise ValueError(_("A commit must be selected in the history"))
        return str(locator.commit)

    def _token_HEAD(self) -> str:
        repo = self.repo
        if repo.head_is_unborn:
            raise ValueError(_("HEAD cannot be unborn"))
        return str(repo.head_commit_id)

    def _token_SELBRANCH(self) -> str:
        sidebarNode = self.sidebarNode
        if sidebarNode.kind != SidebarItem.LocalBranch:
            raise ValueError(_("A local branch must be selected in the sidebar"))
        return sidebarNode.data

    def _token_CURBRANCH(self) -> str:
        repo = self.repo
        if repo.head_is_unborn or repo.head_is_detached:
            raise ValueError(_("HEAD cannot be unborn or detached"))
        return repo.head_branch_fullname

    def _token_FILE(self) -> str:
        locator = self.locator
        if not locator.path:
            raise ValueError(_("A file must be selected"))
        return self.repo.in_workdir(locator.path)

    def _token_FILEDIR(self) -> str:
        path = Path(self._token_FILE())
        return str(path.parent)

    @staticmethod
    def tokenHelpTable():
        return {
            "WORKDIR"   : _("Absolute path to the repository’s working directory"),
            "COMMIT"    : _("SHA-1 hash of the selected commit in the history"),
            "HEAD"      : _("SHA-1 hash of the HEAD commit"),
            "SELBRANCH" : _("Full ref name of the selected local branch in the sidebar"),
            "CURBRANCH" : _("Full ref name of the checked-out local branch"),
            "FILE"      : _("Absolute path to the selected file"),
            "FILEDIR"   : _("Absolute path to the selected file’s parent directory"),
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

            yield command, comment
