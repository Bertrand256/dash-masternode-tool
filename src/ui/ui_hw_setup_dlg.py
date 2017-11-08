# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_hw_setup_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.9
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_HwSetupDlg(object):
    def setupUi(self, HwSetupDlg):
        HwSetupDlg.setObjectName("HwSetupDlg")
        HwSetupDlg.resize(366, 141)
        self.verticalLayout = QtWidgets.QVBoxLayout(HwSetupDlg)
        self.verticalLayout.setContentsMargins(8, 8, 8, 6)
        self.verticalLayout.setSpacing(8)
        self.verticalLayout.setObjectName("verticalLayout")
        self.gridLayout = QtWidgets.QGridLayout()
        self.gridLayout.setSpacing(4)
        self.gridLayout.setObjectName("gridLayout")
        self.btnEnDisPass = QtWidgets.QPushButton(HwSetupDlg)
        self.btnEnDisPass.setAutoDefault(False)
        self.btnEnDisPass.setObjectName("btnEnDisPass")
        self.gridLayout.addWidget(self.btnEnDisPass, 2, 2, 1, 1)
        self.lblPinStatusLabel = QtWidgets.QLabel(HwSetupDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.lblPinStatusLabel.setFont(font)
        self.lblPinStatusLabel.setObjectName("lblPinStatusLabel")
        self.gridLayout.addWidget(self.lblPinStatusLabel, 1, 0, 1, 1)
        self.label_2 = QtWidgets.QLabel(HwSetupDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_2.setFont(font)
        self.label_2.setObjectName("label_2")
        self.gridLayout.addWidget(self.label_2, 0, 0, 1, 1)
        self.btnChangePin = QtWidgets.QPushButton(HwSetupDlg)
        self.btnChangePin.setAutoDefault(False)
        self.btnChangePin.setObjectName("btnChangePin")
        self.gridLayout.addWidget(self.btnChangePin, 1, 3, 1, 1)
        self.lblPinStatus = QtWidgets.QLabel(HwSetupDlg)
        self.lblPinStatus.setObjectName("lblPinStatus")
        self.gridLayout.addWidget(self.lblPinStatus, 1, 1, 1, 1)
        self.btnEnDisPin = QtWidgets.QPushButton(HwSetupDlg)
        self.btnEnDisPin.setAutoDefault(False)
        self.btnEnDisPin.setObjectName("btnEnDisPin")
        self.gridLayout.addWidget(self.btnEnDisPin, 1, 2, 1, 1)
        self.lblPassStatus = QtWidgets.QLabel(HwSetupDlg)
        self.lblPassStatus.setObjectName("lblPassStatus")
        self.gridLayout.addWidget(self.lblPassStatus, 2, 1, 1, 1)
        self.lblPassStatusLabel = QtWidgets.QLabel(HwSetupDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.lblPassStatusLabel.setFont(font)
        self.lblPassStatusLabel.setObjectName("lblPassStatusLabel")
        self.gridLayout.addWidget(self.lblPassStatusLabel, 2, 0, 1, 1)
        self.lblVersion = QtWidgets.QLabel(HwSetupDlg)
        self.lblVersion.setMinimumSize(QtCore.QSize(128, 0))
        self.lblVersion.setObjectName("lblVersion")
        self.gridLayout.addWidget(self.lblVersion, 0, 1, 1, 3)
        self.verticalLayout.addLayout(self.gridLayout)
        self.lblMessage = QtWidgets.QLabel(HwSetupDlg)
        self.lblMessage.setStyleSheet("color:red")
        self.lblMessage.setObjectName("lblMessage")
        self.verticalLayout.addWidget(self.lblMessage)
        self.buttonBox = QtWidgets.QDialogButtonBox(HwSetupDlg)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(HwSetupDlg)
        QtCore.QMetaObject.connectSlotsByName(HwSetupDlg)

    def retranslateUi(self, HwSetupDlg):
        _translate = QtCore.QCoreApplication.translate
        HwSetupDlg.setWindowTitle(_translate("HwSetupDlg", "Dialog"))
        self.btnEnDisPass.setText(_translate("HwSetupDlg", "Disable"))
        self.lblPinStatusLabel.setText(_translate("HwSetupDlg", "PIN:"))
        self.label_2.setText(_translate("HwSetupDlg", "Version:"))
        self.btnChangePin.setText(_translate("HwSetupDlg", "Change"))
        self.lblPinStatus.setText(_translate("HwSetupDlg", "enabled"))
        self.btnEnDisPin.setText(_translate("HwSetupDlg", "Disable"))
        self.lblPassStatus.setText(_translate("HwSetupDlg", "enabled"))
        self.lblPassStatusLabel.setText(_translate("HwSetupDlg", "Passphrase:"))
        self.lblVersion.setText(_translate("HwSetupDlg", "?"))
        self.lblMessage.setText(_translate("HwSetupDlg", "PIN/passphrase features are not available for Ledger devices."))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    HwSetupDlg = QtWidgets.QDialog()
    ui = Ui_HwSetupDlg()
    ui.setupUi(HwSetupDlg)
    HwSetupDlg.show()
    sys.exit(app.exec_())

