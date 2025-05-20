# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon
from gitfourchette.toolbox.qtutils import CallbackAccumulator


class QTabBar2(QTabBar):
    tabMiddleClicked = Signal(int)
    tabDoubleClicked = Signal(int)
    visibilityChanged = Signal(bool)
    wheelDelta = Signal(QPoint)
    layoutChanged = Signal()
    suggestScrollToCurrentTab = Signal()

    middleClickedIndex: int
    doubleClickedIndex: int

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.middleClickedIndex = -1
        self.doubleClickedIndex = -1
        self.setObjectName("QTabBar2")

    def tabLayoutChange(self):
        self.layoutChanged.emit()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middleClickedIndex = self.tabAt(event.position().toPoint())
        else:
            self.middleClickedIndex = -1
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClickedIndex = self.tabAt(event.position().toPoint())
        else:
            self.doubleClickedIndex = -1
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Block double-click signal if mouse moved before releasing button
        self.doubleClickedIndex = -1
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        self.wheelDelta.emit(event.angleDelta())

        # DO NOT forward mouse wheel events to superclass
        # (avoid default Qt behavior that switches tabs via scroll wheel)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.buttons() != Qt.MouseButton.NoButton:
            # Signals will only fire if clicking a single button at a time
            pass

        elif event.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(event.position().toPoint())
            if i >= 0 and i == self.middleClickedIndex:
                self.tabMiddleClicked.emit(i)

        elif event.button() == Qt.MouseButton.LeftButton:
            i = self.tabAt(event.position().toPoint())
            if i >= 0 and i == self.doubleClickedIndex:
                self.tabDoubleClicked.emit(i)

        self.middleClickedIndex = -1
        self.doubleClickedIndex = -1

        super().mouseReleaseEvent(event)

    def focusInEvent(self, event: QFocusEvent):
        """Suggest scrolling to current tab when we receive keyboard focus"""
        super().focusInEvent(event)
        self.suggestScrollToCurrentTab.emit()

    def setVisible(self, visible: bool):
        """Forward setVisible to parent scroll area (when we get hidden due to only 1 tab remaining)"""
        super().setVisible(visible)
        self.visibilityChanged.emit(visible)


class QTabWidget2OverflowGradient(QWidget):
    def paintEvent(self, event: QPaintEvent):
        W = 16  # gradient width
        P = 4  # opaque padding inside the gradient

        scrollArea = self.parentWidget()
        assert isinstance(scrollArea, QAbstractScrollArea)
        scrollBar = scrollArea.horizontalScrollBar()

        saw = scrollArea.width()
        sah = scrollArea.height()

        opaque = self.palette().color(QPalette.ColorRole.Window)
        transp = QColor(opaque)
        transp.setAlpha(0)

        painter = QPainter(self)

        if scrollBar.value() != 0:
            gradient = QLinearGradient(P, 0, W, 0)
            gradient.setColorAt(0, opaque)
            gradient.setColorAt(1, transp)
            painter.fillRect(QRect(0, 0, W, sah-1), gradient)

        if scrollBar.value() < scrollBar.maximum()-1:
            gradient = QLinearGradient(saw-W, 0, saw-P, 0)
            gradient.setColorAt(0, transp)
            gradient.setColorAt(1, opaque)
            painter.fillRect(QRect(saw-W, 0, W, sah-1), gradient)


