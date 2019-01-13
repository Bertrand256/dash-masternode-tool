# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_cmd_console_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.9.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_CmdConsoleDlg(object):
    def setupUi(self, CmdConsoleDlg):
        CmdConsoleDlg.setObjectName("CmdConsoleDlg")
        CmdConsoleDlg.resize(468, 334)
        self.verticalLayout = QtWidgets.QVBoxLayout(CmdConsoleDlg)
        self.verticalLayout.setObjectName("verticalLayout")
        self.edtCmdLog = QtWidgets.QTextBrowser(CmdConsoleDlg)
        font = QtGui.QFont()
        font.setFamily("Courier New")
        font.setPointSize(12)
        font.setKerning(False)
        self.edtCmdLog.setFont(font)
        self.edtCmdLog.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        self.edtCmdLog.setObjectName("edtCmdLog")
        self.verticalLayout.addWidget(self.edtCmdLog)
        self.label = QtWidgets.QLabel(CmdConsoleDlg)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.edtCommand = QtWidgets.QLineEdit(CmdConsoleDlg)
        self.edtCommand.setClearButtonEnabled(True)
        self.edtCommand.setObjectName("edtCommand")
        self.verticalLayout.addWidget(self.edtCommand)
        self.buttonBox = QtWidgets.QDialogButtonBox(CmdConsoleDlg)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Close)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(CmdConsoleDlg)
        self.buttonBox.accepted.connect(CmdConsoleDlg.accept)
        self.buttonBox.rejected.connect(CmdConsoleDlg.reject)
        QtCore.QMetaObject.connectSlotsByName(CmdConsoleDlg)

    def retranslateUi(self, CmdConsoleDlg):
        _translate = QtCore.QCoreApplication.translate
        CmdConsoleDlg.setWindowTitle(_translate("CmdConsoleDlg", "Dialog"))
        self.edtCmdLog.setPlaceholderText(_translate("CmdConsoleDlg", "Type \'help\' to display commands description"))
        self.label.setText(_translate("CmdConsoleDlg", "Command:"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    CmdConsoleDlg = QtWidgets.QDialog()
    ui = Ui_CmdConsoleDlg()
    ui.setupUi(CmdConsoleDlg)
    CmdConsoleDlg.show()
    sys.exit(app.exec_())

