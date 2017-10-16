# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_thread_fun_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.9
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_ThreadFunDlg(object):
    def setupUi(self, ThreadFunDlg):
        ThreadFunDlg.setObjectName("ThreadFunDlg")
        ThreadFunDlg.setWindowModality(QtCore.Qt.NonModal)
        ThreadFunDlg.resize(400, 99)
        ThreadFunDlg.setModal(True)
        self.verticalLayout = QtWidgets.QVBoxLayout(ThreadFunDlg)
        self.verticalLayout.setSpacing(3)
        self.verticalLayout.setObjectName("verticalLayout")
        self.lblText = QtWidgets.QLabel(ThreadFunDlg)
        self.lblText.setOpenExternalLinks(True)
        self.lblText.setObjectName("lblText")
        self.verticalLayout.addWidget(self.lblText)
        self.progressBar = QtWidgets.QProgressBar(ThreadFunDlg)
        self.progressBar.setProperty("value", 0)
        self.progressBar.setInvertedAppearance(False)
        self.progressBar.setObjectName("progressBar")
        self.verticalLayout.addWidget(self.progressBar)
        self.btnBox = QtWidgets.QDialogButtonBox(ThreadFunDlg)
        self.btnBox.setOrientation(QtCore.Qt.Horizontal)
        self.btnBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok)
        self.btnBox.setCenterButtons(False)
        self.btnBox.setObjectName("btnBox")
        self.verticalLayout.addWidget(self.btnBox)

        self.retranslateUi(ThreadFunDlg)
        self.btnBox.accepted.connect(ThreadFunDlg.accept)
        self.btnBox.rejected.connect(ThreadFunDlg.reject)
        QtCore.QMetaObject.connectSlotsByName(ThreadFunDlg)

    def retranslateUi(self, ThreadFunDlg):
        _translate = QtCore.QCoreApplication.translate
        ThreadFunDlg.setWindowTitle(_translate("ThreadFunDlg", "Dialog"))
        self.lblText.setText(_translate("ThreadFunDlg", "<html><head/><body><p><br/></p></body></html>"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    ThreadFunDlg = QtWidgets.QDialog()
    ui = Ui_ThreadFunDlg()
    ui.setupUi(ThreadFunDlg)
    ThreadFunDlg.show()
    sys.exit(app.exec_())

