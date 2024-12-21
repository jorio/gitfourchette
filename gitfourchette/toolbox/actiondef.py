# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Callable, Iterable
from typing import ClassVar

from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon
from gitfourchette.toolbox.qtutils import MultiShortcut, appendShortcutToToolTipText


@dataclasses.dataclass
class ActionDef:
    """
    Build QMenus quickly with a list of ActionDefs.
    """

    SEPARATOR: ClassVar[ActionDef]
    SPACER: ClassVar[ActionDef]

    class Kind(enum.IntEnum):
        Action = enum.auto()
        Section = enum.auto()
        Separator = enum.auto()
        Spacer = enum.auto()

    caption: str = ""
    callback: SignalInstance | Callable | None = None
    icon: str = ""
    checkState: int = 0
    radioGroup: str = ""
    enabled: bool = True
    submenu: list[ActionDef] = dataclasses.field(default_factory=list)
    shortcuts: MultiShortcut | QKeySequence | QKeySequence.StandardKey | Qt.Key | str = ""
    tip: str = ""
    objectName: str = ""
    menuRole: QAction.MenuRole = QAction.MenuRole.NoRole
    kind: Kind = Kind.Action

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)

    def toQAction(self, parent: QWidget) -> QAction:
        if self.submenu:
            raise NotImplementedError("ActionDef.toQAction cannot be used for submenus")

        action = QAction(self.caption, parent=parent)

        if self.objectName:
            action.setObjectName(self.objectName)

        if self.callback is None:
            pass
        elif isinstance(self.callback, SignalInstance):
            action.triggered.connect(self.callback)
        else:
            action.triggered.connect(lambda: self.callback())

        if self.icon:
            action.setIcon(stockIcon(self.icon))

        if self.checkState != 0:
            action.setCheckable(True)
            action.setChecked(self.checkState == 1)

        if self.tip:
            tip = self.tip
            if self.shortcuts and not isinstance(parent, QMenu):
                if isinstance(self.shortcuts, list):
                    tip = appendShortcutToToolTipText(tip, self.shortcuts[0])
                else:
                    tip = appendShortcutToToolTipText(tip, self.shortcuts)
            if "<" not in tip and len(tip) > 40:  # wrap long tooltips
                tip = f"<p>{tip}</p>"
            action.setToolTip(tip)

        # Enforce menu role (including NoRole) to prevent Qt/macOS from moving
        # items that start with the localized word for "Settings" to the
        # application menu (e.g. "Repository Settings" in French).
        action.setMenuRole(self.menuRole)

        action.setEnabled(bool(self.enabled))

        if self.shortcuts:
            if isinstance(self.shortcuts, list):
                action.setShortcuts(self.shortcuts)
            else:
                action.setShortcut(self.shortcuts)

        return action

    def makeSubmenu(self, parent: QMenu) -> QMenu | None:
        if not self.submenu:
            return None

        submenu = ActionDef.makeQMenu(parent=parent, actionDefs=self.submenu)
        submenu.setTitle(self.caption)
        submenu.setEnabled(self.enabled)
        if self.icon:
            submenu.setIcon(stockIcon(self.icon))
        if self.objectName:
            submenu.setObjectName(self.objectName)

        return submenu

    @staticmethod
    def addToQMenu(menu: QMenu, *actionDefs: ActionDef | QAction):
        radioGroups: dict[str, QActionGroup] = {}

        for item in actionDefs:
            if isinstance(item, QAction):
                item.setParent(menu)  # reparent it
                menu.addAction(item)
            elif item.kind == ActionDef.Kind.Separator:
                menu.addSeparator()
            elif item.kind == ActionDef.Kind.Section:
                menu.addSection(item.caption)
            elif item.submenu:
                submenu = item.makeSubmenu(parent=menu)
                menu.addMenu(submenu)
            elif item.kind == ActionDef.Kind.Action:
                action = item.toQAction(parent=menu)
                menu.addAction(action)

                groupKey = item.radioGroup
                if groupKey:
                    try:
                        group = radioGroups[groupKey]
                    except KeyError:
                        group = QActionGroup(menu)
                        group.setObjectName(f"ActionDefGroup{groupKey}")
                        group.setExclusive(True)
                        radioGroups[groupKey] = group
                    group.addAction(action)
            else:
                raise NotImplementedError(f"Unsupported ActionDef kind in menu: {item.kind}")

    @staticmethod
    def addToQToolBar(toolbar: QToolBar, *actionDefs: ActionDef | QAction):
        for item in actionDefs:
            if isinstance(item, QAction):
                action: QAction = item
                action.setParent(toolbar)  # reparent it
                action.setShortcut("")  # clear shortcut for toolbar
                toolbar.addAction(action)
            elif item.kind == ActionDef.Kind.Separator:
                toolbar.addSeparator()
            elif item.kind == ActionDef.Kind.Spacer:
                spacer = QWidget()
                spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                toolbar.addWidget(spacer)
            elif item.submenu:
                raise NotImplementedError("Cannot add ActionDef submenus to QToolbar")
            elif item.kind == ActionDef.Kind.Action:
                assert not item.radioGroup
                action = item.toQAction(parent=toolbar)
                action.setShortcut("")  # clear shortcut for toolbar
                toolbar.addAction(action)
            else:
                raise NotImplementedError(f"Unsupported ActionDef kind in toolbar: {item.kind}")

    @staticmethod
    def makeQMenu(
            parent: QWidget,
            actionDefs: Iterable[ActionDef | QAction],
            bottomEntries: QMenu | None = None
    ) -> QMenu:

        menu = QMenu(parent)
        menu.setObjectName("ActionDefMenu")

        ActionDef.addToQMenu(menu, *actionDefs)

        if bottomEntries:
            menu.addSeparator()
            menu.addActions(bottomEntries.actions())

        return menu


ActionDef.SEPARATOR = ActionDef(kind=ActionDef.Kind.Separator)
ActionDef.SPACER = ActionDef(kind=ActionDef.Kind.Spacer)
