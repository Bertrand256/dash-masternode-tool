# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'src/wnd_trezor_pass_base.ui'
#
# Created by: PyQt5 UI code generator 5.8.1
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogTrezorPass(object):
    def setupUi(self, DialogTrezorPass):
        DialogTrezorPass.setObjectName("DialogTrezorPass")
        DialogTrezorPass.resize(328, 107)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(DialogTrezorPass.sizePolicy().hasHeightForWidth())
        DialogTrezorPass.setSizePolicy(sizePolicy)
        DialogTrezorPass.setMinimumSize(QtCore.QSize(328, 107))
        DialogTrezorPass.setMaximumSize(QtCore.QSize(328, 107))
        font = QtGui.QFont()
        font.setBold(False)
        font.setWeight(50)
        DialogTrezorPass.setFont(font)
        DialogTrezorPass.setModal(True)
        self.btnEnterPass = QtWidgets.QPushButton(DialogTrezorPass)
        self.btnEnterPass.setGeometry(QtCore.QRect(80, 70, 161, 31))
        self.btnEnterPass.setAutoRepeatDelay(36)
        self.btnEnterPass.setAutoDefault(False)
        self.btnEnterPass.setDefault(True)
        self.btnEnterPass.setObjectName("btnEnterPass")
        self.layoutWidget = QtWidgets.QWidget(DialogTrezorPass)
        self.layoutWidget.setGeometry(QtCore.QRect(10, 10, 311, 54))
        self.layoutWidget.setObjectName("layoutWidget")
        self.gridLayout = QtWidgets.QGridLayout(self.layoutWidget)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setObjectName("gridLayout")
        self.label = QtWidgets.QLabel(self.layoutWidget)
        self.label.setObjectName("label")
        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)
        self.edtPass = QtWidgets.QLineEdit(self.layoutWidget)
        self.edtPass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtPass.setObjectName("edtPass")
        self.gridLayout.addWidget(self.edtPass, 0, 1, 1, 1)
        self.label_2 = QtWidgets.QLabel(self.layoutWidget)
        self.label_2.setObjectName("label_2")
        self.gridLayout.addWidget(self.label_2, 1, 0, 1, 1)
        self.edtPassConfirm = QtWidgets.QLineEdit(self.layoutWidget)
        self.edtPassConfirm.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtPassConfirm.setObjectName("edtPassConfirm")
        self.gridLayout.addWidget(self.edtPassConfirm, 1, 1, 1, 1)

        self.retranslateUi(DialogTrezorPass)
        QtCore.QMetaObject.connectSlotsByName(DialogTrezorPass)

    def retranslateUi(self, DialogTrezorPass):
        _translate = QtCore.QCoreApplication.translate
        DialogTrezorPass.setWindowTitle(_translate("DialogTrezorPass", "Dialog"))
        self.btnEnterPass.setText(_translate("DialogTrezorPass", "Enter"))
        self.label.setText(_translate("DialogTrezorPass", "Passphrase:"))
        self.label_2.setText(_translate("DialogTrezorPass", "Confirm passphrase:"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    DialogTrezorPass = QtWidgets.QDialog()
    ui = Ui_DialogTrezorPass()
    ui.setupUi(DialogTrezorPass)
    DialogTrezorPass.show()
    sys.exit(app.exec_())