class QTabWidget2(QWidget):
    currentChanged: Signal = Signal(int)
    tabCloseRequested: Signal = Signal(int)
    tabDoubleClicked: Signal = Signal(int)
    tabContextMenuRequested: Signal = Signal(QPoint, int)

    currentWidgetChanged = Signal()
    """Emitted when the displayed widget is actually changed (in contrast to
    currentChanged, which is emitted even when dragging the foreground tab)."""

    UrgentPropertyName = "QTabBar2_UrgentFlag"

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("QTabWidget2")

        self.stacked = QStackedWidget(self)
        self.stacked.setObjectName("QTW2StackedWidget")

        self.shadowCurrentWidgetId = 0
        """ Keep an id instead of a real reference to not impede GC of a dead widget """

        self.tabScrollArea = QScrollArea(self)
        self.tabScrollArea.setWidgetResizable(True)
        self.tabScrollArea.setFrameStyle(QFrame.Shape.NoFrame)
        self.tabScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabScrollArea.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)  # works ok but tries to expand the window width when opening a new tab?
        self.tabScrollArea.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.tabs = QTabBar2(self.tabScrollArea)
        self.tabs.tabMoved.connect(self.onTabMoved)
        self.tabs.currentChanged.connect(self.onCurrentChanged)
        self.tabs.tabCloseRequested.connect(self.tabCloseRequested)
        self.tabs.tabMiddleClicked.connect(self.tabCloseRequested)
        self.tabs.tabDoubleClicked.connect(self.tabDoubleClicked)
        self.tabs.suggestScrollToCurrentTab.connect(self.ensureCurrentTabVisible)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)  # dramatically improves the tabs' appearance on macOS
        self.tabs.setUsesScrollButtons(False)  # can't have those with scroll area

        self.overflowButton = QToolButton(self)
        self.overflowButton.setArrowType(Qt.ArrowType.DownArrow)
        self.overflowButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overflowButton.setToolTip(_("List all tabs"))
        self.overflowButton.clicked.connect(self.onOverflowButtonClicked)
        self.overflowButton.setCheckable(True)
        self.overflowButton.setAutoRaise(True)
        self.overflowButton.hide()  # hiding now prevents jitter on boot because maximum height is adjuster later

        self.tabScrollArea.setWidget(self.tabs)
        self.tabs.visibilityChanged.connect(self.tabScrollArea.setVisible)
        self.tabs.wheelDelta.connect(self.scrollTabs)
        self.tabs.layoutChanged.connect(self.updateOverflowDropdown)

        self.overflowGradient = QTabWidget2OverflowGradient(self.tabScrollArea)
        self.overflowGradient.setObjectName("QTW2OverflowGradient")
        self.overflowGradient.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        topWidget = QWidget(self)
        self.topWidget = topWidget
        topLayout = QHBoxLayout(topWidget)
        topLayout.setSpacing(2)
        topLayout.setContentsMargins(0, 0, 0, 0)
        topLayout.addWidget(self.tabScrollArea)
        topLayout.addWidget(self.overflowButton)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(topWidget)
        layout.addWidget(self.stacked)

        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.onCustomContextMenuRequested)

        self.overflowMenu = QMenu(self)
        self.overflowMenu.setObjectName("QTW2OverflowMenu")
        self.overflowMenu.setToolTipsVisible(True)
        self.overflowMenu.aboutToHide.connect(lambda: self.overflowButton.setChecked(False))

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

    def __len__(self):
        return self.tabs.count()

    def refreshPrefs(self):
        self.tabs.setExpanding(settings.prefs.expandingTabs)
        self.tabs.setAutoHide(settings.prefs.autoHideTabs)
        self.tabs.setTabsClosable(settings.prefs.tabCloseButton)
        self.tabs.update()
        self.syncBarSize()
        self.onResize()
        self.updateOverflowDropdown()

    def onCustomContextMenuRequested(self, localPoint: QPoint):
        globalPoint = self.tabs.mapToGlobal(localPoint)
        index = self.tabs.tabAt(localPoint)
        self.tabContextMenuRequested.emit(globalPoint, index)

    def onTabMoved(self, fromIndex: int, toIndex: int):
        # Keep QStackedWidget in sync with QTabBar
        w = self.stacked.widget(fromIndex)
        self.stacked.removeWidget(w)
        self.stacked.insertWidget(toIndex, w)

    def onCurrentChanged(self, i: int):
        # Keep QStackedWidget in sync with QTabBar
        self.stacked.setCurrentIndex(i)
        currentWidget = self.currentWidget()

        # Make sure the tab is visible within the scrollable area
        self.ensureCurrentTabVisible()

        # Remove urgent flag if any
        if currentWidget is not None and currentWidget.property(QTabWidget2.UrgentPropertyName):
            currentWidget.setProperty(QTabWidget2.UrgentPropertyName, None)
            self.tabs.setTabIcon(i, QIcon())  # clear icon

        # See if we should emit the currentWidgetChanged signal
        if id(currentWidget) != self.shadowCurrentWidgetId:
            self.shadowCurrentWidgetId = id(currentWidget)
            self.currentWidgetChanged.emit()

        # Forward signal
        self.currentChanged.emit(i)

    def addTab(self, w: QWidget, name: str) -> int:
        return self.insertTab(self.count(), w, name)

    def insertTab(self, index: int, w: QWidget, name: str) -> int:
        i1 = self.stacked.insertWidget(index, w)
        i2 = self.tabs.insertTab(index, name)
        self.syncBarSize()
        assert i1 == i2
        return i1

    def setCurrentIndex(self, i: int):
        self.tabs.setCurrentIndex(i)
        self.stacked.setCurrentIndex(i)
        self.tabs.update()

    def indexOf(self, widget: QWidget):
        return self.stacked.indexOf(widget)

    def widget(self, i: int):
        return self.stacked.widget(i)

    def currentIndex(self) -> int:
        return self.stacked.currentIndex()

    def setTabText(self, i: int, text: str):
        self.tabs.setTabText(i, text)

    def setTabTooltip(self, i: int, toolTip: str):
        self.tabs.setTabToolTip(i, toolTip)

    def currentWidget(self) -> QWidget:
        return self.stacked.currentWidget()

    def count(self) -> int:
        return self.stacked.count()

    def removeTab(self, i: int):
        widget = self.stacked.widget(i)
        # remove widget from stacked view _before_ removing the tab,
        # because removing the tab may send a tab change event
        self.stacked.removeWidget(widget)
        self.tabs.removeTab(i)
        self.syncBarSize()

    def widgets(self):
        for i in range(self.stacked.count()):
            yield self.stacked.widget(i)

    def syncBarSize(self):
        h = self.tabs.sizeHint().height()
        if h != 0:
            self.tabScrollArea.setFixedHeight(self.tabs.sizeHint().height())
            self.overflowGradient.resize(self.tabScrollArea.size())

    # I don't like deferring ensureCurrentTabVisible to the next event loop,
    # but the new tabbar width doesn't seem to be refreshed immediately in onCurrentChanged.
    @CallbackAccumulator.deferredMethod
    def ensureCurrentTabVisible(self):
        i = self.currentIndex()
        if i < 0:
            return
        rect = self.tabs.tabRect(i)

        vr = self.tabScrollArea.viewport().contentsRect()
        vr.translate(self.tabScrollArea.horizontalScrollBar().value(), self.tabScrollArea.verticalScrollBar().value())

        if rect.left() < vr.left():
            p = QPoint(rect.left(), rect.center().y())
        else:
            p = QPoint(rect.right(), rect.center().y())
        self.tabScrollArea.ensureVisible(p.x(), p.y())

    def scrollTabs(self, delta: QPoint):
        x = delta.x()
        y = delta.y()
        deltaValue = x if abs(x) > abs(y) else y
        scrollBar = self.tabScrollArea.horizontalScrollBar()
        scrollBar.setValue(scrollBar.value() - deltaValue)

    @CallbackAccumulator.deferredMethod  # don't update overflow button too often
    def updateOverflowDropdown(self):
        if self.tabs.count() <= 1:  # never overflow if there's just one tab
            isOverflowing = False
        else:
            isOverflowing = self.topWidget.width() < self.tabs.width()

        self.overflowGradient.setVisible(isOverflowing)
        self.overflowButton.setVisible(isOverflowing)

        if isOverflowing:
            self.overflowButton.setMaximumHeight(self.tabs.height())

    def onOverflowButtonClicked(self):
        self.overflowMenu.clear()
        for i in range(self.count()):
            action = QAction(self.overflowMenu)
            action.setText(self.tabs.tabText(i))
            action.setToolTip(self.tabs.tabToolTip(i))
            action.triggered.connect(lambda _dummy, j=i: self.setCurrentIndex(j))
            self.overflowMenu.addAction(action)

        pos = self.mapToGlobal(self.overflowButton.pos() + self.overflowButton.rect().bottomLeft())
        self.overflowMenu.popup(pos)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.onResize()

    def onResize(self):
        self.overflowGradient.resize(self.tabScrollArea.size())
        self.ensureCurrentTabVisible()

    def requestAttention(self, i: int):
        if i == self.currentIndex():
            return
        widget = self.widget(i)
        if widget is None:
            return
        if widget.property(QTabWidget2.UrgentPropertyName) == "true":
            return
        widget.setProperty(QTabWidget2.UrgentPropertyName, "true")
        self.tabs.setTabIcon(i, stockIcon("urgent-tab"))
