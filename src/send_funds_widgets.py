#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-03
import logging
import re
from functools import partial
from typing import List, Callable, Optional, Tuple
import sys
import os
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import QSize, QEventLoop, QObject, QTimer, QVariant
from PyQt5.QtWidgets import QPushButton, QToolButton, QWidgetItem, QSpacerItem, QLayout, QHBoxLayout, QLineEdit, \
    QLabel, QComboBox, QMenu, QMessageBox, QVBoxLayout
import app_cache
import app_utils
import dash_utils
from app_defs import FEE_SAT_PER_BYTE, MIN_TX_FEE
from encrypted_files import write_file_encrypted, read_file_encrypted
from hw_common import HwSessionInfo
from wnd_utils import WndUtils


OUTPUT_VALUE_UNIT_AMOUNT = 'AMT'
OUTPUT_VALUE_UNIT_PERCENT = 'PCT'
MAX_DATA_FILE_SIZE = 10000000
CSV_SEPARATOR = ';'
CACHE_ITEM_DATA_FILE_MRU_LIST = 'SendFundsDestination_DataFileMRUList'


class SendFundsDestinationItem(QObject):
    sig_remove_address = QtCore.pyqtSignal(object)
    sig_use_all_funds = QtCore.pyqtSignal(object)
    sig_amount_changed = QtCore.pyqtSignal(object)

    def __init__(self, parent, app_config, grid_layout, row_index, address_widget_width):
        QObject.__init__(self)
        self.app_config = app_config
        self.main_layout = grid_layout
        self.row_number = row_index
        self.values_unit = OUTPUT_VALUE_UNIT_AMOUNT
        self.value_amount = None
        self.value_percent = None
        self.inputs_total_amount = None  # sum of all inputs (for counting percent type value)
        self.address_widget_width = address_widget_width
        self.setupUi(parent)

    def setupUi(self, Form):

        self.lbl_dest_address = QLabel(Form)
        self.lbl_dest_address.setText("Address")
        self.lbl_dest_address.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.main_layout.addWidget(self.lbl_dest_address, self.row_number, 0)

        self.edt_dest_address = QLineEdit(Form)
        self.edt_dest_address.setFixedWidth(self.address_widget_width)
        self.main_layout.addWidget(self.edt_dest_address, self.row_number, 1)

        self.lbl_amount = QLabel(Form)
        self.lbl_amount.setText("Amount")
        self.main_layout.addWidget(self.lbl_amount, self.row_number, 2)

        self.lay_amount = QHBoxLayout()
        self.lay_amount.setContentsMargins(0, 0, 0, 0)
        self.lay_amount.setSpacing(0)
        self.main_layout.addLayout(self.lay_amount, self.row_number, 3)
        self.edt_amount = QLineEdit(Form)
        self.edt_amount.setFixedWidth(100)
        self.edt_amount.textChanged.connect(self.on_edt_amount_changed)
        self.lay_amount.addWidget(self.edt_amount)
        self.btn_use_all = QToolButton(Form)
        self.btn_use_all.setText('\u2b06')
        self.btn_use_all.setFixedSize(14, self.edt_amount.sizeHint().height())
        self.btn_use_all.setToolTip('Use remaining funds')
        self.btn_use_all.clicked.connect(self.on_btn_use_all_funds_clicked)
        self.lay_amount.addWidget(self.btn_use_all)

        # label for the second unit (e.g. percent if self.values_unit equals OUTPUT_VALUE_UNIT_AMOUNT)
        self.lbl_second_unit_value = QLabel(Form)
        self.main_layout.addWidget(self.lbl_second_unit_value, self.row_number, 4)

        self.btn_remove_address = QToolButton(Form)
        self.btn_remove_address.setFixedSize(self.edt_amount.sizeHint().height(), self.edt_amount.sizeHint().height())
        self.main_layout.addWidget(self.btn_remove_address, self.row_number, 5)

        self.btn_remove_address.setStyleSheet("QToolButton{color: red}")
        self.btn_remove_address.setVisible(False)
        self.btn_remove_address.clicked.connect(self.on_btn_remove_address_clicked)
        self.btn_remove_address.setText('\u2716')  # 2501, 2716
        self.btn_remove_address.setToolTip("Remove address")

    def set_btn_remove_address_visible(self, visible):
        self.btn_remove_address.setVisible(visible)

    def on_btn_remove_address_clicked(self):
        self.sig_remove_address.emit(self)

    def on_btn_use_all_funds_clicked(self):
        self.sig_use_all_funds.emit(self)

    def on_edt_amount_changed(self, text):
        try:
            value = round(float(self.edt_amount.text()), 8)

            if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
                self.value_amount = value
            elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
                self.value_percent = value

            self.re_calculate_second_unit_value()
            self.sig_amount_changed.emit(self)

        except Exception:
            pass

    def get_value(self, default_value=None):
        """
        :param default_value: value that will be returned if the value entered by a user is invalid or empty
        """
        amount = self.edt_amount.text()
        if amount:
            try:
                return float(amount)
            except Exception:
                pass
        return default_value

    def get_value_amount(self):
        return self.value_amount

    def set_value(self, value):
        old_state = self.edt_amount.blockSignals(True)
        try:
            if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
                self.value_amount = value
            elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
                self.value_percent = value
            self.re_calculate_second_unit_value()

            self.edt_amount.setText(app_utils.to_string(value))
        finally:
            self.edt_amount.blockSignals(old_state)
        self.edt_amount.update()

    def display_second_unit_value(self):
        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            if self.value_percent is not None:
                self.lbl_second_unit_value.setText(app_utils.to_string(round(self.value_percent, 3)) + '%')
            else:
                self.lbl_second_unit_value.setText('')
        elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
            if self.value_amount is not None:
                self.lbl_second_unit_value.setText(app_utils.to_string(round(self.value_amount, 8)) + ' Dash')
            else:
                self.lbl_second_unit_value.setText('')

    def re_calculate_second_unit_value(self):
        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            # calculate the percent-value based on the inputs total amount and our item's amount
            if self.inputs_total_amount and self.value_amount is not None:
                self.value_percent = round(self.value_amount * 100 / self.inputs_total_amount, 8)
                self.display_second_unit_value()
        elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
            # calculate the amount value based on inputs total amount and our item's percent-value
            if self.inputs_total_amount is not None and self.value_percent is not None:
                self.value_amount = round(self.inputs_total_amount * self.value_percent / 100, 8)
                self.display_second_unit_value()

    def set_inputs_total_amount(self, amount):
        self.inputs_total_amount = amount
        self.re_calculate_second_unit_value()

    def set_address(self, address):
        self.edt_dest_address.setText(address)

    def get_address(self):
        return self.edt_dest_address.text()

    def set_output_value_unit(self, unit):
        old_state = self.edt_amount.blockSignals(True)
        try:
            if unit == OUTPUT_VALUE_UNIT_AMOUNT:
                self.edt_amount.setText(app_utils.to_string(self.value_amount))
                self.lbl_amount.setText('value')
            elif unit == OUTPUT_VALUE_UNIT_PERCENT:
                self.edt_amount.setText(app_utils.to_string(self.value_percent))
                self.lbl_amount.setText('pct. value')
            else:
                raise Exception('Invalid unit')
            self.values_unit = unit
            self.display_second_unit_value()
        finally:
            self.edt_amount.blockSignals(old_state)
        self.edt_amount.update()

    def set_style_sheet(self):
        style = 'QLineEdit[invalid="true"]{border: 1px solid red}'
        self.edt_dest_address.setStyleSheet(style)
        self.edt_amount.setStyleSheet(style)

    def validate(self):
        valid = True
        address = self.edt_dest_address.text()
        if not address:
            valid = False
        elif not dash_utils.validate_address(address, self.app_config.dash_network):
            valid = False
        else:
            self.message = None
        if valid:
            self.edt_dest_address.setProperty('invalid', False)
        else:
            self.edt_dest_address.setProperty('invalid', True)

        amount = self.edt_amount.text()
        try:
            amount = float(amount)
            if amount > 0.0:
                self.edt_amount.setProperty('invalid', False)
            else:
                self.edt_amount.setProperty('invalid', True)
                valid = False
        except:
            self.edt_amount.setProperty('invalid', True)
            valid = False

        self.set_style_sheet()
        return valid

    def clear_validation_results(self):
        self.edt_amount.setProperty('invalid', False)
        self.edt_dest_address.setProperty('invalid', False)
        self.set_style_sheet()


