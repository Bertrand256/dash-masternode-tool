# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'src/wnd_sign_message_base.ui'
#
# Created by: PyQt5 UI code generator 5.8.1
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogSignMessage(object):
    def setupUi(self, DialogSignMessage):
        DialogSignMessage.setObjectName("DialogSignMessage")
        DialogSignMessage.resize(473, 312)
        DialogSignMessage.setModal(True)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogSignMessage)
        self.verticalLayout.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout.setSpacing(3)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setContentsMargins(-1, -1, -1, 6)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label_4 = QtWidgets.QLabel(DialogSignMessage)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_4.sizePolicy().hasHeightForWidth())
        self.label_4.setSizePolicy(sizePolicy)
        self.label_4.setObjectName("label_4")
        self.horizontalLayout_2.addWidget(self.label_4)
        self.lblSigningAddress = QtWidgets.QLabel(DialogSignMessage)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.lblSigningAddress.setFont(font)
        self.lblSigningAddress.setText("")
        self.lblSigningAddress.setObjectName("lblSigningAddress")
        self.horizontalLayout_2.addWidget(self.lblSigningAddress)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        self.label = QtWidgets.QLabel(DialogSignMessage)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.edtMessageToSign = QtWidgets.QPlainTextEdit(DialogSignMessage)
        self.edtMessageToSign.setObjectName("edtMessageToSign")
        self.verticalLayout.addWidget(self.edtMessageToSign)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.btnSignMessage = QtWidgets.QPushButton(DialogSignMessage)
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
        self.label_2 = QtWidgets.QLabel(DialogSignMessage)
        self.label_2.setObjectName("label_2")
        self.verticalLayout.addWidget(self.label_2)
        self.edtSignedMessage = QtWidgets.QPlainTextEdit(DialogSignMessage)
        self.edtSignedMessage.setReadOnly(True)
        self.edtSignedMessage.setObjectName("edtSignedMessage")
        self.verticalLayout.addWidget(self.edtSignedMessage)
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_3.addItem(spacerItem)
        self.btnClose = QtWidgets.QPushButton(DialogSignMessage)
        self.btnClose.setObjectName("btnClose")
        self.horizontalLayout_3.addWidget(self.btnClose)
        self.verticalLayout.addLayout(self.horizontalLayout_3)

        self.retranslateUi(DialogSignMessage)
        QtCore.QMetaObject.connectSlotsByName(DialogSignMessage)

    def retranslateUi(self, DialogSignMessage):
        _translate = QtCore.QCoreApplication.translate
        DialogSignMessage.setWindowTitle(_translate("DialogSignMessage", "Dialog"))
        self.label_4.setText(_translate("DialogSignMessage", "Signing address:"))
        self.label.setText(_translate("DialogSignMessage", "Message to sign:"))
        self.btnSignMessage.setText(_translate("DialogSignMessage", "Sign message"))
        self.label_2.setText(_translate("DialogSignMessage", "Signed message:"))
        self.btnClose.setText(_translate("DialogSignMessage", "Close"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    DialogSignMessage = QtWidgets.QDialog()
    ui = Ui_DialogSignMessage()
    ui.setupUi(DialogSignMessage)
    DialogSignMessage.show()
    sys.exit(app.exec_())

