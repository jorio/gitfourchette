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
    System = ""
    Modern = "modern"
    ModernLight = "modern-light"
    ModernDark = "modern-dark"

    @property
    def isModern(self) -> bool:
        return self != AppTheme.System


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

    def asDict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}


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
    accentGhost       = "rgba(74, 140, 255, 40)",
    onAccent          = "#ffffff",
    hover             = "rgba(255, 255, 255, 18)",
    pressed           = "rgba(255, 255, 255, 32)",
    selInactive       = "#343a44",
    tabSelected       = "#1b1e23",
    button            = "#2c3138",
    buttonHover       = "#343a43",
    buttonPressed     = "#262a31",
    input             = "#15181d",
    inputDisabled     = "#1e2127",
    scrollHandle      = "rgba(255, 255, 255, 42)",
    scrollHandleHover = "rgba(255, 255, 255, 78)",
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
    accentGhost       = "rgba(47, 111, 237, 30)",
    onAccent          = "#ffffff",
    hover             = "rgba(0, 0, 0, 16)",
    pressed           = "rgba(0, 0, 0, 28)",
    selInactive       = "#dde1e8",
    tabSelected       = "#ffffff",
    button            = "#ffffff",
    buttonHover       = "#f4f6f8",
    buttonPressed     = "#e9ecf1",
    input             = "#ffffff",
    inputDisabled     = "#f2f3f6",
    scrollHandle      = "rgba(0, 0, 0, 56)",
    scrollHandleHover = "rgba(0, 0, 0, 96)",
    tooltipBg         = "#2f343c",
    tooltipText       = "#f0f2f5",
    tooltipBorder     = "#2f343c",
    danger            = "#d92b1f",
)


def systemPrefersDark(fallbackPalette: QPalette | None = None) -> bool:
    """
    Detect whether the desktop environment asks for a dark color scheme.

    Falls back to sniffing a palette (typically the palette captured at boot,
    before we've overwritten it with a theme of our own).
    """

    with suppress(AttributeError, NameError):
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False

    palette = fallbackPalette if fallbackPalette is not None else QApplication.palette()
    return palette.color(QPalette.ColorRole.Base).value() < palette.color(QPalette.ColorRole.Text).value()


def resolveTheme(theme: AppTheme, fallbackPalette: QPalette | None = None) -> ThemeColors | None:
    """Return the color tokens for a theme, or None to keep the system theme."""

    if theme == AppTheme.ModernDark:
        return MODERN_DARK
    if theme == AppTheme.ModernLight:
        return MODERN_LIGHT
    if theme == AppTheme.Modern:
        return MODERN_DARK if systemPrefersDark(fallbackPalette) else MODERN_LIGHT
    return None


def _c(spec: str) -> QColor:
    """Parse a theme token into a QColor ('#rrggbb' or 'rgba(r, g, b, a)')."""

    spec = spec.strip()
    if spec.startswith("rgba("):
        r, g, b, a = (int(x) for x in spec[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(spec)


def _blend(over: QColor, under: QColor) -> QColor:
    """Flatten a translucent color onto an opaque one (QPalette wants opaque)."""

    a = over.alphaF()
    return QColor(
        round(over.red() * a + under.red() * (1 - a)),
        round(over.green() * a + under.green() * (1 - a)),
        round(over.blue() * a + under.blue() * (1 - a)))


def buildPalette(colors: ThemeColors) -> QPalette:
    Role = QPalette.ColorRole
    Group = QPalette.ColorGroup

    bg = _c(colors.bg)
    surface = _c(colors.surface)
    text = _c(colors.text)
    textDim = _c(colors.textDim)
    textFaint = _c(colors.textFaint)
    accent = _c(colors.accent)
    onAccent = _c(colors.onAccent)
    button = _c(colors.button)
    selInactive = _c(colors.selInactive)

    palette = QPalette()

    palette.setColor(Role.Window, bg)
    palette.setColor(Role.WindowText, text)
    palette.setColor(Role.Base, surface)
    palette.setColor(Role.AlternateBase, _c(colors.altRow))
    palette.setColor(Role.Text, text)
    palette.setColor(Role.Button, button)
    palette.setColor(Role.ButtonText, text)
    palette.setColor(Role.BrightText, _c(colors.danger))
    palette.setColor(Role.Highlight, accent)
    palette.setColor(Role.HighlightedText, onAccent)
    palette.setColor(Role.ToolTipBase, _c(colors.tooltipBg))
    palette.setColor(Role.ToolTipText, _c(colors.tooltipText))
    palette.setColor(Role.PlaceholderText, textFaint)
    palette.setColor(Role.Link, accent)
    palette.setColor(Role.LinkVisited, _c(colors.accentPressed))

    # 3D bevel roles: Fusion still uses these for frames, grooves and arrows.
    palette.setColor(Role.Light, _blend(_c(colors.hover), bg))
    palette.setColor(Role.Midlight, _c(colors.borderSoft))
    palette.setColor(Role.Mid, _c(colors.border))
    palette.setColor(Role.Dark, _c(colors.borderStrong))
    palette.setColor(Role.Shadow, QColor(0, 0, 0, 90 if colors.dark else 40))

    # Unfocused windows get a muted selection instead of a screaming accent.
    palette.setColor(Group.Inactive, Role.Highlight, selInactive)
    palette.setColor(Group.Inactive, Role.HighlightedText, text)

    for role in (Role.WindowText, Role.Text, Role.ButtonText):
        palette.setColor(Group.Disabled, role, textFaint)
    palette.setColor(Group.Disabled, Role.Highlight, selInactive)
    palette.setColor(Group.Disabled, Role.HighlightedText, textDim)
    palette.setColor(Group.Disabled, Role.Base, _c(colors.inputDisabled))
    palette.setColor(Group.Disabled, Role.Link, textDim)

    return palette


def currentTheme() -> ThemeColors | None:
    """Color tokens of the theme in effect, or None if we defer to the desktop."""

    from gitfourchette import settings

    app = QApplication.instance()
    fallbackPalette = getattr(app, "platformDefaultPalette", None)
    return resolveTheme(settings.prefs.appTheme, fallbackPalette)


def buildStyleSheet(colors: ThemeColors) -> str:
    template = Path(QFile("assets:style-modern.qss").fileName()).read_text(encoding="utf-8")
    return Template(template).substitute(colors.asDict())
