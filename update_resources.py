#! /usr/bin/env python3
# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import argparse
import datetime
import difflib
import os
import re
import subprocess
import sys
import textwrap
from contextlib import suppress
from pathlib import Path

import pygit2

REPO_ROOTDIR = os.path.dirname(os.path.realpath(sys.argv[0]))
REPO_ROOTDIR = os.path.relpath(REPO_ROOTDIR)
SRC_DIR = os.path.join(REPO_ROOTDIR, "gitfourchette")
ASSETS_DIR = os.path.join(SRC_DIR, "assets")
LANG_DIR = os.path.join(ASSETS_DIR, "lang")
LANG_TEMPLATE = os.path.join(LANG_DIR, "gitfourchette.pot")

FORCE = False


def makeParser():
    parser = argparse.ArgumentParser(description="Update GitFourchette assets")

    parser.add_argument("-f", "--force", action="store_true",
                        help="skip mtime and equality checks before regenerating an asset")

    parser.add_argument("-V", "--version", action="store_true",
                        help="show tool versions and exit")

    loc_group = parser.add_argument_group("Localization options")

    loc_group.add_argument("--pot", action="store_true",
                           help="sync .pot template with new strings from python code")

    loc_group.add_argument("--po", action="store_true",
                           help="sync translatable .po files with .pot template")

    loc_group.add_argument("--mo", action="store_true",
                           help="compile .po files to .mo so you can try them in GitFourchette")

    loc_group.add_argument("-l", "--lang", action="store_true",
                           help="sync all .pot/.po/.mo files (run all localization steps above)")

    loc_group.add_argument("--clean-po", action="store_true",
                           help="remove obsolete strings from .po files")

    ui_group = parser.add_argument_group("UI Designer options")

    ui_group.add_argument("-u", "--ui", action="store_true",
                          help="update ui_*.py files from .ui files (and svg status icons)")

    ui_group.add_argument("--uic", default="pyuic6",
                          help="path to Python-compatible uic tool ('pyuic6' by default; AVOID 'pyside6-uic' because its output doesn't work with PyQt6)")

    ui_group.add_argument("--no-uic-cleanup", action="store_true",
                          help="don't postprocess uic output")

    pkg_group = parser.add_argument_group("Packaging options")

    pkg_group.add_argument("--freeze", default="", metavar="QT_API",
                           help="write frozen constants to appconsts.py")

    return parser


def call(*args, **kwargs) -> subprocess.CompletedProcess:
    cmdstr = ""
    for token in args:
        cmdstr += " "
        if " " in token:
            cmdstr += F"\"{token}\""
        else:
            cmdstr += token
    print(F">{cmdstr}")

    capture_output = kwargs.pop("capture_output", True)
    check = kwargs.pop("check", True)
    try:
        return subprocess.run(args, encoding='utf-8', capture_output=capture_output, check=check, **kwargs)
    except subprocess.CalledProcessError as e:
        print(F"Aborting setup because: {e}")
        sys.exit(1)


def writeIfDifferent(path: Path, text: str, ignoreChangedLines=None):
    ignoreChangedLines = ignoreChangedLines or []
    needRewrite = True

    if not FORCE and path.is_file():
        ignoreList = []
        for icl in ignoreChangedLines:
            ignoreList.append("+ " + icl)
            ignoreList.append("- " + icl)

        # See if the differences can be ignored (e.g. Qt User Interface Compiler version comment)
        oldText = path.read_text(encoding="utf-8")
        needRewrite = False
        if oldText != text:
            t1 = oldText.splitlines(keepends=True)
            t2 = text.splitlines(keepends=True)
            for dl in difflib.ndiff(t1, t2):
                if (dl.rstrip() not in ["+", "-"]  # pure whitespace change
                        and not dl.startswith(tuple(ignoreList))
                        and dl.startswith(("+ ", "- "))):
                    needRewrite = True
                    break

    if needRewrite:
        path.write_text(text, encoding="utf-8")
        print("Wrote", path)
    else:
        path.touch()


