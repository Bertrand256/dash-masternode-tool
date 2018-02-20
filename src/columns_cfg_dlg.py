#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-09
from PyQt5 import QtWidgets, QtCore

from PyQt5.QtCore import QSize, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QLayout, QStyle
from ui import ui_columns_cfg_dlg
from wnd_utils import WndUtils


class ColumnsConfigDlg(QDialog, ui_columns_cfg_dlg.Ui_ColumnsConfigDlg, WndUtils):
    def __init__(self, parent, columns):
        QDialog.__init__(self, parent)
        ui_columns_cfg_dlg.Ui_ColumnsConfigDlg.__init__(self)
        WndUtils.__init__(self, None)
        self.columns = columns
        self.initialized = False
        self.setupUi()

    def setupUi(self):
        ui_columns_cfg_dlg.Ui_ColumnsConfigDlg.setupUi(self, self)
        self.setWindowTitle("Columns")
        self.setIcon(self.btnMoveUp, QStyle.SP_ArrowUp)
        self.setIcon(self.btnMoveDown, QStyle.SP_ArrowDown)
        self.tableWidget.verticalHeader().setSectionsMovable(True)

        self.tableWidget.verticalHeader().setDefaultSectionSize(
            self.tableWidget.verticalHeader().fontMetrics().height() + 8)

        self.tableWidget.verticalHeader().sectionMoved.connect(self.on_tableRowMoved)

        self.tableWidget.setRowCount(len(self.columns))
        for col_idx, col in enumerate(self.columns):
            item = QtWidgets.QTableWidgetItem()
            item.setText('  ')

            self.tableWidget.setVerticalHeaderItem(col_idx, item)

            visible = col[1]
            item = QtWidgets.QTableWidgetItem()
            item.setText(col[0])
            self.tableWidget.setItem(col_idx, 0, item)
            item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.Checked if visible else QtCore.Qt.Unchecked)

        self.update_buttons_state()
        self.initialized = True

    def on_tableRowMoved(self, logicalIndex, oldVisualIndex, newVisualIndex):
        self.columns.insert(newVisualIndex, self.columns.pop(oldVisualIndex))

    @pyqtSlot(QtWidgets.QTableWidgetItem)
    def on_tableWidget_itemChanged(self, item):
        if not self.initialized:
            return
        row = self.tableWidget.row(item)
        if row >= 0:
            self.columns[row][1] = item.checkState() == QtCore.Qt.Checked

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.update_buttons_state()

    def update_buttons_state(self):
        up_enabled = True
        down_enabled = True
        selected = False
        for item in self.tableWidget.selectedItems():
            row = self.tableWidget.visualRow(item.row())
            selected = True
            if row == 0:
                up_enabled = False
            if row == len(self.columns):
                down_enabled = False
        if not selected:
            up_enabled = False
            down_enabled = False
        self.btnMoveUp.setEnabled(up_enabled)
        self.btnMoveDown.setEnabled(down_enabled)

    @pyqtSlot()
    def on_btnMoveUp_clicked(self):
        # sort selected item to move lower-indexed items first
        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()))
        for item in items:
            row = self.tableWidget.visualRow(item.row())
            if row > 0:
                self.tableWidget.verticalHeader().moveSection(row, row-1)
        if len(items):
            self.update_buttons_state()

    @pyqtSlot()
    def on_btnMoveDown_clicked(self):
        # sort selected item to move higher-indexed items first
        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()),
                       reverse=True)

        for item in items:
            row = self.tableWidget.visualRow(item.row())
            if row < len(self.columns) - 1:
                self.tableWidget.verticalHeader().moveSection(row, row+1)
        if len(items):
            self.update_buttons_state()
