# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
import logging
from collections.abc import Generator, Iterable

from gitfourchette import settings
from gitfourchette.appconsts import *
from gitfourchette.graph import Graph, GraphSpliceLoop, MockCommit
from gitfourchette.porcelain import *
from gitfourchette.repoprefs import RepoPrefs
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

UC_FAKEID = NULL_OID
"Fake Oid for Uncommitted Changes (aka Working Directory in the UI)."

UC_FAKEREF = "UC_FAKEREF"
"Fake reference name for Uncommitted Changes (aka Working Directory in the UI)."
# Actual refs are either "HEAD" or they start with "refs/",
# so this name should never collide with user refs.

BEGIN_SSH_SIGNATURE = b"-----BEGIN SSH SIGNATURE-----"


def toggleSetElement(s: set, element):
    assert isinstance(s, set)
    try:
        s.remove(element)
        return False
    except KeyError:
        s.add(element)
        return True


class GpgStatus(enum.IntEnum):
    Unsigned        = 0
    Pending         = enum.auto()
    CantCheck       = enum.auto()
    MissingKey      = enum.auto()
    GoodTrusted     = enum.auto()
    GoodUntrusted   = enum.auto()
    ExpiredSig      = enum.auto()
    ExpiredKey      = enum.auto()
    RevokedKey      = enum.auto()
    Bad             = enum.auto()
    ProcessError    = enum.auto()

    def iconName(self):
        return _GpgStatusIconTable.get(self, "gpg-verify-cantcheck")

    def iconHtml(self):
        return stockIconImgTag(self.iconName())


_GpgStatusIconTable = {
    GpgStatus.Pending       : "gpg-verify-pending",
    GpgStatus.GoodTrusted   : "gpg-verify-good-trusted",
    GpgStatus.GoodUntrusted : "gpg-verify-good-untrusted",
    GpgStatus.ExpiredSig    : "gpg-verify-expired",
    GpgStatus.ExpiredKey    : "gpg-verify-expired",
    GpgStatus.RevokedKey    : "gpg-verify-bad",
    GpgStatus.Bad           : "gpg-verify-bad",
    GpgStatus.ProcessError  : "gpg-verify-cantcheck",
}


class RepoModel:
    repo: Repo

    walker: Walker | None
    """Walker used to generate the graph. Call initializeWalker before use.
    Keep it around to speed up ulterior refreshes."""

    commitSequence: list[Commit]
    "Ordered list of commits."

    truncatedHistory: bool

    graph: Graph

    refs: dict[str, Oid]
    "Get target commit ID by reference name."

    refsAt: dict[Oid, list[str]]
    "Get all reference names pointing at a given commit ID."

    mergeheads: list[Oid]

    stashes: list[Oid]

    submodules: dict[str, str]
    "Map of submodule names to the relative paths of their workdirs."

    initializedSubmodules: set[str]
    "Set of submodule names that are registered in .gitmodules."

    remotes: list[str]
    "List of remote names."

    upstreams: dict[str, str]
    "Table of local branch names to upstream shorthand names."

    superproject: str
    "Path of the superproject. Empty string if this isn't a submodule."

    foreignCommits: set[Oid]
    """Use this to look up which commits are part of local branches,
    and which commits are 'foreign'."""

    hiddenRefs: set[str]
    "All cached refs that are hidden, either explicitly or via ref patterns."

    hideSeeds: set[Oid]
    localSeeds: set[Oid]

    hiddenCommits: set[Oid]
    "All cached commit oids that are hidden."

    gpgStatusCache: dict[Oid, tuple[GpgStatus, str]]

    workdirStale: bool
    "Flag indicating that the workdir should be refreshed before use."

    workdirDiffsReady: bool
    "Flag indicating that stageDiff and dirtyDiff are available."

    stageDiff: Diff
    dirtyDiff: Diff

    numUncommittedChanges: int
    "Number of unstaged+staged files. Negative means unknown count."

    headIsDetached: bool
    homeBranch: str

    prefs: RepoPrefs

    def __init__(self, repo: Repo):
        assert isinstance(repo, Repo)

        self.commitSequence = []
        self.truncatedHistory = True

        self.walker = None
        self.graph = Graph()

        self.headIsDetached = False
        self.homeBranch = ""

        self.superproject = ""
        self.workdirStale = True
        self.workdirDiffsReady = False
        self.numUncommittedChanges = -1

        self.refs = {}
        self.refsAt = {}
        self.mergeheads = []
        self.stashes = []
        self.submodules = {}
        self.initializedSubmodules = set()
        self.remotes = []
        self.upstreams = {}

        self.hiddenRefs = set()
        self.hiddenCommits = set()
        self.hideSeeds = set()
        self.localSeeds = set()

        self.gpgStatusCache = {}
        self.gpgVerificationQueue = set()

        self.repo = repo

        self.prefs = RepoPrefs.initForRepo(repo)

        if settings.prefs.refSortClearTimestamp > self.prefs.refSortClearTimestamp:
            self.prefs.clearRefSort()

        # Prime ref cache after loading prefs (prefs contain hidden ref patterns)
        self.syncRefs()
        self.syncMergeheads()
        self.syncStashes()
        self.syncSubmodules()
        self.syncRemotes()
        self.syncUpstreams()
        self.superproject = repo.get_superproject()

    def __del__(self):
        logger.debug("__del__ RepoModel")

    @property
    def numRealCommits(self):
        # The first item in the commit sequence is the "fake commit" for Uncommitted Changes.
        return max(0, len(self.commitSequence) - 1)

    @property
    def headCommitId(self) -> Oid:
        """ Oid of the currently checked-out commit. """
        return self.refs.get("HEAD", NULL_OID)

    @property
    def singleRemote(self) -> bool:
        return len(self.remotes) == 1

    @benchmark
    def syncRefs(self):
        """ Refresh cached refs (`refs` and `refsAt`).

        Return True if there were any changes in the refs since the last
        refresh, or False if nothing changed.
        """

        headWasDetached = self.headIsDetached
        self.headIsDetached = self.repo.head_is_detached

        if self.headIsDetached or self.repo.head_is_unborn:
            self.homeBranch = ""
        else:
            self.homeBranch = self.repo.head_branch_shorthand

        refs = self.repo.map_refs_to_ids(include_stashes=False)
        refs[UC_FAKEREF] = UC_FAKEID

        if refs == self.refs:
            # Make sure it's sorted in the exact same order...
            if APP_DEBUG:
                assert list(refs) == list(self.refs), "refs key order changed! how did that happen?"

            # Nothing to do!
            # Still, signal a change if HEAD just detached/reattached.
            return headWasDetached != self.headIsDetached

        # Build reverse ref cache.
        refsAt = {}
        for k, v in refs.items():
            try:
                refsAt[v].append(k)
            except KeyError:
                # Not using defaultdict because we don't want to create a
                # million empty lists when the UI code consults this dict.
                refsAt[v] = [k]

        # Special case for HEAD: Make it appear first in reverse ref cache
        try:
            headId = refs["HEAD"]
        except KeyError:
            pass
        else:
            refsAt[headId].remove("HEAD")
            refsAt[headId].insert(0, "HEAD")

        # Store new cache
        self.refs = refs
        self.refsAt = refsAt

        # Since the refs have changed, we need to refresh hidden refs
        self.refreshHiddenRefCache()

        # Let caller know that the refs changed.
        return True

    @benchmark
    def syncMergeheads(self):
        mh = self.repo.listall_mergeheads()
        if mh != self.mergeheads:
            self.mergeheads = mh
            return True
        return False

    @benchmark
    def syncStashes(self):
        stashes = []
        for stash in self.repo.listall_stashes():
            stashes.append(stash.commit_id)
        if stashes != self.stashes:
            self.stashes = stashes
            return True
        return False

    @benchmark
    def syncSubmodules(self):
        submodules = self.repo.listall_submodules_dict()
        initializedSubmodules = {name for name, path in submodules.items() if self.repo.submodule_dotgit_present(path)}

        if submodules != self.submodules or initializedSubmodules != self.initializedSubmodules:
            self.submodules = submodules
            self.initializedSubmodules = initializedSubmodules
            return True

        return False

    @benchmark
    def syncRemotes(self):
        # We could infer remote names from refCache, but we don't want
        # to miss any "blank" remotes that don't have any branches yet.
        # RemoteCollection.names() is much faster than iterating on RemoteCollection itself
        remotes = self.repo.listall_remotes_fast()
        if remotes != self.remotes:
            self.remotes = remotes
            return True
        return False

    @benchmark
    def syncUpstreams(self):
        upstreams = self.repo.listall_upstreams_fast()
        if upstreams != self.upstreams:
            self.upstreams = upstreams
            return True
        return False

    @property
    def shortName(self) -> str:
        prefix = ""
        if self.superproject:
            superprojectNickname = settings.history.getRepoNickname(self.superproject)
            prefix = superprojectNickname + ": "

        return prefix + settings.history.getRepoNickname(self.repo.workdir)

    @benchmark
    def primeWalker(self) -> Walker:
        tipIds = self.refs.values()
        sorting = SortMode.TOPOLOGICAL

        if settings.prefs.chronologicalOrder:
            # In strictly chronological ordering, a commit may appear before its
            # children if it was "created" later than its children. The graph
            # generator produces garbage in this case. So, for chronological
            # ordering, keep TOPOLOGICAL in addition to TIME.
            sorting |= SortMode.TIME

        if self.walker is None:
            self.walker = self.repo.walk(None, sorting)
        else:
            self.walker.reset()
            self.walker.sort(sorting)  # this resets the walker IF ALREADY WALKING (i.e. next was called once)

        # In topological mode, the order in which the tips are pushed is
        # significant (last in, first out). The tips should be pre-sorted in
        # ASCENDING chronological order so that the latest modified branches
        # come out at the top of the graph in topological mode.
        for tip in tipIds:
            if tip == UC_FAKEID:
                continue
            self.walker.push(tip)

        return self.walker

    def uncommittedChangesMockCommit(self):
        try:
            head = self.refs["HEAD"]
            parents = [head] + self.mergeheads
        except KeyError:  # Unborn HEAD
            parents = []

        return MockCommit(UC_FAKEID, parents)

    @property
    def nextTruncationThreshold(self) -> int:
        n = self.numRealCommits * 2
        n -= n % -1000  # round up to next thousand
        return max(n, settings.prefs.maxCommits)

    def dangerouslyDetachedHead(self):
        if not self.headIsDetached:
            return False

        try:
            headTips = self.refsAt[self.headCommitId]
        except KeyError:
            return False

        if headTips != ["HEAD"]:
            return False

        try:
            frame = self.graph.getCommitFrame(self.headCommitId)
        except KeyError:
            # Head commit not in graph, cannot determine if dangerous, err on side of caution
            return True

        arcs = list(frame.arcsClosedByCommit())

        if len(arcs) == 0:
            return True

        if len(arcs) != 1:
            return False

        return arcs[0].openedBy == UC_FAKEID

    @benchmark
    def syncTopOfGraph(self, oldRefs: dict[str, Oid]) -> GraphSpliceLoop:
        # DO NOT call processEvents() here. While splicing a large amount of
        # commits, GraphView may try to repaint an incomplete graph.
        # GraphView somehow ignores setUpdatesEnabled(False) here!
        gsl = GraphSpliceLoop(self.graph, self.commitSequence,
                              oldHeads=oldRefs.values(), newHeads=self.refs.values(),
                              hideSeeds=self.getHiddenTips(), localSeeds=self.getLocalTips())
        coSplice = gsl.coSplice()
        coSplice.send(None)  # prime the generator

        try:
            coSplice.send(self.uncommittedChangesMockCommit())
        except StopIteration:
            # e.g. switching from a branch to Detached HEAD on the same commit as the branch
            pass
        else:
            walker = self.primeWalker()
            for commit in walker:
                try:
                    coSplice.send(commit)
                except StopIteration:
                    break
        coSplice.close()  # flush it

        self.commitSequence = gsl.commitSequence
        self.hideSeeds = gsl.hideSeeds
        self.localSeeds = gsl.localSeeds
        self.hiddenCommits = gsl.hiddenCommits
        self.foreignCommits = gsl.foreignCommits
        return gsl

    @benchmark
    def toggleHideRefPattern(self, refPattern: str, allButThis: bool = False):
        if not allButThis:
            self.prefs.showPatterns.clear()  # clear show patterns in non-allButThis mode
            toggleSetElement(self.prefs.hidePatterns, refPattern)
        else:
            wasShowingThis = refPattern in self.prefs.showPatterns
            self.prefs.hidePatterns.clear()  # clear hide patterns in allButThis mode
            self.prefs.showPatterns.clear()  # only retain a single show pattern
            if not wasShowingThis:
                toggleSetElement(self.prefs.showPatterns, refPattern)

        self.prefs.setDirty()
        self.refreshHiddenRefCache()

        # Sync hidden commits
        heads = self.refs.values()
        newHideSeeds = self.getHiddenTips()
        newLocalSeeds = self.getLocalTips()
        gsl = GraphSpliceLoop(self.graph, self.commitSequence, oldHeads=heads, newHeads=heads,
                              hideSeeds=newHideSeeds, localSeeds=newLocalSeeds)
        gsl.sendAll(self.commitSequence)  # send the same commit sequence
        self.hiddenCommits = gsl.hiddenCommits
        self.foreignCommits = gsl.foreignCommits
        self.hideSeeds = newHideSeeds
        self.localSeeds = newLocalSeeds

    @benchmark
    def refreshHiddenRefCache(self):
        showPatterns = self.prefs.showPatterns
        hidePatterns = self.prefs.hidePatterns
        numStalePatterns = 0

        assert type(self.hiddenRefs) is set
        self.hiddenRefs.clear()

        if showPatterns:
            matchingRefs, numStalePatterns = self._matchPatterns(showPatterns)
            self.hiddenRefs.update(self.refs.keys())
            self.hiddenRefs.difference_update(matchingRefs)
        elif hidePatterns:
            matchingRefs, numStalePatterns = self._matchPatterns(hidePatterns)
            self.hiddenRefs.update(matchingRefs)

        if numStalePatterns > 0:
            self.prefs.setDirty()

    def _matchPatterns(self, patterns):
        assert type(patterns) is set

        matchingRefs = set()
        patternsSeen = set()

        for ref in self.refs:
            # Test for verbatim match first
            if ref in patterns:
                matchingRefs.add(ref)
                patternsSeen.add(ref)
                continue

            # Break up directory segments
            i = len(ref)
            while i >= 0:
                i = ref.rfind('/', 0, i)
                if i < 0:
                    break
                prefix = ref[:i+1]
                if prefix in patterns:
                    matchingRefs.add(ref)
                    patternsSeen.add(prefix)
                    break

        numStalePatterns = len(patterns) - len(patternsSeen)
        assert numStalePatterns >= 0, "there can't be fewer patterns in total than we've visited!"
        if numStalePatterns != 0:
            logger.debug(f"Culling {numStalePatterns} stale ref patterns")
            patterns.intersection_update(patternsSeen)

        return matchingRefs, numStalePatterns

    def getKnownTips(self) -> Iterable[Oid]:
        return self.refs.values()

    def getLocalTips(self):
        return {
            oid for oid, refList in self.refsAt.items()
            if any(name == "HEAD" or name.startswith("refs/heads/") for name in refList)}

    def getHiddenTips(self) -> set[Oid]:
        seeds = set()
        hiddenRefs = self.hiddenRefs

        def isSharedByVisibleBranch(oid: Oid):
            return any(
                ref for ref in self.refsAt[oid]
                if ref not in hiddenRefs and not ref.startswith(RefPrefix.TAGS))

        for ref in hiddenRefs:
            oid = self.refs[ref]
            if not isSharedByVisibleBranch(oid):
                seeds.add(oid)

        return seeds

    def commitsMatchingRefPattern(self, refPattern: str) -> Generator[Oid, None, None]:
        if not refPattern.endswith("/"):
            # Explicit ref
            try:
                yield self.refs[refPattern]
            except KeyError:
                pass
        else:
            # Wildcard
            for ref, oid in self.refs.items():
                if ref.startswith(refPattern):
                    yield oid

    def getCachedGpgStatus(self, commit: Commit) -> tuple[GpgStatus, str]:
        oid = commit.id

        try:
            return self.gpgStatusCache[oid]
        except KeyError:
            pass

        sig, _payload = commit.gpg_signature
        status = GpgStatus.Pending if sig else GpgStatus.Unsigned

        if not sig:
            status = GpgStatus.Unsigned
            keyInfo = ""
        else:
            isSsh = sig.startswith(BEGIN_SSH_SIGNATURE)
            keyInfo = "ssh" if isSsh else ""

        self.gpgStatusCache[commit.id] = (status, keyInfo)
        return status, keyInfo

    def cacheGpgStatus(self, oid: Oid, status: GpgStatus, keyInfo: str = ""):
        self.gpgStatusCache[oid] = (status, keyInfo)

    def queueGpgVerification(self, oid: Oid):
        if not settings.prefs.verifyGpgOnTheFly:
            return
        assert self.gpgStatusCache[oid][0] == GpgStatus.Pending
        self.gpgVerificationQueue.add(oid)
