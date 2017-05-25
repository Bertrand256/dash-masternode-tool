# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'X:\src\ui\ui_sign_message_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.8.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_SignMessageDlg(object):
    def setupUi(self, SignMessageDlg):
        SignMessageDlg.setObjectName("SignMessageDlg")
        SignMessageDlg.resize(473, 312)
        SignMessageDlg.setModal(True)
        self.verticalLayout = QtWidgets.QVBoxLayout(SignMessageDlg)
        self.verticalLayout.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout.setSpacing(3)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setContentsMargins(-1, -1, -1, 6)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label_4 = QtWidgets.QLabel(SignMessageDlg)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_4.sizePolicy().hasHeightForWidth())
        self.label_4.setSizePolicy(sizePolicy)
        self.label_4.setObjectName("label_4")
        self.horizontalLayout_2.addWidget(self.label_4)
        self.lblSigningAddress = QtWidgets.QLabel(SignMessageDlg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.lblSigningAddress.setFont(font)
        self.lblSigningAddress.setText("")
        self.lblSigningAddress.setObjectName("lblSigningAddress")
        self.horizontalLayout_2.addWidget(self.lblSigningAddress)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        self.label = QtWidgets.QLabel(SignMessageDlg)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.edtMessageToSign = QtWidgets.QPlainTextEdit(SignMessageDlg)
        self.edtMessageToSign.setObjectName("edtMessageToSign")
        self.verticalLayout.addWidget(self.edtMessageToSign)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.btnSignMessage = QtWidgets.QPushButton(SignMessageDlg)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.btnSignMessage.sizePolicy().hasHeightForWidth())
        self.btnSignMessage.setSizePolicy(sizePolicy)
        font = QtGui.QFont()
        font.setBold(False)
        font.setWeight(50)
        self.btnSignMessage.setFont(font)
        self.btnSignMessage.setObjectName("btnSignMessage")
        self.horizontalLayout.addWidget(self.btnSignMessage)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.label_2 = QtWidgets.QLabel(SignMessageDlg)
        self.label_2.setObjectName("label_2")
        self.verticalLayout.addWidget(self.label_2)
        self.edtSignedMessage = QtWidgets.QPlainTextEdit(SignMessageDlg)
        self.edtSignedMessage.setReadOnly(True)
        self.edtSignedMessage.setObjectName("edtSignedMessage")
        self.verticalLayout.addWidget(self.edtSignedMessage)
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_3.addItem(spacerItem)
        self.btnClose = QtWidgets.QPushButton(SignMessageDlg)
        self.btnClose.setDefault(True)
        self.btnClose.setObjectName("btnClose")
        self.horizontalLayout_3.addWidget(self.btnClose)
        self.verticalLayout.addLayout(self.horizontalLayout_3)

        self.retranslateUi(SignMessageDlg)
        QtCore.QMetaObject.connectSlotsByName(SignMessageDlg)

    def retranslateUi(self, SignMessageDlg):
        _translate = QtCore.QCoreApplication.translate
        SignMessageDlg.setWindowTitle(_translate("SignMessageDlg", "Dialog"))
        self.label_4.setText(_translate("SignMessageDlg", "Signing address:"))
        self.label.setText(_translate("SignMessageDlg", "Message to sign:"))
        self.btnSignMessage.setText(_translate("SignMessageDlg", "Sign message"))
        self.label_2.setText(_translate("SignMessageDlg", "Signed message:"))
        self.btnClose.setText(_translate("SignMessageDlg", "Close"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    SignMessageDlg = QtWidgets.QDialog()
    ui = Ui_SignMessageDlg()
    ui.setupUi(SignMessageDlg)
    SignMessageDlg.show()
    sys.exit(app.exec_())

