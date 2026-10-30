# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pygit2
import pytest

from .util import *

from gitfourchette.gitdriver import GitDeltaFile
from gitfourchette.syntax import LexJobCache, LexJob, LexerCache
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


def testLexJobOutOfBoundsLine(tempDir, mainWindow):
    lexer = LexerCache.getLexerFromPath("hello.py", False)
    assert lexer is not None

    job = LexJob(lexer, "print('hello')\n", "out-of-bounds-line")
    job.start()
    while not job.lexingComplete:
        QTest.qWait(0)

    # A line within the lexed file is served from the high-quality token map.
    assert job.tokens(1, "print('hello')")

    # A line beyond the end of the lexed file must not raise KeyError.
    # (This can happen if the displayed document and the lexed file don't
    # have exactly the same number of lines.)
    assert job.tokens(999, "print('hello')")


def testLexJobMatchesUnstagedDiffSnapshot(tempDir, mainWindow):
    smallText = "hello = 0"
    largeText = "\n".join(f"hello = {i}" for i in range(5000))

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    # Enter threaded mode (like non-test environment). The first refresh may
    # generate a patch for the large file before the second write lands, which
    # used to leave a LexJob keyed by the large blob's hash but containing the
    # small file's contents.
    with AsynchronousTaskContext(rw.taskRunner):
        writeFile(f"{wd}/hello.py", largeText)
        rw.refreshRepo()

        writeFile(f"{wd}/hello.py", smallText)
        rw.refreshRepo()

    # Make sure we're displaying the final contents of the file.
    rw.jump(NavLocator.inUnstaged("hello.py"), check=True)

    diffDocument = rw.diffView.currentDiffDocument
    newLexJob = rw.diffView.highlighter.newLexJob
    assert newLexJob is not None
    assert diffDocument.newHash == str(pygit2.hash(smallText.encode()))
    assert newLexJob.fileKey == diffDocument.newHash
    assert newLexJob.fileSize == len(smallText)

    # The final contents are short, so the whole file should have been lexed
    # long before any request for line 999 (which the old buggy snapshot would
    # have tried to highlight).
    assert "hello = 0" in rw.diffView.toPlainText()


def testRegeneratePatchIfWorkdirChangesDuringLoad(tempDir, mainWindow, monkeypatch):
    smallText = "hello = 0"
    largeText = "\n".join(f"hello = {i}" for i in range(5000))
    smallHash = str(pygit2.hash(smallText.encode()))

    wd = unpackRepo(tempDir)
    path = f"{wd}/hello.py"
    writeFile(path, largeText)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("hello.py"), check=True)
    assert rw.diffView.currentDiffDocument.newHash == str(pygit2.hash(largeText.encode()))

    # Bump mtime without touching the contents, so that the next jump reloads
    # the patch (which will still be generated from the large file).
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    # Simulate the file being modified after `git diff` has read it, but before
    # LoadPatch reads it to prime the lexer.
    originalRead = GitDeltaFile.readWorkdirSnapshot
    snapshotCalls = []

    def racingRead(self, repo):
        if not snapshotCalls:
            writeFile(path, smallText)
        snapshotCalls.append(self.path)
        return originalRead(self, repo)

    monkeypatch.setattr(GitDeltaFile, "readWorkdirSnapshot", racingRead)
    rw.jump(NavLocator.inUnstaged("hello.py"), check=True)

    # The first patch (large file) must have been rejected and regenerated
    assert len(snapshotCalls) == 2

    # The displayed patch and the LexJob must both refer to the small file
    diffDocument = rw.diffView.currentDiffDocument
    newLexJob = rw.diffView.highlighter.newLexJob
    assert diffDocument.newHash == smallHash
    assert newLexJob is not None
    assert newLexJob.fileKey == smallHash
    assert newLexJob.fileSize == len(smallText)
    assert "hello = 4999" not in rw.diffView.toPlainText()


@pytest.mark.skipif(WINDOWS, reason="TODO: flaky on Windows")
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
