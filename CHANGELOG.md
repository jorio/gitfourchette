# GitFourchette version history

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
