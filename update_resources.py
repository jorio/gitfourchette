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
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

import pygit2

REPO_ROOTDIR = os.path.dirname(os.path.realpath(sys.argv[0]))
REPO_ROOTDIR = os.path.relpath(REPO_ROOTDIR)
SRC_DIR = os.path.join(REPO_ROOTDIR, "gitfourchette")
ASSETS_DIR = os.path.join(SRC_DIR, "assets")
LANG_DIR = os.path.join(ASSETS_DIR, "lang")

FORCE = False


def makeParser():
    parser = argparse.ArgumentParser(description="Update GitFourchette assets")

    parser.add_argument("--force", action="store_true",
                        help="skip mtime and equality checks before regenerating an asset")

    parser.add_argument("--lang", action="store_true",
                        help="update .ts/.qm files")

    parser.add_argument("--clean-lang", action="store_true",
                        help="update .ts/.qm files without source code info")

    parser.add_argument("--ui", action="store_true",
                        help="update UI files")

    parser.add_argument("--lupdate", default="pyside6-lupdate",
                        help="path to Python-compatible lupdate tool ('pyside6-lupdate' by default, 'pylupdate6' NOT supported)")

    parser.add_argument("--lrelease", default="pyside6-lrelease",
                        help="path to lrelease tool ('pyside6-lrelease' by default; standard Qt 'lrelease' also supported.)")

    parser.add_argument("--uic", default="pyuic6",
                        help="path to Python-compatible uic tool ('pyuic6' by default; AVOID 'pyside6-uic' because its output doesn't work with PyQt6)")

    parser.add_argument("--no-uic-cleanup", action="store_true",
                        help="don't postprocess uic output")

    parser.add_argument("--version", action="store_true",
                        help="show tool versions and exit")

    parser.add_argument("--freeze", default="", metavar="QT_API",
                        help="write frozen constants to appconsts.py and exit")

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


def writeIfDifferent(path, text, ignoreChangedLines=None):
    ignoreChangedLines = ignoreChangedLines or []
    needRewrite = True

    if not FORCE:
        ignoreList = []
        for icl in ignoreChangedLines:
            ignoreList.append("+ " + icl)
            ignoreList.append("- " + icl)

        if os.path.isfile(path):
            with open(path, encoding="utf-8") as existingFile:
                oldText = existingFile.read()

            # See if the differences can be ignored (e.g. Qt User Interface Compiler version comment)
            needRewrite = False
            if oldText != text:
                needRewrite = False
                t1 = oldText.splitlines(keepends=True)
                t2 = text.splitlines(keepends=True)
                for dl in difflib.ndiff(t1, t2):
                    if (dl.rstrip() not in ["+", "-"]  # pure whitespace change
                            and not dl.startswith(tuple(ignoreList))
                            and dl.startswith(("+ ", "- "))):
                        needRewrite = True
                        break

    if needRewrite:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            print("Wrote", path)
    else:
        Path(path).touch()


def patchSection(path: str, contents: str):
    def ensureNewline(s: str):
        return s + ("" if s.endswith("\n") else "\n")

    with open(path, encoding="utf-8") as f:
        text = f.read()

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
        svgFileName = F"{ASSETS_DIR}/icons/status_{char.lower()}{suffix}.svg"
        writeIfDifferent(svgFileName, svg)


def compileUi(uic, uiPath, pyPath, force=False, cleanupOutput=True):
    if not force:
        with suppress(FileNotFoundError):
            uiStat = os.stat(uiPath)
            pyStat = os.stat(pyPath)
            if pyStat.st_mtime > uiStat.st_mtime:
                return

    result = call(uic, os.path.basename(uiPath), cwd=os.path.dirname(uiPath))
    text = result.stdout
    ignoreDiffs = []

    if not cleanupOutput:
        pass
    elif "from PyQt" in text:
        text = re.sub(r"^from PyQt[56] import .+$", "from gitfourchette.qt import *", text, count=1, flags=re.M)
        text = re.sub(r"(?<!\w)Qt(Core|Gui|Widgets)\.", "", text, flags=re.M)
        text = text.strip() + "\n"
        ignoreDiffs = ["# Created by: PyQt5 UI code generator",
                       "# Created by: PyQt6 UI code generator",]
    elif "from PySide" in text:
        text = re.sub(r"^# -\*- coding:.*$", "", text, flags=re.M)
        text = re.sub(r"^from PySide6.* import \([^\)]+\)$", "from gitfourchette.qt import *", text, count=1, flags=re.M)
        for nukePattern in [
                r"^# -\*- coding:.*$",
                r"^from PySide6.* import \([^\)]+\)$\n",
                r"^ {4}# (setupUi|retranslateUi)$\n",
        ]:
            text = re.sub(nukePattern, "", text, flags=re.M)
        ignoreDiffs = ["## Created by: Qt User Interface Compiler version"]
    else:
        print("Unknown uic output")

    writeIfDifferent(pyPath, text, ignoreDiffs)


