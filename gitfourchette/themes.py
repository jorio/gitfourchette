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
    dark: bool

    bg: str
    """Window chrome: toolbar, tab strip, menu bar, status bar."""
    surface: str
    """Content background: item views, code panes."""
    sidebarBg: str
    elevated: str
    """Popups: menus, combobox dropdowns."""
    altRow: str

    border: str
    borderSoft: str
    borderStrong: str

    text: str
    textDim: str
    textFaint: str

    accent: str
    accentHover: str
    accentPressed: str
    accentGhost: str
    onAccent: str

    hover: str
    pressed: str
    selInactive: str
    tabSelected: str

    button: str
    buttonHover: str
    buttonPressed: str

    input: str
    inputDisabled: str

    scrollHandle: str
    scrollHandleHover: str

    tooltipBg: str
    tooltipText: str
    tooltipBorder: str

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

    def buildStyleSheet(self) -> str:
        templatePath = Path(QFile("assets:style-modern.qss").fileName())
        templateText = templatePath.read_text(encoding="utf-8")
        replacements = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        return Template(templateText).substitute(replacements)

    def buildPalette(self) -> QPalette:
        from gitfourchette.toolbox import mixColors

        Role = QPalette.ColorRole
        Group = QPalette.ColorGroup

        bg = QColor(self.bg)
        surface = QColor(self.surface)
        text = QColor(self.text)
        textDim = QColor(self.textDim)
        textFaint = QColor(self.textFaint)
        accent = QColor(self.accent)
        onAccent = QColor(self.onAccent)
        button = QColor(self.button)
        selInactive = QColor(self.selInactive)

        # Flatten the translucent hover tint onto the background (QPalette wants opaque colors).
        hover = QColor(self.hover)
        hoverOpaque = mixColors(bg, hover, ratio=hover.alphaF())
        hoverOpaque.setAlphaF(1)

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
        palette.setColor(Role.LinkVisited, QColor(self.accentPressed))
        with suppress(AttributeError):  # Qt 6.6+
            palette.setColor(Role.Accent, accent)

        # 3D bevel roles: Fusion still uses these for frames, grooves and arrows.
        palette.setColor(Role.Light, hoverOpaque)
        palette.setColor(Role.Midlight, QColor(self.borderSoft))
        palette.setColor(Role.Mid, QColor(self.border))
        palette.setColor(Role.Dark, QColor(self.borderStrong))
        palette.setColor(Role.Shadow, QColor(0, 0, 0, 90 if self.dark else 40))

        palette.setColor(Group.Inactive, Role.Highlight, selInactive)
        palette.setColor(Group.Inactive, Role.HighlightedText, text)

        for role in (Role.WindowText, Role.Text, Role.ButtonText):
            palette.setColor(Group.Disabled, role, textFaint)
        palette.setColor(Group.Disabled, Role.Highlight, selInactive)
        palette.setColor(Group.Disabled, Role.HighlightedText, textDim)
        palette.setColor(Group.Disabled, Role.Base, QColor(self.inputDisabled))
        palette.setColor(Group.Disabled, Role.Link, textDim)

        return palette


MODERN_DARK = ThemeColors(
    dark              = True,
    bg                = "#23262c",
    surface           = "#1b1e23",
    sidebarBg         = "#1f2228",
    elevated          = "#2b2f36",
    altRow            = "#1f2228",
    border            = "#343941",
    borderSoft        = "#2b2f36",
    borderStrong      = "#454b55",
    text              = "#d7dbe1",
    textDim           = "#939aa6",
    textFaint         = "#666d78",
    accent            = "#4a8cff",
    accentHover       = "#5f9bff",
    accentPressed     = "#3a79e6",
    accentGhost       = "#284a8cff",
    onAccent          = "#ffffff",
    hover             = "#12ffffff",
    pressed           = "#20ffffff",
    selInactive       = "#343a44",
    tabSelected       = "#1b1e23",
    button            = "#2c3138",
    buttonHover       = "#343a43",
    buttonPressed     = "#262a31",
    input             = "#15181d",
    inputDisabled     = "#1e2127",
    scrollHandle      = "#2affffff",
    scrollHandleHover = "#4effffff",
    tooltipBg         = "#2f343c",
    tooltipText       = "#e4e7ec",
    tooltipBorder     = "#3d434c",
    danger            = "#ff6b60",
)

MODERN_LIGHT = ThemeColors(
    dark              = False,
    bg                = "#eef0f3",
    surface           = "#ffffff",
    sidebarBg         = "#f6f7f9",
    elevated          = "#ffffff",
    altRow            = "#f7f8fa",
    border            = "#d5d9e0",
    borderSoft        = "#e4e7ec",
    borderStrong      = "#bcc2cb",
    text              = "#1f2329",
    textDim           = "#6a727d",
    textFaint         = "#a2a8b1",
    accent            = "#2f6fed",
    accentHover       = "#4681f2",
    accentPressed     = "#255fd6",
    accentGhost       = "#1e2f6fed",
    onAccent          = "#ffffff",
    hover             = "#10000000",
    pressed           = "#1c000000",
    selInactive       = "#dde1e8",
    tabSelected       = "#ffffff",
    button            = "#ffffff",
    buttonHover       = "#f4f6f8",
    buttonPressed     = "#e9ecf1",
    input             = "#ffffff",
    inputDisabled     = "#f2f3f6",
    scrollHandle      = "#38000000",
    scrollHandleHover = "#60000000",
    tooltipBg         = "#2f343c",
    tooltipText       = "#f0f2f5",
    tooltipBorder     = "#2f343c",
    danger            = "#d92b1f",
)
