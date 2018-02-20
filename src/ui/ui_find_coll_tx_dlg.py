# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_find_coll_tx_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.9.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_FindCollateralTxDlg(object):
    def setupUi(self, FindCollateralTxDlg):
        FindCollateralTxDlg.setObjectName("FindCollateralTxDlg")
        FindCollateralTxDlg.resize(458, 237)
        FindCollateralTxDlg.setModal(True)
        self.verticalLayout = QtWidgets.QVBoxLayout(FindCollateralTxDlg)
        self.verticalLayout.setContentsMargins(8, 8, 8, 8)
        self.verticalLayout.setSpacing(8)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setContentsMargins(-1, 8, -1, 6)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.label_3 = QtWidgets.QLabel(FindCollateralTxDlg)
        self.label_3.setObjectName("label_3")
        self.horizontalLayout.addWidget(self.label_3)
        self.edtAddress = QtWidgets.QLineEdit(FindCollateralTxDlg)
        self.edtAddress.setReadOnly(True)
        self.edtAddress.setObjectName("edtAddress")
        self.horizontalLayout.addWidget(self.edtAddress)
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem)
        self.horizontalLayout.setStretch(1, 1)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.lblMessage = QtWidgets.QLabel(FindCollateralTxDlg)
        self.lblMessage.setText("")
        self.lblMessage.setWordWrap(True)
        self.lblMessage.setObjectName("lblMessage")
        self.verticalLayout.addWidget(self.lblMessage)
        self.tableWidget = QtWidgets.QTableWidget(FindCollateralTxDlg)
        self.tableWidget.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContentsOnFirstShow)
        self.tableWidget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tableWidget.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tableWidget.setShowGrid(True)
        self.tableWidget.setObjectName("tableWidget")
        self.tableWidget.setColumnCount(4)
        self.tableWidget.setRowCount(0)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(1, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(2, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(3, item)
        self.tableWidget.horizontalHeader().setSortIndicatorShown(False)
        self.tableWidget.horizontalHeader().setStretchLastSection(True)
        self.tableWidget.verticalHeader().setCascadingSectionResizes(False)
        self.verticalLayout.addWidget(self.tableWidget)
        self.buttonBox = QtWidgets.QDialogButtonBox(FindCollateralTxDlg)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Close)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(FindCollateralTxDlg)
        QtCore.QMetaObject.connectSlotsByName(FindCollateralTxDlg)

    def retranslateUi(self, FindCollateralTxDlg):
        _translate = QtCore.QCoreApplication.translate
        FindCollateralTxDlg.setWindowTitle(_translate("FindCollateralTxDlg", "Dialog"))
        self.label_3.setText(_translate("FindCollateralTxDlg", "Address:"))
        self.tableWidget.setSortingEnabled(False)
        item = self.tableWidget.horizontalHeaderItem(0)
        item.setText(_translate("FindCollateralTxDlg", "Transaction ID"))
        item = self.tableWidget.horizontalHeaderItem(1)
        item.setText(_translate("FindCollateralTxDlg", "Index"))
        item = self.tableWidget.horizontalHeaderItem(2)
        item.setText(_translate("FindCollateralTxDlg", "TX date/time"))
        item = self.tableWidget.horizontalHeaderItem(3)
        item.setText(_translate("FindCollateralTxDlg", "Confirmations"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    FindCollateralTxDlg = QtWidgets.QDialog()
    ui = Ui_FindCollateralTxDlg()
    ui.setupUi(FindCollateralTxDlg)
    FindCollateralTxDlg.show()
    sys.exit(app.exec_())

