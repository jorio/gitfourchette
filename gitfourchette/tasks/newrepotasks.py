# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
from collections.abc import Callable

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import RepoTask, AbortTask
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class NewRepo(RepoTask):
    def flow(self, openRepo: Callable[[str], None]):
        fileDialog = PersistentFileDialog.saveFile(self.parentWidget(), "NewRepo", _("New repository"))
        fileDialog.setFileMode(QFileDialog.FileMode.Directory)
        fileDialog.setLabelText(QFileDialog.DialogLabel.Accept, _("&Create repo here"))
        fileDialog.setWindowModality(Qt.WindowModality.WindowModal)
        path = yield from self.flowFileDialog(fileDialog)

        # macOS's native file picker may return a directory that doesn't exist yet
        # (it expects us to create it ourselves). "git rev-parse" won't detect the
        # parent repo if the directory doesn't exist.
        parentDetectionPath = path
        if not os.path.exists(parentDetectionPath):
            parentDetectionPath = os.path.dirname(parentDetectionPath)

        # Discover parent repo. If found, ask user if they want to open the
        # parent repo or create a subrepo inside it.
        revParse = yield from self.flowCallGit("rev-parse", "--show-toplevel", workdir=parentDetectionPath, autoFail=False)
        if revParse.exitCode() == 0:
            parentPath = revParse.stdoutScrollback().rstrip()
            yield from self._confirmCreateSubrepo(path, parentPath, openRepo)

        # Ask if user wants to create .git in an existing source tree
        if os.path.exists(path) and os.listdir(path):
            message = _("Are you sure you want to initialize a Git repository in {0}? "
                        "This directory isn’t empty.", bquo(path))
            yield from self.flowConfirm(title=_("Directory isn’t empty"), text=message, icon="warning")

        yield from self.flowCallGit("init", "--", path)
        openRepo(path)

    def _confirmCreateSubrepo(self, path: str, parentPath: str, openRepo: Callable[[str], None]):
        assert parentPath
        myBasename = os.path.basename(path)

        parentPath = os.path.normpath(parentPath)
        parentWorkdir = os.path.dirname(parentPath) if os.path.basename(parentPath) == ".git" else parentPath
        parentBasename = os.path.basename(parentWorkdir)

        if parentPath == path or parentWorkdir == path:
            yield from self.flowConfirm(
                title=_("Repository already exists"),
                text=paragraphs(_("A repository already exists here:"), escape(compactPath(parentWorkdir))),
                verb=_("&Open existing repo"),
                buttonIcon="SP_DirOpenIcon")
            wantOpen = True

        else:
            displayPath = compactPath(path)
            commonLength = len(os.path.commonprefix([displayPath, compactPath(parentWorkdir)]))
            i1 = commonLength - len(parentBasename)
            i2 = commonLength
            dp1 = escape(displayPath[: i1])
            dp2 = escape(displayPath[i1: i2])
            dp3 = escape(displayPath[i2:])
            muted = mutedTextColorHex(self)
            prettyPath = (f"<div style='white-space: pre;'>"
                          f"<span style='color: {muted};'>{dp1}</span>"
                          f"<b>{dp2}</b>"
                          f"<span style='color: {muted};'>{dp3}</span></div>")

            message = paragraphs(
                _("An existing repository, {0}, was found in a parent folder of this location:", bquoe(parentBasename)),
                prettyPath,
                _("Are you sure you want to create {0} within the existing repo?", hquoe(myBasename)))

            createButton = QPushButton(_("&Create {0}", lquoe(myBasename)))
            createButton.clicked.connect(lambda: self.newRepo(path, detectParentRepo=False))

            result = yield from self.flowConfirm(
                title=_("Repository found in parent folder"),
                text=message,
                verb=_("&Open {0}", lquoe(parentBasename)),
                buttonIcon="SP_DirOpenIcon")

            # OK button is Open; Create is the other one. (Cancel would have aborted early.)
            # Also checking for Accepted so that unit tests can do qmb.accept().
            wantOpen = result in [QMessageBox.StandardButton.Ok, QDialog.DialogCode.Accepted]

        if wantOpen:
            openRepo(parentWorkdir)
            raise AbortTask()
