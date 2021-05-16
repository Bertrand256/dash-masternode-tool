#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-07
import logging
from enum import Enum

from PyQt5.QtCore import Qt, pyqtSlot, QSortFilterProxyModel, QVariant, QAbstractItemModel, \
    QModelIndex
from PyQt5.QtWidgets import QTableView, QWidget, QAbstractItemView, QTreeView
from typing import List, Optional, Any, Dict, Generator

import thread_utils
from columns_cfg_dlg import ColumnsConfigDlg
from common import AttrsProtected
import app_cache
from wnd_utils import WndUtils


log = logging.getLogger('dmt.ext_item_model')


class HorizontalAlignment(Enum):
    LEFT = 1
    RIGHT = 2


class TableModelColumn(AttrsProtected):
    def __init__(self, name, caption, visible, initial_width: int = None,
                 additional_attrs: Optional[List[str]] = None,
                 horizontal_alignment: Optional[HorizontalAlignment] = None):
        AttrsProtected.__init__(self)
        self.name = name
        self.caption = caption
        self.visible = visible
        self.initial_width = initial_width
        self.visual_index = None
        self.horizontal_alignment = horizontal_alignment
        if additional_attrs:
            for attr in additional_attrs:
                self.add_attribute(attr)
        self.def_width = None
        self.set_attr_protection()


class ColumnedSortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent):
        QSortFilterProxyModel.__init__(self, parent)
        self.source_model: Optional[ExtSortFilterItemModel] = None

    def setSourceModel(self, source_model):
        try:
            self.source_model = source_model
            QSortFilterProxyModel.setSourceModel(self, self.source_model)
        except Exception as e:
            logging.exception('exception occurred')

    def filterAcceptsRow(self, source_row, source_parent):
        return self.source_model.filterAcceptsRow(source_row, source_parent)

    def lessThan(self, left, right):
        is_less = None
        col_index = left.column()
        col = self.source_model.col_by_index(col_index)
        if col:
            left_row_index = left.row()
            right_row_index = right.row()
            is_less = self.source_model.lessThan(col_index, left_row_index, right_row_index)
        if is_less is None:
            return super().lessThan(left, right)
        else:
            return is_less