def patchSection(path: Path, contents: str):
    def ensureNewline(s: str):
        return s + ("" if s.endswith("\n") else "\n")

    text = path.read_text(encoding="utf-8")
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
    writeIfDifferent(path, newText)
    return newText


def writeStatusIcon(fill='#ff00ff', char='X', round=2):
    for suffix, color in (["", "white"], ["@dark", "black"]):
        svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>\n"
        svg += f"<rect rx='{round}' ry='{round}' x='0.5' y='0.5' width='15' height='15' stroke='{color}' stroke-width='1' fill='{fill}'/>\n"
        svg += f"<text x='8' y='12' font-weight='bold' font-size='11' font-family='sans-serif' text-anchor='middle' fill='{color}'>{char}</text>\n"
        svg += "</svg>"
        svgPath = Path(ASSETS_DIR) / f"icons/status_{char.lower()}{suffix}.svg"
        writeIfDifferent(svgPath, svg)


def compileUi(uic: str, uiPath: Path, pyPath: Path, force=False, cleanupOutput=True):
    if not force:
        with suppress(FileNotFoundError):
            if pyPath.stat().st_mtime > uiPath.stat().st_mtime:
                return

    result = call(uic, uiPath.name, cwd=uiPath.parent)
    text = result.stdout
    nukePatterns = []
    ignoreDiffs = []

    myImport = "from gitfourchette.localization import *\nfrom gitfourchette.qt import *"

    if not cleanupOutput:
        pass
    elif "from PyQt" in text:
        text = re.sub(r"^from PyQt[56] import .+$", myImport, text, count=1, flags=re.M)
        text = re.sub(r"_translate(?=\(\")", "_p", text, flags=re.M)
        nukePatterns = [
            r"(?<!\w)Qt(Core|Gui|Widgets)\.",
            r"^\s+_translate = QCoreApplication\.translate\n",
        ]
        ignoreDiffs = ["# Created by: PyQt6 UI code generator"]
        text = text.strip() + "\n"
    elif "from PySide" in text:
        text = re.sub(r"^from PySide6.* import \([^\)]+\)$", myImport, text, count=1, flags=re.M)
        text = re.sub(r"QCoreApplication\.translate\((.+), None\)", r"_p(\1)", text, flags=re.M)
        nukePatterns = [
            r"^#if QT_CONFIG\(.+\n",
            r"^#endif // QT_CONFIG\(.+\n",
            r"^from PySide6.* import \([^\)]+\)$\n",
            r"^ {4}# (setupUi|retranslateUi)$\n",
        ]
        ignoreDiffs = ["## Created by: Qt User Interface Compiler version"]
        text = text.strip() + "\n"
    else:
        print("Unknown uic output")

    for pattern in nukePatterns:
        text = re.sub(pattern, "", text, flags=re.M)

    writeIfDifferent(pyPath, text, ignoreDiffs)


def compileUiFiles(uic, force, cleanupOutput):
    for uiPath in Path(SRC_DIR).glob("**/*.ui"):
        pyPath = uiPath.parent / f"ui_{uiPath.stem}.py"
        compileUi(uic, uiPath, pyPath, force=force, cleanupOutput=cleanupOutput)

    for pyPath in Path(SRC_DIR).glob("**/ui_*.py"):
        uiPath = pyPath.parent / (pyPath.stem.removeprefix("ui_") + ".ui")
        if not uiPath.exists():
            print("[!] Removing obsolete compiled ui file because there's no matching designer file:", pyPath)
            pyPath.unlink()


def generateIcons():
    # Generate status icons.
    # 'U' (unmerged) has custom colors/text, so don't generate it automatically.
    # 'C' (copied) doesn't appear in GitFourchette.
    writeStatusIcon('#0EDF00', 'A')  # add
    writeStatusIcon('#FE635F', 'D')  # delete
    writeStatusIcon('#F7C342', 'M')  # modify
    writeStatusIcon('#D18DE1', 'R')  # rename
    writeStatusIcon('#85144B', 'T')  # typechange
    writeStatusIcon('#ff00ff', 'X')  # unknown


