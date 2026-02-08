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
    assert src.startswith("assets:icons/")
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

