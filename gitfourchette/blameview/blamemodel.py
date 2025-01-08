# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from pygit2 import Blame

from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.trace import TraceNode


@dataclasses.dataclass
class BlameModel:
    repoModel: RepoModel
    trace: list[TraceNode]
    blame: dict[Oid, Blame]
    commitId: Oid = NULL_OID

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def currentBlame(self) -> Blame:
        return self.blame[self.commitId]

