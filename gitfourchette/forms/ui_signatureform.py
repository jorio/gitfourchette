# Form implementation generated from reading ui file 'signatureform.ui'
#
# Created by: PyQt6 UI code generator 6.8.0.dev2410211537
#
# WARNING: Any manual changes made to this file will be lost when pyuic6 is
# run again.  Do not edit this file unless you know what you are doing.


from gitfourchette.qt import *


class Ui_SignatureForm(object):
    def setupUi(self, SignatureForm):
        SignatureForm.setObjectName("SignatureForm")
        SignatureForm.resize(340, 96)
        self.formLayout = QFormLayout(SignatureForm)
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.formLayout.setObjectName("formLayout")
        self.replaceLabel = QLabel(parent=SignatureForm)
        self.replaceLabel.setObjectName("replaceLabel")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.replaceLabel)
        self.nameLabel = QLabel(parent=SignatureForm)
        self.nameLabel.setObjectName("nameLabel")
        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.nameLabel)
        self.identityLayout = QHBoxLayout()
        self.identityLayout.setObjectName("identityLayout")
        self.nameEdit = QLineEdit(parent=SignatureForm)
        self.nameEdit.setObjectName("nameEdit")
        self.identityLayout.addWidget(self.nameEdit)
        self.emailEdit = QLineEdit(parent=SignatureForm)
        self.emailEdit.setObjectName("emailEdit")
        self.identityLayout.addWidget(self.emailEdit)
        self.formLayout.setLayout(1, QFormLayout.ItemRole.FieldRole, self.identityLayout)
        self.timeLabel = QLabel(parent=SignatureForm)
        self.timeLabel.setObjectName("timeLabel")
        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.timeLabel)
        self.timeLayout = QHBoxLayout()
        self.timeLayout.setObjectName("timeLayout")
        self.timeEdit = QDateTimeEdit(parent=SignatureForm)
        self.timeEdit.setCurrentSection(QDateTimeEdit.Section.YearSection)
        self.timeEdit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.timeEdit.setCalendarPopup(True)
        self.timeEdit.setObjectName("timeEdit")
        self.timeLayout.addWidget(self.timeEdit)
        self.offsetEdit = QComboBox(parent=SignatureForm)
        self.offsetEdit.setEditable(False)
        self.offsetEdit.setObjectName("offsetEdit")
        self.timeLayout.addWidget(self.offsetEdit)
        self.nowButton = QToolButton(parent=SignatureForm)
        self.nowButton.setObjectName("nowButton")
        self.timeLayout.addWidget(self.nowButton)
        self.formLayout.setLayout(2, QFormLayout.ItemRole.FieldRole, self.timeLayout)
        self.replaceComboBox = QComboBox(parent=SignatureForm)
        self.replaceComboBox.setObjectName("replaceComboBox")
        self.replaceComboBox.addItem("")
        self.replaceComboBox.addItem("")
        self.replaceComboBox.addItem("")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.replaceComboBox)
        self.replaceLabel.setBuddy(self.replaceComboBox)
        self.nameLabel.setBuddy(self.nameEdit)
        self.timeLabel.setBuddy(self.timeEdit)

        self.retranslateUi(SignatureForm)
        QMetaObject.connectSlotsByName(SignatureForm)
        SignatureForm.setTabOrder(self.replaceComboBox, self.nameEdit)
        SignatureForm.setTabOrder(self.nameEdit, self.emailEdit)
        SignatureForm.setTabOrder(self.emailEdit, self.timeEdit)
        SignatureForm.setTabOrder(self.timeEdit, self.offsetEdit)
        SignatureForm.setTabOrder(self.offsetEdit, self.nowButton)

    def retranslateUi(self, SignatureForm):
        _translate = QCoreApplication.translate
        SignatureForm.setWindowTitle(_translate("SignatureForm", "Signature"))
        self.replaceLabel.setText(_translate("SignatureForm", "&Override:"))
        self.nameLabel.setText(_translate("SignatureForm", "&Identity:"))
        self.nameEdit.setToolTip(_translate("SignatureForm", "Name"))
        self.nameEdit.setPlaceholderText(_translate("SignatureForm", "Name"))
        self.emailEdit.setToolTip(_translate("SignatureForm", "Email"))
        self.emailEdit.setPlaceholderText(_translate("SignatureForm", "Email"))
        self.timeLabel.setText(_translate("SignatureForm", "&Time:"))
        self.offsetEdit.setToolTip(_translate("SignatureForm", "Offset from UTC"))
        self.nowButton.setToolTip(_translate("SignatureForm", "Set to current local time"))
        self.nowButton.setText(_translate("SignatureForm", "Now"))
        self.replaceComboBox.setToolTip(_translate("SignatureForm", "<p>Two signatures are recorded in every commit – one for the author, and one for the committer. Select which signature you want to customize."))
        self.replaceComboBox.setItemText(0, _translate("SignatureForm", "Author’s Signature"))
        self.replaceComboBox.setItemText(1, _translate("SignatureForm", "Committer’s Signature"))
        self.replaceComboBox.setItemText(2, _translate("SignatureForm", "Both Signatures"))
