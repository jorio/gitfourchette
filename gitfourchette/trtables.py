# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import textwrap
from enum import Enum
from typing import TYPE_CHECKING

from gitfourchette.localization import *
from gitfourchette.porcelain import *

if TYPE_CHECKING:
    from gitfourchette.toolbox.gitutils import PatchPurpose


_userCommandsGuideUrl = "https://gitfourchette.org/guide/commands"


def _tokenReferenceTable(table):
    markup = "<table>"
    for token, caption in table.items():
        markup += f"<tr><td><b>{token} </b></td><td> {caption}</td></tr>\n"
    markup += "</table>"
    return markup


class TrTables:
    _enums                      : dict[type[Enum], dict[Enum, str]] = {}
    _exceptionNames             : dict[str, str] = {}
    _prefKeys                   : dict[str, str] = {}
    _diffStatusChars            : dict[str, str] = {}
    _shortFileModes             : dict[FileMode, str] = {}
    _patchPurposesPastTense     : dict[PatchPurpose, str] = {}

    @classmethod
    def init(cls):
        if not cls._exceptionNames:
            cls.retranslate()

    @classmethod
    def retranslate(cls):
        cls._enums = cls._init_enums()
        cls._exceptionNames = cls._init_exceptionNames()
        cls._prefKeys = cls._init_prefKeys()
        cls._diffStatusChars = cls._init_diffStatusChars()
        cls._shortFileModes = cls._init_shortFileModes()
        cls._patchPurposesPastTense = cls._init_patchPurposesPastTense()

    @classmethod
    def enum(cls, enumValue: Enum) -> str:
        try:
            return cls._enums[type(enumValue)][enumValue]
        except KeyError:
            return enumValue.name

    @classmethod
    def exceptionName(cls, exc: BaseException):
        name = type(exc).__name__
        return cls._exceptionNames.get(name, name)

    @classmethod
    def prefKey(cls, key: str):
        return cls._prefKeys.get(key, str(key))

    @classmethod
    def prefKeyNoDefault(cls, key: str):
        return cls._prefKeys.get(key, "")

    @classmethod
    def diffStatusChar(cls, c: str):
        return cls._diffStatusChars.get(c, c)

    @classmethod
    def shortFileModes(cls, m: FileMode):
        try:
            return cls._shortFileModes[m]
        except KeyError:
            return f"{m:o}"

    @classmethod
    def patchPurposePastTense(cls, purpose: PatchPurpose):
        return cls._patchPurposesPastTense.get(purpose, "???")

    @staticmethod
    def _init_exceptionNames():
        return {
            "ConnectionRefusedError": _("Connection refused"),
            "FileNotFoundError": _("File not found"),
            "PermissionError": _("Permission denied"),
            "GitError": _("Git error"),
            "NotImplementedError": _("Unsupported feature"),
            "InterruptedError": _("Operation interrupted"),
        }

    @staticmethod
    def _init_enums():
        from gitfourchette.gitdriver import GitConflictSides
        from gitfourchette.porcelain import FileMode, NameValidationError
        from gitfourchette.toolbox import toLengthVariants
        from gitfourchette.sidebar.sidebarmodel import SidebarItem
        from gitfourchette.settings import GraphRowHeight, QtApiNames, GraphRefBoxWidth, RefSort
        from gitfourchette.toolbox import PatchPurpose, PathDisplayStyle, AuthorDisplayStyle
        from gitfourchette.repomodel import GpgStatus

        NVERule = NameValidationError.Rule

        return {
            NVERule: {
                NVERule.ILLEGAL_NAME            : _("Illegal name."),
                NVERule.ILLEGAL_SUFFIX          : _("Illegal suffix."),
                NVERule.ILLEGAL_PREFIX          : _("Illegal prefix."),
                NVERule.CONTAINS_ILLEGAL_SEQ    : _("Contains illegal character sequence."),
                NVERule.CONTAINS_ILLEGAL_CHAR   : _("Contains illegal character."),
                NVERule.CANNOT_BE_EMPTY         : _("Cannot be empty."),
                NVERule.NOT_WINDOWS_FRIENDLY    : _("This name is discouraged for compatibility with Windows."),
                NVERule.NAME_TAKEN_BY_REF       : _("This name is already taken."),
                NVERule.NAME_TAKEN_BY_FOLDER    : _("This name is already taken by a folder."),
                NVERule.NOT_A_FOLDER            : _("The folder in this path clashes with an existing ref that isn’t a folder."),
            },

            FileMode: {
                0                       : _p("FileMode", "deleted"),
                FileMode.BLOB           : _p("FileMode", "regular file"),
                FileMode.BLOB_EXECUTABLE: _p("FileMode", "executable file"),
                FileMode.LINK           : _p("FileMode", "symbolic link"),
                FileMode.TREE           : _p("FileMode", "subtree"),
                FileMode.COMMIT         : _p("FileMode", "subtree commit"),
            },

            RepositoryState: {
                RepositoryState.NONE                    : _p("RepositoryState", "None"),
                RepositoryState.MERGE                   : _p("RepositoryState", "Merging"),
                RepositoryState.REVERT                  : _p("RepositoryState", "Reverting"),
                RepositoryState.REVERT_SEQUENCE         : _p("RepositoryState", "Reverting (sequence)"),
                RepositoryState.CHERRYPICK              : _p("RepositoryState", "Cherry-picking"),
                RepositoryState.CHERRYPICK_SEQUENCE     : _p("RepositoryState", "Cherry-picking (sequence)"),
                RepositoryState.BISECT                  : _p("RepositoryState", "Bisecting"),
                RepositoryState.REBASE                  : _p("RepositoryState", "Rebasing"),
                RepositoryState.REBASE_INTERACTIVE      : _p("RepositoryState", "Rebasing (interactive)"),
                RepositoryState.REBASE_MERGE            : _p("RepositoryState", "Rebasing (merging)"),
                RepositoryState.APPLY_MAILBOX           : "Apply Mailbox",  # intentionally untranslated
                RepositoryState.APPLY_MAILBOX_OR_REBASE : "Apply Mailbox or Rebase",  # intentionally untranslated
            },

            GitConflictSides: {
                GitConflictSides.BothDeleted    : _p("ConflictSides", "deleted by both sides"),
                GitConflictSides.AddedByUs      : _p("ConflictSides", "added by us"),
                GitConflictSides.DeletedByThem  : _p("ConflictSides", "deleted by them"),
                GitConflictSides.AddedByThem    : _p("ConflictSides", "added by them"),
                GitConflictSides.DeletedByUs    : _p("ConflictSides", "deleted by us"),
                GitConflictSides.BothAdded      : _p("ConflictSides", "added by both sides"),
                GitConflictSides.BothModified   : _p("ConflictSides", "modified by both sides"),
            },

            PatchPurpose: {
                PatchPurpose.Stage                          : _p("PatchPurpose", "Stage"),
                PatchPurpose.Unstage                        : _p("PatchPurpose", "Unstage"),
                PatchPurpose.Discard                        : _p("PatchPurpose", "Discard"),
                PatchPurpose.Lines | PatchPurpose.Stage     : _p("PatchPurpose", "Stage lines"),
                PatchPurpose.Lines | PatchPurpose.Unstage   : _p("PatchPurpose", "Unstage lines"),
                PatchPurpose.Lines | PatchPurpose.Discard   : _p("PatchPurpose", "Discard lines"),
                PatchPurpose.Hunk | PatchPurpose.Stage      : _p("PatchPurpose", "Stage hunk"),
                PatchPurpose.Hunk | PatchPurpose.Unstage    : _p("PatchPurpose", "Unstage hunk"),
                PatchPurpose.Hunk | PatchPurpose.Discard    : _p("PatchPurpose", "Discard hunk"),
                PatchPurpose.File | PatchPurpose.Stage      : _p("PatchPurpose", "Stage file"),
                PatchPurpose.File | PatchPurpose.Unstage    : _p("PatchPurpose", "Unstage file"),
                PatchPurpose.File | PatchPurpose.Discard    : _p("PatchPurpose", "Discard file"),
            },

            SidebarItem: {
                SidebarItem.UncommittedChanges  : toLengthVariants(_p("SidebarModel", "Working Directory|Workdir")),
                SidebarItem.LocalBranchesHeader : toLengthVariants(_p("SidebarModel", "Local Branches|Branches")),
                SidebarItem.StashesHeader       : _p("SidebarModel", "Stashes"),
                SidebarItem.RemotesHeader       : _p("SidebarModel", "Remotes"),
                SidebarItem.TagsHeader          : _p("SidebarModel", "Tags"),
                SidebarItem.SubmodulesHeader    : _p("SidebarModel", "Submodules"),
                SidebarItem.LocalBranch         : _p("SidebarModel", "Local branch"),
                SidebarItem.DetachedHead        : _p("SidebarModel", "Detached HEAD"),
                SidebarItem.UnbornHead          : _p("SidebarModel", "Unborn HEAD"),
                SidebarItem.RemoteBranch        : _p("SidebarModel", "Remote branch"),
                SidebarItem.Stash               : _p("SidebarModel", "Stash"),
                SidebarItem.Remote              : _p("SidebarModel", "Remote"),
                SidebarItem.Tag                 : _p("SidebarModel", "Tag"),
                SidebarItem.Submodule           : _p("SidebarModel", "Submodules"),
                SidebarItem.Spacer              : "---",
            },

            PathDisplayStyle: {
                PathDisplayStyle.FullPaths      : _("Full paths"),
                PathDisplayStyle.AbbreviateDirs : _("Abbreviate directories"),
                PathDisplayStyle.FileNameOnly   : _("Show filename only"),
                PathDisplayStyle.FileNameFirst  : _("Filename first"),
            },

            AuthorDisplayStyle: {
                AuthorDisplayStyle.FullName     : _("Full name"),
                AuthorDisplayStyle.FirstName    : _("First name"),
                AuthorDisplayStyle.LastName     : _("Last name"),
                AuthorDisplayStyle.Initials     : _("Initials"),
                AuthorDisplayStyle.FullEmail    : _("Full email"),
                AuthorDisplayStyle.EmailUserName: _("Abbreviated email"),
            },

            GraphRowHeight: {
                GraphRowHeight.Cramped          : _p("row spacing", "Cramped"),
                GraphRowHeight.Tight            : _p("row spacing", "Tight"),
                GraphRowHeight.Relaxed          : _p("row spacing", "Relaxed"),
                GraphRowHeight.Roomy            : _p("row spacing", "Roomy"),
                GraphRowHeight.Spacious         : _p("row spacing", "Spacious"),
            },

            QtApiNames: {
                QtApiNames.Automatic            : _p("Qt binding", "Automatic (recommended)"),
                QtApiNames.PySide6              : "PySide6",
                QtApiNames.PyQt6                : "PyQt6",
                QtApiNames.PyQt5                : "PyQt5"
            },

            GraphRefBoxWidth: {
                GraphRefBoxWidth.IconsOnly      : _("Icons Only"),
                GraphRefBoxWidth.Standard       : _("Truncate long ref names"),
                GraphRefBoxWidth.Wide           : _("Show full ref names"),
            },

            RefSort: {
                RefSort.TimeDesc                : _p("sort refs by date of latest commit, descending", "Date, Newest First"),
                RefSort.TimeAsc                 : _p("sort refs by date of latest commit, ascending", "Date, Oldest First"),
                RefSort.AlphaAsc                : _p("sort refs alphabetically, ascending", "Name, A-Z"),
                RefSort.AlphaDesc               : _p("sort refs alphabetically, descending", "Name, Z-A"),
                RefSort.UseGlobalPref           : "",
            },

            GpgStatus: {
                GpgStatus.Unsigned              : _("Not signed"),
                GpgStatus.Pending               : _("Signature not verified yet"),
                GpgStatus.CantCheck             : _("Unable to verify signature"),
                GpgStatus.MissingKey            : _("Can’t verify signature; Key not in your keyring"),
                GpgStatus.GoodTrusted           : _("Good signature; Key trusted"),
                GpgStatus.GoodUntrusted         : _("Good signature; Key not fully trusted"),
                GpgStatus.ExpiredSig            : _("Good signature; Signature expired"),
                GpgStatus.ExpiredKey            : _("Good signature; Key expired"),
                GpgStatus.RevokedKey            : _("Good signature; Key revoked"),
                GpgStatus.Bad                   : _("Bad signature"),
                GpgStatus.ProcessError          : _("Failed to start verification process"),
            },
        }

    @staticmethod
    def _init_diffStatusChars():
        # see git_diff_status_char (diff_print.c)
        return {
            "A": _p("FileStatus", "added"),
            "Z": _p("FileStatus", "added"),
            "C": _p("FileStatus", "copied"),
            "D": _p("FileStatus", "deleted"),
            "I": _p("FileStatus", "ignored"),
            "M": _p("FileStatus", "modified"),
            "R": _p("FileStatus", "renamed"),
            "T": _p("FileStatus", "file type changed"),
            "U": _p("FileStatus", "merge conflict"),  # "updated but unmerged"
            "X": _p("FileStatus", "unreadable"),
            "?": _p("FileStatus", "untracked"),
        }

    @staticmethod
    def _init_shortFileModes():
        return {
            0: "",
            FileMode.BLOB: "",
            FileMode.BLOB_EXECUTABLE: "+x",
            FileMode.LINK: _("link"),
            FileMode.TREE: _("new subtree"),
            FileMode.COMMIT: _("commit in subtree"),
        }

    @staticmethod
    def _init_patchPurposesPastTense():
        from gitfourchette.toolbox.gitutils import PatchPurpose as pp
        return {
            pp.Stage                : _p("PatchPurpose", "Staged."),
            pp.Unstage              : _p("PatchPurpose", "Unstaged."),
            pp.Discard              : _p("PatchPurpose", "Discarded."),
            pp.Lines | pp.Stage     : _p("PatchPurpose", "Lines staged."),
            pp.Lines | pp.Unstage   : _p("PatchPurpose", "Lines unstaged."),
            pp.Lines | pp.Discard   : _p("PatchPurpose", "Lines discarded."),
            pp.Hunk | pp.Stage      : _p("PatchPurpose", "Hunk staged."),
            pp.Hunk | pp.Unstage    : _p("PatchPurpose", "Hunk unstaged."),
            pp.Hunk | pp.Discard    : _p("PatchPurpose", "Hunk discarded."),
            pp.File | pp.Stage      : _p("PatchPurpose", "File staged."),
            pp.File | pp.Unstage    : _p("PatchPurpose", "File unstaged."),
            pp.File | pp.Discard    : _p("PatchPurpose", "File discarded."),
        }

    @staticmethod
    def _timeFormatTable():
        from gitfourchette.qt import QLocale, QDateTime, QDate, QTime

        locale = QLocale()
        firstDay = QDateTime(QDate(2000, 1, 1), QTime(0, 0))
        lastDay = QDateTime(QDate(2099, 12, 31), QTime(23, 59, 59))
        monday = QDateTime(QDate(2024, 12, 23), QTime(12, 0))
        sunday = QDateTime(QDate(2024, 12, 29), QTime(12, 0))

        def row(fmt: str, caption="", date1: QDateTime | None = firstDay, date2=lastDay):
            sample = ""
            if date1 is not None:
                f1 = locale.toString(date1, fmt)
                f2 = locale.toString(date2, fmt)
                sample = f1 + "–" + f2
                if caption:
                    sample = f", {sample}"
            return f"\n<code>{fmt:>4} </code> {caption}{sample}"

        return (
            "<html style='white-space: pre'>"
            + _p("date/time formats", "Available formats:")
            + "<p>"
            + row("yy", _("year"))
            + row("yyyy", _("year") + f", {QDate.currentDate().year()}", None)
            + "</p><p>"
            + row("M", _("month"))
            + row("MM", _("month"))
            + row("MMM")
            + row("MMMM")
            + "</p><p>"
            + row("d", _("day"))
            + row("dd", _("day"))
            + row("ddd", "", monday, sunday)
            + row("dddd", "", monday, sunday)
            + "</p><p>"
            + row("h", _("hour") + ", 0–23/1–12", None)
            + row("hh", _("hour") + ", 00–23/01–12", None)
            + row("mm", _("minute"))
            + row("ss", _("second"))
            + "</p><p>"
            + row("a")
            + row("A")
            + "</p>")

    @staticmethod
    def _init_prefKeys():
        from gitfourchette.toolbox.textutils import paragraphs, tquo, escape
        from gitfourchette.exttools.usercommand import UserCommand
        from gitfourchette.appconsts import APP_DISPLAY_NAME
        from gitfourchette.repomodel import GpgStatus

        sshAuthSock = os.environ.get("SSH_AUTH_SOCK", "")
        if sshAuthSock:
            sshAuthSockHelp = paragraphs([
                _("Note: Per {k}, your system is providing an ssh-agent ({v}). "
                  "It’s recommended to use this one."),
                _("If your system’s agent isn’t saving any passphrases, "
                  "make sure you’ve enabled {c} in your SSH configuration."),
            ])
        else:
            sshAuthSockHelp = _("Note: Per {k}, no ssh-agent seems to be running on your system.")
        sshAuthSockHelp = "<blockquote>" + sshAuthSockHelp.format(
            k="SSH_AUTH_SOCK", v=escape(sshAuthSock), c="AddKeysToAgent")

        return {
            "general": _p("Prefs", "General"),
            "diff": _p("Prefs", "Code"),
            "imageDiff": _p("Prefs", "Images"),
            "tabs": _p("Prefs", "Tabs"),
            "graph": _p("Prefs", "Commit History"),
            "trash": _p("Prefs", "Trash"),
            "git": _p("Prefs", "Git Integration"),
            "external": _p("Prefs", "External Tools"),
            "advanced": _p("Prefs", "Advanced"),
            "userCommands": _p("Prefs", "Custom Commands"),

            "language": _("Language"),
            "qtStyle": _("Qt style"),
            "shortHashChars": _("Shorten hashes to # characters"),
            "shortTimeFormat": _("Date/time format"),
            "shortTimeFormat_help": TrTables._timeFormatTable(),
            "pathDisplayStyle": _("Path display style"),
            "authorDisplayStyle": _("Author display style"),
            "maxRecentRepos": _("Remember up to # recent repositories"),
            "showStatusBar": _("Show status bar"),
            "showToolBar": _("Show toolbar"),
            "showMenuBar": _("Show menu bar"),
            "showMenuBar_help": _("When the menu bar is hidden, press the Alt key to show it again."),
            "resetDontShowAgain": _("Restore all “don’t show this again” messages"),
            "middleClickToStage": _("Middle-click to stage/unstage a file or the selected lines"),
            "middleClickToStage_help": paragraphs(
                _("This option lets you:"),
                "\u25aa " + _("Middle-click a file name in the Unstaged/Staged boxes to stage/unstage this file;"),
                "\u25aa " + _("Select lines in the diff, then middle-click to stage/unstage your selection."),
            ),
            "pygmentsPlugins": _("Allow third-party Pygments plugins"),
            "pygmentsPlugins_help": "<p>" + _("Let {app} load third-party Pygments plugins installed on your system. "
                                              "These plugins extend syntax highlighting with new languages "
                                              "and color schemes. <b>May incur significant slowdowns.</b>"),
            "refSort": _("Sort branches && tags by"),
            "refSort_help": paragraphs(
                _("The default sorting mode for local branches, remote branches, and tags in the sidebar."),
                _("You can fine-tune this setting in each repo by right-clicking Branches, Remotes, or Tags "
                  "in the sidebar. (Note that changing the default setting here will clear per-repo tweaks.)")),

            "font": _("Font"),
            "tabSpaces": _("One tab is # spaces"),
            "contextLines": _("Show up to # context lines"),
            "contextLines_help": _("Amount of unmodified lines to show around red or green lines in a diff."),
            "largeFileThresholdKB": _("Load diffs up to # KB"),
            "imageFileThresholdKB": _("Load images up to # KB"),
            "syntaxHighlighting": _("Syntax highlighting"),
            "wordWrap": _("Word wrap"),
            "showStrayCRs": _("Display alien line endings (CRLF)"),
            "colorblind": _("“-/+” colors"),
            "colorblind_help": _("Background colors for deleted (-) and added (+) lines."),
            "renderSvg": _("Treat SVG files as"),

            "tabCloseButton": _("Show tab close button"),
            "expandingTabs": _("Expand tabs to available width"),
            "autoHideTabs": _("Auto-hide tabs if only one repo is open"),
            "doubleClickTabOpensFolder": _("Double-click a tab to open repo folder"),

            "chronologicalOrder": _("Sort commits"),
            "chronologicalOrder_true": _("Chronologically"),
            "chronologicalOrder_false": _("Topologically"),
            "chronologicalOrder_help": paragraphs(
                _("<b>Chronological mode</b> lets you stay on top of the latest activity in the repository. "
                  "The most recent commits always show up at the top of the graph. "
                  "However, the graph can get messy when multiple branches receive commits in the same timeframe."),
                _("<b>Topological mode</b> makes the graph easier to read. It attempts to present sequences of "
                  "commits within a branch in a linear fashion. Since this is not a strictly chronological "
                  "mode, you may have to do more scrolling to see the latest changes in various branches."),
            ),
            "graphRowHeight": _("Row spacing"),
            "flattenLanes": _("Avoid gaps between branches in the graph"),
            "authorDiffAsterisk": _("Mark author/committer signature differences"),
            "authorDiffAsterisk_help": paragraphs(
                _("The commit history displays information about a commit’s <b>author</b>—"
                  "their name and the date at which they made the commit. But in some cases, a commit "
                  "might have been revised by someone else than the original author—"
                  "this person is called the <b>committer</b>."),
                _("If you tick this option, an asterisk (*) will appear after the author’s name "
                  "and/or date if they differ from the committer’s for any given commit."),
                _("Note that you can always hover over the author’s name or date to obtain "
                  "detailed information about the author and the committer."),
            ),
            "maxCommits": _("Load up to # commits in the history"),
            "maxCommits_help": _("Set to 0 to always load the full commit history."),
            "alternatingRowColors": _("Draw rows using alternating background colors"),
            "refBoxMaxWidth": _("Ref indicators"),
            "refBoxMaxWidth_help": _("You can always hover over an indicator to display the full name of the ref."),
            "verifyGpgOnTheFly": _("Verify signed commits on the fly"),
            "verifyGpgOnTheFly_help": _("As commits scroll into view, call {0} automatically to verify their signatures. "
                                        "The verification status is materialized by a seal icon next to the author’s name:", tquo("git verify-commit")
                                        ) + _tokenReferenceTable({
                GpgStatus.Pending.iconHtml()        : _("Verification pending"),
                GpgStatus.CantCheck.iconHtml()      : _("Verification failed (e.g. missing key)"),
                GpgStatus.GoodTrusted.iconHtml()    : _("Good signature; Key trusted"),
                GpgStatus.GoodUntrusted.iconHtml()  : _("Good signature; Key not fully trusted"),
                GpgStatus.ExpiredSig.iconHtml()     : _("Good signature; Key or signature expired"),
                GpgStatus.Bad.iconHtml()            : _("Key revoked or bad signature"),
            }) + "<br>" + _("(No seal = Commit isn’t signed)"),

            "maxTrashFiles": _("The trash keeps up to # discarded patches"),
            "maxTrashFileKB": _("Patches bigger than # KB won’t be salvaged"),
            "trash_HEADER": _(
                "When you discard changes from the working directory, {app} keeps a temporary copy in a hidden "
                "“trash” folder. This gives you a last resort to rescue changes that you have discarded by mistake. "
                "You can look around this trash folder via <i>“Help &rarr; Open Trash”</i>."),

            "verbosity": _("Logging verbosity"),
            "autoRefresh": _("Auto-refresh when app regains focus"),
            "autoRefresh_help": paragraphs(
                _("When you return to {app} from another application, it automatically "
                  "scans for changes in the working directory and local branches. "
                  "This keeps the interface in sync with the state of your repo on disk."),
                _("If you turn this off, you will need to hit {key} to "
                  "perform this refresh manually.", key="F5"),
                "<b>" + _("We strongly recommend to keep this setting enabled.") + "</b>"),
            "autoFetchMinutes": _("Auto-fetch remotes every # minutes"),
            "animations": _("Animation effects in sidebar"),
            "smoothScroll": _("Smooth scrolling (where applicable)"),
            "forceQtApi": _("Preferred Qt binding"),
            "forceQtApi_help": paragraphs(
                _("After restarting, {app} will use this Qt binding if available."),
                _("You can also pass the name of a Qt binding via the “QT_API” environment variable."),
            ),
            "condensedFonts": _("Use condensed fonts"),
            "condensedFonts_help": "<p>" + _(
                "When a branch name or author name is too long to fit in its allotted space, "
                "condense the font before truncating the text."),

            "externalEditor": _("Text editor"),
            "externalDiff": _("Diff tool"),
            "externalDiff_help":
                "<p style='white-space: pre'>" + _("Argument placeholders:") + "\n" + _tokenReferenceTable({
                    "$L": _("Old / Left"),
                    "$R": _("New / Right"),
                }),
            "externalMerge": _("Merge tool"),
            "externalMerge_help":
                "<p style='white-space: pre'>" + _("Argument placeholders:") + "\n" + _tokenReferenceTable({
                    "$B": _("Ancestor / Base / Center"),
                    "$L": _("Ours / Local / Left"),
                    "$R": _("Theirs / Remote / Right"),
                    "$M": _("Merged / Output / Result"),
                }),
            "terminal": _("Terminal"),
            "terminal_help": paragraphs(
                _("Argument placeholders:"),
                _tokenReferenceTable({"$COMMAND": _("Command to execute after launching the terminal")}),
                _("The {0} placeholder is mandatory. It is automatically substituted for a wrapper script that "
                  "enters your working directory and optionally starts one of your Custom Commands.",
                  "$COMMAND")),
            "gitPath": "git",
            "ownAskpass": _("Have OpenSSH ask for passphrases via {app}", app=APP_DISPLAY_NAME),
            "ownAskpass_help": paragraphs(
                _("Tick this to have OpenSSH use {app} to ask for passphrases."),
                _("Untick this if you’ve set up another program in the {0} environment variable (such as {1}).", tquo("SSH_ASKPASS"), tquo("ksshaskpass"))),
            "ownSshAgent": "ssh-agent",
            "ownSshAgent_false": _("Use ssh-agent provided by the system") + " " + "" if sshAuthSock else _("(not detected)"),
            "ownSshAgent_true": _("Have {app} manage its own ssh-agent", app=APP_DISPLAY_NAME),
            "ownSshAgent_help": paragraphs(
                _("“ssh-agent” can save your SSH credentials so you don’t have to retype the same passphrase over and over. "
                  "Some Linux distributions set up an ssh-agent for you."),
                _("You can also have {app} start its own instance of ssh-agent "
                  "for the duration of your session and have it remember passphrases."),
                sshAuthSockHelp,
            ),

            "userCommands_GUIDE": TrTables.userCommandsGuide(),
            "commands": "",
            "confirmCommands": _("Ask for confirmation before running any command"),
            "confirmCommands_help": _(
                "If you untick this, you can still force a prompt to appear for "
                "specific commands by prepending them with {0}. For example: {1}",
                tquo(f"<tt>{UserCommand.AlwaysConfirmPrefix}</tt>"),
                "<pre>?git stash</pre>"),
        }

    @staticmethod
    def userCommandsGuide():
        from gitfourchette.toolbox.textutils import paragraphs, linkify, stripAccelerators, tquo
        from gitfourchette.exttools.usercommand import UserCommand

        def cmdName(s: str):
            s = re.sub(r"&(.)", r"<u>&amp;\1</u>", s)
            return f"<com># {s}</com>"

        markup = textwrap.dedent("""\
        <style>
        body {background-color: palette(window); }
        pre { font-size: small; white-space: pre-wrap; margin: 0px; margin-left: 16px; }
        com { color: gray; font-style: italic; }
        tok { font-weight: bold; }
        </style><body>""")
        markup += paragraphs(_("Feel free to copy the sample below and paste it into the text box. "
                               "Then, click OK, and explore {menu} in the menu bar.",
                               menu=tquo(stripAccelerators(_("&Commands")))))
        markup += textwrap.dedent(f"""\
        <pre>
        git rebase -i <tok>$COMMIT</tok>   {cmdName(_("&Interactive Rebase"))}
        git rebase --continue   {cmdName(_("&Continue Rebase"))}
        <tok>?</tok> git rebase --abort    {cmdName(_("&Abort Rebase"))}
        git diff <tok>$COMMIT</tok> HEAD   {cmdName(_("Diff Commit With &HEAD"))}
        </pre>""")
        markup += paragraphs(_("You may use the following placeholders in your commands:"))
        markup += _tokenReferenceTable(UserCommand.tokenHelpTable())
        markup += paragraphs(linkify(_("For advanced usage tips, please visit [the user’s guide]."
                                       ), _userCommandsGuideUrl))
        return markup