def updatePotTemplate():
    """ Update .pot files from strings contained in the source code """
    # Gather all .py files
    pyFiles = [str(f.relative_to(SRC_DIR)) for f in Path(SRC_DIR).glob("**/*.py")]
    pyFiles.sort()
    call(
        "xgettext",
        "--output=" + LANG_TEMPLATE,
        "--sort-by-file",
        "--no-wrap",
        "--language=Python",
        "--from-code=UTF-8",
        "--keyword=_n:1,2",
        "--keyword=_p:1c,2",
        "--keyword=_np:1c,2,3",
        "--directory=" + SRC_DIR,
        "--package-name=GitFourchette",
        "--msgid-bugs-address=https://github.com/jorio/gitfourchette/issues",
        *pyFiles,
        capture_output=False,
    )

    nukePatterns = [
        r"^# SOME DESCRIPTIVE TITLE\.\n",
        r"^# Copyright .C. YEAR THE PACKAGE'S COPYRIGHT HOLDER\n",
        r"^# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR\.\n",
        r'^"POT-Creation-Date: .+"\n',
        r'^"PO-Revision-Date: .+"\n',
        r'^"Language-Team: .+"\n',
    ]
    text = Path(LANG_TEMPLATE).read_text(encoding="utf-8")
    for pattern in nukePatterns:
        text = re.sub(pattern, "", text, flags=re.M)
    Path(LANG_TEMPLATE).write_text(text, "utf-8")



def updatePoFiles():
    """ Update .po files from strings contained in the .pot template """
    for poPath in Path(LANG_DIR).glob("*.po"):
        call(
            "msgmerge",
            "--update",
            "--sort-by-file",
            "--no-wrap",
            str(poPath),
            LANG_TEMPLATE,
            capture_output=False)


def cleanUpPoFiles():
    """ Remove obsolete strings from .po files """
    for poPath in Path(LANG_DIR).glob("*.po"):
        call(
            "msgattrib",
            "--sort-by-file",
            "--no-wrap",
            "--no-obsolete",
            "-o", str(poPath),
            str(poPath),
            capture_output=False)


def compileMoFiles():
    """ Generate .mo files from .po files """
    for poPath in Path(LANG_DIR).glob("*.po"):
        moPath: Path = poPath.with_suffix(".mo")

        call("msgfmt", "-o", str(moPath), str(poPath), capture_output=False)

        if moPath.stat().st_size < 1000:
            print(f"*** Removing '{moPath.name}' -- looks like a stub.")
            moPath.unlink()


def writeFreezeFile(qtApi: str):
    repo = pygit2.Repository(SRC_DIR)
    headCommit = repo.head.target

    buildDate = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    freezeText = textwrap.dedent(f"""\
        # BEGIN_FREEZE_CONSTS
        ####################################
        # Do not commit these changes!
        ####################################

        APP_FREEZE_COMMIT = "{headCommit}"
        APP_FREEZE_DATE = "{buildDate}"
        APP_FREEZE_QT = "{qtApi.lower()}"
        # END_FREEZE_CONSTS""")
    patchSection(Path(SRC_DIR) / 'appconsts.py', freezeText)


if __name__ == '__main__':
    args = makeParser().parse_args()

    FORCE = args.force

    if args.lang:
        args.pot = True
        args.po = True
        args.mo = True

    if args.version:
        toolVersions = ""
        toolVersions += args.uic + " " + call(args.uic, "--version").stdout
        toolVersions += call("msgmerge", "--version").stdout.splitlines()[0]
        print(toolVersions)
        sys.exit(0)

    if args.freeze:
        writeFreezeFile(args.freeze)

    if not (args.ui or args.pot or args.po or args.mo or args.clean_po):
        makeParser().print_usage()
        sys.exit(1)

    # Generate .py files from .ui files
    if args.ui:
        generateIcons()
        compileUiFiles(args.uic, args.force, not args.no_uic_cleanup)

    if args.pot:
        updatePotTemplate()

    if args.po:
        updatePoFiles()

    if args.mo:
        compileMoFiles()

    if args.clean_po:
        cleanUpPoFiles()
