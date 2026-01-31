# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.forms.aboutdialog import DONATE_URL
from gitfourchette.forms.ui_donateprompt import Ui_DonatePrompt
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class DonatePrompt(QDialog):
    MinStartups = 15
    InitialDelay = 60
    PostponeDelay = 90
    SuggestedAmount = float(3)  # float: for Qt 5 compat (QLocale.toCurrencyString)

    def __init__(self, parent):
        super().__init__(parent)

        self.openDonateLinkOnClose = False

        self.ui = Ui_DonatePrompt()
        self.ui.setupUi(self)
        self.ui.stackedWidget.setCurrentIndex(0)
        self.ui.donateButton.setToolTip(DONATE_URL)

        formatWidgetText(self.ui.label, app=qAppName())
        tweakWidgetFont(self.ui.byeButton, 80)
        tweakWidgetFont(self.ui.thanksLabel, 130, bold=True)

        self.ui.mugshot.setText("")
        self.ui.mugshot.setPixmap(QPixmap("assets:icons/mug"))

        nextDate = QDateTime.fromSecsSinceEpoch(settings.prefs.donatePrompt)
        nextMonth = QLocale().monthName(nextDate.date().month())
        formatWidgetText(self.ui.postponeButton, month=nextMonth)

        amount = QLocale().toCurrencyString(DonatePrompt.SuggestedAmount, "$", 0)
        donateText = formatWidgetText(self.ui.donateButton, amount=amount)
        self.ui.donateButton.setText(donateText + "\n")  # Make room for URL label
        donateButtonLabel = QLabel(f"&nbsp;<br><small><u>{DONATE_URL}</u></small>")
        donateButtonLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        donateLayout = QVBoxLayout(self.ui.donateButton)
        donateLayout.setContentsMargins(QMargins())
        donateLayout.addWidget(donateButtonLabel)
        self.ui.donateButton.setCursor(Qt.CursorShape.PointingHandCursor)

        self.ui.donateButton.clicked.connect(self.onDonateButtonPressed)
        self.ui.byeButton.clicked.connect(self.onByeButtonPressed)
        self.ui.postponeButton.clicked.connect(self.close)

        self.finished.connect(self.onDone)

    @staticmethod
    def postpone(days: int) -> int:
        date = QDateTime.currentDateTimeUtc()
        date = date.addDays(days)
        date.setTime(QTime(0, 0, 0))
        scheduledTime = date.toSecsSinceEpoch()

        settings.prefs.donatePrompt = scheduledTime
        settings.prefs.setDirty()
        settings.prefs.write()
        return scheduledTime

    @staticmethod
    def onBoot(parent: QWidget):
        scheduledTime = settings.prefs.donatePrompt

        # Don't show if permanently disabled
        if scheduledTime < 0:
            return

        # Don't show yet if app hasn't been launched enough times
        if settings.history.startups < DonatePrompt.MinStartups:
            return

        # First boot with enough launches, schedule first appearance in the future
        if scheduledTime == 0:
            DonatePrompt.postpone(DonatePrompt.InitialDelay)
            return

        # Don't show yet if scheduled time is still in the future
        now = QDateTime.currentDateTimeUtc()
        if now.toSecsSinceEpoch() < scheduledTime:
            return

        # Don't show yet if any other dialogs are vying for the user's attention on boot
        if parent.findChild(QDialog):
            return

        # Reschedule next appearance
        DonatePrompt.postpone(DonatePrompt.PostponeDelay)

        dp = DonatePrompt(parent)
        dp.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dp.show()

    def onDonateButtonPressed(self):
        settings.prefs.donatePrompt = -1
        settings.prefs.setDirty()
        settings.prefs.write()

        # Show thank-you slide
        self.ui.stackedWidget.setCurrentIndex(1)
        self.setCursor(Qt.CursorShape.WaitCursor)

        self.openDonateLinkOnClose = True
        QTimer.singleShot(1250, self.close)

    def onByeButtonPressed(self):
        settings.prefs.donatePrompt = -1
        settings.prefs.setDirty()
        settings.prefs.write()
        self.close()

    def onDone(self, result):
        if self.openDonateLinkOnClose:
            QDesktopServices.openUrl(QUrl(DONATE_URL))
