# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from .util import *

from gitfourchette.syntax import LexJobCache, LexJob
from gitfourchette.nav import NavLocator

SAMPLE_CODE = """\
'''
hello multiline comment
such advanced lexing
'''

from ark import Bird

class Duck(Bird):
    def __init__(self, *args, **kwargs):
        print("quack")
"""


def formatRangeAt(block: QTextBlock, column: int) -> QTextLayout.FormatRange:
    return next(fr for fr in block.layout().formats() if fr.start <= column < fr.start + fr.length)


def testDeferredSyntaxHighlighting(tempDir, mainWindow, colorTheme):
    wd = unpackRepo(tempDir)

    # Write sample code, with enough tokens to require a round-trip in LexJob
    writeFile(f"{wd}/hello.py", SAMPLE_CODE * 500)

    rw = mainWindow.openRepo(wd)

    commentLine = rw.diffView.document().findBlockByLineNumber(2)
    importLine = rw.diffView.document().findBlockByLineNumber(6)
    defLine = rw.diffView.document().findBlockByLineNumber(9)
    assert commentLine.text() == "hello multiline comment"
    assert importLine.text() == "from ark import Bird"
    assert defLine.text() == "    def __init__(self, *args, **kwargs):"

    assert not rw.diffView.highlighter.newLexJob.lexingComplete

    # Color of a plain identifier ("args") in the current scheme (varies between light/dark themes)
    QTest.qWait(0)
    formatRange = formatRangeAt(defLine, defLine.text().index("args"))
    nameColor = formatRange.format.foreground().color()

    # Check low-quality lexing of comment line (lexed as plain identifiers)
    formatRange = formatRangeAt(commentLine, 0)
    assert formatRange.format.foreground().color() == nameColor

    # Low-quality lexing of import line should suffice
    formatRange = formatRangeAt(importLine, 0)
    assert (formatRange.start, formatRange.length) == (0, len("from"))
    assert formatRange.format.foreground().color() != nameColor

    # Let LexJob finish its high-quality highlighting
    while not rw.diffView.highlighter.newLexJob.lexingComplete:
        QTest.qWait(0)
    QTest.qWait(0)  # Let highlighter respond

    # Now the inside of the multiline comment should be properly formatted
    formatRange = commentLine.layout().formats()[0]
    assert (formatRange.start, formatRange.length) == (0, len("hello multiline comment"))
    assert formatRange.format.foreground().color() != nameColor


def testLexJobCaching(tempDir, mainWindow):
    GFApplication.applyPrefs(largeFileThresholdKB=0)

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/aaaa.empty", "")  # first file is empty to avoid starting a LexJob off the bat
    writeFile(f"{wd}/big.py", SAMPLE_CODE * 3000)  # enough tokens to require LexJob round-trip
    writeFile(f"{wd}/small.py", SAMPLE_CODE * 4)

    rw = mainWindow.openRepo(wd)

    def getNewLexJob() -> LexJob:
        return rw.diffView.highlighter.newLexJob

    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()

    # Remember which job handles big.py
    job = getNewLexJob()

    assert not getNewLexJob().lexingComplete
    waitUntilTrue(lambda: getNewLexJob().scheduler.isActive(), interval=0)
    assert not getNewLexJob().lexingComplete

    # Switch away from DiffView, put LexJob on ice
    rw.jump(NavLocator.inUnstaged("aaaa.empty"), check=True)
    assert not rw.diffView.isVisible()
    assert not getNewLexJob().scheduler.isActive()

    # Switch back to DiffView, restore LexJob
    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    assert job is getNewLexJob()
    assert getNewLexJob().scheduler.isActive()

    # Change document in DiffView
    rw.jump(NavLocator.inUnstaged("small.py"), check=True)
    assert job is not getNewLexJob()

    # Restore document
    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    assert job is getNewLexJob()


