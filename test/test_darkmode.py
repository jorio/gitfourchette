# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.syntax.colorscheme import PygmentsPresets
from gitfourchette.themes import MODERN_DARK, MODERN_LIGHT, ThemeAccent, ThemeColors, ThemeName
from gitfourchette.toolbox import isDarkTheme
from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine
from .util import *

BUILTIN_LIGHT = f"{ThemeName.BuiltIn},light"
BUILTIN_DARK = f"{ThemeName.BuiltIn},dark"


@pytest.fixture
def iconColorTableSpy(monkeypatch) -> list[str]:
    """
    Record the color table that stockIcon passes to each new RecolorSvgIconEngine.
    """
    from gitfourchette.toolbox import iconbank

    colorTables = []

    class SpyEngine(RecolorSvgIconEngine):
        def __init__(self, iconPath, colorTable="", flags=RecolorSvgIconEngine.Flags.NoFlags):
            colorTables.append(colorTable)
            super().__init__(iconPath, colorTable, flags)

    monkeypatch.setattr(iconbank, "RecolorSvgIconEngine", SpyEngine)
    iconbank.clearStockIconCache()
    return colorTables


@pytest.mark.parametrize("variant", ["light", "dark"])
def testResolveBuiltInTheme(mainWindow, variant):
    dark = variant == "dark"
    theme = ThemeColors.resolveTheme(f"{ThemeName.BuiltIn},{variant}")
    assert theme is (MODERN_DARK if dark else MODERN_LIGHT)
    assert theme.darkSelector == ("@dark" if dark else "")
    assert isDarkTheme(theme.buildPalette()) == dark

    # Accent override keeps the light/dark base
    theme = ThemeColors.resolveTheme(f"{ThemeName.BuiltIn},{variant},{ThemeAccent.Pink}")
    assert theme.accent == ThemeAccent.Pink
    assert theme.bg == (MODERN_DARK if dark else MODERN_LIGHT).bg
    assert isDarkTheme(theme.buildPalette()) == dark

    # Native Qt styles aren't ours to resolve
    assert ThemeColors.resolveTheme("fusion") is None


def testSwitchBetweenLightAndDarkTheme(mainWindow):
    app = GFApplication.instance()
    IconColors = RecolorSvgIconEngine.IconColors

    for _round in range(2):
        GFApplication.applyPrefs(qtStyle=BUILTIN_DARK)
        assert isDarkTheme()
        assert isDarkTheme(mainWindow.palette())
        assert app.palette().color(QPalette.ColorRole.Window) == QColor(MODERN_DARK.bg)
        assert IconColors.preferDarkVariants
        assert "@dark.svg" in app.styleSheet()

        GFApplication.applyPrefs(qtStyle=BUILTIN_LIGHT)
        assert not isDarkTheme()
        assert not isDarkTheme(mainWindow.palette())
        assert app.palette().color(QPalette.ColorRole.Window) == QColor(MODERN_LIGHT.bg)
        assert not IconColors.preferDarkVariants
        assert "@dark.svg" not in app.styleSheet()


def testStockIconAutoDarkVariants(mainWindow, iconColorTableSpy):
    from gitfourchette.toolbox.iconbank import stockIcon

    def colorTableFor(iconId, colorTable=""):
        iconColorTableSpy.clear()
        stockIcon(iconId, colorTable)
        assert len(iconColorTableSpy) == 1
        return set(iconColorTableSpy[0].split())

    # Light mode: color tables are passed through as-is
    GFApplication.applyPrefs(qtStyle=BUILTIN_LIGHT)
    assert colorTableFor("status_a") == set()
    assert colorTableFor("status_a", "gray=#123456") == {"gray=#123456"}

    # Dark mode: icons with an automatic dark variant swap black & white
    GFApplication.applyPrefs(qtStyle=BUILTIN_DARK)
    assert colorTableFor("status_a") == {"white=#000", "black=#fff"}

    # Icons without an automatic dark variant are left alone
    assert colorTableFor("status_u") == set()
    assert colorTableFor("git-branch", "gray=#123456") == {"gray=#123456"}

    # Caller's color table is merged with the dark variant remapping (regression test)
    assert colorTableFor("status_a", "gray=#123456") == {"gray=#123456", "white=#000", "black=#fff"}

    # Caller's entries take precedence over the dark variant remapping
    assert colorTableFor("status_a", "white=#f00") == {"white=#f00", "black=#fff"}


def testSidebarPaintsAutoDarkVariantIconWhenSelected(tempDir, mainWindow):
    """
    Regression test: painting a selected sidebar item whose icon has an
    automatic dark variant used to raise an AssertionError in dark mode.
    """

    sm = "submosub"

    # Non-recursive clone so that the submodule is uninitialized,
    # which gives it the "achtung" icon in the sidebar.
    upstreamWd = unpackRepo(tempDir, "submoroot", renameTo="upstream")
    repo = pygit2.clone_repository(upstreamWd, f"{tempDir.name}/submoroot")
    wd = repo.workdir
    repo.free()
    del repo

    GFApplication.applyPrefs(qtStyle=BUILTIN_DARK)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert node.data == sm
    index = rw.sidebar.nodeToFilterIndex(node)
    assert index.data(rw.sidebar.sidebarModel.Role.IconKey) == "achtung"

    # Select the node so that the delegate passes a color table to stockIcon, then force a repaint
    rw.sidebar.selectNode(node)
    rw.sidebar.grab()


def testCodeViewFollowsDarkTheme(tempDir, mainWindow):
    assert settings.prefs.syntaxHighlighting == PygmentsPresets.Automatic

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/hello.py", "hello = 0\n")
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("hello.py"), check=True)
    assert rw.diffView.isVisible()

    GFApplication.applyPrefs(qtStyle=BUILTIN_LIGHT)
    assert rw.diffView.property("dark") == "false"
    assert not settings.prefs.syntaxHighlightingScheme().isDark()

    GFApplication.applyPrefs(qtStyle=BUILTIN_DARK)
    assert rw.diffView.property("dark") == "true"
    assert settings.prefs.syntaxHighlightingScheme().isDark()

    GFApplication.applyPrefs(qtStyle=BUILTIN_LIGHT)
    assert rw.diffView.property("dark") == "false"
