# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from .util import *

from gitfourchette.toolbox.iconbank import STOCK_ICON_URL_SCHEME, stockIconImgTag, stockIconResourceProvider


def extractPixmap(imgTag: str) -> QPixmap:
    src = re.search(r"<img src='([^']+)'", imgTag).group(1)

    assert QT_RESOURCE_PROVIDER_OK == src.startswith(STOCK_ICON_URL_SCHEME)
    if not QT_RESOURCE_PROVIDER_OK:  # PyQt5, PySide6 as of 11/2026 (PYSIDE-3518)
        assert not PYQT6, "PyQt6 should support this"
        assert src.startswith(qTempDir())
        assert src.endswith(".png")
        return QPixmap(src)

    return stockIconResourceProvider(QUrl(src))


# Use mainWindow fixture to make sure the temp icon cache is properly reset
@pytest.mark.skipif(not QT_RESOURCE_PROVIDER_OK,
                    reason="can't generate img tag pixmaps at render time with this Qt binding")
def testStockIconImgTagDpr(mainWindow, monkeypatch):
    # Set DPR=1
    monkeypatch.setattr(mainWindow, "devicePixelRatio", lambda: 1)

    # DPR=1 cache miss
    tag = stockIconImgTag("git-head")
    pix = extractPixmap(tag)
    assert pix.size() == QSize(16, 16)
    assert pix.devicePixelRatio() == 1.0
    pix1 = pix

    # DPR=1 cache hit
    tag = stockIconImgTag("git-head")
    pix = extractPixmap(tag)
    assert pix is pix1

    # Set DPR=2
    monkeypatch.setattr(mainWindow, "devicePixelRatio", lambda: 2)

    # DPR=2 cache miss
    tag = stockIconImgTag("git-head")
    pix = extractPixmap(tag)
    assert pix is not pix1
    assert pix.size() == QSize(32, 32)
    assert pix.devicePixelRatio() == 2.0
    pix2 = pix

    # DPR=2 cache hit
    tag = stockIconImgTag("git-head")
    pix = extractPixmap(tag)
    assert pix is pix2

    # Set DPR=1.5
    monkeypatch.setattr(mainWindow, "devicePixelRatio", lambda: 1.5)

    # DPR=1.5 cache miss
    tag = stockIconImgTag("git-head")
    pix = extractPixmap(tag)
    assert pix is not pix1
    assert pix is not pix2
    assert pix.size() == QSize(24, 24)
    assert pix.devicePixelRatio() == 1.5


def testStockIconImgTagStandardIcon(mainWindow, monkeypatch):
    # Qt 5 can't pass devicePixelRatio to QIcon.pixmap()
    ratios = [1] if not QT_RESOURCE_PROVIDER_OK else [1.0, 1.5, 2.0]

    for dpr in ratios:
        monkeypatch.setattr(mainWindow, "devicePixelRatio", lambda r=dpr: r)

        tag = stockIconImgTag("SP_MessageBoxWarning", size=48)
        pixmap = extractPixmap(tag)

        # We can't rely on system-provided icons to come out at the requested
        # size or DPR, so don't check those in the pixmap, otherwise the test
        # might fail on "legacy" runners. The icon is stretched to the desired
        # size via the width & height attributes in the img tag.
        assert "width=48 height=48" in tag
        assert pixmap is not None
        assert not pixmap.isNull()
