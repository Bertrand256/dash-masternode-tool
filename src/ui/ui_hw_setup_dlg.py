# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_hw_setup_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.8.1
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_HwSetupDlg(object):
    def setupUi(self, HwSetupDlg):
        HwSetupDlg.setObjectName("HwSetupDlg")
        HwSetupDlg.resize(317, 112)
        self.gridLayout = QtWidgets.QGridLayout(HwSetupDlg)
        self.gridLayout.setHorizontalSpacing(4)
        self.gridLayout.setVerticalSpacing(0)
        self.gridLayout.setObjectName("gridLayout")
        self.btnEnDisPin = QtWidgets.QPushButton(HwSetupDlg)
        self.btnEnDisPin.setAutoDefault(False)
        self.btnEnDisPin.setObjectName("btnEnDisPin")
        self.gridLayout.addWidget(self.btnEnDisPin, 1, 2, 1, 1)
        self.btnClose = QtWidgets.QPushButton(HwSetupDlg)
        self.btnClose.setObjectName("btnClose")
        self.gridLayout.addWidget(self.btnClose, 3, 3, 1, 1)
        self.label = QtWidgets.QLabel(HwSetupDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label.setFont(font)
        self.label.setObjectName("label")
        self.gridLayout.addWidget(self.label, 1, 0, 1, 1)
        self.label_3 = QtWidgets.QLabel(HwSetupDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_3.setFont(font)
        self.label_3.setObjectName("label_3")
        self.gridLayout.addWidget(self.label_3, 2, 0, 1, 1)
        self.btnEnDisPass = QtWidgets.QPushButton(HwSetupDlg)
        self.btnEnDisPass.setAutoDefault(False)
        self.btnEnDisPass.setObjectName("btnEnDisPass")
        self.gridLayout.addWidget(self.btnEnDisPass, 2, 2, 1, 1)
        self.lblPinStatus = QtWidgets.QLabel(HwSetupDlg)
        self.lblPinStatus.setObjectName("lblPinStatus")
        self.gridLayout.addWidget(self.lblPinStatus, 1, 1, 1, 1)
        self.btnChangePin = QtWidgets.QPushButton(HwSetupDlg)
        self.btnChangePin.setAutoDefault(False)
        self.btnChangePin.setObjectName("btnChangePin")
        self.gridLayout.addWidget(self.btnChangePin, 1, 3, 1, 1)
        self.lblPassStatus = QtWidgets.QLabel(HwSetupDlg)
        self.lblPassStatus.setObjectName("lblPassStatus")
        self.gridLayout.addWidget(self.lblPassStatus, 2, 1, 1, 1)
        self.label_2 = QtWidgets.QLabel(HwSetupDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_2.setFont(font)
        self.label_2.setObjectName("label_2")
        self.gridLayout.addWidget(self.label_2, 0, 0, 1, 1)
        self.lblVersion = QtWidgets.QLabel(HwSetupDlg)
        self.lblVersion.setObjectName("lblVersion")
        self.gridLayout.addWidget(self.lblVersion, 0, 1, 1, 1)

        self.retranslateUi(HwSetupDlg)
        QtCore.QMetaObject.connectSlotsByName(HwSetupDlg)

    def retranslateUi(self, HwSetupDlg):
        _translate = QtCore.QCoreApplication.translate
        HwSetupDlg.setWindowTitle(_translate("HwSetupDlg", "Dialog"))
        self.btnEnDisPin.setText(_translate("HwSetupDlg", "Disable"))
        self.btnClose.setText(_translate("HwSetupDlg", "Close"))
        self.label.setText(_translate("HwSetupDlg", "PIN:"))
        self.label_3.setText(_translate("HwSetupDlg", "Passphrase:"))
        self.btnEnDisPass.setText(_translate("HwSetupDlg", "Disable"))
        self.lblPinStatus.setText(_translate("HwSetupDlg", "enabled"))
        self.btnChangePin.setText(_translate("HwSetupDlg", "Change"))
        self.lblPassStatus.setText(_translate("HwSetupDlg", "enabled"))
        self.label_2.setText(_translate("HwSetupDlg", "Version:"))
        self.lblVersion.setText(_translate("HwSetupDlg", "?"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    HwSetupDlg = QtWidgets.QDialog()
    ui = Ui_HwSetupDlg()
    ui.setupUi(HwSetupDlg)
    HwSetupDlg.show()
    sys.exit(app.exec_())

