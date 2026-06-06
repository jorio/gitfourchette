# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
from collections.abc import Callable, Generator
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import RepoTask, AbortTask, FlowControlToken
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class NewRepo(RepoTask):
    def flow(self, openRepo: Callable[[str], None]):
        fileDialog = PersistentFileDialog.saveFile(self.parentWidget(), "NewRepo", _("New repository"))
        fileDialog.setFileMode(QFileDialog.FileMode.Directory)
        fileDialog.setLabelText(QFileDialog.DialogLabel.Accept, _("&Create repo here"))
        fileDialog.setWindowModality(Qt.WindowModality.WindowModal)
        pathStr = yield from self.flowFileDialog(fileDialog)
        path = Path(pathStr)

        # macOS's native file picker may return a directory that doesn't exist yet
        # (it expects us to create it ourselves). "git rev-parse" won't detect the
        # parent repo if the directory doesn't exist.
        parentDetectionPath = path if path.exists() else path.parent

        # Discover parent repo. If found, ask user if they want to open the
        # parent repo or create a subrepo inside it.
        revParse = yield from self.flowCallGit(
            "rev-parse",
            "--show-toplevel",
            workdir=str(parentDetectionPath),
            autoFail=False)

        if revParse.exitCode() == 0:
            parentPathStr = revParse.stdoutScrollback().rstrip()
            parentPath = Path(parentPathStr)
            parentWorkdir = parentPath.parent if parentPath.name == ".git" else parentPath
            wantOpen = yield from self._confirmOpenParentRepo(path, parentPath, parentWorkdir)
            if wantOpen:
                openRepo(str(parentWorkdir))
                raise AbortTask()

        # Confirm whether to create .git in existing source tree (non-empty directory)
        if path.exists() and any(path.iterdir()):
            message = _("Are you sure you want to initialize a Git repository in {0}? "
                        "This directory isn’t empty.", bquo(str(path)))
            yield from self.flowConfirm(
                title=_("Directory isn’t empty"),
                text=message,
                verb=_("&Create repo here"),
                icon="warning")

        yield from self.flowCallGit("init", "--", str(path))
        openRepo(str(path))

    def _confirmOpenParentRepo(
            self,
            path: Path,
            parentPath: Path,
            parentWorkdir: Path
    ) -> Generator[FlowControlToken, None, bool]:
        """
        If the user is attempting to initialize a repo nested inside a parent
        repo, ask them if they'd rather open the parent repo.
        Return True to open the parent repo, False to create a nested repo.
        """

        path = path.resolve()
        parentPath = parentPath.resolve()
        parentWorkdir = parentWorkdir.resolve()

        if parentPath == path or parentWorkdir == path:
            message = paragraphs(
                _("A repository already exists here:"),
                escape(compactPath(parentWorkdir)))
            yield from self.flowConfirm(
                title=_("Repository already exists"),
                text=message,
                verb=_("&Open existing repo"),
                buttonIcon="SP_DirOpenIcon")
            wantOpen = True

        else:
            displayParentName = parentWorkdir.name
            displayName = path.name
            displayPath = compactPath(path)
            commonLength = len(os.path.commonprefix([displayPath, compactPath(parentWorkdir)]))
            i1 = commonLength - len(displayParentName)
            i2 = commonLength
            dp1 = escape(displayPath[: i1])
            dp2 = escape(displayPath[i1: i2])
            dp3 = escape(displayPath[i2:])
            muted = mutedTextColorHex(self.parentWidget())
            prettyPath = (f"<div style='white-space: pre;'>"
                          f"<span style='color: {muted};'>{dp1}</span>"
                          f"<b>{dp2}</b>"
                          f"<span style='color: {muted};'>{dp3}</span></div>")

            message = paragraphs(
                _("An existing repository, {0}, was found in a parent folder "
                  "of this location:", bquoe(displayParentName)),
                prettyPath,
                _("Are you sure you want to create {0} within the existing "
                  "repo?", hquoe(displayName)))

            createButton = QPushButton(_("&Create {0}", lquoe(displayName)))

            result = yield from self.flowConfirm(
                title=_("Repository found in parent folder"),
                text=message,
                verb=_("&Open {0}", lquoe(displayParentName)),
                buttonIcon="SP_DirOpenIcon",
                actionButton=createButton)

            # OK button is Open; Create is the other one. (Cancel would have aborted early.)
            # Also checking for Accepted so that unit tests can do qmb.accept().
            wantOpen = result in [QMessageBox.StandardButton.Ok, QDialog.DialogCode.Accepted]

        return wantOpen
