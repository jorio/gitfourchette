#! /usr/bin/env python3

from pathlib import Path
import markdown
import re

def patchSection(path: Path, contents: str):
    def ensureNewline(s: str):
        return s + ("" if s.endswith("\n") else "\n")

    text = path.read_text("utf-8")
    contents = ensureNewline(contents)
    lines = contents.splitlines(keepends=True)
    assert len(lines) >= 2
    beginMarker = lines[0]
    endMarker = lines[-1]
    assert beginMarker
    assert endMarker

    beginPos = text.index(beginMarker)
    endPos = text.index(endMarker.rstrip())

    newText = (text[: beginPos] + contents + text[endPos + len(endMarker) :])
    path.write_text(newText, "utf-8")
    return newText

thisDir = Path(__file__).parent
changelogPath = thisDir / '../../CHANGELOG.md'
metainfoPath = thisDir / 'org.gitfourchette.gitfourchette.metainfo.xml'

changelogText = changelogPath.read_text('utf-8')
changelogSoup = markdown.markdown(changelogText)

releases = []

for soupLine in changelogSoup.splitlines():
    # Flatpak linter doesn't recognize <strong>, they'll reject the build if the changelog contains one
    soupLine = re.sub(r"<(/?)strong>", r"<\1em>", soupLine)

    if soupLine.startswith("<h"):
        if soupLine.startswith("<h1>"):
            continue
        ma = re.match(r"<h2>(\S+)\s+\((\d+-\d+-\d+)\)</h2>", soupLine)
        assert ma, f"Line does not match pattern: {soupLine}"
        version = ma.group(1)
        date = ma.group(2)
        releases.append(f'  <release version="{version}" date="{date}" type="stable">')
        releases.append(f'    <url>https://github.com/jorio/gitfourchette/releases/tag/v{version}</url>')
        releases.append( '    <description>')
        releases.append( '    </description>')
        releases.append( '  </release>')
    else:
        releases.insert(-2, (' ' * 6) + soupLine)

releases.insert(0, "<releases>")
releases.append("</releases>")
releases = ['  ' + r for r in releases]

patchSection(metainfoPath, "\n".join(releases))
print(f"Updated: {metainfoPath}")
