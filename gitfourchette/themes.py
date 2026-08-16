# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Built-in "Modern" look: a flat, roomy theme that doesn't depend on the
desktop environment's widget style.

A theme is a bunch of color tokens (ThemeColors). The tokens feed both a
QPalette (for everything Qt draws natively, including custom item delegates)
and assets/style-modern.qss (for metrics, rounded corners and hover states
that a palette can't express).
"""

from __future__ import annotations

import dataclasses
import enum
from contextlib import suppress
from pathlib import Path
from string import Template

from gitfourchette.qt import *
from gitfourchette.toolbox import mixColors


class AppTheme(enum.StrEnum):
    """
    Our built-in themes. These share the Prefs.qtStyle namespace with the
    native Qt style names (Breeze, Fusion, Windows...), so their values must
    not collide with anything QStyleFactory may return.
    """

    Modern = "modern"
    ModernLight = "modern-light"
    ModernDark = "modern-dark"

    @classmethod
    def isOurs(cls, styleName: str) -> bool:
        """True if a Prefs.qtStyle value refers to one of our themes."""
        return styleName in (cls.Modern, cls.ModernLight, cls.ModernDark)


@dataclasses.dataclass(frozen=True)
class ThemeColors:
    bg: str
    surface: str
    altRow: str
    border: str
    text: str
    accent: str
    onAccent: str
    hover: str
    selInactive: str
    button: str
    scrollHandle: str
    tooltipBg: str
    tooltipText: str
    danger: str

    @classmethod
    def resolveTheme(cls, styleName: str, standardAccent: QColor | None = None) -> ThemeColors | None:
        """
        Return the color tokens for one of our themes.

        Returns None if styleName isn't ours, i.e. it names a native Qt style or
        it's empty (system default) - in that case we don't touch the palette.
        """

        if styleName == AppTheme.ModernDark:
            dark = True
        elif styleName == AppTheme.ModernLight:
            dark = False
        elif styleName == AppTheme.Modern:
            try:
                appScheme = QGuiApplication.styleHints().colorScheme()
                dark = appScheme == Qt.ColorScheme.Dark
            except AttributeError:  # Qt < 6.5
                dark = False
        else:
            return None

        theme = MODERN_DARK if dark else MODERN_LIGHT
        accent = standardAccent.name() if standardAccent else ""
        if accent:
            theme = dataclasses.replace(theme, accent=accent)

        return theme

    @classmethod
    def bestStyleEngine(cls) -> str:
        """
        Return the name of the Qt style engine upon which to base custom themes,
        as a lowercase string. Favor "breeze", if available, for better-looking
        menus (with drop shadows and rounded corners) that "fusion" cannot do.
        """
        hasBreeze = any(key.lower() == "breeze" for key in QStyleFactory.keys())  # noqa: SIM118
        return "breeze" if hasBreeze else "fusion"

    def derivedColors(self):
        accent = QColor(self.accent)
        button = QColor(self.button)
        text = QColor(self.text)
        surface = QColor(self.surface)
        bg = QColor(self.bg)
        tooltipText = QColor(self.tooltipText)
        tooltipBg = QColor(self.tooltipBg)

        return {
            "defaultButton"         : mixColors(button, accent, .25),
            "defaultButtonHover"    : mixColors(button, accent, .33),
            "buttonHover"           : mixColors(button, text, .04),
            "buttonPressed"         : mixColors(button, accent, .66),
            "tooltipBorder"         : mixColors(tooltipText, tooltipBg, .8),
            "textDim"               : mixColors(text, surface, .4),
            "textFaint"             : mixColors(text, surface, .7),
            "inputDisabled"         : mixColors(bg, surface),
        }

    def buildStyleSheet(self) -> str:
        engine = self.bestStyleEngine()

        outerRadius = 7
        innerRadius = round(outerRadius * .75)
        menuRadius = outerRadius if (engine == "breeze") else 0

        # Breeze draws menu/combobox menu shadows at hardcoded radius, which looks ugly if our radius is larger.
        menuRadius = min(menuRadius, 7)
        comboBoxMenuRadius = min(menuRadius, 7)

        templatePath = Path(QFile("assets:style-modern.qss").fileName())
        templateText = templatePath.read_text(encoding="utf-8")
        replacements = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

        replacements["outerRadius"] = f"{outerRadius}px"
        replacements["innerRadius"] = f"{innerRadius}px"
        replacements["menuRadius"] = f"{menuRadius}px"
        replacements["comboBoxMenuRadius"] = f"{comboBoxMenuRadius}px"
        replacements["fusionOnly"] = "" if engine == "fusion" else "___IGNORE"

        replacements.update({k: v.name() for k, v in self.derivedColors().items()})

        qss = Template(templateText).substitute(replacements)
        return qss

    def buildPalette(self) -> QPalette:
        Role = QPalette.ColorRole
        Group = QPalette.ColorGroup

        derivedColors = self.derivedColors()

        bg = QColor(self.bg)
        surface = QColor(self.surface)
        text = QColor(self.text)
        textDim = derivedColors["textDim"]
        textFaint = derivedColors["textFaint"]
        accent = QColor(self.accent)
        onAccent = QColor(self.onAccent)
        button = QColor(self.button)
        selInactive = QColor(self.selInactive)

        palette = QPalette()
        palette.setColor(Role.Window, bg)
        palette.setColor(Role.WindowText, text)
        palette.setColor(Role.Base, surface)
        palette.setColor(Role.AlternateBase, QColor(self.altRow))
        palette.setColor(Role.Text, text)
        palette.setColor(Role.Button, button)
        palette.setColor(Role.ButtonText, text)
        palette.setColor(Role.BrightText, QColor(self.danger))
        palette.setColor(Role.Highlight, accent)
        palette.setColor(Role.HighlightedText, onAccent)
        palette.setColor(Role.ToolTipBase, QColor(self.tooltipBg))
        palette.setColor(Role.ToolTipText, QColor(self.tooltipText))
        palette.setColor(Role.PlaceholderText, textFaint)
        palette.setColor(Role.Link, accent)
        palette.setColor(Role.LinkVisited, accent)
        with suppress(AttributeError):  # Qt 6.6+
            palette.setColor(Role.Accent, accent)

        # Old-school 3D bevel/shadow colors: Derive them all from `button`.
        # Practically unused in Breeze, very rarely in Fusion, mostly in Windows
        palette.setColor(Role.Light, button.lighter(200))
        palette.setColor(Role.Midlight, button.lighter(150))
        palette.setColor(Role.Mid, button.darker(150))
        palette.setColor(Role.Dark, button.darker(200))
        palette.setColor(Role.Shadow, button.darker(20))

        palette.setColor(Group.Inactive, Role.Highlight, selInactive)
        palette.setColor(Group.Inactive, Role.HighlightedText, text)

        for role in (Role.WindowText, Role.Text, Role.ButtonText):
            palette.setColor(Group.Disabled, role, textFaint)
        palette.setColor(Group.Disabled, Role.Highlight, selInactive)
        palette.setColor(Group.Disabled, Role.HighlightedText, textDim)
        palette.setColor(Group.Disabled, Role.Base, derivedColors["inputDisabled"]),
        palette.setColor(Group.Disabled, Role.Link, textDim)

        return palette


MODERN_DARK = ThemeColors(
    bg                = "#23262c",
    surface           = "#1b1e23",
    altRow            = "#1f2228",
    border            = "#444b55",
    text              = "#d7dbe1",
    accent            = "#4a8cff",
    onAccent          = "#ffffff",
    hover             = "#12ffffff",
    selInactive       = "#343a44",
    button            = "#2c3138",
    scrollHandle      = "#2affffff",
    tooltipBg         = "#2f343c",
    tooltipText       = "#e4e7ec",
    danger            = "#ff6b60",
)

MODERN_LIGHT = ThemeColors(
    bg                = "#eef0f3",
    surface           = "#ffffff",
    altRow            = "#f7f8fa",
    border            = "#d2d6dd",
    text              = "#1f2329",
    accent            = "#2f6fed",
    onAccent          = "#ffffff",
    hover             = "#10000000",
    selInactive       = "#dde1e8",
    button            = "#ffffff",
    scrollHandle      = "#38000000",
    tooltipBg         = "#2f343c",
    tooltipText       = "#f0f2f5",
    danger            = "#d92b1f",
)
