# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from .util import *


# Use mainWindow fixture to make sure the temp icon cache is properly reset
@pytest.mark.skipif(QT5, reason="Qt 5: can't specify devicePixelRatio in QIcon.pixmap()")
def testStockIconImgTagDpr(mainWindow):
    from gitfourchette.toolbox import iconbank

    def extractSrc(imgTag):
        return re.search(r"<img src='([^']+)'", imgTag).group(1)

    pixmap = QPixmap()

    # DPR=1 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=1)
    src = extractSrc(tag)
    assert src.startswith(qTempDir())
    pixmap.load(src)
    assert pixmap.size() == QSize(16, 16)
    srcDpr1 = src

    # DPR=1 cache hit
    tag = iconbank.stockIconImgTag("git-head", dpr=1)
    src = extractSrc(tag)
    assert src == srcDpr1

    # DPR=2 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=2)
    src = extractSrc(tag)
    srcDpr2 = src
    assert src.startswith(qTempDir())
    pixmap.load(src)
    assert pixmap.size() == QSize(32, 32)

    # DPR=2 cache hit
    tag = iconbank.stockIconImgTag("git-head", dpr=2)
    src = extractSrc(tag)
    assert src == srcDpr2

    # DPR=1.5 cache miss
    tag = iconbank.stockIconImgTag("git-head", dpr=1.5)
    src = extractSrc(tag)
    pixmap.load(src)
    assert pixmap.size() == QSize(24, 24)


@pytest.mark.parametrize("dpr", [1, 2])
def testStockIconImgTagSizeAndStandardIcon(mainWindow, dpr):
    from gitfourchette.toolbox import iconbank

    tag = iconbank.stockIconImgTag("SP_MessageBoxWarning", dpr=dpr, size=48)
    assert "width=48 height=48" in tag
    pixmap = QPixmap(re.search(r"<img src='([^']+)'", tag).group(1))
    assert not pixmap.isNull()
    if not QT5:  # Qt 5 can't pass devicePixelRatio to QIcon.pixmap()
        assert pixmap.size() == QSize(48 * dpr, 48 * dpr)
