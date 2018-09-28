# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/blogin/PycharmProjects/DMT-git/src/ui/ui_columns_cfg_dlg.ui'
#
# Created by: PyQt5 UI code generator 5.9.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_ColumnsConfigDlg(object):
    def setupUi(self, ColumnsConfigDlg):
        ColumnsConfigDlg.setObjectName("ColumnsConfigDlg")
        ColumnsConfigDlg.resize(262, 412)
        self.verticalLayout = QtWidgets.QVBoxLayout(ColumnsConfigDlg)
        self.verticalLayout.setContentsMargins(8, 8, 8, 8)
        self.verticalLayout.setSpacing(8)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setSpacing(3)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.tableWidget = QtWidgets.QTableWidget(ColumnsConfigDlg)
        self.tableWidget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tableWidget.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tableWidget.setObjectName("tableWidget")
        self.tableWidget.setColumnCount(1)
        self.tableWidget.setRowCount(0)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, item)
        self.tableWidget.horizontalHeader().setVisible(False)
        self.tableWidget.horizontalHeader().setStretchLastSection(True)
        self.horizontalLayout.addWidget(self.tableWidget)
        self.verticalLayout_2 = QtWidgets.QVBoxLayout()
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.btnMoveUp = QtWidgets.QToolButton(ColumnsConfigDlg)
        self.btnMoveUp.setText("")
        self.btnMoveUp.setObjectName("btnMoveUp")
        self.verticalLayout_2.addWidget(self.btnMoveUp)
        self.btnMoveDown = QtWidgets.QToolButton(ColumnsConfigDlg)
        self.btnMoveDown.setText("")
        self.btnMoveDown.setObjectName("btnMoveDown")
        self.verticalLayout_2.addWidget(self.btnMoveDown)
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem)
        self.horizontalLayout.addLayout(self.verticalLayout_2)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.buttonBox = QtWidgets.QDialogButtonBox(ColumnsConfigDlg)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(ColumnsConfigDlg)
        self.buttonBox.accepted.connect(ColumnsConfigDlg.accept)
        self.buttonBox.rejected.connect(ColumnsConfigDlg.reject)
        QtCore.QMetaObject.connectSlotsByName(ColumnsConfigDlg)

    def retranslateUi(self, ColumnsConfigDlg):
        _translate = QtCore.QCoreApplication.translate
        ColumnsConfigDlg.setWindowTitle(_translate("ColumnsConfigDlg", "Dialog"))
        item = self.tableWidget.horizontalHeaderItem(0)
        item.setText(_translate("ColumnsConfigDlg", "Columns"))
        self.btnMoveUp.setToolTip(_translate("ColumnsConfigDlg", "Move Up"))
        self.btnMoveDown.setToolTip(_translate("ColumnsConfigDlg", "Move Down"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    ColumnsConfigDlg = QtWidgets.QDialog()
    ui = Ui_ColumnsConfigDlg()
    ui.setupUi(ColumnsConfigDlg)
    ColumnsConfigDlg.show()
    sys.exit(app.exec_())

