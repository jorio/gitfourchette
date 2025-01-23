# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.trace import Trace, Blame, BlameCollection
from gitfourchette.qt import *


class BlameModel:
    taskInvoker: QWidget
    repoModel: RepoModel
    trace: Trace
    blameCollection: BlameCollection
    commitId: Oid
    currentBlame: Blame

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo
