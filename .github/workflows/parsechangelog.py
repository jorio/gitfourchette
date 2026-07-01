#!/usr/bin/env python3

import os
import re
import datetime
import sys
from pathlib import Path


def parseChangelog():
    lines = Path("CHANGELOG.md").read_text().splitlines()

    bound1 = next(i for i, v in enumerate(lines) if v.startswith("## "))
    bound2 = next(i for i, v in enumerate(lines) if v.startswith("## ") and i > bound1)

    versionLine = lines[bound1]
    notes = "\n".join(lines[bound1+1:bound2]).strip()

    versionMatch = re.match(r"^## (\d(?:\.\d)+) \((20\d\d-\d\d-\d\d)\)", versionLine)
    version, versionDate = versionMatch.groups()

    # Make sure changelog date is close enough to now
    d1 = datetime.datetime.now(datetime.UTC)
    d2 = datetime.datetime.strptime(versionDate, "%Y-%m-%d")
    d2 = d2.replace(tzinfo=datetime.UTC, hour=12)  # assume changelog time is UTC noon
    hourDiff = abs(d1 - d2).total_seconds() / 3600
    if hourDiff >= 24+12:
        notes = f"# !!!!WARNING!!!! {round(hourDiff)}-hour diff to changelog date: {versionDate}\n\n" + notes

    return version, notes


def main():
    version, notes = parseChangelog()
    print(f"Extracted release notes for version {version}", file=sys.stderr)
    with Path(os.environ["GITHUB_OUTPUT"]).open('a') as githubOutput:
        githubOutput.write(f"releasetag=v{version}\n")
    Path("github_actions_release_notes.md").write_text(notes)


if __name__ == '__main__':
    main()
