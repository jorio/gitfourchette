# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

def versiontuple(s: str) -> tuple[int, ...]:
    v = []
    for n in s.split("."):
        try:
            v.append(int(n))
        except ValueError:
            v.append(0)
    # Trim trailing zeros to ease comparison
    while v and v[-1] == 0:
        v.pop()
    return tuple(v)
