################################################################################
## Form generated from reading UI file 'identitydialog.ui'
##
## Created by: Qt User Interface Compiler version 6.4.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from gitfourchette.qt import *

class Ui_IdentityDialog(object):
    def setupUi(self, IdentityDialog):
        if not IdentityDialog.objectName():
            IdentityDialog.setObjectName(u"IdentityDialog")
        IdentityDialog.resize(488, 439)
        self.gridLayout = QGridLayout(IdentityDialog)
        self.gridLayout.setObjectName(u"gridLayout")
        self.verticalSpacer = QSpacerItem(20, 62, QSizePolicy.Minimum, QSizePolicy.Expanding)

        self.gridLayout.addItem(self.verticalSpacer, 0, 0, 1, 1)

        self.label_2 = QLabel(IdentityDialog)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout.addWidget(self.label_2, 1, 0, 1, 2)

        self.nameEdit = QLineEdit(IdentityDialog)
        self.nameEdit.setObjectName(u"nameEdit")

        self.gridLayout.addWidget(self.nameEdit, 1, 2, 1, 1)

        self.label_3 = QLabel(IdentityDialog)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 2, 0, 1, 2)

        self.emailEdit = QLineEdit(IdentityDialog)
        self.emailEdit.setObjectName(u"emailEdit")

        self.gridLayout.addWidget(self.emailEdit, 2, 2, 1, 1)

        self.validatorLabel = QLabel(IdentityDialog)
        self.validatorLabel.setObjectName(u"validatorLabel")
        self.validatorLabel.setEnabled(False)
        self.validatorLabel.setText(u"-validator-")
        self.validatorLabel.setWordWrap(True)

        self.gridLayout.addWidget(self.validatorLabel, 3, 0, 1, 3)

        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Preferred)

        self.gridLayout.addItem(self.verticalSpacer_2, 4, 0, 1, 1)

        self.setGlobalIdentity = QRadioButton(IdentityDialog)
        self.setGlobalIdentity.setObjectName(u"setGlobalIdentity")
        self.setGlobalIdentity.setChecked(True)

        self.gridLayout.addWidget(self.setGlobalIdentity, 5, 0, 1, 3)

        self.horizontalSpacer = QSpacerItem(13, 13, QSizePolicy.Fixed, QSizePolicy.Minimum)

        self.gridLayout.addItem(self.horizontalSpacer, 6, 0, 1, 1)

        self.label_4 = QLabel(IdentityDialog)
        self.label_4.setObjectName(u"label_4")
        self.label_4.setEnabled(False)
        font = QFont()
        font.setPointSize(11)
        self.label_4.setFont(font)
        self.label_4.setWordWrap(True)

        self.gridLayout.addWidget(self.label_4, 6, 1, 1, 2)

        self.setLocalIdentity = QRadioButton(IdentityDialog)
        self.setLocalIdentity.setObjectName(u"setLocalIdentity")

        self.gridLayout.addWidget(self.setLocalIdentity, 7, 0, 1, 3)

        self.horizontalSpacer_2 = QSpacerItem(13, 13, QSizePolicy.Fixed, QSizePolicy.Minimum)

        self.gridLayout.addItem(self.horizontalSpacer_2, 8, 0, 1, 1)

        self.label_5 = QLabel(IdentityDialog)
        self.label_5.setObjectName(u"label_5")
        self.label_5.setEnabled(False)
        self.label_5.setFont(font)
        self.label_5.setWordWrap(True)

        self.gridLayout.addWidget(self.label_5, 8, 1, 1, 2)

        self.verticalSpacer_3 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)

        self.gridLayout.addItem(self.verticalSpacer_3, 9, 0, 1, 1)

        self.buttonBox = QDialogButtonBox(IdentityDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)

        self.gridLayout.addWidget(self.buttonBox, 10, 0, 1, 3)

#if QT_CONFIG(shortcut)
        self.label_2.setBuddy(self.nameEdit)
        self.label_3.setBuddy(self.emailEdit)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(IdentityDialog)
        self.buttonBox.accepted.connect(IdentityDialog.accept)
        self.buttonBox.rejected.connect(IdentityDialog.reject)

        QMetaObject.connectSlotsByName(IdentityDialog)

    def retranslateUi(self, IdentityDialog):
        IdentityDialog.setWindowTitle(QCoreApplication.translate("IdentityDialog", u"Set up your Git identity", None))
        self.label_2.setText(QCoreApplication.translate("IdentityDialog", u"&Name:", None))
        self.label_3.setText(QCoreApplication.translate("IdentityDialog", u"&Email:", None))
        self.setGlobalIdentity.setText(QCoreApplication.translate("IdentityDialog", u"Set &global identity", None))
        self.label_4.setText(QCoreApplication.translate("IdentityDialog", u"Will apply to all repositories on this computer.", None))
        self.setLocalIdentity.setText(QCoreApplication.translate("IdentityDialog", u"Set identity for this &repository only", None))
        self.label_5.setText(QCoreApplication.translate("IdentityDialog", u"You will be prompted to set up an identity for other repositories.", None))
