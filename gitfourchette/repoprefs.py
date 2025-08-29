# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Manage proprietary settings in a repository's .git/config and .git/gitfourchette.json.
"""

from dataclasses import dataclass, field

from gitfourchette.appconsts import *
from gitfourchette.forms.signatureform import SignatureOverride
from gitfourchette.porcelain import *
from gitfourchette.settings import RefSort
from gitfourchette.prefsfile import PrefsFile


@dataclass
class RepoPrefs(PrefsFile):
    _filename = f"{APP_SYSTEM_NAME}.json"
    _allowMakeDirs = False
    _parentDir = ""

    _GitConfigShadowUpstreamKey = f"{APP_SYSTEM_NAME}-shadow-remote"

    _repo: Repo
    draftCommitMessage: str = ""
    draftCommitSignature: Signature | None = None
    draftCommitSignatureOverride: SignatureOverride = SignatureOverride.Nothing
    draftAmendMessage: str = ""
    hidePatterns: set = field(default_factory=set)
    showPatterns: set = field(default_factory=set)
    collapseCache: set = field(default_factory=set)
    sortBranches: RefSort = RefSort.UseGlobalPref
    sortRemoteBranches: RefSort = RefSort.UseGlobalPref
    sortTags: RefSort = RefSort.UseGlobalPref
    refSortClearTimestamp: int = 0
    customKeyFile: str = ""

    @classmethod
    def initForRepo(cls, repo: Repo):
        repoPrefs = cls(repo)
        repoPrefs._parentDir = repo.path
        repoPrefs.load()
        return repoPrefs

    def getParentDir(self):
        return self._parentDir

    def hasDraftCommit(self):
        return self.draftCommitMessage or self.draftCommitSignatureOverride != SignatureOverride.Nothing

    def clearDraftCommit(self):
        self.draftCommitMessage = ""
        self.draftCommitSignature = None
        self.draftCommitSignatureOverride = SignatureOverride.Nothing
        self.setDirty()

    def clearDraftAmend(self):
        self.draftAmendMessage = ""
        self.setDirty()

    def clearRefSort(self):
        self.sortBranches = RefSort.UseGlobalPref
        self.sortRemoteBranches = RefSort.UseGlobalPref
        self.sortTags = RefSort.UseGlobalPref
        self.refSortClearTimestamp = 0
        self.setDirty()

    def getShadowUpstream(self, localBranchName: str):
        return self._repo.get_config_value(("branch", localBranchName, self._GitConfigShadowUpstreamKey))

    def setShadowUpstream(self, localBranchName: str, upstreamName: str):
        self._repo.set_config_value(("branch", localBranchName, self._GitConfigShadowUpstreamKey), upstreamName)