def testEvictLexJobFromCache(tempDir, mainWindow):
    GFApplication.applyPrefs(largeFileThresholdKB=1_000_000)
    assert not LexJobCache.cache
    assert LexJobCache.totalFileSize == 0

    wd = unpackRepo(tempDir)

    bigChunk = SAMPLE_CODE * 100
    bigChunk += "\n# Differentiator: XXXX"

    # Make one too many copies of the file to fit in LexJob cache
    numCopies = 1 + LexJobCache.MaxBudget // len(bigChunk)
    for i in range(numCopies):
        blobContents = bigChunk.removesuffix("XXXX") + f"{i:04}"
        writeFile(f"{wd}/copy{i:04}.py", blobContents)

    # Create a giant file that doesn't fit in cache
    writeFile(f"{wd}/giantfile.py", SAMPLE_CODE * (1 + LexJobCache.MaxBudget // len(SAMPLE_CODE)))

    rw = mainWindow.openRepo(wd)

    def getNewLexJob() -> LexJob:
        return rw.diffView.highlighter.newLexJob

    # Remember which LexJob handles copy0000.py
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("copy0000.py"))
    job = getNewLexJob()

    # Check that jumping back and forth to copy0000.py reuses the cached LexJob
    rw.jump(NavLocator.inUnstaged("copy0001.py"), True)
    assert job is not getNewLexJob()
    # Giant file that exceeds cache size shouldn't evict our old job
    rw.jump(NavLocator.inUnstaged("giantfile.py"), True)
    assert rw.diffView.isVisible()  # make we're not showing the "diff too large" message
    assert job is not getNewLexJob()
    rw.jump(NavLocator.inUnstaged("copy0000.py"), True)
    assert job is getNewLexJob()

    # Start lexing every file.
    # Touching the last file should cause copy0000.py's LexJob to be evicted.
    for i in range(numCopies):
        rw.jump(NavLocator.inUnstaged(f"copy{i:04}.py"), check=True)

    # Jump back to copy0000.py
    # Should start a new LexJob because it's been evicted
    rw.jump(NavLocator.inUnstaged("copy0000.py"), check=True)
    assert job is not getNewLexJob()


# Simple coverage test
def testSyntaxHighlightingNullOid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell(f"""
        echo {shlex.quote(SAMPLE_CODE)} > hello.py
        git add hello.py
        rm hello.py
    """, wd)

    mainWindow.openRepo(wd)


# Simple coverage test
def testSyntaxHighlightingEmptyOid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell(f"""
        touch hello.py
        git add hello.py
        echo {shlex.quote(SAMPLE_CODE)} > hello.py
    """, wd)

    mainWindow.openRepo(wd)


def testSyntaxHighlightingFillInFallbackTokenTypes(tempDir, mainWindow):
    # YAML has bespoke token types that aren't part of the standard Pygments token set,
    # e.g. Token.Literal.Scalar.Plain, Token.Punctuation.Indicator.
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/hello.yml", "- name: Hello\n")

    from gitfourchette.settings import prefs
    scheme = prefs.syntaxHighlightingScheme()
    numKnownTokens1 = len(scheme.highContrastScheme)

    mainWindow.openRepo(wd)
    numKnownTokens2 = len(scheme.highContrastScheme)
    assert numKnownTokens2 > numKnownTokens1


def testWhitespaceHighlighting(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    GFApplication.applyPrefs(showWhitespace=True)

    for space in [" ", "\t", "\xA0"]:
        writeFile(f"{wd}/hello.txt", f"hello{space}space\n")
        rw.refreshRepo()
        QTest.qWait(0)  # wait for syntax highlighting to finish

        doc: QTextDocument = rw.diffView.document()
        block = doc.findBlockByNumber(1)
        formatRanges = block.layout().formats()

        # In plain text files, the highlighter only applies formatting to
        # whitespace. Non-space text is not formatted. Make sure we apply
        # formatting to all kinds of whitespace rendered by ShowTabsAndSpaces.
        assert formatRanges
        for span in formatRanges:
            token = block.text()[span.start: span.start + span.length]
            assert token == space
