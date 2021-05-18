#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-09
from PyQt5 import QtWidgets, QtCore

from PyQt5.QtCore import QSize, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QLayout, QStyle
from typing import List

from ui import ui_columns_cfg_dlg
from wnd_utils import WndUtils


class ColumnsConfigDlg(QDialog, ui_columns_cfg_dlg.Ui_ColumnsConfigDlg, WndUtils):
    def __init__(self, parent, columns: List):
        QDialog.__init__(self, parent)
        ui_columns_cfg_dlg.Ui_ColumnsConfigDlg.__init__(self)
        WndUtils.__init__(self, None)
        self.columns: List = columns
        self.initialized = False
        self.setupUi(self)

    def setupUi(self, dialog: QtWidgets.QDialog):
        ui_columns_cfg_dlg.Ui_ColumnsConfigDlg.setupUi(self, self)
        self.setWindowTitle("Columns")
        WndUtils.set_icon(self, self.btnMoveBegin, "first-page@16px.png", rotate=90)
        WndUtils.set_icon(self, self.btnMoveEnd, "first-page@16px.png", rotate=-90)
        WndUtils.set_icon(self, self.btnMoveUp, "arrow-downward@16px.png", rotate=-180)
        WndUtils.set_icon(self, self.btnMoveDown, "arrow-downward@16px.png")
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
            row = self.tableWidget.visualRow(row)
            self.columns[row][1] = item.checkState() == QtCore.Qt.Checked

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.update_buttons_state()

    def update_buttons_state(self):
        up_enabled = False
        down_enabled = False

        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()))
        last_row = -1
        first_selected_row = -1
        last_selected_row = len(items)
        was_gap = False
        for item in items:
            row = self.tableWidget.visualRow(item.row())
            if 0 <= last_row < row - 1:
                was_gap = True
            if first_selected_row < 0:
                first_selected_row = row
            last_selected_row = row
            last_row = row

        if first_selected_row > 0 or was_gap:
            up_enabled = True

        if last_selected_row < len(self.columns) - 1 or was_gap:
            down_enabled = True

        self.btnMoveBegin.setEnabled(up_enabled)
        self.btnMoveEnd.setEnabled(down_enabled)
        self.btnMoveUp.setEnabled(up_enabled)
        self.btnMoveDown.setEnabled(down_enabled)

    @pyqtSlot()
    def on_btnMoveUp_clicked(self):
        # sort selected item to move lower-indexed items first
        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()))

        last_row_index = -1
        moved = False
        for item in items:
            row = self.tableWidget.visualRow(item.row())
            if row > 0:
                if last_row_index + 1 < row:
                    self.tableWidget.verticalHeader().moveSection(row, row-1)
                    last_row_index = row - 1
                    moved = True
                else:
                    last_row_index = row
            else:
                last_row_index = row
        if moved:
            self.update_buttons_state()
            self.tableWidget.scrollToItem(items[0])

    @pyqtSlot()
    def on_btnMoveBegin_clicked(self):
        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()))
        moved = False
        for new_row_idx, item in enumerate(items):
            cur_row_idx = self.tableWidget.visualRow(item.row())
            if cur_row_idx != new_row_idx:
                self.tableWidget.verticalHeader().moveSection(cur_row_idx, new_row_idx)
                moved = True
        if moved:
            self.update_buttons_state()
            self.tableWidget.scrollToItem(items[0])

    @pyqtSlot()
    def on_btnMoveDown_clicked(self):
        # sort selected item to move higher-indexed items first
        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()),
                       reverse=True)

        last_row_index = None
        moved = False
        for item in items:
            row = self.tableWidget.visualRow(item.row())
            if row < len(self.columns) - 1:
                if last_row_index is None or row + 1 < last_row_index:
                    self.tableWidget.verticalHeader().moveSection(row, row+1)
                    last_row_index = row + 1
                    moved = True
                else:
                    last_row_index = row
            else:
                last_row_index = row
        if moved:
            self.update_buttons_state()
            self.tableWidget.scrollToItem(items[0])

    @pyqtSlot()
    def on_btnMoveEnd_clicked(self):
        items = sorted(self.tableWidget.selectedItems(), key=lambda x: self.tableWidget.visualRow(x.row()),
                       reverse=True)
        moved = False
        for idx, item in enumerate(items):
            cur_row_idx = self.tableWidget.visualRow(item.row())
            new_row_idx = len(self.columns) - idx - 1
            if cur_row_idx != new_row_idx:
                self.tableWidget.verticalHeader().moveSection(cur_row_idx, new_row_idx)
                moved = True
        if moved:
            self.update_buttons_state()
            self.tableWidget.scrollToItem(items[0])