class SendFundsDestination(QtWidgets.QWidget):
    resized_signal = QtCore.pyqtSignal()

    def __init__(self, parent, parent_dialog, app_config, hw_session: HwSessionInfo):
        QtWidgets.QWidget.__init__(self, parent)
        self.app_config = app_config
        self.parent_dialog = parent_dialog
        self.hw_session = hw_session
        self.recipients: List[SendFundsDestinationItem] = []
        self.change_addresses: List[Tuple[str, str]] = []  # List[Tuple[address, bip32 path]]
        self.change_controls_visible = True
        self.address_widget_width = None
        self.inputs_total_amount = 0.0
        self.fee_amount = 0.0
        self.inputs_count = 0
        self.values_unit = OUTPUT_VALUE_UNIT_AMOUNT
        self.tm_calculate_change_value = QTimer(self)
        self.tm_calculate_change_value.timeout.connect(self.on_tm_calculate_change_value)
        self.current_file_name = ''
        self.current_file_encrypted = False
        self.recent_data_files = []  # recent used data files
        self.setupUi(self)

    def setupUi(self, Form):
        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.MinimumExpanding))

        self.lay_main = QtWidgets.QVBoxLayout(Form)
        self.lay_main.setContentsMargins(6, 6, 6, 6)
        self.lay_main.setSpacing(3)

        # 'totals' area:
        self.lbl_totals = QLabel(Form)
        self.lbl_totals.setTextInteractionFlags(
            QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByMouse)
        self.lay_main.addWidget(self.lbl_totals)

        # output definition data file labels:
        self.lay_data_file = QHBoxLayout()
        self.lay_data_file.setContentsMargins(0, 0, 0, 6)
        self.lay_main.addItem(self.lay_data_file)
        self.lbl_data_file_name = QLabel(Form)
        self.lay_data_file.addWidget(self.lbl_data_file_name)
        self.lbl_data_file_badge = QLabel(Form)
        self.lay_data_file.addWidget(self.lbl_data_file_badge)
        self.lbl_data_file_name.setTextInteractionFlags(
            QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByMouse)
        self.lbl_data_file_badge.setTextInteractionFlags(
            QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByMouse)
        self.lay_data_file.addStretch()

        # actions/options area:
        self.lay_actions = QHBoxLayout()
        self.lay_actions.setSpacing(6)
        self.lay_actions.setContentsMargins(0, 0, 0, 0)
        self.lay_main.addItem(self.lay_actions)
        self.btn_add_recipient = QPushButton(Form)
        self.btn_add_recipient.clicked.connect(partial(self.add_dest_address, 1))
        self.btn_add_recipient.setAutoDefault(False)
        self.btn_add_recipient.setText("Add recipient")
        self.lay_actions.addWidget(self.btn_add_recipient)
        #
        self.btn_actions = QPushButton(Form)
        self.btn_actions.clicked.connect(partial(self.add_dest_address, 1))
        self.btn_actions.setAutoDefault(False)
        self.btn_actions.setText("Actions")
        self.lay_actions.addWidget(self.btn_actions)

        # context menu for the 'Actions' button
        self.mnu_actions = QMenu()
        self.btn_actions.setMenu(self.mnu_actions)
        a = self.mnu_actions.addAction("Load from file...")
        a.triggered.connect(self.on_read_from_file_clicked)
        self.mnu_recent_files = self.mnu_actions.addMenu('Recent files')
        self.mnu_recent_files.setVisible(False)
        a = self.mnu_actions.addAction("Save to encrypted file...")
        a.triggered.connect(partial(self.save_to_file, True))
        a = self.mnu_actions.addAction("Save to plain CSV file...")
        a.triggered.connect(partial(self.save_to_file, False))
        a = self.mnu_actions.addAction("Clear recipients")
        a.triggered.connect(self.clear_outputs)

        self.lbl_output_unit = QLabel(Form)
        self.lbl_output_unit.setText('Values as')
        self.lay_actions.addWidget(self.lbl_output_unit)
        self.cbo_output_unit = QComboBox(Form)
        self.cbo_output_unit.addItems(['amount', 'percentage'])
        self.cbo_output_unit.setCurrentIndex(0)
        self.cbo_output_unit.currentIndexChanged.connect(self.on_cbo_output_unit_change)
        self.lay_actions.addWidget(self.cbo_output_unit)
        self.lay_actions.addStretch(0)

        # scroll area for send to (destination) addresses
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(30)
        self.scroll_area.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.MinimumExpanding))
        self.scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.lay_main.addWidget(self.scroll_area)

        self.scroll_area_widget = QtWidgets.QWidget()
        self.scroll_area_widget.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.MinimumExpanding))
        self.lay_scroll_area = QtWidgets.QVBoxLayout()
        self.lay_scroll_area.setContentsMargins(0, 0, 0, 0)
        self.lay_scroll_area.setSpacing(0)
        self.scroll_area_widget.setLayout(self.lay_scroll_area)
        self.scroll_area.setWidget(self.scroll_area_widget)

        # grid layout for destination addresses and their corresponding controls:
        self.lay_addresses = QtWidgets.QGridLayout()
        self.lay_addresses.setSpacing(3)
        self.lay_addresses.setContentsMargins(0, 0, 0, 0)
        self.lay_scroll_area.addLayout(self.lay_addresses)
        self.lay_scroll_area.addStretch(0)

        # controls for the 'change' address/amount (it's placed in the last row of the addresses grid layout):
        self.lbl_change_address = QLabel(self.scroll_area_widget)
        self.lbl_change_address.setText('Change address')
        self.lbl_change_address.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lay_addresses.addWidget(self.lbl_change_address, 0, 0)
        # the 'change' address combobox:
        self.cbo_change_address = QtWidgets.QComboBox(self.scroll_area_widget)
        width = self.cbo_change_address.fontMetrics().width('XvqNXF23dRBksxjW3VQGrBtJw7vkhWhenQ')
        self.address_widget_width = width + 40
        # combobox width on macos needs to be tweaked:
        self.cbo_change_address.setFixedWidth(self.address_widget_width + {'darwin': 5}.get(sys.platform, 0))
        self.lay_addresses.addWidget(self.cbo_change_address, 0, 1)
        self.lbl_change_amount = QLabel(self.scroll_area_widget)
        self.set_change_value_label()
        self.lay_addresses.addWidget(self.lbl_change_amount, 0, 2)
        # read only editbox for the amount of the change:
        self.edt_change_amount = QLineEdit(self.scroll_area_widget)
        self.edt_change_amount.setFixedWidth(100)
        self.edt_change_amount.setReadOnly(True)
        self.edt_change_amount.setStyleSheet('background-color:lightgray')
        self.lay_addresses.addWidget(self.edt_change_amount, 0, 3)
        # label dedicated to the second-unit value (e.g percentage if the main unit is set to (Dash) amount value)
        self.lbl_second_unit = QLabel(self.scroll_area_widget)
        self.lay_addresses.addWidget(self.lbl_second_unit, 0, 4)
        # spacer
        spacer = QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.lay_addresses.addItem(spacer, 0, 5)

        # the last row of the grid layout is dedicated to 'fee' controls
        self.lbl_fee = QLabel(self.scroll_area_widget)
        self.lbl_fee.setText('Fee [Dash]')
        self.lbl_fee.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lay_addresses.addWidget(self.lbl_fee, 1, 0)

        # the fee value editbox with the 'use default' button:
        self.lay_fee_value = QHBoxLayout()
        self.lay_fee_value.setContentsMargins(0, 0, 0, 0)
        self.lay_fee_value.setSpacing(0)
        self.lay_addresses.addItem(self.lay_fee_value, 1, 1)
        self.edt_fee_value = QLineEdit(self.scroll_area_widget)
        self.edt_fee_value.setFixedWidth(100)
        self.edt_fee_value.textChanged.connect(self.on_edt_fee_value_changed)
        self.lay_fee_value.addWidget(self.edt_fee_value)
        self.btn_get_default_fee = QToolButton(self.scroll_area_widget)
        self.btn_get_default_fee.setText('\u2b06')
        self.btn_get_default_fee.setFixedSize(14, self.edt_fee_value.sizeHint().height())
        self.btn_get_default_fee.setToolTip('Use default fee')
        self.btn_get_default_fee.clicked.connect(self.on_btn_get_default_fee_clicked)
        self.lay_fee_value.addWidget(self.btn_get_default_fee)
        self.lay_fee_value.addStretch(0)

        # below the addresses grid place a label dedicated do display messages
        self.lbl_message = QLabel(Form)
        self.lbl_message.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByMouse)
        self.lbl_message.setVisible(False)
        self.lay_main.addWidget(self.lbl_message)

        # add one 'send to' address row (in most cases it will bu sufficient)
        self.add_dest_address(1)

        # load last used file names from cache
        mru = app_cache.get_value(CACHE_ITEM_DATA_FILE_MRU_LIST, default_value=[], type=list)
        if isinstance(mru, list):
            for file_name in mru:
                if os.path.exists(file_name):
                    self.recent_data_files.append(file_name)
        self.update_mru_menu_items()

        self.retranslateUi(Form)

    def retranslateUi(self, Form):
        pass

    def sizeHint(self):
        sh = self.lay_scroll_area.sizeHint()
        marg_sl = self.lay_scroll_area.getContentsMargins()
        marg_ml = self.lay_main.getContentsMargins()
        if self.lbl_message.isVisible():
            msg_height = self.lbl_message.height()
        else:
            msg_height = 0
        sh.setHeight(sh.height() + marg_sl[1] + marg_sl[3] + self.lay_actions.sizeHint().height() +
                     self.lbl_totals.sizeHint().height() +
                     self.lay_data_file.sizeHint().height() +
                     ((self.lay_main.count() - 1) * self.lay_main.spacing()) + marg_ml[1] + marg_ml[3] + msg_height)
        return sh

    def display_message(self, message, color: Optional[str] = None):
        if message:
            self.lbl_message.setText(message)
            if color:
                self.lbl_message.setStyleSheet(f'QLabel{{color:{color}}}')
            changed_visibility = self.lbl_message.isVisible() != True
            self.lbl_message.setVisible(True)
        else:
            changed_visibility = self.lbl_message.isVisible() != False
            self.lbl_message.setVisible(False)

        if changed_visibility:
            QtWidgets.qApp.processEvents(QEventLoop.ExcludeUserInputEvents)
            self.resized_signal.emit()

    def move_grid_layout_row(self, from_row, to_row):
        for col_idx in range(self.lay_addresses.columnCount()):
            item = self.lay_addresses.itemAtPosition(from_row, col_idx)
            if item:
                if isinstance(item, QWidgetItem):
                    w = item.widget()
                    self.lay_addresses.removeWidget(w)
                    self.lay_addresses.addWidget(w, to_row, col_idx)
                elif isinstance(item, QLayout):
                    self.lay_addresses.removeItem(item)
                    self.lay_addresses.addItem(item, to_row, col_idx)
                elif isinstance(item, QSpacerItem):
                    self.lay_addresses.removeItem(item)
                    self.lay_addresses.addItem(item, to_row, col_idx)
                else:
                    raise Exception('Invalid item type')

    def add_dest_address(self, address_count: int = 1):
        # make a free space in the grid-layout for new addresses, just behind the last item related to the dest address
        for row_idx in reversed(range(len(self.recipients), self.lay_addresses.rowCount())):
            self.move_grid_layout_row(row_idx, row_idx + address_count)

        for nr in range(address_count):
            rcp_item = SendFundsDestinationItem(self.scroll_area_widget,
                                                self.app_config,
                                                self.lay_addresses,
                                                len(self.recipients),
                                                self.address_widget_width)
            rcp_item.sig_remove_address.connect(self.remove_dest_address)
            rcp_item.sig_use_all_funds.connect(self.use_all_funds_for_address)
            rcp_item.sig_amount_changed.connect(self.amount_changed)
            rcp_item.set_output_value_unit(self.values_unit)
            rcp_item.set_inputs_total_amount(self.inputs_total_amount - self.fee_amount)
            self.recipients.append(rcp_item)

        QtWidgets.qApp.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.resized_signal.emit()
        self.show_hide_remove_buttons()
        self.display_totals()
        self.set_default_fee()

    def remove_item_from_layout(self, item):
        if item:
            if isinstance(item, QWidgetItem):
                w = item.widget()
                self.lay_addresses.removeWidget(w)
                w.setParent(None)
                del w
            elif isinstance(item, QLayout):
                for subitem_idx in reversed(range(item.count())):
                    subitem = item.itemAt(subitem_idx)
                    self.remove_item_from_layout(subitem)
                self.lay_addresses.removeItem(item)
                item.setParent(None)
                del item
            elif isinstance(item, QSpacerItem):
                del item
            else:
                raise Exception('Invalid item type')

    def remove_dest_address(self, address_item):
        row_idx = self.recipients.index(address_item)
        # remove all widgets related to the 'send to' address that is being removed
        for col_idx in range(self.lay_addresses.columnCount()):
            item = self.lay_addresses.itemAtPosition(row_idx, col_idx)
            self.remove_item_from_layout(item)

        # move up all rows greater than the row being removed
        for row in range(row_idx + 1, len(self.recipients)):
            self.move_grid_layout_row(row, row - 1 )

        del self.recipients[row_idx]

        QtWidgets.qApp.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.resized_signal.emit()
        self.show_hide_remove_buttons()
        self.set_default_fee()
        # self.calculate_change_amount()
        self.display_totals()

    def use_all_funds_for_address(self, address_item):
        row_idx = self.recipients.index(address_item)
        sum = 0.0
        left = 0.0

        # sum all the funds in all rows other than the current one
        for idx, addr in enumerate(self.recipients):
            if idx != row_idx:
                sum += addr.get_value(default_value=0.0)

        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            left = self.inputs_total_amount - sum - self.fee_amount
        elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
            left = 100.0 - sum

        left = round(left, 8) + 0.0
        if left < 0:
            left = 0.0
        address_item.set_value(left)
        self.update_change_amount()

    def amount_changed(self, addres_item):
        """ Activated after changing value in the 'amount' edit box of a recipient address. """
        self.init_calculate_change_value()

    def on_edt_fee_value_changed(self, text):
        if not text:
            text = '0.0'
        try:
            self.fee_amount = float(text)
            self.init_calculate_change_value()
        except Exception:
            self.display_message('Invalid \'transaction fee\' value.', 'red')  # display error message

    def show_hide_change_address(self, visible):
        if visible != self.change_controls_visible:
            row_nr = self.lay_addresses.rowCount() - 1
            if row_nr >= 0:
                for col_idx in range(self.lay_addresses.columnCount()):
                    item = self.lay_addresses.itemAtPosition(row_nr, col_idx)
                    if item:
                        if isinstance(item, QWidgetItem):
                            item.widget().setVisible(visible)
                        elif isinstance(item, (QSpacerItem, QHBoxLayout, QVBoxLayout)):
                            pass
                        else:
                            raise Exception('Invalid item type')
            self.change_controls_visible = visible
            QtWidgets.qApp.processEvents(QEventLoop.ExcludeUserInputEvents)
            self.resized_signal.emit()

    def show_hide_remove_buttons(self):
        visible = len(self.recipients) > 1
        for item in self.recipients:
            item.set_btn_remove_address_visible(visible)

    def set_change_addresses(self, addresses: List[Tuple[str, str]]):
        """
        :param addresses: addresses[0]: dest change address
                          addresses[1]: dest change bip32
        :return:
        """
        self.cbo_change_address.clear()
        self.change_addresses.clear()
        for addr in addresses:
            self.cbo_change_address.addItem(addr[0])
            self.change_addresses.append((addr[0], addr[1]))

    def set_input_amount(self, amount, inputs_count):
        self.inputs_count = inputs_count
        if amount != self.inputs_total_amount or inputs_count != self.inputs_count:
            # if there is only one recipient address and his current amount equals to the
            # previuus input_amount, assign new value to him

            last_total_amount = self.inputs_total_amount
            last_fee_amount = self.fee_amount
            self.inputs_total_amount = amount
            self.fee_amount = self.calculate_fee()

            if (len(self.recipients) == 1 or
                self.recipients[0].get_value(default_value=0.0) == 0.0 or
                self.recipients[0].get_value(default_value=0.0) == round(last_total_amount - last_fee_amount, 8)):

                if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
                    amount_minus_fee = round(amount - self.fee_amount, 8)
                    if amount_minus_fee < 0:
                        amount_minus_fee = 0.0
                    self.recipients[0].set_value(amount_minus_fee)
                elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
                    self.recipients[0].set_value(100.0)

            old_state = self.edt_fee_value.blockSignals(True)
            self.edt_fee_value.setText(app_utils.to_string(self.fee_amount))
            self.edt_fee_value.blockSignals(old_state)

            for addr in self.recipients:
                addr.set_inputs_total_amount(amount - self.fee_amount)
                addr.clear_validation_results()

            self.edt_fee_value.update()
            self.update_change_amount()
            self.display_totals()

    def calculate_change_value(self) -> float:
        """Returns the change value in Dash."""
        sum = 0.0
        for addr in self.recipients:
            sum += addr.get_value(default_value=0.0)

        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            change_amount = round(self.inputs_total_amount - sum - self.fee_amount, 8) + 0  # eliminate -0.0
        elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
            change_amount = round((100.0 - sum) * (self.inputs_total_amount - self.fee_amount) / 100 , 8)
        else:
            raise Exception('Invalid unit')
        return change_amount

    def update_change_amount(self) -> None:
        change_amount = self.calculate_change_value()
        if self.inputs_total_amount - self.fee_amount != 0:
            change_pct = round(change_amount * 100 / (self.inputs_total_amount - self.fee_amount), 8) + 0
        else:
            change_pct = 0.0

        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            left_second_unit_str = app_utils.to_string(round(change_pct, 3)) + '%'
            self.edt_change_amount.setText(app_utils.to_string(round(change_amount, 8)))
        elif self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
            left_second_unit_str = app_utils.to_string(round(change_amount, 8)) + ' Dash'
            sum = 0.0
            for addr in self.recipients:
                sum += addr.get_value(default_value=0.0)
            self.edt_change_amount.setText(app_utils.to_string(round(100 - sum, 8)))
        else:
            raise Exception('Invalid unit')

        msg = ''
        if change_amount < 0:
            used_amount = round(self.inputs_total_amount - change_amount, 8) + 0
            msg = f'Not enough funds - used amount: ' \
                  f'{used_amount}, available: {self.inputs_total_amount}. Adjust ' \
                  f'the output values.'
        self.lbl_second_unit.setText(left_second_unit_str)
        self.display_message(msg, 'red')

    def validate_output_data(self) -> bool:
        ret = True
        for addr in self.recipients:
            if not addr.validate():
                ret = False
        if not ret:
            self.display_message('Data of at least one recipient is invalid or empty. '
                                 'Please correct the data to continue.', 'red')
        else:
            self.display_message('')
        return ret

    def on_tm_calculate_change_value(self):
        self.tm_calculate_change_value.stop()
        for addr_item in self.recipients:
            addr_item.set_inputs_total_amount(self.inputs_total_amount - self.fee_amount)
        self.update_change_amount()

    def calculate_fee(self):
        if self.inputs_total_amount > 0.0:
            bytes = (self.inputs_count * 148) + (len(self.recipients) * 34) + 10
            fee = round(bytes * FEE_SAT_PER_BYTE, 8)
            if not fee:
                fee = MIN_TX_FEE
            fee = round(fee / 1e8, 8)
        else:
            fee = 0.0
        return fee

    def get_tx_fee(self):
        if self.fee_amount < 0.0:
            raise Exception('Invalid the fee value.')
        return round(self.fee_amount * 1e8)

    def init_calculate_change_value(self):
        self.tm_calculate_change_value.start(100)

    def set_default_fee(self):
        self.fee_amount = self.calculate_fee()

        old_status = self.edt_fee_value.blockSignals(True)
        try:
            self.edt_fee_value.setText(app_utils.to_string(self.fee_amount))
        finally:
            self.edt_fee_value.blockSignals(old_status)
        self.edt_fee_value.update()
        self.init_calculate_change_value()

    def on_btn_get_default_fee_clicked(self):
        self.set_default_fee()

    def set_dest_addresses(self, addresses: List):
        if len(addresses) > 0:
            count_diff = len(addresses) - len(self.recipients)
            if count_diff > 0:
                self.add_dest_address(count_diff)
            elif count_diff < 0:
                # remove unecessary rows, beginning from the largest one
                for nr in reversed(range(len(addresses), len(self.recipients))):
                    self.remove_dest_address(self.recipients[nr])
            for idx, addr_item in enumerate(self.recipients):
                if isinstance(addresses[idx], (list,tuple)):
                    # passed address-value tuple
                    if len(addresses[idx]) >= 1:
                        addr_item.set_address(addresses[idx][0])
                    if len(addresses[idx]) >= 2:
                        addr_item.set_value(addresses[idx][1])
                else:
                    addr_item.set_address(addresses[idx])
            self.display_totals()

    def set_change_value_label(self):
        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            self.lbl_change_amount.setText('value')
            self.lbl_change_amount.setToolTip('Unused amount - will be sent back to the change address')
        else:
            self.lbl_change_amount.setText('pct. value')
            self.lbl_change_amount.setToolTip('Unused amount (as percent of the total value of all inputs) - will '
                                              'be sent back to the change address')

    def on_cbo_output_unit_change(self, index):
        if index == 0:
            self.values_unit = OUTPUT_VALUE_UNIT_AMOUNT
        else:
            self.values_unit = OUTPUT_VALUE_UNIT_PERCENT

        self.set_change_value_label()
        for addr_item in self.recipients:
            addr_item.set_output_value_unit(self.values_unit)
        self.update_change_amount()

    def update_ui_value_unit(self):
        if self.values_unit == OUTPUT_VALUE_UNIT_AMOUNT:
            self.cbo_output_unit.setCurrentIndex(0)
        else:
            self.cbo_output_unit.setCurrentIndex(1)

    def simplyfy_file_home_dir(self, file_name):
        home_dir = os.path.expanduser('~')
        if self.current_file_name.find(home_dir) == 0:
            file_name = '~' + self.current_file_name[len(home_dir):]
        else:
            file_name = self.current_file_name
        return file_name

    def display_totals(self):
        bytes = (self.inputs_count * 148) + (len(self.recipients) * 34) + 10
        text = f'<span class="label"><b>Total value of selected inputs:</b>&nbsp;</span><span class="value">&nbsp;{self.inputs_total_amount} Dash&nbsp;</span>'
        if self.inputs_total_amount > 0:
            text += f'<span class="label">&nbsp;<b>Inputs:</b>&nbsp;</span><span class="value">&nbsp;{self.inputs_count}&nbsp;</span>' \
                    f'<span class="label">&nbsp;<b>Outputs:</b>&nbsp;</span><span class="value">&nbsp;{len(self.recipients)}&nbsp;</span>' \
                    f'<span class="label">&nbsp;<b>Transaction size:</b>&nbsp;</span><span class="value">&nbsp;{bytes} B&nbsp;</span>'
        self.lbl_totals.setText(text)

        if self.current_file_name:
            file_name = self.simplyfy_file_home_dir(self.current_file_name)
            text = f'<span class="label"><b>File:</b>&nbsp;</span><span class="value">{file_name}&nbsp;</span>'
            self.lbl_data_file_name.setText(text)
            self.lbl_data_file_name.setVisible(True)
            self.lbl_data_file_badge.setVisible(True)

            if self.current_file_encrypted:
                self.lbl_data_file_badge.setText('Encrypted')
                self.lbl_data_file_badge.setStyleSheet("QLabel{background-color:#2eb82e;color:white; padding: 1px 3px 1px 3px; border-radius: 3px;}")
            else:
                self.lbl_data_file_badge.setText('Not encrypted')
                self.lbl_data_file_badge.setStyleSheet("QLabel{background-color:orange;color:white; padding: 1px 3px 1px 3px; border-radius: 3px;}")
        else:
            self.lbl_data_file_name.setVisible(False)
            self.lbl_data_file_badge.setVisible(False)

    def clear_outputs(self):
        if WndUtils.queryDlg("Do you really want to clear all outputs?", default_button=QMessageBox.Cancel,
                             icon=QMessageBox.Warning) == QMessageBox.Ok:
            self.set_dest_addresses([('', '')])
            self.use_all_funds_for_address(self.recipients[0])

    def save_to_file(self, save_encrypted):
        if self.current_file_name and os.path.exists(os.path.dirname(self.current_file_name)):
            dir = os.path.dirname(self.current_file_name)
        else:
            dir = self.app_config.data_dir

        if save_encrypted:
            initial_filter = "DAT files (*.dat)"
        else:
            initial_filter = "CSV files (*.csv)"

        file_filter = f"{initial_filter};;All Files (*)"

        file_name = WndUtils.save_file_query(
            self.parent_dialog,
            message='Enter the file name to save the data.',
            directory=dir,
            filter=file_filter,
            initial_filter=initial_filter)

        if file_name:
            data = bytes()
            data += b'RECIPIENT_ADDRESS\tVALUE\n'
            if self.values_unit == OUTPUT_VALUE_UNIT_PERCENT:
                suffix = '%'
            else:
                suffix = ''

            for addr in self.recipients:
                line = f'{addr.get_address()}{CSV_SEPARATOR}{str(addr.get_value(default_value=""))}{suffix}\n'
                data += line.encode('utf-8')

            if save_encrypted:
                write_file_encrypted(file_name, self.hw_session, data)
            else:
                with open(file_name, 'wb') as f_ptr:
                    f_ptr.write(data)

            self.current_file_name = file_name
            self.current_file_encrypted = save_encrypted
            self.add_menu_item_to_mru(self.current_file_name)
            self.update_mru_menu_items()
            self.display_totals()

    def on_read_from_file_clicked(self):
        try:
            if self.current_file_name and os.path.exists(os.path.dirname(self.current_file_name)):
                dir = os.path.dirname(self.current_file_name)
            else:
                dir = self.app_config.data_dir

            initial_filter1 = "DAT files (*.dat)"
            initial_filter2 = "CSV files (*.csv)"

            file_filter = f"{initial_filter1};;{initial_filter2};;All Files (*.*)"

            file_name = WndUtils.open_file_query(
                self.parent_dialog,
                message='Enter the file name to read the data.',
                directory=dir,
                filter=file_filter,
                initial_filter='All Files (*.*)')

            if file_name:
                self.read_from_file(file_name)
        except Exception as e:
            self.parent_dialog.errorMsg(str(e))

    def read_from_file(self, file_name):
        try:
            file_info = {}
            data_decrypted = bytearray()
            for block in read_file_encrypted(file_name, file_info, self.hw_session):
                data_decrypted.extend(block)

            file_encrypted = file_info.get('encrypted', False)
            data = data_decrypted.decode('utf-8')

            addresses = []
            value_unit = None
            for line_idx, line in enumerate(data.split('\n')):
                if line:
                    elems = line.split('\t')
                    if len(elems) < 2:
                        elems = line.split(';')

                    if len(elems) < 2:
                        raise ValueError(f'Invalid data file entry for line: {line_idx+1}.')

                    address = elems[0].strip()
                    value = elems[1].strip()

                    address_valid = dash_utils.validate_address(address, dash_network=None)
                    if not address_valid:
                        if line_idx == 0 and re.match(r'^[A-Za-z_]+$', address):
                            continue  # header line
                        else:
                            raise ValueError(f'Invalid recipient address ({address}) (line {line_idx+1}).')

                    if value.endswith('%'):
                        vu = OUTPUT_VALUE_UNIT_PERCENT
                        value = value[:-1]
                    else:
                        vu = OUTPUT_VALUE_UNIT_AMOUNT
                    if value_unit is None:
                        value_unit = vu
                    elif value_unit != vu:
                        raise ValueError(f'The value unit in line {line_idx+1} differs from the previous '
                                         f'line.')

                    try:
                        if value:
                            value = float(value.replace(',', '.'))
                        else:
                            value = None
                        addresses.append((address, value))
                    except Exception as e:
                        raise ValueError(f'Invalid data in the \'value\' field (line {line_idx+1}).')

            if len(addresses) == 0:
                raise Exception('File doesn\'t contain any recipient\'s data.')
            else:
                if self.values_unit != value_unit:
                    self.values_unit = value_unit
                    self.update_ui_value_unit()
                self.set_dest_addresses(addresses)
                self.current_file_name = file_name
                self.current_file_encrypted = file_encrypted
                self.add_menu_item_to_mru(self.current_file_name)
                self.update_mru_menu_items()
                self.update_change_amount()
                self.display_totals()
        except Exception as e:
            self.update_mru_menu_items()
            logging.exception('Exception while reading file with recipients data.')
            self.parent_dialog.errorMsg(str(e))

    def add_menu_item_to_mru(self, file_name: str) -> None:
        if file_name:
            try:
                if file_name in self.recent_data_files:
                    idx = self.recent_data_files.index(file_name)
                    del self.recent_data_files[idx]
                    self.recent_data_files.insert(0, file_name)
                else:
                    self.recent_data_files.insert(0, file_name)
                app_cache.set_value(CACHE_ITEM_DATA_FILE_MRU_LIST, self.recent_data_files)
            except Exception as e:
                logging.warning(str(e))

    def update_mru_menu_items(self):
        app_utils.update_mru_menu_items(self.recent_data_files, self.mnu_recent_files,
                                        self.on_data_file_mru_action_triggered,
                                        self.current_file_name,
                                        self.on_act_clear_mru_items)

    def on_act_clear_mru_items(self):
        self.recent_data_files.clear()
        app_cache.set_value(CACHE_ITEM_DATA_FILE_MRU_LIST, self.recent_data_files)
        self.update_mru_menu_items()

    def on_data_file_mru_action_triggered(self, file_name: str) -> None:
        """ Triggered by clicking one of the subitems of the 'Open Recent' menu item. Each subitem is
        related to one of recently openend data files.
        :param file_name: A data file name accociated with the menu action clicked.
        """
        self.read_from_file(file_name)

    def get_tx_destination_data(self) -> List[Tuple[str, int, str]]:
        """
        :return: Tuple structure:
            [0]: dest address
            [1]: value in satoshis/duffs
            [2]: bip32 path of the address if the item is a change address, otherwise None
        """
        if self.validate_output_data():
            change_amount = self.calculate_change_value()
            if change_amount < 0.0:
                self.update_change_amount()  # here an appropriate message will be displayed
                raise Exception('Not enough funds!!!')

            dest_data = []
            for addr in self.recipients:
                dest_addr = addr.get_address()
                value = round(addr.get_value_amount() * 1e8)
                dest_data.append((dest_addr, value, None))

            if change_amount > 0.0:
                change_address_idx = self.cbo_change_address.currentIndex()
                if change_address_idx >= 0 and change_address_idx < len(self.change_addresses):
                    dest_data.append((self.change_addresses[change_address_idx][0],
                                      round(change_amount * 1e8),
                                      self.change_addresses[change_address_idx][1]))
                else:
                    raise Exception('Invalid address for the change.')
            return dest_data
        else:
            return []

    def get_recipients_list(self) -> List[Tuple[str,]]:
        """
        :return: List of recipient addresses
                 List[Tuple[str <address>, float <value>]
        """
        dest_data = []
        for addr in self.recipients:
            dest_addr = addr.get_address()
            if dest_addr:
                dest_data.append((dest_addr,))
        return dest_data
