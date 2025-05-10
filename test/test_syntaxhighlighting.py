# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from .util import *

from gitfourchette.syntax import syntaxHighlightingAvailable, LexJobCache
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


def digestFormatRange(formatRange: QTextLayout.FormatRange):
    start = formatRange.start
    length = formatRange.length
    isStyled = formatRange.format.foreground().color() != QColor(Qt.GlobalColor.black)
    return (start, length, isStyled)


@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
def testDeferredSyntaxHighlighting(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Write sample code, with enough tokens to require a round-trip in LexJob
    writeFile(f"{wd}/hello.py", SAMPLE_CODE * 500)

    rw = mainWindow.openRepo(wd)

    commentLine = rw.diffView.document().findBlockByLineNumber(2)
    importLine = rw.diffView.document().findBlockByLineNumber(6)
    assert commentLine.text() == "hello multiline comment"
    assert importLine.text() == "from ark import Bird"

    assert not rw.diffView.highlighter.newLexJob.lexingComplete

    # Check low-quality lexing of comment line
    QTest.qWait(0)
    formatRange = commentLine.layout().formats()[0]
    assert digestFormatRange(formatRange) == (0, len("hello"), False)

    # Low-quality lexing of import line should suffice
    formatRange = importLine.layout().formats()[0]
    assert digestFormatRange(formatRange) == (0, len("from"), True)

    # Let LexJob finish its high-quality highlighting
    while not rw.diffView.highlighter.newLexJob.lexingComplete:
        QTest.qWait(0)
    QTest.qWait(0)  # Let highlighter respond

    # Now the inside of the multiline comment should be properly formatted
    formatRange = commentLine.layout().formats()[0]
    assert digestFormatRange(formatRange) == (0, len("hello multiline comment"), True)


@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
def testLexJobCaching(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/big.py", SAMPLE_CODE * 500)  # enough tokens to require LexJob round-trip
    writeFile(f"{wd}/small.py", SAMPLE_CODE * 4)
    writeFile(f"{wd}/zzempty.txt", "")

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    lexJobId = id(rw.diffView.highlighter.newLexJob)
    assert not rw.diffView.highlighter.newLexJob.lexingComplete
    while not rw.diffView.highlighter.newLexJob.scheduler.isActive():
        QTest.qWait(0)
    assert not rw.diffView.highlighter.newLexJob.lexingComplete

    # Switch away from DiffView, put LexJob on ice
    rw.jump(NavLocator.inUnstaged("zzempty.txt"), check=True)
    assert not rw.diffView.isVisible()
    assert not rw.diffView.highlighter.newLexJob.scheduler.isActive()

    # Switch back to DiffView, restore LexJob
    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    assert lexJobId == id(rw.diffView.highlighter.newLexJob)
    assert rw.diffView.highlighter.newLexJob.scheduler.isActive()

    # Change document in DiffView
    rw.jump(NavLocator.inUnstaged("small.py"), check=True)
    assert lexJobId != id(rw.diffView.highlighter.newLexJob)

    # Restore document
    rw.jump(NavLocator.inUnstaged("big.py"), check=True)
    assert rw.diffView.isVisible()
    assert lexJobId == id(rw.diffView.highlighter.newLexJob)


@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
def testEvictLexJobFromCache(tempDir, mainWindow):
    mainWindow.onAcceptPrefsDialog({ 'largeFileThresholdKB': 1e6 })

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

    # Remember which LexJob handles copy0000.py
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("copy0000.py"))
    lexJobId = id(rw.diffView.highlighter.newLexJob)

    # Check that jumping back and forth to copy0000.py reuses the cached LexJob
    rw.jump(NavLocator.inUnstaged("copy0001.py"), True)
    assert lexJobId != id(rw.diffView.highlighter.newLexJob)
    # Giant file that exceeds cache size shouldn't evict our old job
    rw.jump(NavLocator.inUnstaged("giantfile.py"), True)
    assert rw.diffView.isVisible()  # make we're not showing the "diff too large" message
    assert lexJobId != id(rw.diffView.highlighter.newLexJob)
    rw.jump(NavLocator.inUnstaged("copy0000.py"), True)
    assert lexJobId == id(rw.diffView.highlighter.newLexJob)

    # Start lexing every file.
    # Touching the last file should cause copy0000.py's LexJob to be evicted.
    for i in range(numCopies):
        rw.jump(NavLocator.inUnstaged(f"copy{i:04}.py"), check=True)

    # Jump back to copy0000.py
    # Should start a new LexJob because it's been evicted
    rw.jump(NavLocator.inUnstaged("copy0000.py"), check=True)
    assert lexJobId != id(rw.diffView.highlighter.newLexJob)


# Simple coverage test
@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
def testSyntaxHighlightingNullOid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd, write_index=True) as repo:
        writeFile(f"{wd}/hello.py", SAMPLE_CODE)
        repo.index.add_all()
        os.unlink(f"{wd}/hello.py")

    mainWindow.openRepo(wd)


# Simple coverage test
@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
def testSyntaxHighlightingEmptyOid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd, write_index=True) as repo:
        writeFile(f"{wd}/hello.py", "")
        repo.index.add_all()
        writeFile(f"{wd}/hello.py", SAMPLE_CODE)

    mainWindow.openRepo(wd)


@pytest.mark.skipif(not syntaxHighlightingAvailable, reason="pygments not available")
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
