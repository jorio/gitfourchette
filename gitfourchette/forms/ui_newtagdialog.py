# Form implementation generated from reading ui file 'newtagdialog.ui'
#
# Created by: PyQt6 UI code generator 6.7.1
#
# WARNING: Any manual changes made to this file will be lost when pyuic6 is
# run again.  Do not edit this file unless you know what you are doing.


from gitfourchette.qt import *


class Ui_NewTagDialog(object):
    def setupUi(self, NewTagDialog):
        NewTagDialog.setObjectName("NewTagDialog")
        NewTagDialog.setWindowModality(Qt.WindowModality.WindowModal)
        NewTagDialog.resize(405, 303)
        self.formLayout = QFormLayout(NewTagDialog)
        self.formLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.formLayout.setObjectName("formLayout")
        self.label = QLabel(parent=NewTagDialog)
        self.label.setObjectName("label")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label)
        self.nameEdit = QLineEdit(parent=NewTagDialog)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.nameEdit.sizePolicy().hasHeightForWidth())
        self.nameEdit.setSizePolicy(sizePolicy)
        self.nameEdit.setObjectName("nameEdit")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.nameEdit)
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.pushCheckBox = QCheckBox(parent=NewTagDialog)
        self.pushCheckBox.setObjectName("pushCheckBox")
        self.horizontalLayout.addWidget(self.pushCheckBox)
        self.remoteComboBox = QComboBox(parent=NewTagDialog)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.remoteComboBox.sizePolicy().hasHeightForWidth())
        self.remoteComboBox.setSizePolicy(sizePolicy)
        self.remoteComboBox.setObjectName("remoteComboBox")
        self.horizontalLayout.addWidget(self.remoteComboBox)
        self.formLayout.setLayout(1, QFormLayout.ItemRole.FieldRole, self.horizontalLayout)
        self.buttonBox = QDialogButtonBox(parent=NewTagDialog)
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.formLayout.setWidget(2, QFormLayout.ItemRole.SpanningRole, self.buttonBox)
        self.label.setBuddy(self.nameEdit)

        self.retranslateUi(NewTagDialog)
        self.buttonBox.accepted.connect(NewTagDialog.accept) # type: ignore
        self.buttonBox.rejected.connect(NewTagDialog.reject) # type: ignore
        self.pushCheckBox.toggled['bool'].connect(self.remoteComboBox.setEnabled) # type: ignore
        QMetaObject.connectSlotsByName(NewTagDialog)

    def retranslateUi(self, NewTagDialog):
        _translate = QCoreApplication.translate
        NewTagDialog.setWindowTitle(_translate("NewTagDialog", "New tag"))
        self.label.setText(_translate("NewTagDialog", "&Name:"))
        self.nameEdit.setPlaceholderText(_translate("NewTagDialog", "Enter tag name"))
        self.pushCheckBox.setText(_translate("NewTagDialog", "&Push to:"))
