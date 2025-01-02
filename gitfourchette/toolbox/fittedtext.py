# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from math import ceil

from gitfourchette.qt import *

class FittedText:
    enable = True

    stretchPresets = [
        QFont.Stretch.SemiCondensed,  # 87
        QFont.Stretch.Condensed,  # 75
        QFont.Stretch(70),
        QFont.Stretch(66),
        QFont.Stretch.ExtraCondensed,  # 62
        QFont.Stretch(56),
        QFont.Stretch.UltraCondensed,  # 50
    ]

    if MACOS:
        # WEIRD! SemiCondensed is actually wider than Unstretched
        # with Mac system font (Qt 6.8.0, macOS 15)
        stretchPresets.remove(QFont.Stretch.SemiCondensed)

    defaultStretchLimit = stretchPresets[0]

    @classmethod
    def fit(
            cls,
            wideFont: QFont,
            maxWidth: int,
            text: str,
            mode=Qt.TextElideMode.ElideRight,
            limit=defaultStretchLimit,
    ) -> tuple[str, QFont, int]:
        metrics = QFontMetricsF(wideFont)
        width = ceil(metrics.horizontalAdvance(text))

        if width < 1:
            return text, wideFont, 0

        if not cls.enable:
            font = wideFont
        else:
            # Figure out upper bound for the stretch factor
            baselineStretch = int(100 * maxWidth / width)

            if baselineStretch >= 100:
                # No condensing needed - early out
                return text, wideFont, width

            baselineStretch = max(baselineStretch, limit)

            font = QFont(wideFont)
            for stretch in cls.stretchPresets:
                # Skip stretch factors that are too wide
                if stretch > baselineStretch:
                    continue

                # Don't stretch beyond user preference
                if stretch < limit:
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

    @classmethod
    def draw(
            cls,
            painter: QPainter,
            rect: QRect,
            flags: Qt.AlignmentFlag,
            text: str,
            mode=Qt.TextElideMode.ElideRight,
            minStretch=defaultStretchLimit,
    ) -> tuple[str, QFont, int]:
        wideFont = painter.font()
        text, font, width = cls.fit(wideFont, rect.width(), text, mode, minStretch)
        if font is wideFont:
            painter.drawText(rect, flags, text)
        else:
            painter.setFont(font)
            painter.drawText(rect, flags, text)
            painter.setFont(wideFont)
        return text, font, width