class ExtSortFilterItemModel(QAbstractItemModel, AttrsProtected):
    def __init__(self, parent, columns: List[TableModelColumn], columns_movable, filtering_sorting):
        AttrsProtected.__init__(self)
        QAbstractItemModel.__init__(self, parent)
        self.parent_widget = parent
        self._columns = columns
        self._col_idx_by_name: Dict[str, int] = {}
        self._rebuild_column_index()
        self.view: Optional[QAbstractItemView] = None
        self.columns_movable = columns_movable
        self.initial_sorting_column_name = ''
        self.initial_sorting_order = Qt.AscendingOrder
        self.proxy_model: Optional[ColumnedSortFilterProxyModel] = None
        self.data_lock = thread_utils.EnhRLock()
        if filtering_sorting:
            self.enable_filter_proxy_model(self)

    def acquire_lock(self):
        self.data_lock.acquire()

    def release_lock(self):
        self.data_lock.release()

    def __enter__(self):
        self.acquire_lock()

    def __exit__(self, type, value, traceback):
        self.release_lock()

    def set_sort_column(self, col_name: str, sort_order: Qt.SortOrder):
        if self.proxy_model:
            idx = self.col_index_by_name(col_name)
            if idx >= 0:
                self.proxy_model.sort(idx, sort_order)
                if self.view:
                    self.view.horizontalHeader().setSortIndicator(idx, sort_order)
                else:
                    self.initial_sorting_order = col_name
                    self.initial_sorting_order = sort_order
            else:
                raise Exception(f'Column {col_name} not in column list' )

    def set_view(self, view: QAbstractItemView):
        self.view = view
        self.get_view_horizontal_header().sectionMoved.connect(self.on_view_column_moved)
        if self.proxy_model:
            self.view.setModel(self.proxy_model)
        else:
            self.view.setModel(self)
        self._apply_columns_to_ui()

        if self.initial_sorting_column_name:
            self.set_sort_column(self.initial_sorting_column_name, self.initial_sorting_order)
        else:
            col_idx = self.get_sort_column_index()
            sort_order = self.get_sort_order()
            if 0 <= col_idx < len(self._columns):
                self.view.horizontalHeader().setSortIndicator(col_idx, sort_order)

        if self.columns_movable:
            self.get_view_horizontal_header().setSectionsMovable(True)
        for idx, col in enumerate(self._columns):
            if col.initial_width:
                self.get_view_horizontal_header().resizeSection(idx, col.initial_width)

    def get_sort_column_index(self) -> int:
        if self.proxy_model:
            return self.proxy_model.sortColumn()
        else:
            return -1

    def get_sort_column(self) -> Optional[TableModelColumn]:
        if self.proxy_model:
            col_idx = self.proxy_model.sortColumn()
            if 0 <= col_idx < len(self._columns):
                return self._columns[col_idx]
        return None

    def get_sort_order(self) -> Optional[Qt.SortOrder]:
        if self.proxy_model:
            return self.proxy_model.sortOrder()
        else:
            return None

    def index(self, row, column, parent=None, *args, **kwargs):
        return self.createIndex(row, column)

    def parent(self, index=None):
        return QModelIndex()

    def selected_rows(self) -> Generator[int, None, None]:
        if self.view:
            sel = self.view.selectionModel()
            rows = sel.selectedRows()
            for row in rows:
                if self.proxy_model:
                    source_row = self.proxy_model.mapToSource(row)
                    row_idx = source_row.row()
                else:
                    row_idx = row.row()
                if row_idx >= 0:
                    yield row_idx

    def data_by_row_index(self, row_index):
        # Reimplement in derived classes. Used by selected_data_items
        pass

    def selected_data_items(self) -> Generator[Any, None, None]:
        for row in self.selected_rows():
            d = self.data_by_row_index(row)
            if d:
                yield d

    def enable_filter_proxy_model(self, source_model):
        if not self.proxy_model:
            self.proxy_model = ColumnedSortFilterProxyModel(self.parent_widget)
            self.proxy_model.setSourceModel(source_model)
        else:
            raise Exception('Proxy model already set')

    def _rebuild_column_index(self):
        self._col_idx_by_name.clear()
        for idx, c in enumerate(self._columns):
            c.visual_index = idx
            self._col_idx_by_name[c.name] = idx

    def insert_column(self, insert_before_index: int, col: TableModelColumn):
        if insert_before_index >= 0:
            if insert_before_index < len(self._columns):
                self._columns.insert(insert_before_index, col)
            else:
                self._columns.append(col)
            self._rebuild_column_index()
        else:
            raise IndexError('Invalid column index value')

    def col_count(self):
        return len(self._columns)

    def col_by_name(self, name: str):
        idx = self._col_idx_by_name.get(name)
        if idx is not None and idx >= 0:
            return self._columns[idx]
        else:
            return None

    def col_index_by_name(self, name: str):
        return self._col_idx_by_name.get(name)

    def col_by_index(self, index: int):
        return self._columns[index]

    def columns(self):
        for c in self._columns:
            yield c

    def add_col_attribute(self, name: str, initial_value: Any = None):
        for c in self._columns:
            c.add_attribute(name, initial_value)

    def save_col_defs(self, setting_name: str):
        cols = []
        if self.view:
            hdr = self.get_view_horizontal_header()
        else:
            hdr = None

        for c in sorted(self._columns, key=lambda x: x.visual_index):
            if hdr:
                width = hdr.sectionSize(self._columns.index(c))
            else:
                width = c.initial_width

            cols.append({'name': c.name,
                         'visible': c.visible,
                         'width': width})
        app_cache.set_value(setting_name, cols)

    def restore_col_defs(self, setting_name: str) -> bool:
        """
        :return: True, if columns settings were found in cache, False otherwise
        """
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
            self._columns.sort(key=lambda x: x.visual_index)
            self._rebuild_column_index()
            return True
        return False

    def on_view_column_moved(self, logicalIndex, oldVisualIndex, newVisualIndex):
        hdr = self.get_view_horizontal_header()
        for logical_index, col in enumerate(self._columns):
            vis_index = hdr.visualIndex(logical_index)
            col.visual_index = vis_index

    def exec_columns_dialog(self, parent_window: QWidget):
        try:
            cols = []
            for col in sorted(self._columns, key=lambda x: x.visual_index):
                cols.append([col.caption, col.visible, col])

            ui = ColumnsConfigDlg(parent_window, columns=cols)
            ret = ui.exec_()
            if ret > 0:
                for visual_idx, (_, visible, col) in enumerate(cols):
                    col.visual_index = visual_idx
                    col.visible = visible
                self._apply_columns_to_ui()
        except Exception as e:
            logging.exception('Exception while configuring table view columns')
            WndUtils.error_msg(str(e))

    def columnCount(self, parent=None, *args, **kwargs):
        return self.col_count()

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            col = self.col_by_index(section)
            if col:
                return col.caption
            return ''
        else:
            return ''

    def getDefaultColWidths(self):
        return [c.initial_width for c in self._columns]

    def get_view_horizontal_header(self):
        if isinstance(self.view, QTableView):
            return self.view.horizontalHeader()
        elif isinstance(self.view, QTreeView):
            return self.view.header()
        else:
            raise Exception('Unsupported view type: %s', str(type(self.view)))

    def _apply_columns_to_ui(self):
        hdr = self.get_view_horizontal_header()
        for cur_visual_index, c in enumerate(sorted(self._columns, key=lambda x: x.visual_index)):
            logical_index = self._columns.index(c)
            hdr.setSectionHidden(logical_index, not c.visible)
            view_visual_index = hdr.visualIndex(logical_index)
            if cur_visual_index != view_visual_index:
                hdr.swapSections(cur_visual_index, view_visual_index)

    def lessThan(self, col_index, left_row_index, right_row_index):
        pass

    def filterAcceptsRow(self, row_index, source_parent):
        return True

    def invalidateFilter(self):
        if self.proxy_model:
            self.proxy_model.invalidateFilter()

    def mapToSource(self, index):
        if self.proxy_model:
            return self.proxy_model.mapToSource(index)
        else:
            return index

    def mapFromSource(self, index):
        if self.proxy_model:
            return self.proxy_model.mapFromSource(index)
        else:
            return index
