# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'src/wnd_hw_setup_base.ui'
#
# Created by: PyQt5 UI code generator 5.8.1
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogHwSetup(object):
    def setupUi(self, DialogHwSetup):
        DialogHwSetup.setObjectName("DialogHwSetup")
        DialogHwSetup.resize(317, 92)
        self.gridLayout = QtWidgets.QGridLayout(DialogHwSetup)
        self.gridLayout.setHorizontalSpacing(4)
        self.gridLayout.setVerticalSpacing(0)
        self.gridLayout.setObjectName("gridLayout")
        self.lblPinStatus = QtWidgets.QLabel(DialogHwSetup)
        self.lblPinStatus.setObjectName("lblPinStatus")
        self.gridLayout.addWidget(self.lblPinStatus, 0, 1, 1, 1)
        self.btnChangePin = QtWidgets.QPushButton(DialogHwSetup)
        self.btnChangePin.setAutoDefault(False)
        self.btnChangePin.setObjectName("btnChangePin")
        self.gridLayout.addWidget(self.btnChangePin, 0, 3, 1, 1)
        self.lblPassStatus = QtWidgets.QLabel(DialogHwSetup)
        self.lblPassStatus.setObjectName("lblPassStatus")
        self.gridLayout.addWidget(self.lblPassStatus, 1, 1, 1, 1)
        self.label_3 = QtWidgets.QLabel(DialogHwSetup)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_3.setFont(font)
        self.label_3.setObjectName("label_3")
        self.gridLayout.addWidget(self.label_3, 1, 0, 1, 1)
        self.btnEnDisPass = QtWidgets.QPushButton(DialogHwSetup)
        self.btnEnDisPass.setAutoDefault(False)
        self.btnEnDisPass.setObjectName("btnEnDisPass")
        self.gridLayout.addWidget(self.btnEnDisPass, 1, 2, 1, 1)
        self.label = QtWidgets.QLabel(DialogHwSetup)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label.setFont(font)
        self.label.setObjectName("label")
        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)
        self.btnClose = QtWidgets.QPushButton(DialogHwSetup)
        self.btnClose.setObjectName("btnClose")
        self.gridLayout.addWidget(self.btnClose, 2, 3, 1, 1)
        self.btnEnDisPin = QtWidgets.QPushButton(DialogHwSetup)
        self.btnEnDisPin.setAutoDefault(False)
        self.btnEnDisPin.setObjectName("btnEnDisPin")
        self.gridLayout.addWidget(self.btnEnDisPin, 0, 2, 1, 1)

        self.retranslateUi(DialogHwSetup)
        QtCore.QMetaObject.connectSlotsByName(DialogHwSetup)

    def retranslateUi(self, DialogHwSetup):
        _translate = QtCore.QCoreApplication.translate
        DialogHwSetup.setWindowTitle(_translate("DialogHwSetup", "Dialog"))
        self.lblPinStatus.setText(_translate("DialogHwSetup", "enabled"))
        self.btnChangePin.setText(_translate("DialogHwSetup", "Change"))
        self.lblPassStatus.setText(_translate("DialogHwSetup", "enabled"))
        self.label_3.setText(_translate("DialogHwSetup", "Passphrase:"))
        self.btnEnDisPass.setText(_translate("DialogHwSetup", "Disable"))
        self.label.setText(_translate("DialogHwSetup", "PIN:"))
        self.btnClose.setText(_translate("DialogHwSetup", "Close"))
        self.btnEnDisPin.setText(_translate("DialogHwSetup", "Disable"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    DialogHwSetup = QtWidgets.QDialog()
    ui = Ui_DialogHwSetup()
    ui.setupUi(DialogHwSetup)
    DialogHwSetup.show()
    sys.exit(app.exec_())

