# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""Non-textual diffs"""

from __future__ import annotations

import os
from contextlib import suppress

from gitfourchette import settings
from gitfourchette.gitdriver import ABDelta
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables


class DiffImagePair:
    oldImage: QImage
    newImage: QImage
    delta: ABDelta

    def __init__(self, repo: Repo, delta: ABDelta):
        imageDataA = delta.old.read(repo)
        imageDataB = delta.new.read(repo)
        self.oldImage = QImage.fromData(imageDataA)
        self.newImage = QImage.fromData(imageDataB)
        self.delta = delta


class SpecialDiffError:
    def __init__(
            self,
            message: str,
            details: str = "",
            icon: str = "SP_MessageBoxInformation",
            preformatted: str = "",
            longform: str = "",
    ):
        self.message = message
        self.details = details
        self.icon = icon
        self.preformatted = preformatted
        self.longform = longform
        self.links = DocumentLinks()

    @staticmethod
    def noChange(delta: ABDelta):
        message = _("File contents didn’t change.")
        details: list[str] = []
        longform: list[str] = []

        oldFile = delta.old
        newFile = delta.new
        oldFileExists = not oldFile.isId0()
        newFileExists = not newFile.isId0()

        if not newFileExists:
            message = _("Empty file was deleted.")

        if not oldFileExists:
            if delta.new.mode == FileMode.TREE:
                return SpecialDiffError.treeDiff(delta)
            else:
                assert delta.status in "A?"  # added or untracked
                message = _("New empty file.")

        if oldFile.path != newFile.path:
            intro = _("Renamed:")
            details.append(f"{intro} {hquo(oldFile.path)} &rarr; {hquo(newFile.path)}.")

        if oldFileExists and oldFile.mode != newFile.mode:
            intro = _("Mode change:")
            details.append(f"{intro} {TrTables.enum(oldFile.mode)} &rarr; {TrTables.enum(newFile.mode)}.")

        # TODO: "and oldFile.size != newFile.size" lost in translation, still OK?
        if delta.context.isWorkdir() and oldFile == newFile:
            message = _("Canonical file contents unchanged.")
            longform.append(toRoomyUL([
                _("Due to filters such as {filter}, your working copy is not bit-for-bit identical to the file’s "
                  "canonical state. However, the contents tracked by Git are equivalent after filtering.",
                  filter=hquo("core.autocrlf")),
                _("You can stage the file to dismiss this message; no changes will be recorded.")
            ]))

        return SpecialDiffError(message, "\n".join(details), longform="\n".join(longform))

    @staticmethod
    def diffTooLarge(size, threshold, locator):
        locale = QLocale()
        humanSize = locale.formattedDataSize(size, 1)
        humanThreshold = locale.formattedDataSize(threshold, 0)
        loadAnyway = locator.withExtraFlags(NavFlags.AllowLargeFiles)
        configure = makeInternalLink("prefs", "largeFileThresholdKB")
        longform = toRoomyUL([
            linkify(_("[Load diff anyway] (this may take a moment)"), loadAnyway.url()),
            linkify(_("[Configure diff preview limit] (currently: {0})", humanThreshold), configure),
        ])
        return SpecialDiffError(
            _("This diff is very large."),
            _("Diff size: {0}", humanSize),
            "SP_MessageBoxWarning",
            longform=longform)

    @staticmethod
    def imageTooLarge(size, threshold, locator):
        locale = QLocale()
        humanSize = locale.formattedDataSize(size, 1)
        humanThreshold = locale.formattedDataSize(threshold, 0)
        loadAnyway = locator.withExtraFlags(NavFlags.AllowLargeFiles)
        configure = makeInternalLink("prefs", "imageFileThresholdKB")
        longform = toRoomyUL([
            linkify(_("[Load image anyway] (this may take a moment)"), loadAnyway.url()),
            linkify(_("[Configure image preview limit] (currently: {0})", humanThreshold), configure),
        ])
        return SpecialDiffError(
            _("This image is very large."),
            _("Image size: {0}", humanSize),
            "SP_MessageBoxWarning",
            longform=longform)

    @staticmethod
    def typeChange(delta: ABDelta):
        oldText = _("Old type:")
        newText = _("New type:")
        oldMode = TrTables.enum(delta.old.mode)
        newMode = TrTables.enum(delta.new.mode)
        table = ("<table>"
                 f"<tr><td><del><b>{oldText}</b></del> </td><td>{oldMode}</tr>"
                 f"<tr><td><add><b>{newText}</b></add> </td><td>{newMode}</td></tr>"
                 "</table>")
        return SpecialDiffError(_("This file’s type has changed."), table)

    @staticmethod
    def binaryDiff(repo: Repo, delta: ABDelta, locator: NavLocator) -> SpecialDiffError | DiffImagePair:
        locale = QLocale()
        of, nf = delta.old, delta.new

        if isImageFormatSupported(of.path) and isImageFormatSupported(nf.path):
            largestSize = max(of.size, nf.size)
            if locator.hasFlags(NavFlags.AllowLargeFiles):
                threshold = 0
            else:
                threshold = settings.prefs.imageFileThresholdKB * 1024
            if largestSize > threshold > 0:
                return SpecialDiffError.imageTooLarge(largestSize, threshold, locator)
            return DiffImagePair(repo, delta)

        oldHumanSize = locale.formattedDataSize(of.size)
        newHumanSize = locale.formattedDataSize(nf.size)
        return SpecialDiffError(
            _("File appears to be binary."),
            f"{oldHumanSize} &rarr; {newHumanSize}")

    @staticmethod
    def treeDiff(delta):
        # TODO: Migrate to VanillaStatus
        from gitfourchette.tasks import AbsorbSubmodule

        treePath = os.path.normpath(delta.new_file.path)
        treeName = os.path.basename(treePath)
        message = _("This untracked subtree is the root of another Git repository.")

        # TODO: if we had the full path to the root repo, we could just make a standard file link, and we wouldn't need the "opensubfolder" authority
        prompt1 = _("Open {0}", bquo(treeName))
        openLink = makeInternalLink("opensubfolder", treePath)

        prompt2 = _("Absorb {0} as submodule", bquo(treeName))
        prompt2 = _("Recommended action:") + " [" + prompt2 + "]"
        taskLink = AbsorbSubmodule.makeInternalLink(path=treePath)

        return SpecialDiffError(
            message,
            linkify(prompt1, openLink),
            longform=toRoomyUL([linkify(prompt2, taskLink)]))

    @staticmethod
    def submoduleDiff(repo: Repo, patch: Patch, locator: NavLocator) -> SpecialDiffError:
        # TODO: Migrate to VanillaStatus
        from gitfourchette.tasks import AbsorbSubmodule, DiscardFiles, RegisterSubmodule

        smDiff = repo.analyze_subtree_commit_patch(patch, in_workdir=locator.context.isWorkdir())
        isTree = not smDiff.is_submodule

        # Compose title.
        # Explicit permutations of "subtree"/"submodule" text so that translations
        # can be grammatically correct (in case of different genders, etc.)
        if smDiff.is_del:
            title = (_("Subtree {0} was [removed.]") if isTree else
                     _("Submodule {0} was [removed.]"))
            title = tagify(title, "<del><b>")
        elif smDiff.is_add:
            title = (_("Subtree {0} was [added.]") if isTree else
                     _("Submodule {0} was [added.]"))
            title = tagify(title, "<add><b>")
        elif smDiff.head_did_move:
            title = (_("Subtree {0} was updated.") if isTree else
                     _("Submodule {0} was updated."))
        else:
            title = (_("Subtree {0} contains changes.") if isTree else
                     _("Submodule {0} contains changes."))

        title = title.format(bquo(smDiff.short_name))

        # Add link to open the submodule as a subtitle
        subtitle = ""
        openLink = QUrl.fromLocalFile(smDiff.workdir)
        if smDiff.still_exists:
            subtitle = _("Open subtree") if isTree else _("Open submodule")
            if smDiff.short_name != patch.delta.new_file.path:
                subtitle += " " + _("(path: {0})", escape(patch.delta.new_file.path))
            subtitle = linkify(subtitle, openLink)

        # Initialize SpecialDiffError (we'll return this)
        specialDiff = SpecialDiffError(title, subtitle)
        longformParts = []

        # Create old/new table if the submodule's HEAD commit was moved
        if smDiff.head_did_move and not smDiff.is_del:
            targets = [shortHash(smDiff.old_id), shortHash(smDiff.new_id)]
            messages = ["", ""]

            # Show additional details about the commits if there's still a workdir for this submo
            if smDiff.still_exists:
                try:
                    with RepoContext(smDiff.workdir, RepositoryOpenFlag.NO_SEARCH) as subRepo:
                        for i, h in enumerate([smDiff.old_id, smDiff.new_id]):
                            if h == NULL_OID:
                                continue

                            # Link to specific commit
                            targets[i] = linkify(shortHash(h), f"{openLink.toString()}#{h}")

                            # Get commit summary
                            with suppress(LookupError, GitError):
                                m = subRepo[h].peel(Commit).message
                                m = messageSummary(m)[0]
                                m = elide(m, Qt.TextElideMode.ElideRight, 25)
                                m = hquo(m)
                                messages[i] = m
                except GitError:
                    # RepoContext may fail if the submodule couldn't be opened for any reason.
                    # Don't show an error for this, show the diff document anyway
                    pass

            oldText = _("Old:")
            newText = _("New:")
            table = ("<table>"
                     f"<tr><td><del><b>{oldText}</b></del> </td><td><code>{targets[0]} </code> {messages[0]}</td></tr>"
                     f"<tr><td><add><b>{newText}</b></add> </td><td><code>{targets[1]} </code> {messages[1]}</td></tr>"
                     "</table>")

            intro = (_("The subtree’s <b>HEAD</b> has moved to another commit.") if isTree else
                     _("The submodule’s <b>HEAD</b> has moved to another commit."))
            if locator.context == NavContext.UNSTAGED:
                intro += " " + _("You can stage this update:")
            longformParts.append(f"{intro}<p>{table}</p>")

        # Show additional tips if this submodule is in the workdir.
        if locator.context.isWorkdir():
            m = ""
            if smDiff.is_del:
                if smDiff.is_registered:
                    m = _("To complete the removal of this submodule, <b>remove it from {gitmodules}</b>.")
                elif smDiff.was_registered:
                    m = _("To complete the removal of this submodule, make sure to <b>commit "
                          "{gitmodules}</b> at the same time as the submodule folder itself.")

            elif smDiff.is_registered and not smDiff.was_registered:
                m = _("To complete the addition of this submodule, make sure to <b>commit "
                      "{gitmodules}</b> at the same time as the submodule folder itself.")

            elif not smDiff.is_absorbed:
                if isTree:
                    m = _("<b>This subtree isn’t a submodule yet!</b> "
                          "You should [absorb this subtree] into the parent repository so it becomes a submodule.")
                else:
                    m = _("To complete the addition of this submodule, "
                          "you should [absorb the submodule] into the parent repository.")
                m = linkify(m, AbsorbSubmodule.makeInternalLink(path=patch.delta.new_file.path))

            elif not smDiff.is_registered:
                m = _("To complete the addition of this submodule, [register it in {gitmodules}].")
                m = linkify(m, RegisterSubmodule.makeInternalLink(path=patch.delta.new_file.path))

            if m:
                important = _("IMPORTANT")
                m = m.format(gitmodules=f"<tt>{DOT_GITMODULES}</tt>")
                m = f"{stockIconImgTag('achtung')} <b>{important}</b> &ndash; {m}"
                longformParts.insert(0, m)

            # Tell about any uncommitted changes
            if smDiff.dirty:
                discardLink = specialDiff.links.new(lambda invoker: DiscardFiles.invoke(invoker, [patch]))

                if isTree:
                    uc1 = _("The subtree contains <b>uncommitted changes</b>. They can’t be committed from the parent repo. You can:")
                    uc2 = _("[Open] the subtree and commit the changes.")
                    uc3 = _("Or, [Reset] the subtree to a clean state.")
                else:
                    uc1 = _("The submodule has <b>uncommitted changes</b>. They can’t be committed from the parent repo. You can:")
                    uc2 = _("[Open] the submodule and commit the changes.")
                    uc3 = _("Or, [Reset] the submodule to a clean state.")

                m = f"{uc1}<ul><li>{uc2}</li><li>{uc3}</li></ul>"
                m = linkify(m, openLink, discardLink)
                longformParts.append(m)

        # Compile longform parts into an unordered list
        specialDiff.longform = toRoomyUL(longformParts)

        return specialDiff
