# Form implementation generated from reading ui file 'reposettingsdialog.ui'
#
# Created by: PyQt6 UI code generator 6.7.0
#
# WARNING: Any manual changes made to this file will be lost when pyuic6 is
# run again.  Do not edit this file unless you know what you are doing.


from gitfourchette.qt import *


class Ui_RepoSettingsDialog(object):
    def setupUi(self, RepoSettingsDialog):
        RepoSettingsDialog.setObjectName("RepoSettingsDialog")
        RepoSettingsDialog.resize(465, 229)
        self.formLayout = QFormLayout(RepoSettingsDialog)
        self.formLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.formLayout.setObjectName("formLayout")
        self.nicknameLabel = QLabel(parent=RepoSettingsDialog)
        self.nicknameLabel.setObjectName("nicknameLabel")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.nicknameLabel)
        self.nicknameEdit = QLineEdit(parent=RepoSettingsDialog)
        self.nicknameEdit.setClearButtonEnabled(True)
        self.nicknameEdit.setObjectName("nicknameEdit")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.nicknameEdit)
        spacerItem = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.formLayout.setItem(1, QFormLayout.ItemRole.LabelRole, spacerItem)
        self.localIdentityCheckBox = QCheckBox(parent=RepoSettingsDialog)
        self.localIdentityCheckBox.setObjectName("localIdentityCheckBox")
        self.formLayout.setWidget(2, QFormLayout.ItemRole.SpanningRole, self.localIdentityCheckBox)
        self.nameLabel = QLabel(parent=RepoSettingsDialog)
        self.nameLabel.setObjectName("nameLabel")
        self.formLayout.setWidget(3, QFormLayout.ItemRole.LabelRole, self.nameLabel)
        self.nameEdit = QLineEdit(parent=RepoSettingsDialog)
        self.nameEdit.setObjectName("nameEdit")
        self.formLayout.setWidget(3, QFormLayout.ItemRole.FieldRole, self.nameEdit)
        self.emailLabel = QLabel(parent=RepoSettingsDialog)
        self.emailLabel.setObjectName("emailLabel")
        self.formLayout.setWidget(4, QFormLayout.ItemRole.LabelRole, self.emailLabel)
        self.emailEdit = QLineEdit(parent=RepoSettingsDialog)
        self.emailEdit.setObjectName("emailEdit")
        self.formLayout.setWidget(4, QFormLayout.ItemRole.FieldRole, self.emailEdit)
        spacerItem1 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.formLayout.setItem(5, QFormLayout.ItemRole.LabelRole, spacerItem1)
        self.buttonBox = QDialogButtonBox(parent=RepoSettingsDialog)
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.formLayout.setWidget(6, QFormLayout.ItemRole.SpanningRole, self.buttonBox)
        self.nicknameLabel.setBuddy(self.nicknameEdit)
        self.nameLabel.setBuddy(self.nameEdit)
        self.emailLabel.setBuddy(self.emailEdit)

        self.retranslateUi(RepoSettingsDialog)
        self.buttonBox.accepted.connect(RepoSettingsDialog.accept) # type: ignore
        self.buttonBox.rejected.connect(RepoSettingsDialog.reject) # type: ignore
        self.localIdentityCheckBox.toggled['bool'].connect(self.nameLabel.setEnabled) # type: ignore
        self.localIdentityCheckBox.toggled['bool'].connect(self.nameEdit.setEnabled) # type: ignore
        self.localIdentityCheckBox.toggled['bool'].connect(self.emailLabel.setEnabled) # type: ignore
        self.localIdentityCheckBox.toggled['bool'].connect(self.emailEdit.setEnabled) # type: ignore
        QMetaObject.connectSlotsByName(RepoSettingsDialog)

    def retranslateUi(self, RepoSettingsDialog):
        _translate = QCoreApplication.translate
        RepoSettingsDialog.setWindowTitle(_translate("RepoSettingsDialog", "Repo Settings for {repo}"))
        self.nicknameLabel.setText(_translate("RepoSettingsDialog", "Repo Nic&kname:"))
        self.nicknameEdit.setToolTip(_translate("RepoSettingsDialog", "This nickname will appear within {app} in tab names, menus, etc. It does not change the actual name of the repo’s directory. Leave blank to clear the nickname."))
        self.nicknameEdit.setPlaceholderText(_translate("RepoSettingsDialog", "No nickname"))
        self.localIdentityCheckBox.setText(_translate("RepoSettingsDialog", "Create commits under a custom &identity in this repo"))
        self.nameLabel.setText(_translate("RepoSettingsDialog", "&Name:"))
        self.emailLabel.setText(_translate("RepoSettingsDialog", "&Email:"))
