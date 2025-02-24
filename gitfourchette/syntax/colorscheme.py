# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations
from contextlib import suppress

from gitfourchette.qt import *
from gitfourchette.toolbox.qtutils import isDarkTheme
from gitfourchette.toolbox.benchmark import benchmark

try:
    import pygments.styles
    hasPygments = True
except ImportError:  # pragma: no cover
    hasPygments = False


class PygmentsPresets:
    Automatic = ""
    Off = "off"
    Light = "stata-light"
    Dark = "stata-dark"


class ColorScheme:
    fallbackScheme: ColorScheme = None
    _cachedScheme: ColorScheme = None
    _cachedPreviews: dict[str, str] = {}

    name: str
    backgroundColor: QColor
    foregroundColor: QColor
    scheme: dict
    highContrastScheme: dict

    def __init__(self):
        self.name = ""
        self.scheme = {}
        self.highContrastScheme = {}

        palette = QApplication.palette()
        self.backgroundColor = palette.color(QPalette.ColorRole.Base)
        self.foregroundColor = palette.color(QPalette.ColorRole.Text)

    def __bool__(self):
        return bool(self.scheme)

    def isDark(self):
        return self.backgroundColor.lightnessF() < .5

    def primeHighContrastVersion(self):
        """
        Prepare a high-contrast alternative where colors pop against red/green backgrounds
        """

        if self.highContrastScheme:
            return

        isDarkBackground = self.isDark()

        for tokenType, lowContrastCharFormat in self.scheme.items():
            charFormat = QTextCharFormat(lowContrastCharFormat)

            fgColor = charFormat.foreground().color()
            if isDarkBackground:
                fgColor = fgColor.lighter(150)
            else:
                fgColor = fgColor.darker(130)

            charFormat.setForeground(fgColor)
            charFormat.clearBackground()

            self.highContrastScheme[tokenType] = charFormat

    def basicQss(self, widget: QWidget):
        if not bool(self):
            return "/* NO PYGMENTS STYLE */"

        bg = self.backgroundColor.name()
        fg = self.foregroundColor.name()
        return f"{type(widget).__name__} {{ background-color: {bg}; color: {fg}; }}"

    @classmethod
    def resolve(cls, name: str) -> ColorScheme:
        if not hasPygments:  # pragma: no cover
            return cls.fallbackScheme

        # Resolve style alias
        if name == PygmentsPresets.Automatic:
            name = PygmentsPresets.Dark if isDarkTheme() else PygmentsPresets.Light
        if name == PygmentsPresets.Off:
            return cls.fallbackScheme

        if cls._cachedScheme.name == name:
            return cls._cachedScheme

        style = pygments.styles.get_style_by_name(name)

        scheme = ColorScheme()
        scheme.name = name
        scheme.backgroundColor = QColor(style.background_color)

        # Unpack style colors
        # (Intentionally skipping 'bgcolor' to prevent confusion with red/green backgrounds)
        for tokenType, styleForToken in style:
            charFormat = QTextCharFormat()
            if styleForToken['color']:
                assert not styleForToken['color'].startswith('#')
                color = QColor('#' + styleForToken['color'])
                charFormat.setForeground(color)
            if styleForToken['bold']:
                charFormat.setFontWeight(QFont.Weight.Bold)
            if styleForToken['italic']:
                charFormat.setFontItalic(True)
            if styleForToken['underline']:
                charFormat.setFontUnderline(True)
            scheme.scheme[tokenType] = charFormat

        with suppress(KeyError):
            scheme.foregroundColor = scheme.scheme[pygments.token.Token.Text].foreground().color()

        cls._cachedScheme = scheme
        return scheme

    @classmethod
    @benchmark
    def stylePreviews(cls, withPlugins: bool) -> dict[str, str]:
        if not hasPygments or cls._cachedPreviews:
            return cls._cachedPreviews

        # pygments.styles.STYLES appeared in Pygments 2.17,
        # but we're maintaining backwards compatibility with old Pygments versions for now.
        if not hasattr(pygments.styles, 'STYLES'):  # pragma: no cover
            withPlugins = True

        if withPlugins:
            allStyles = pygments.styles.get_all_styles()
        else:
            allStyles = (styleName for _dummy1, styleName, _dummy2 in pygments.styles.STYLES.values())

        def extractColor(style, *tokenTypes):
            for t in tokenTypes:
                with suppress(TypeError):
                    return QColor('#' + style.style_for_token(t)['color'])
            return QColor(Qt.GlobalColor.black)

        primary = {}
        secondary = {}

        for styleName in sorted(allStyles):
            style = pygments.styles.get_style_by_name(styleName)
            bgColor = QColor(style.background_color)
            accent1 = extractColor(style, pygments.token.Name.Class, pygments.token.Text)
            accent2 = extractColor(style, pygments.token.Name.Function, pygments.token.Operator)
            accent3 = extractColor(style, pygments.token.Keyword, pygments.token.Comment)

            # Little icon to preview the colors in this style (colorscheme-chip.svg)
            chipColors = f"black={bgColor.name()} white={accent1.name()} red={accent2.name()} blue={accent3.name()}"

            # Sort light and dark themes in separate tables
            dark = bgColor.lightnessF() < .5
            table = secondary if dark else primary
            table[styleName] = chipColors

        primary.update(secondary)
        cls._cachedPreviews = primary
        return primary

    @classmethod
    def refreshFallbackScheme(cls):
        fallbackScheme = cls()
        cls.fallbackScheme = fallbackScheme
        cls._cachedScheme = fallbackScheme


ColorScheme.refreshFallbackScheme()
