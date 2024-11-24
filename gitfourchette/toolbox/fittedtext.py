# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from math import ceil

from gitfourchette.qt import *

_condensedStretchPresets = [
    QFont.Stretch.SemiCondensed,  # 87
    QFont.Stretch.Condensed,  # 75
    QFont.Stretch(70),
    QFont.Stretch(66),
    QFont.Stretch.ExtraCondensed,  # 62
    QFont.Stretch(56),
    QFont.Stretch.UltraCondensed,  # 50
]

if MACOS:
    # WEIRD! SemiCondensed is actually wider than Unstretched with Mac system font (Qt 6.8.0, macOS 15)
    _condensedStretchPresets.remove(QFont.Stretch.SemiCondensed)

_defaultMinStretch = _condensedStretchPresets[0]


def fitText(
        wideFont: QFont,
        maxWidth: int,
        text: str,
        mode=Qt.TextElideMode.ElideRight,
        minStretch=_defaultMinStretch,
):
    metrics = QFontMetricsF(wideFont)
    width = ceil(metrics.horizontalAdvance(text))

    if width < 1:
        return text, wideFont, 0

    # Figure out upper bound for the stretch factor
    baselineStretch = int(100 * maxWidth / width)

    if baselineStretch >= 100:
        # No condensing needed - early out
        return text, wideFont, width

    baselineStretch = max(baselineStretch, minStretch)

    font = QFont(wideFont)
    for stretch in _condensedStretchPresets:
        # Skip stretch factors that are too wide
        if stretch > baselineStretch:
            continue

        # Don't stretch beyond user preference
        if stretch < minStretch:
            break

        font.setStretch(stretch)
        metrics = QFontMetricsF(font)

        width = ceil(metrics.horizontalAdvance(text))

        if width < maxWidth:
            return text, font, width

    # Still no room at most condensed preset, must elide the text
    text = metrics.elidedText(text, mode, maxWidth)
    width = metrics.horizontalAdvance(text)
    width = ceil(width)
    return text, font, width


def drawFittedText(
        painter: QPainter,
        rect: QRect,
        flags: Qt.AlignmentFlag,
        text: str,
        mode=Qt.TextElideMode.ElideRight,
        minStretch=_defaultMinStretch,
):
    wideFont = painter.font()
    text, font, width = fitText(wideFont, rect.width(), text, mode, minStretch)
    if font is wideFont:
        painter.drawText(rect, flags, text)
    else:
        painter.setFont(font)
        painter.drawText(rect, flags, text)
        painter.setFont(wideFont)
    return text, font, width
