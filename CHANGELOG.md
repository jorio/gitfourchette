# GitFourchette version history

## 1.1.1 (2025-01-19)

- Option to remember passphrases in encrypted keyfiles (#15)
- Omit remote name from refboxes when there's just 1 remote (#11)
- Display blob hashes in FileList tooltips
- Fix custom key file feature in CloneDialog and AddRemote
- Fix remote branch context menu in a repo with an unborn head
- GraphView tries to use the 'tnum' OpenType feature to align ISO-8601 dates if your system font has digits with uneven widths
- GraphSplicer: Fix discrete branch may vanish from graph if moved past another branch by topological sorting
- In commit/filename SearchBars, don't re-trigger a search if appending to a word that is known to have no occurrences

## 1.1.0 (2025-01-05)

- Syntax highlighting with Pygments (optional dependency)
- Customizable ref indicator width (Settings → Commit History) (#10)
- Condensed fonts can be disabled (Settings → Advanced) (#10)
- Improved settings dialog UI

## 1.0.2 (2024-12-16)

- Support launching a Flatpak as an external diff/merge tool (#4)
- Fix web URLs in remote-tracking branch context menus (e.g. visit a branch on github.com)

## 1.0.1 (2024-12-03)

- Friendlier ConflictView UI
- Improve 3-way merging with external merge tools when there's no ancestor in the conflict
- Distinguish submodules and subtrees in SpecialDiff verbiage
- Fix discarding untracked non-submodule subtrees (#1)

## 1.0.0 (2024-11-16)

- First public release
