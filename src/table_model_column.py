#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-07
import logging
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QTableView, QWidget
from typing import List, Optional, Any, Dict

from columns_cfg_dlg import ColumnsConfigDlg
from common import AttrsProtected
import app_cache
from wnd_utils import WndUtils


class TableModelColumn(AttrsProtected):
    def __init__(self, name, caption, visible, initial_width: int = None, additional_attrs: Optional[List[str]] = None):
        AttrsProtected.__init__(self)
        self.name = name
        self.caption = caption
        self.visible = visible
        self.initial_width = initial_width
        self.visual_index = None
        if additional_attrs:
            for attr in additional_attrs:
                self.add_attribute(attr)
        self.def_width = None
        self.set_attr_protection()


class TableModelColumns(AttrsProtected):
    def __init__(self, columns: List[TableModelColumn]):
        AttrsProtected.__init__(self)
        self.__columns = columns
        self.__col_idx_by_name: Dict[str, int] = {}
        for idx, c in enumerate(self.__columns):
            c.visual_index = idx
            self.__col_idx_by_name[c.name] = idx
        self.table_view: QTableView = None
        self.set_attr_protection()

    def insert(self, insert_before_index: int, col: TableModelColumn):
        if insert_before_index >= 0:
            if insert_before_index < len(self.__columns):
                self.__columns.insert(insert_before_index, col)
            else:
                self.__columns.append(col)
        else:
            raise IndexError('Invalid column index value')

    def set_table_view(self, table_view: QTableView, columns_movable: bool, sorting_column: str, sorting_order: int):
        self.table_view = table_view
        self.table_view.horizontalHeader().sectionMoved.connect(self.on_ViewColumnMoved)
        self.apply_to_view()
        if sorting_column:
            idx = self.col_index_by_name(sorting_column)
            if idx is not None:
                self.table_view.sortByColumn(idx, sorting_order)
        if columns_movable:
            self.table_view.horizontalHeader().setSectionsMovable(True)
        for idx, col in enumerate(self.__columns):
            if col.initial_width:
                table_view.horizontalHeader().resizeSection(idx, col.initial_width)

    def col_count(self):
        return len(self.__columns)

    def col_by_name(self, name: str):
        idx = self.__col_idx_by_name.get(name)
        if idx is not None and idx >= 0:
            return self.__columns[idx]
        else:
            return None

    def col_index_by_name(self, name: str):
        return self.__col_idx_by_name.get(name)

    def col_by_index(self, index: int):
        return self.__columns[index]

    def columns(self):
        for c in self.__columns:
            yield c

    def add_col_attribute(self, name: str, initial_value: Any = None):
        for c in self.__columns:
            c.add_attribute(name, initial_value)

    def save_col_defs(self, setting_name: str):
        cols = []
        if self.table_view:
            hdr = self.table_view.horizontalHeader()
        else:
            hdr = None

        for c in sorted(self.__columns, key=lambda x: x.visual_index):
            if hdr:
                width = hdr.sectionSize(self.__columns.index(c))
            else:
                width = c.initial_width

            cols.append({'name': c.name,
                         'visible': c.visible,
                         'width': width})
        app_cache.set_value(setting_name, cols)

    def restore_col_defs(self, setting_name: str):
        cols = app_cache.get_value(setting_name, [], list)
        if cols:
            idx = 0
            for _c in cols:
                name = _c.get('name')
                c = self.col_by_name(name)
                if c:
                    c.visual_index = idx
                    c.visible = _c.get('visible', True)
                    c.initial_width = _c.get('width', c.initial_width)
                    idx += 1

    def apply_to_view(self):
        hdr = self.table_view.horizontalHeader()
        for cur_visual_index, c in enumerate(sorted(self.__columns, key=lambda x: x.visual_index)):
            logical_index = self.__columns.index(c)
            hdr.setSectionHidden(logical_index, not c.visible)
            view_visual_index = hdr.visualIndex(logical_index)
            if cur_visual_index != view_visual_index:
                hdr.swapSections(cur_visual_index, view_visual_index)

    def on_ViewColumnMoved(self, logicalIndex, oldVisualIndex, newVisualIndex):
        hdr = self.table_view.horizontalHeader()
        for logical_index, col in enumerate(self.__columns):
            vis_index = hdr.visualIndex(logical_index)
            col.visual_index = vis_index

    def exec_columns_dialog(self, parent_window: QWidget):
        try:
            cols = []
            for col in sorted(self.__columns, key=lambda x: x.visual_index):
                cols.append([col.caption, col.visible, col])

            ui = ColumnsConfigDlg(parent_window, columns=cols)
            ret = ui.exec_()
            if ret > 0:
                for visual_idx, (_, visible, col) in enumerate(cols):
                    col.visual_index = visual_idx
                    col.visible = visible
                self.apply_to_view()
        except Exception as e:
            logging.exception('Exception while configuring table view columns')
            WndUtils.errorMsg(str(e))
