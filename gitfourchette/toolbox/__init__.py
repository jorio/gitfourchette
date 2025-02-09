# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Library of widgets and utilities that aren't specifically tied to GitFourchette's core functionality.
"""

from .actiondef import ActionDef
from .autohidemenubar import AutoHideMenuBar
from .benchmark import Benchmark, benchmark
from .calledfromqthread import calledFromQThread
from .fittedtext import FittedText
from .excutils import shortenTracebackPath, excStrings
from .fontpicker import FontPicker
from .gitutils import (
    shortHash, dumpTempBlob, nameValidationMessage,
    AuthorDisplayStyle, abbreviatePerson,
    PatchPurpose,
    simplifyOctalFileMode,
    remoteUrlProtocol,
    splitRemoteUrl,
    stripRemoteUrlPath,
    guessRemoteUrlFromText,
    signatureQDateTime,
    signatureDateFormat,
)
from .memoryindicator import MemoryIndicator
from .messageboxes import (
    MessageBoxIconName, excMessageBox, asyncMessageBox,
    showWarning, showInformation, askConfirmation,
    addULToMessageBox,
    NonCriticalOperation)
from .iconbank import stockIcon, clearStockIconCache
from .pathutils import PathDisplayStyle, abbreviatePath, compactPath
from .persistentfiledialog import PersistentFileDialog
from .qbusyspinner import QBusySpinner
from .qcomboboxwithpreview import QComboBoxWithPreview
from .qelidedlabel import QElidedLabel
from .qfaintseparator import QFaintSeparator
from .qfilepickercheckbox import QFilePickerCheckBox
from .qhintbutton import QHintButton
from .qsignalblockercontext import QSignalBlockerContext
from .qstatusbar2 import QStatusBar2
from .qtabwidget2 import QTabWidget2, QTabBar2
from .qtutils import (
    enforceComboBoxMaxVisibleItems,
    isImageFormatSupported,
    onAppThread,
    setFontFeature,
    adjustedWidgetFontSize,
    tweakWidgetFont,
    formatWidgetText,
    formatWidgetTooltip,
    itemViewVisibleRowRange,
    isDarkTheme,
    mutedTextColorHex,
    mutedToolTipColorHex,
    appendShortcutToToolTipText,
    appendShortcutToToolTip,
    openFolder, showInFolder,
    DisableWidgetContext,
    DisableWidgetUpdatesContext,
    QScrollBackupContext,
    makeInternalLink,
    MultiShortcut,
    makeMultiShortcut,
    keyEventMatchesMultiShortcut,
    CallbackAccumulator,
    lerp,
    DocumentLinks,
    writeTempFile,
    waitForSignal,
    findParentWidget,
    setTabOrder,
    QModelIndex_default,
    QPoint_zero,
)
from .textutils import (
    toLengthVariants,
    escape, escamp, paragraphs, messageSummary, elide,
    toRoomyUL,
    toTightUL,
    linkify,
    tagify,
    clipboardStatusMessage,
    hquo, hquoe, bquo, bquoe, lquo, lquoe, tquo, tquoe,
    btag,
    stripHtml,
    withUniqueSuffix,
    englishTitleCase,
    naturalSort,
)
from .urltooltip import UrlToolTip
from .validatormultiplexer import ValidatorMultiplexer
