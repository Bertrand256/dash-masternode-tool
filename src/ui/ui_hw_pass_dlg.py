# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'X:\src\ui\ui_hw_pass_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.8.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_HardwareWalletPassDlg(object):
    def setupUi(self, HardwareWalletPassDlg):
        HardwareWalletPassDlg.setObjectName("HardwareWalletPassDlg")
        HardwareWalletPassDlg.resize(340, 106)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(HardwareWalletPassDlg.sizePolicy().hasHeightForWidth())
        HardwareWalletPassDlg.setSizePolicy(sizePolicy)
        HardwareWalletPassDlg.setMinimumSize(QtCore.QSize(0, 0))
        HardwareWalletPassDlg.setMaximumSize(QtCore.QSize(1000, 1000))
        font = QtGui.QFont()
        font.setBold(False)
        font.setWeight(50)
        HardwareWalletPassDlg.setFont(font)
        HardwareWalletPassDlg.setModal(True)
        self.verticalLayout = QtWidgets.QVBoxLayout(HardwareWalletPassDlg)
        self.verticalLayout.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout.setSpacing(4)
        self.verticalLayout.setObjectName("verticalLayout")
        self.gridLayout = QtWidgets.QGridLayout()
        self.gridLayout.setObjectName("gridLayout")
        self.label = QtWidgets.QLabel(HardwareWalletPassDlg)
        self.label.setObjectName("label")
        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)
        self.edtPass = QtWidgets.QLineEdit(HardwareWalletPassDlg)
        self.edtPass.setMinimumSize(QtCore.QSize(180, 0))
        self.edtPass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtPass.setObjectName("edtPass")
        self.gridLayout.addWidget(self.edtPass, 0, 1, 1, 1)
        self.label_2 = QtWidgets.QLabel(HardwareWalletPassDlg)
        self.label_2.setObjectName("label_2")
        self.gridLayout.addWidget(self.label_2, 1, 0, 1, 1)
        self.edtPassConfirm = QtWidgets.QLineEdit(HardwareWalletPassDlg)
        self.edtPassConfirm.setMinimumSize(QtCore.QSize(180, 0))
        self.edtPassConfirm.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtPassConfirm.setObjectName("edtPassConfirm")
        self.gridLayout.addWidget(self.edtPassConfirm, 1, 1, 1, 1)
        self.verticalLayout.addLayout(self.gridLayout)
        spacerItem = QtWidgets.QSpacerItem(20, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem1 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem1)
        self.btnEnterPass = QtWidgets.QPushButton(HardwareWalletPassDlg)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.btnEnterPass.sizePolicy().hasHeightForWidth())
        self.btnEnterPass.setSizePolicy(sizePolicy)
        self.btnEnterPass.setMinimumSize(QtCore.QSize(150, 0))
        self.btnEnterPass.setAutoRepeatDelay(36)
        self.btnEnterPass.setAutoDefault(False)
        self.btnEnterPass.setDefault(True)
        self.btnEnterPass.setObjectName("btnEnterPass")
        self.horizontalLayout.addWidget(self.btnEnterPass)
        spacerItem2 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem2)
        self.verticalLayout.addLayout(self.horizontalLayout)

        self.retranslateUi(HardwareWalletPassDlg)
        QtCore.QMetaObject.connectSlotsByName(HardwareWalletPassDlg)

    def retranslateUi(self, HardwareWalletPassDlg):
        _translate = QtCore.QCoreApplication.translate
        HardwareWalletPassDlg.setWindowTitle(_translate("HardwareWalletPassDlg", "Dialog"))
        self.label.setText(_translate("HardwareWalletPassDlg", "Passphrase:"))
        self.label_2.setText(_translate("HardwareWalletPassDlg", "Confirm passphrase:"))
        self.btnEnterPass.setText(_translate("HardwareWalletPassDlg", "Enter"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    HardwareWalletPassDlg = QtWidgets.QDialog()
    ui = Ui_HardwareWalletPassDlg()
    ui.setupUi(HardwareWalletPassDlg)
    HardwareWalletPassDlg.show()
    sys.exit(app.exec_())

