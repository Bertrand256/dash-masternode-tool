# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/Projects/dash-masternode-tool/src/ui/ui_conn_ssh_wdg.ui'
#
# Created by: PyQt5 UI code generator 5.9.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_SshConnection(object):
    def setupUi(self, SshConnection):
        SshConnection.setObjectName("SshConnection")
        SshConnection.resize(417, 135)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(SshConnection.sizePolicy().hasHeightForWidth())
        SshConnection.setSizePolicy(sizePolicy)
        self.verticalLayout = QtWidgets.QVBoxLayout(SshConnection)
        self.verticalLayout.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout.setSpacing(3)
        self.verticalLayout.setObjectName("verticalLayout")
        self.gridLayout = QtWidgets.QGridLayout()
        self.gridLayout.setHorizontalSpacing(12)
        self.gridLayout.setObjectName("gridLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.edtSshHost = QtWidgets.QLineEdit(SshConnection)
        self.edtSshHost.setObjectName("edtSshHost")
        self.horizontalLayout.addWidget(self.edtSshHost)
        self.lblSshPort = QtWidgets.QLabel(SshConnection)
        self.lblSshPort.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.lblSshPort.setObjectName("lblSshPort")
        self.horizontalLayout.addWidget(self.lblSshPort)
        self.edtSshPort = QtWidgets.QLineEdit(SshConnection)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.edtSshPort.sizePolicy().hasHeightForWidth())
        self.edtSshPort.setSizePolicy(sizePolicy)
        self.edtSshPort.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edtSshPort.setObjectName("edtSshPort")
        self.horizontalLayout.addWidget(self.edtSshPort)
        self.gridLayout.addLayout(self.horizontalLayout, 0, 1, 1, 1)
        self.cboAuthentication = QtWidgets.QComboBox(SshConnection)
        self.cboAuthentication.setObjectName("cboAuthentication")
        self.cboAuthentication.addItem("")
        self.cboAuthentication.addItem("")
        self.cboAuthentication.addItem("")
        self.cboAuthentication.addItem("")
        self.gridLayout.addWidget(self.cboAuthentication, 2, 1, 1, 1)
        self.lblSshUsername = QtWidgets.QLabel(SshConnection)
        self.lblSshUsername.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.lblSshUsername.setObjectName("lblSshUsername")
        self.gridLayout.addWidget(self.lblSshUsername, 1, 0, 1, 1)
        self.lblAuthentication = QtWidgets.QLabel(SshConnection)
        self.lblAuthentication.setObjectName("lblAuthentication")
        self.gridLayout.addWidget(self.lblAuthentication, 2, 0, 1, 1)
        self.edtSshUsername = QtWidgets.QLineEdit(SshConnection)
        self.edtSshUsername.setObjectName("edtSshUsername")
        self.gridLayout.addWidget(self.edtSshUsername, 1, 1, 1, 1)
        self.lblSshHost = QtWidgets.QLabel(SshConnection)
        self.lblSshHost.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.lblSshHost.setObjectName("lblSshHost")
        self.gridLayout.addWidget(self.lblSshHost, 0, 0, 1, 1)
        self.lblPrivateKeyPath = QtWidgets.QLabel(SshConnection)
        self.lblPrivateKeyPath.setObjectName("lblPrivateKeyPath")
        self.gridLayout.addWidget(self.lblPrivateKeyPath, 3, 0, 1, 1)
        self.edtPrivateKeyPath = QtWidgets.QLineEdit(SshConnection)
        self.edtPrivateKeyPath.setClearButtonEnabled(False)
        self.edtPrivateKeyPath.setObjectName("edtPrivateKeyPath")
        self.gridLayout.addWidget(self.edtPrivateKeyPath, 3, 1, 1, 1)
        self.verticalLayout.addLayout(self.gridLayout)
        self.lblSshPort.setBuddy(self.edtSshPort)
        self.lblSshUsername.setBuddy(self.edtSshUsername)
        self.lblSshHost.setBuddy(self.edtSshHost)

        self.retranslateUi(SshConnection)
        QtCore.QMetaObject.connectSlotsByName(SshConnection)

    def retranslateUi(self, SshConnection):
        _translate = QtCore.QCoreApplication.translate
        SshConnection.setWindowTitle(_translate("SshConnection", "Form"))
        self.lblSshPort.setText(_translate("SshConnection", "port:"))
        self.cboAuthentication.setItemText(0, _translate("SshConnection", "Any available"))
        self.cboAuthentication.setItemText(1, _translate("SshConnection", "Password"))
        self.cboAuthentication.setItemText(2, _translate("SshConnection", "RSA key pair"))
        self.cboAuthentication.setItemText(3, _translate("SshConnection", "SSH agent"))
        self.lblSshUsername.setText(_translate("SshConnection", "SSH username:"))
        self.lblAuthentication.setText(_translate("SshConnection", "Authentication:"))
        self.lblSshHost.setText(_translate("SshConnection", "SSH host:"))
        self.lblPrivateKeyPath.setText(_translate("SshConnection", "Private key path:"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    SshConnection = QtWidgets.QWidget()
    ui = Ui_SshConnection()
    ui.setupUi(SshConnection)
    SshConnection.show()
    sys.exit(app.exec_())