def updateTsFiles(lupdate, clean):
    """ Update .ts files from strings contained in the source code """
    for file in os.listdir(LANG_DIR):
        if not file.endswith(".ts"):
            continue

        filePath = os.path.join(LANG_DIR, file)

        opts = "-extensions py,ui"
        if clean:
            opts += " -no-ui-lines -no-obsolete -locations none"

        call(lupdate, *opts.split(), SRC_DIR, "-ts", filePath, capture_output=False)

    cleanUpEnglishFile(os.path.join(LANG_DIR, "gitfourchette_en.ts"))

    if not clean:
        print("""
    *******************************************************************************
    You are using --lang, which generates extra info in the .ts files.
    Before committing the .ts files, please clean them up by running
    this script again with --clean-lang.
    *******************************************************************************
    """)


def cleanUpEnglishFile(filePath):
    """ Post-process English .ts file for compatibility with Weblate """
    xml = ET.parse(filePath)

    for messageTag in xml.getroot().findall('context/message'):
        sourceText = messageTag.findtext('source').strip()
        translationTag = messageTag.find('translation')

        # Skip numerus strings. Those must be manually translated.
        if translationTag.find('numerusform') is not None:
            continue

        assert translationTag.text in [None, sourceText], \
            f"English text mismatch: {translationTag.text} // {sourceText}"

        translationTag.text = sourceText

        # Remove type='unfinished'
        with suppress(KeyError):
            translationTag.attrib.pop('type')

    text = ET.tostring(xml.getroot(), "unicode")
    text = '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n' + text
    Path(filePath).write_text(text, "utf-8")


def updateQmFiles(lrelease):
    """Generate .qm files from .ts files"""

    anyPlaceholderMismatches = False
    for file in os.listdir(LANG_DIR):
        if not file.endswith(".ts"):
            continue

        filePath = os.path.join(LANG_DIR, file)
        basename = os.path.splitext(file)[0]
        qmPath = os.path.join(LANG_DIR, F"{basename}.qm")
        call(lrelease, "-removeidentical", filePath, "-qm", qmPath)

        # Check placeholders in .ts files
        for messageTag in ET.parse(filePath).getroot().findall('context/message'):
            sourceText = messageTag.findtext('source')
            sourcePlaceholders = set(re.findall(r"\{.*?\}", sourceText))
            if not sourcePlaceholders:
                continue

            translationText = messageTag.findtext('translation').strip()
            if translationText:
                translations = [translationText]
            else:
                translations = [t.text for t in messageTag.find('translation') if t.text and t.text.strip()]

            for tt in translations:
                translationPlaceholders = set(re.findall(r"\{.*?\}", tt))
                missingPlaceholders = sourcePlaceholders - translationPlaceholders
                if translationPlaceholders != sourcePlaceholders:
                    anyPlaceholderMismatches = True
                    print(f"******* {file}: PLACEHOLDER MISMATCH! "
                          f"Missing: {' '.join(s for s in missingPlaceholders)} "
                          f"in: \"{tt}\"")

    if anyPlaceholderMismatches:
        print("""
    *******************************************************************************
    THE TRANSLATION FILES CONTAIN MISMATCHED PLACEHOLDERS.
    PLEASE REVIEW THE TRANSLATIONS BEFORE COMMITTING!
    *******************************************************************************
    """)


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

    if args.version:
        toolVersions = ""
        toolVersions += call(args.uic, "--version").stdout
        toolVersions += call(args.lupdate, "-version").stdout
        toolVersions += call(args.lrelease, "-version").stdout
        print(toolVersions)
        sys.exit(0)

    if args.freeze:
        writeFreezeFile(args.freeze)
        sys.exit(0)

    # Generate status icons.
    # 'U' (unmerged) has custom colors/text, so don't generate it automatically.
    # 'C' (copied) doesn't appear in GitFourchette.
    writeStatusIcon('#0EDF00', 'A')  # add
    writeStatusIcon('#FE635F', 'D')  # delete
    writeStatusIcon('#F7C342', 'M')  # modify
    writeStatusIcon('#D18DE1', 'R')  # rename
    writeStatusIcon('#85144B', 'T')  # typechange
    writeStatusIcon('#ff00ff', 'X')  # unknown

    # Generate .py files from .ui files
    if args.ui:
        for root, _, files in os.walk(SRC_DIR):
            for file in files:
                basename = os.path.splitext(file)[0]
                fullpath = os.path.join(root, file)

                if file.endswith(".ui"):
                    compileUi(args.uic, fullpath, F"{root}/ui_{basename}.py", force=args.force, cleanupOutput=not args.no_uic_cleanup)
                elif re.match(r"^ui_.+\.py$", file) and \
                        not os.path.isfile(F"{root}/{basename.removeprefix('ui_')}.ui"):
                    print("[!] Removing generated UI source file because there's no matching designer file:", fullpath)
                    os.unlink(fullpath)

    if args.lang or args.clean_lang:
        updateTsFiles(args.lupdate, args.clean_lang)
        updateQmFiles(args.lrelease)
