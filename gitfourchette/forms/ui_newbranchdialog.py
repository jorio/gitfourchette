# Form implementation generated from reading ui file 'newbranchdialog.ui'
#
# Created by: PyQt6 UI code generator 6.6.0
#
# WARNING: Any manual changes made to this file will be lost when pyuic6 is
# run again.  Do not edit this file unless you know what you are doing.


from gitfourchette.qt import *


class Ui_NewBranchDialog(object):
    def setupUi(self, NewBranchDialog):
        NewBranchDialog.setObjectName("NewBranchDialog")
        NewBranchDialog.setWindowModality(Qt.WindowModality.NonModal)
        NewBranchDialog.setEnabled(True)
        NewBranchDialog.resize(543, 202)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(NewBranchDialog.sizePolicy().hasHeightForWidth())
        NewBranchDialog.setSizePolicy(sizePolicy)
        NewBranchDialog.setSizeGripEnabled(False)
        NewBranchDialog.setModal(True)
        self.formLayout = QFormLayout(NewBranchDialog)
        self.formLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.formLayout.setObjectName("formLayout")
        self.nameLabel = QLabel(parent=NewBranchDialog)
        self.nameLabel.setObjectName("nameLabel")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.nameLabel)
        self.optionsLabel = QLabel(parent=NewBranchDialog)
        self.optionsLabel.setObjectName("optionsLabel")
        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.optionsLabel)
        self.switchToBranchCheckBox = QCheckBox(parent=NewBranchDialog)
        self.switchToBranchCheckBox.setChecked(True)
        self.switchToBranchCheckBox.setObjectName("switchToBranchCheckBox")
        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.switchToBranchCheckBox)
        self.upstreamLayout = QHBoxLayout()
        self.upstreamLayout.setObjectName("upstreamLayout")
        self.upstreamCheckBox = QCheckBox(parent=NewBranchDialog)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.upstreamCheckBox.sizePolicy().hasHeightForWidth())
        self.upstreamCheckBox.setSizePolicy(sizePolicy)
        self.upstreamCheckBox.setObjectName("upstreamCheckBox")
        self.upstreamLayout.addWidget(self.upstreamCheckBox)
        self.upstreamComboBox = QComboBox(parent=NewBranchDialog)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.upstreamComboBox.sizePolicy().hasHeightForWidth())
        self.upstreamComboBox.setSizePolicy(sizePolicy)
        self.upstreamComboBox.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.upstreamComboBox.setObjectName("upstreamComboBox")
        self.upstreamLayout.addWidget(self.upstreamComboBox)
        self.formLayout.setLayout(3, QFormLayout.ItemRole.FieldRole, self.upstreamLayout)
        self.buttonBox = QDialogButtonBox(parent=NewBranchDialog)
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.buttonBox.setCenterButtons(False)
        self.buttonBox.setObjectName("buttonBox")
        self.formLayout.setWidget(6, QFormLayout.ItemRole.FieldRole, self.buttonBox)
        self.nameEdit = QLineEdit(parent=NewBranchDialog)
        self.nameEdit.setObjectName("nameEdit")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.nameEdit)
        self.nameLabel.setBuddy(self.nameEdit)

        self.retranslateUi(NewBranchDialog)
        self.buttonBox.rejected.connect(NewBranchDialog.reject) # type: ignore
        self.buttonBox.accepted.connect(NewBranchDialog.accept) # type: ignore
        self.upstreamCheckBox.toggled['bool'].connect(self.upstreamComboBox.setEnabled) # type: ignore
        QMetaObject.connectSlotsByName(NewBranchDialog)
        NewBranchDialog.setTabOrder(self.switchToBranchCheckBox, self.upstreamCheckBox)
        NewBranchDialog.setTabOrder(self.upstreamCheckBox, self.upstreamComboBox)

    def retranslateUi(self, NewBranchDialog):
        _translate = QCoreApplication.translate
        NewBranchDialog.setWindowTitle(_translate("NewBranchDialog", "New branch"))
        self.nameLabel.setText(_translate("NewBranchDialog", "Name"))
        self.optionsLabel.setText(_translate("NewBranchDialog", "Options"))
        self.switchToBranchCheckBox.setText(_translate("NewBranchDialog", "Switch to branch after creating"))
        self.upstreamCheckBox.setText(_translate("NewBranchDialog", "&Track remote branch"))
