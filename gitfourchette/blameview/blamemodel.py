# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.trace import Trace, Blame, BlameCollection


@dataclasses.dataclass
class BlameModel:
    repoModel: RepoModel
    trace: Trace
    blameCollection: BlameCollection
    commitId: Oid = NULL_OID
    currentBlame: Blame = dataclasses.field(default_factory=Blame)

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo
