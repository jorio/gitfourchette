# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.nav import NavContext, NavLocator
from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.trace import Trace, TraceNode, Blame, BlameCollection
from gitfourchette.qt import *


class BlameModel:
    taskInvoker: QWidget
    repoModel: RepoModel
    trace: Trace
    blameCollection: BlameCollection
    currentTraceNode: TraceNode
    currentBlame: Blame

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def currentLocator(self) -> NavLocator:
        return BlameModel.locatorFromTraceNode(self.currentTraceNode)

    @staticmethod
    def locatorFromTraceNode(node) -> NavLocator:
        isWorkdir = node.commitId == UC_FAKEID
        return NavLocator(
            context=NavContext.WORKDIR if isWorkdir else NavContext.COMMITTED,
            commit=node.commitId,
            path=node.path)
