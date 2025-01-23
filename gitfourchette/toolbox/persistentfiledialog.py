# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

from gitfourchette.qt import *


class PersistentFileDialog:
    @staticmethod
    def getPath(key: str, fallbackPath: str = ""):
        from gitfourchette import settings
        return settings.history.fileDialogPaths.get(key, fallbackPath)

    @staticmethod
    def savePath(key, path):
        if path:
            from gitfourchette import settings
            settings.history.fileDialogPaths[key] = path
            settings.history.write()

    @staticmethod
    def install(qfd: QFileDialog, key: str):
        # Don't use native dialog in unit tests
        # (macOS native file dialog cannot be controlled from unit tests)
        qfd.setOption(QFileDialog.Option.DontUseNativeDialog, APP_TESTMODE)

        # Restore saved path
        savedPath = PersistentFileDialog.getPath(key)
        if savedPath:
            savedPath = os.path.dirname(savedPath)
            if os.path.exists(savedPath):
                qfd.setDirectory(savedPath)

        # Remember selected path
        qfd.fileSelected.connect(lambda path: PersistentFileDialog.savePath(key, path))

        return qfd

    @staticmethod
    def saveFile(parent: QWidget, key: str, caption: str, initialFilename="", filter="", selectedFilter="", deleteOnClose=True):
        qfd = QFileDialog(parent, caption, initialFilename, filter)
        qfd.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        qfd.setFileMode(QFileDialog.FileMode.AnyFile)
        if selectedFilter:
            qfd.selectNameFilter(selectedFilter)
        qfd.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, deleteOnClose)
        qfd.setWindowModality(Qt.WindowModality.WindowModal)
        PersistentFileDialog.install(qfd, key)
        return qfd

    @staticmethod
    def openFile(parent: QWidget, key: str, caption: str, fallbackPath="", filter="", selectedFilter="", deleteOnClose=True):
        qfd = QFileDialog(parent, caption, fallbackPath, filter)
        qfd.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        qfd.setFileMode(QFileDialog.FileMode.AnyFile)
        if selectedFilter:
            qfd.selectNameFilter(selectedFilter)
        qfd.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, deleteOnClose)
        qfd.setWindowModality(Qt.WindowModality.WindowModal)
        PersistentFileDialog.install(qfd, key)
        return qfd

    @staticmethod
    def openDirectory(parent: QWidget, key: str, caption: str, options=QFileDialog.Option.ShowDirsOnly, deleteOnClose=True):
        qfd = QFileDialog(parent, caption)
        qfd.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        qfd.setFileMode(QFileDialog.FileMode.Directory)
        qfd.setOptions(options)
        qfd.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, deleteOnClose)
        qfd.setWindowModality(Qt.WindowModality.WindowModal)
        PersistentFileDialog.install(qfd, key)
        return qfd
