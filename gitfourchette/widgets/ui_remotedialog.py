################################################################################
## Form generated from reading UI file 'remotedialog.ui'
##
## Created by: Qt User Interface Compiler version 6.4.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from gitfourchette.qt import *

class Ui_RemoteDialog(object):
    def setupUi(self, RemoteDialog):
        if not RemoteDialog.objectName():
            RemoteDialog.setObjectName(u"RemoteDialog")
        RemoteDialog.setWindowModality(Qt.NonModal)
        RemoteDialog.setEnabled(True)
        RemoteDialog.resize(500, 296)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(RemoteDialog.sizePolicy().hasHeightForWidth())
        RemoteDialog.setSizePolicy(sizePolicy)
        RemoteDialog.setModal(True)
        self.formLayout = QFormLayout(RemoteDialog)
        self.formLayout.setObjectName(u"formLayout")
        self.formLayout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.buttonBox = QDialogButtonBox(RemoteDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)
        self.buttonBox.setCenterButtons(False)

        self.formLayout.setWidget(6, QFormLayout.SpanningRole, self.buttonBox)

        self.nameEdit = QLineEdit(RemoteDialog)
        self.nameEdit.setObjectName(u"nameEdit")

        self.formLayout.setWidget(0, QFormLayout.FieldRole, self.nameEdit)

        self.urlEdit = QLineEdit(RemoteDialog)
        self.urlEdit.setObjectName(u"urlEdit")

        self.formLayout.setWidget(1, QFormLayout.FieldRole, self.urlEdit)

        self.nameLabel = QLabel(RemoteDialog)
        self.nameLabel.setObjectName(u"nameLabel")

        self.formLayout.setWidget(0, QFormLayout.LabelRole, self.nameLabel)

        self.urlLabel = QLabel(RemoteDialog)
        self.urlLabel.setObjectName(u"urlLabel")

        self.formLayout.setWidget(1, QFormLayout.LabelRole, self.urlLabel)

        self.verticalSpacer = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Fixed)

        self.formLayout.setItem(2, QFormLayout.LabelRole, self.verticalSpacer)

        self.keyFileGroupBox = QGroupBox(RemoteDialog)
        self.keyFileGroupBox.setObjectName(u"keyFileGroupBox")
        sizePolicy.setHeightForWidth(self.keyFileGroupBox.sizePolicy().hasHeightForWidth())
        self.keyFileGroupBox.setSizePolicy(sizePolicy)
        self.keyFileGroupBox.setCheckable(True)
        self.gridLayout = QGridLayout(self.keyFileGroupBox)
        self.gridLayout.setObjectName(u"gridLayout")
        self.keyFilePathEdit = QLineEdit(self.keyFileGroupBox)
        self.keyFilePathEdit.setObjectName(u"keyFilePathEdit")

        self.gridLayout.addWidget(self.keyFilePathEdit, 0, 0, 1, 1)

        self.keyFileBrowseButton = QPushButton(self.keyFileGroupBox)
        self.keyFileBrowseButton.setObjectName(u"keyFileBrowseButton")

        self.gridLayout.addWidget(self.keyFileBrowseButton, 0, 1, 1, 1)


        self.formLayout.setWidget(3, QFormLayout.SpanningRole, self.keyFileGroupBox)

#if QT_CONFIG(shortcut)
        self.nameLabel.setBuddy(self.urlEdit)
        self.urlLabel.setBuddy(self.nameEdit)
#endif // QT_CONFIG(shortcut)
        QWidget.setTabOrder(self.nameEdit, self.urlEdit)
        QWidget.setTabOrder(self.urlEdit, self.keyFileGroupBox)
        QWidget.setTabOrder(self.keyFileGroupBox, self.keyFilePathEdit)
        QWidget.setTabOrder(self.keyFilePathEdit, self.keyFileBrowseButton)

        self.retranslateUi(RemoteDialog)
        self.buttonBox.accepted.connect(RemoteDialog.accept)
        self.buttonBox.rejected.connect(RemoteDialog.reject)

        QMetaObject.connectSlotsByName(RemoteDialog)

    def retranslateUi(self, RemoteDialog):
        RemoteDialog.setWindowTitle(QCoreApplication.translate("RemoteDialog", u"Edit remote", None))
        self.nameLabel.setText(QCoreApplication.translate("RemoteDialog", u"&Name:", None))
        self.urlLabel.setText(QCoreApplication.translate("RemoteDialog", u"&URL:", None))
        self.keyFileGroupBox.setTitle(QCoreApplication.translate("RemoteDialog", u"Use a custom &key file to access this remote", None))
        self.keyFilePathEdit.setPlaceholderText(QCoreApplication.translate("RemoteDialog", u"Path to public or private key", None))
        self.keyFileBrowseButton.setText(QCoreApplication.translate("RemoteDialog", u"&Browse...", None))
