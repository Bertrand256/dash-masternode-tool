# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_message_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.9
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_MessageDlg(object):
    def setupUi(self, MessageDlg):
        MessageDlg.setObjectName("MessageDlg")
        MessageDlg.resize(263, 96)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(15)
        sizePolicy.setVerticalStretch(1)
        sizePolicy.setHeightForWidth(MessageDlg.sizePolicy().hasHeightForWidth())
        MessageDlg.setSizePolicy(sizePolicy)
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(MessageDlg)
        self.verticalLayout_2.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        self.verticalLayout_2.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.lblMessage = QtWidgets.QLabel(MessageDlg)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.lblMessage.sizePolicy().hasHeightForWidth())
        self.lblMessage.setSizePolicy(sizePolicy)
        self.lblMessage.setSizeIncrement(QtCore.QSize(0, 0))
        self.lblMessage.setFrameShape(QtWidgets.QFrame.Box)
        self.lblMessage.setText("")
        self.lblMessage.setScaledContents(True)
        self.lblMessage.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignTop)
        self.lblMessage.setWordWrap(True)
        self.lblMessage.setOpenExternalLinks(True)
        self.lblMessage.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByKeyboard|QtCore.Qt.TextSelectableByMouse)
        self.lblMessage.setObjectName("lblMessage")
        self.verticalLayout_2.addWidget(self.lblMessage)
        spacerItem = QtWidgets.QSpacerItem(20, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem)
        self.buttonBox = QtWidgets.QDialogButtonBox(MessageDlg)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout_2.addWidget(self.buttonBox)

        self.retranslateUi(MessageDlg)
        QtCore.QMetaObject.connectSlotsByName(MessageDlg)

    def retranslateUi(self, MessageDlg):
        _translate = QtCore.QCoreApplication.translate
        MessageDlg.setWindowTitle(_translate("MessageDlg", "Dialog"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    MessageDlg = QtWidgets.QDialog()
    ui = Ui_MessageDlg()
    ui.setupUi(MessageDlg)
    MessageDlg.show()
    sys.exit(app.exec_())

