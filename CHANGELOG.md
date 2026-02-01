# GitFourchette version history

## 1.6.0 (2026-02-01)

New features:

- **Mount commits as folders.** This lets you browse the workdir at a specific point in time using your system's file manager. Available by right-clicking a commit in the Commit History. (FUSE 3 required + new optional dependency 'mfusepy')
- **Auto-fetch remotes periodically (experimental).** Enable this *Settings → Advanced → Auto-fetch remotes every N minutes.*

Quality of life improvements:

- FileList: Improve path readability by muting color of directory string (#77)
- GraphView context menu: Show branch name instead of "Reset HEAD to Here" (#71)
- GraphView context menu: Offer merging for any commit, not just branch tips (#74)
- Image diffs: Ability to toggle between old/new images
- Blame: Emphasize "new" lines with a different background color in the gutter
- Allow pressing the Escape key to quickly close detached diff/blame windows

Bug fixes:

- Fix impossible to open worktrees located in a subdirectory of a bare repo (#82)
- When a merge is blocked by untracked files that would be overwritten, show an error message (instead of denying the merge silently)

Maintenance:

- Continued from the work started in v1.5.0, more operations now use "standard" Git instead of libgit2. This should be transparent to most users; others may benefit from better interoperability with their Git setup. (Reworked operations include: Workdir Status, Commit Diffs, Export Patch, Blame/Revlist, Register/Remove Submodule, New Repository, Add/Remove/Edit Remote, Restore files after stashing)
- Some work on Windows compatibility (experimental)

## 1.5.0 (2025-09-08)

**Major change: Better integration with standard Git tooling.** GitFourchette now uses git instead of libgit2 to edit repositories and communicate with remotes. This enables seamless integration into workflows that depend on OpenSSH, hooks, etc.

The Flatpak version comes bundled with a Git distribution so you can use it without any additional setup. For more control, you can switch to your system's Git install via *Settings → Git Integration*.

New features:

- **GPG-sign your commits.** Look for a little key icon in the Commit Dialog. (#63)
- **Verify commit signatures in the commit history.** *Settings → Commit History → Verify signed commits on the fly*. (#59)

Quality of life improvements:

- Force push with lease (#61)
- Sidebar: Bold current commit and upstream (#60)
- Sidebar: Allow collapsing/expanding all folders from Local Branches context menu
- Keep syntax highlighting active while a search term is being highlighted
- In non-KDE environments (e.g. GNOME), the Return key can now be used to confirm most dialogs regardless of the focused widget (note: KDE already allowed this) (#68)

Bug fixes:

- Fix rendering of Unicode surrogate pairs in character-level diffs (#58)
- Fix parent commit links in Get Commit Info (regression in 1.4.0)

Breaking changes due to integration with Git tooling:

- Passphrase saving has been delegated to ssh-agent. Some Linux distros like Ubuntu and Fedora provide an ssh-agent out of the box. As a fallback, you can have GitFourchette spin up an ssh-agent for you via *Settings → Git Integration → ssh-agent*.
- Per-remote custom SSH keys aren't supported anymore. You can set per-host keys in *~/.ssh/config* to achieve the same effect; or, you can set per-repo custom SSH keys in *Repo → Repo Settings → Log in to SSH remotes with custom key file*.

Note: Although many commands now call git, libgit2 (via pygit2) is still used internally to build a model of the repo.

## 1.4.0 (2025-07-14)

New features:

- Blame/File History. Within GitFourchette, right-click any file and select "Blame File"; or, drag any file in your repo from your file manager and drop it onto the main window to view its history.

Quality of life improvements:

- An informative "drop zone" now appears when you drag an item from an external program over the main window. This tells you what will happen upon dropping the item (open repo folder, open repo containing a file, blame file in current repo, apply patch file, clone URL).
- CheckoutCommitDialog: Also offer Merge, Reset HEAD
- New branch/tag name validation: Friendly warning if attempting to create a folder with the same name as an existing ref
- CodeView: Toggling Word Wrap now preserves your scroll position in the document
- FileList: Reevaluate search term when jumping to another commit
- DiffGutter: Enable high-DPI custom cursor on Wayland

Bug fixes:

- Fix "Detect Renames" may unexpectedly switch to the workdir in rare cases
- Flatpak distribution: Updated to Pygments 2.19.2 to fix problems with Lua syntax highlighting

## 1.3.0 (2025-05-03)

**Upgrade note:** The terminal command template now requires the `$COMMAND` argument placeholder. Please review your terminal command in *Settings → External Tools → Terminal*.

New features:

- Custom terminal commands (Settings → Custom Commands) (#37).
- Sidebar: Hide All But This (#49). You can now show a single branch and hide all others.
- Add file to .gitignore or .git/info/exclude from untracked file context menu (#42)

Quality of life improvements:

- GraphView: Conjoined refboxes when a local branch is in sync with its upstream (#12)
- Add target branch shorthand to default merge commit message (#39)
- NewBranchDialog: Pre-tick upstream checkbox if branching off remote branch
- Report mandatory placeholder token errors when launching external tool commands
- Speed up remote listing and upstream lookup
- Fix Sidebar/DiffArea would sometimes jump around by a few pixels while temporary banners were shown
- Override Yaru icon theme's "scary" red warning icon (#27)
- More helpful message if Python bindings for QtSvg are missing

Bug fixes:

- Sidebar: Strip initial slash in nested RefFolder display names (#45)
- Fix Ctrl+G keyboard shortcut on GNOME
- Work around window snapping issue on GNOME (#50)

Two other bug fixes originally introduced in v1.2.0 had been dormant until now due to depending on a pygit2 version bump – they are now in full effect:

- Fix push progress wasn't reported properly during transfer (requires pygit2 1.18.0) (#22)
- Fix push couldn't be canceled once the transfer starts (requires pygit2 1.18.0) (#22)

## 1.2.1 (2025-03-05)

User-suggested quality of life improvements:

- GraphView: Copy commit message from context menu (#33)
- Rephrase some messages (diff too large, delete untracked file) (#27, #28)
- Add Ptyxis terminal preset (#18)

Other quality of life improvements:

- Friendlier messages related to 'autocrlf' and 'safecrlf' options (#30)
- Flatpak distribution: Detach terminal process from application
- Improve contrast between enabled/disabled SVG icons throughout the UI
- Pasting a multiline commit message into CommitDialog's summary input box will correctly split the message across the summary and description boxes

Bug fixes:

- Fix error when an external program converts line endings in the workdir with 'autocrlf' (#30)
- Flatpak distribution: Fix terminal spawned in incorrect working directory (#18)
- Flatpak distribution: Fix Flatpak tool existence check
- Gracefully handle destruction of parent widget of external tool processes

## 1.2.0 (2025-02-19)

New features:

- Open terminal in workdir (#18)

User-suggested quality of life improvements:

- Reword "Uncommitted changes" to "Working directory" to clear up any confusion when there are no changes (#13)
- Always display the number of uncommitted changes in the sidebar and in the graph; update this whenever the app returns to the foreground (#13)
- Reword "Discard Changes" context menu entry for untracked files to "Delete File" (#17)
- Global ref sorting setting (#20)
- Allow creating a merge commit without fast-forwarding (#21)
- Dark mode readability tweaks (#24)
- Command line: Open arbitrary nested paths in a repo (#25)

Other quality of life improvements:

- Improve consistency of ellipses in menus to signify that an action can be canceled
- Warn user if an external Flatpak isn't installed when attempting to run it (merge tool, terminals, etc.)
- Remind user about any unstaged files when about to create an empty commit
- Allow middle-clicking to quickly stage/unstage selected lines in DiffView (enable in Settings → Advanced → Middle-click)
- Allow clearing draft commit messages by right-clicking the top row in GraphView
- After pushing a branch that doesn't track an upstream, PushDialog will suggest the remote branch you used previously (instead of defaulting to the first one in the repo)
- Pulling will automatically fast-forward if possible without an extra confirmation step, unless your git config contains "pull.ff=false" (behavior aligned to vanilla git). If fast-forwarding isn't possible, you will still be prompted to merge.
- Push/fetch status text uses the 'tnum' OpenType feature to avoid transfer rate numbers jumping around if your system font has digits with uneven widths
- AppImage distribution now compatible with fuse3

Bug fixes:

- Fix crash when closing several repos in quick succession, e.g. by holding down Ctrl+W
- Fix clicking the help button used to close the fast-forward dialog
- Fix DiffView out of sync with rest of RepoWidget after hiding a the currently-selected branch tip
- Fix italics in sidebar didn't update after changing the current branch's upstream (a remote-tracking branch in italics means it's the upstream for the current branch)
- Fix visual artifacts around character-level diffs in DiffView
- Fix push progress wasn't reported properly during transfer (requires pygit2 1.18.0) (#22)
- Fix push couldn't be canceled once the transfer starts (requires pygit2 1.18.0) (#22)

Breaking changes:

- The keyboard shortcut for "Go to Working Directory" is now Ctrl+G (formerly Ctrl+U, for "Uncommitted Changes"). On most keyboard layouts, Ctrl+G pairs nicely with Ctrl+H for "Go to HEAD".

## 1.1.1 (2025-01-19)

New features:

- Option to remember passphrases in encrypted keyfiles (#15)

Quality of life improvements:

- Omit remote name from refboxes when there's just 1 remote (#11)
- Display blob hashes in FileList tooltips
- GraphView tries to use the 'tnum' OpenType feature to align ISO-8601 dates if your system font has digits with uneven widths
- In commit/filename SearchBars, don't re-trigger a search if appending to a word that is known to have no occurrences

Bug fixes:

- Fix custom key file feature in CloneDialog and AddRemote
- Fix remote branch context menu in a repo with an unborn head
- GraphSplicer: Fix discrete branch may vanish from graph if moved past another branch by topological sorting

## 1.1.0 (2025-01-05)

New features:

- Syntax highlighting with Pygments (optional dependency)

Quality of life improvements:

- Customizable ref indicator width (Settings → Commit History) (#10)
- Condensed fonts can be disabled (Settings → Advanced) (#10)
- Improved settings dialog UI

## 1.0.2 (2024-12-16)

Usability improvements:

- Support launching a Flatpak as an external diff/merge tool (#4)

Bug fixes:

- Fix web URLs in remote-tracking branch context menus (e.g. visit a branch on github.com)

## 1.0.1 (2024-12-03)

Quality of life improvements:

- Friendlier ConflictView UI
- Improve 3-way merging with external merge tools when there's no ancestor in the conflict
- Distinguish submodules and subtrees in SpecialDiff verbiage

Bug fixes:

- Fix discarding untracked non-submodule subtrees (#1)

## 1.0.0 (2024-11-16)

- First public release
