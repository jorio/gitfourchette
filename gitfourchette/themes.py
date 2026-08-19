# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Built-in themes that (almost) don't depend on the desktop environment's style.

A theme is a bunch of color tokens that feed both a QPalette and theme.qss.
"""

from __future__ import annotations

import dataclasses
import enum
from contextlib import suppress
from pathlib import Path
from string import Template

from gitfourchette.qt import *
from gitfourchette.toolbox import mixColors, relativeLuminance


class ThemeName(enum.StrEnum):
    """
    Our built-in themes. These share the Prefs.qtStyle namespace with the
    native Qt style names (Breeze, Fusion, Windows...), so their values must
    not collide with anything QStyleFactory may return.
    """
    BuiltIn = "gitfourchette-builtin"


class ThemeAccent(enum.StrEnum):
    Blue = "#3daee9"
    Cyan = "#00d3b8"
    Green = "#3dd425"
    Yellow = "#e8cb2d"
    Orange = "#e9643a"
    Red = "#e93d58"
    Pink = "#e93a9a"
    Gray = "#686b6f"
    Indigo = "#926ee4"
    Purple = "#b875dc"


@dataclasses.dataclass
class ThemeColors:
    bg: str
    surface: str
    altRow: str
    border: str
    text: str
    hover: str
    selInactive: str
    button: str
    scrollHandle: str
    tooltipBg: str
    tooltipText: str
    danger: str = "red"

    accent: str = ThemeAccent.Blue
    outerRadius: int = 7
    innerRadius: int = round(outerRadius * .75)

    # All tokens below are inferred automatically. Do not define manually!
    onAccent: str = "white"
    defaultButton: str = "#f0f"
    defaultButtonHover: str = "#f0f"
    buttonHover: str = "#f0f"
    buttonPressed: str = "#f0f"
    tooltipBorder: str = "#f0f"
    textDim: str = "#f0f"
    textFaint: str = "#f0f"
    inputDisabled: str = "#f0f"
    light: str = "#f0f"
    midlight: str = "#f0f"
    mid: str = "#f0f"
    dark: str = "#f0f"
    shadow: str = "#f0f"

    # Engine-specific rounded rects
    menuRadius: int = outerRadius
    comboBoxMenuRadius: int = outerRadius

    # Engine-specific tokens. Meant to be prepended to a rule, e.g.:
    #     ${fusionOnly}QLabel {color: red}  /* red text only in Fusion */
    # The token is replaced with an empty string if the engine matches,
    # otherwise it's replaced with garbage so that the rule is ignored.
    fusionOnly: str = ""

    def __post_init__(self):
        """
        Derive intermediate colors automatically.
        """
        def mix(a: str, b: str, r=.5):
            return mixColors(QColor(a), QColor(b), r).name()

        # Determine whether 'onAccent' should be white or black.
        isDarkTheme = QColor(self.text).lightness() > QColor(self.surface).lightness()
        accentLuminance = relativeLuminance(QColor(self.accent))
        luminanceThreshold = .24 if isDarkTheme else .45

        # Menus, combobox lists, tooltips cannot be rounded with Fusion.
        # Breeze can round these, but draws menu shadows at a hardcoded radius,
        # which looks ugly if our radius is larger.
        engine = self.bestStyleEngine()
        maxMenuRadius = 7 if engine == "breeze" else 0

        self.defaultButton      = mix(self.button, self.accent, .25)
        self.defaultButtonHover = mix(self.button, self.accent, .33)
        self.buttonHover        = mix(self.button, self.text, .04)
        self.buttonPressed      = mix(self.button, self.accent, .66)
        self.tooltipBorder      = mix(self.tooltipText, self.tooltipBg, .8)
        self.textDim            = mix(self.text, self.surface, .4)
        self.textFaint          = mix(self.text, self.surface, .7)
        self.inputDisabled      = mix(self.bg, self.surface, .5)
        self.onAccent           = "white" if accentLuminance < luminanceThreshold else "black"

        self.fusionOnly         = "" if engine == "fusion" else "___IGNORE"
        self.menuRadius         = min(maxMenuRadius, self.outerRadius)
        self.comboBoxMenuRadius = min(maxMenuRadius, self.outerRadius)

        # Old-school 3D bevel/shadow colors. Derive from button.
        # Practically unused in Breeze, very rarely in Fusion, mostly in Windows.
        self.light              = QColor(self.button).lighter(200).name()
        self.midlight           = QColor(self.button).lighter(150).name()
        self.mid                = QColor(self.button).darker(150).name()
        self.dark               = QColor(self.button).darker(200).name()
        self.shadow             = QColor(self.button).darker(20).name()

    @classmethod
    def resolveTheme(cls, styleName: str, accent: QColor | None = None) -> ThemeColors | None:
        """
        Return the color tokens for one of our themes, or None if the input
        couldn't be parsed (e.g. if the given name is for a native Qt style).

        The input string must follow this format: "styleID,lightOrDark,#accentHex"
        Example: "gitfourchette-builtin,dark,#ff00ff"

        Omit lightOrDark and/or #accentHex to infer colors from system palette.
        """

        tokens = styleName.split(",")

        if tokens.pop(0) != ThemeName.BuiltIn:
            return None

        try:
            appScheme = QGuiApplication.styleHints().colorScheme()
            dark = appScheme == Qt.ColorScheme.Dark
        except AttributeError:  # Qt < 6.5
            dark = False

        while tokens:
            token = tokens.pop(0)
            if token in ("light", "dark"):
                dark = token == "dark"
            elif token.startswith("#"):
                accent = QColor(token)

        theme = MODERN_DARK if dark else MODERN_LIGHT
        if accent is not None:
            theme = dataclasses.replace(theme, accent=accent.name())

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

    def buildStyleSheet(self) -> str:
        templatePath = Path(QFile("assets:style/theme.qss").fileName())
        templateText = templatePath.read_text(encoding="utf-8")
        replacements = dataclasses.asdict(self)
        qss = Template(templateText).substitute(replacements)
        return qss

    def buildPalette(self) -> QPalette:
        Role = QPalette.ColorRole

        normal = {
            Role.Window: self.bg,
            Role.WindowText: self.text,
            Role.Base: self.surface,
            Role.AlternateBase: self.altRow,
            Role.Text: self.text,
            Role.Button: self.button,
            Role.ButtonText: self.text,
            Role.BrightText: self.danger,
            Role.Highlight: self.accent,
            Role.HighlightedText: self.onAccent,
            Role.ToolTipBase: self.tooltipBg,
            Role.ToolTipText: self.tooltipText,
            Role.PlaceholderText: self.textFaint,
            Role.Link: self.accent,
            Role.LinkVisited: self.accent,
            Role.Light: self.light,
            Role.Midlight: self.midlight,
            Role.Mid: self.mid,
            Role.Dark: self.dark,
            Role.Shadow: self.shadow,
        }

        inactive = {
            Role.Highlight: self.selInactive,
            Role.HighlightedText: self.text,
        }

        disabled = {
            Role.WindowText: self.textFaint,
            Role.Text: self.textFaint,
            Role.ButtonText: self.textFaint,
            Role.Highlight: self.selInactive,
            Role.HighlightedText: self.textDim,
            Role.Base: self.inputDisabled,
            Role.Link: self.textDim,
        }

        with suppress(AttributeError):  # Qt 6.6+
            normal[Role.Accent] = self.accent

        palette = QPalette()

        for role, color in normal.items():
            palette.setColor(role, QColor(color))
        for role, color in inactive.items():
            palette.setColor(QPalette.ColorGroup.Inactive, role, QColor(color))
        for role, color in disabled.items():
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))

        return palette


MODERN_DARK = ThemeColors(
    bg                = "#23262c",
    surface           = "#1b1e23",
    altRow            = "#1f2228",
    border            = "#444b55",
    text              = "#d7dbe1",
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
    hover             = "#10000000",
    selInactive       = "#dde1e8",
    button            = "#ffffff",
    scrollHandle      = "#38000000",
    tooltipBg         = "#2f343c",
    tooltipText       = "#f0f2f5",
    danger            = "#d92b1f",
)
