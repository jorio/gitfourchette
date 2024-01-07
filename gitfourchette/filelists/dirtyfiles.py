from gitfourchette import settings
from gitfourchette.filelists.filelist import FileList
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.tasks import *


class DirtyFiles(FileList):
    stageFiles = Signal(list)
    discardFiles = Signal(list)
    discardModeChanges = Signal(list)

    def __init__(self, parent):
        super().__init__(parent, NavContext.UNSTAGED)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def createContextMenuActions(self, patches: list[Patch]) -> list[ActionDef]:
        n = len(patches)

        return [
            ActionDef(
                self.tr("&Stage %n File(s)", "", n),
                self.stage,
                icon="list-add",  # QStyle.StandardPixmap.SP_ArrowDown,
                shortcuts=makeMultiShortcut(GlobalShortcuts.stageHotkeys),
            ),

            ActionDef(
                self.tr("&Discard Changes"),
                self.discard,
                icon=QStyle.StandardPixmap.SP_TrashIcon,
                shortcuts=makeMultiShortcut(GlobalShortcuts.discardHotkeys),
            ),

            ActionDef(
                self.tr("Stas&h Changes..."),
                self.wantPartialStash,
                icon="vcs-stash",
                shortcuts=TaskBook.shortcuts.get(NewStash, [])
            ),

            self.revertModeActionDef(n, self.wantDiscardModeChanges),

            ActionDef.SEPARATOR,

            ActionDef(
                self.tr("Compare in {0}").format(settings.getDiffToolName()),
                self.wantOpenInDiffTool,
                icon="vcs-diff",
            ),

            ActionDef(
                self.tr("E&xport Diff(s) As Patch...", "", n),
                self.savePatchAs
            ),

            ActionDef.SEPARATOR,

            ActionDef(
                self.tr("&Edit in {0}", "", n).format(settings.getExternalEditorName()),
                self.openWorkdirFile,
                icon=QStyle.StandardPixmap.SP_FileIcon,
            ),

            ActionDef(
                self.tr("Edit HEAD Version(s) in {0}", "", n).format(settings.getExternalEditorName()),
                self.openHeadRevision,
            ),

            ActionDef.SEPARATOR,

            ActionDef(
                self.tr("Open &Folder(s)", "", n),
                self.showInFolder,
                icon=QStyle.StandardPixmap.SP_DirIcon,
            ),

            ActionDef(
                self.tr("&Copy Path(s)", "", n),
                self.copyPaths,
                shortcuts=GlobalShortcuts.copy,
            ),

            self.pathDisplayStyleSubmenu()
        ]

    def keyPressEvent(self, event: QKeyEvent):
        k = event.key()
        if k in GlobalShortcuts.stageHotkeys:
            self.stage()
        elif k in GlobalShortcuts.discardHotkeys:
            self.discard()
        else:
            super().keyPressEvent(event)

    def stage(self):
        patches = list(self.selectedPatches())
        self.stageFiles.emit(patches)

    def discard(self):
        patches = list(self.selectedPatches())
        self.discardFiles.emit(patches)

    def wantDiscardModeChanges(self):
        patches = list(self.selectedPatches())
        self.discardModeChanges.emit(patches)
