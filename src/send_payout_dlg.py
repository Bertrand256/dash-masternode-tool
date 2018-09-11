#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
import base64
import bisect
import datetime
import simplejson
import threading
import time
import logging
import math

import traceback
from functools import partial
from more_itertools import consecutive_groups
from typing import Tuple, List, Optional, Dict, Generator
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSlot, QStringListModel, QItemSelectionModel, \
    QItemSelection, QSortFilterProxyModel, QAbstractItemModel, QModelIndex, QObject, QAbstractListModel, QPoint
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QDialog, QTableView, QHeaderView, QMessageBox, QSplitter, QVBoxLayout, QPushButton, \
    QItemDelegate, QLineEdit, QCompleter, QInputDialog, QLayout, QAction, QAbstractItemView, QStatusBar
from cryptography.fernet import Fernet
import app_cache
import app_utils
import dash_utils
import hw_intf
import thread_utils
from app_config import MasternodeConfig
from app_defs import HWType, DEBUG_MODE
from bip44_wallet import Bip44Wallet
from wallet_common import UtxoType, Bip44AccountType, AddressType
from dashd_intf import DashdInterface, DashdIndexException
from db_intf import DBCache
from hw_common import HardwareWalletCancelException, HwSessionInfo
from hw_intf import prepare_transfer_tx, get_address
from table_model_column import AdvTableModel, TableModelColumn
from thread_fun_dlg import WorkerThread, CtrlObject
from tx_history_widgets import TransactionsModel, TransactionsProxyModel
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate
from ui import ui_send_payout_dlg
from send_funds_widgets import SendFundsDestination
from transaction_dlg import TransactionDlg


CACHE_ITEM_UTXO_SOURCE_MODE = 'WalletDlg_UtxoSourceMode'
CACHE_ITEM_HW_ACCOUNT_BASE_PATH = 'WalletDlg_UtxoSrc_HwAccountBasePath_%NETWORK%'
CACHE_ITEM_HW_SEL_ACCOUNT_ADDR_ID = 'WalletDlg_UtxoSrc_HwAccountId'
CACHE_ITEM_HW_SRC_BIP32_PATH = 'WalletDlg_UtxoSrc_HwBip32Path_%NETWORK%'
CACHE_ITEM_UTXO_SRC_MASTRNODE = 'WalletDlg_UtxoSrc_Masternode_%NETWORK%'
CACHE_ITEM_UTXO_COLS = 'WalletDlg_UtxoColumns'
CACHE_ITEM_LAST_RECIPIENTS = 'WalletDlg_LastRecipients_%NETWORK%'
CACHE_ITEM_MAIN_SPLITTER_SIZES = 'WalletDlg_MainSplitterSizes'
FETCH_DATA_INTERVAL_SECONDS = 60

log = logging.getLogger('dmt.wallet_dlg')


class UtxoTableModel(AdvTableModel):
    def __init__(self, parent, masternode_list: List[MasternodeConfig]):
        AdvTableModel.__init__(self, parent, [
            TableModelColumn('satoshis', 'Amount (Dash)', True, 100),
            TableModelColumn('confirmations', 'Confirmations', True, 100),
            TableModelColumn('bip32_path', 'Path', True, 100),
            TableModelColumn('time_str', 'TX Date/Time', True, 140),
            TableModelColumn('address', 'Address', True, 140),
            TableModelColumn('masternode', 'Masternode', False, 40),
            TableModelColumn('txid', 'TX ID', True, 220),
            TableModelColumn('output_index', 'TX Idx', True, 40)
        ], True, True)
        if DEBUG_MODE:
            self.insert_column(len(self._columns), TableModelColumn('id', 'DB id', True, 40))
        self.sorting_column_name = 'confirmations'
        self.sorting_order = Qt.AscendingOrder
        self.hide_collateral_utxos = True
        self.utxos: List[UtxoType] = []
        self.utxo_by_id: Dict[int, UtxoType] = {}
        self.block_height = None

        self.mn_by_collateral_tx: Dict[str, MasternodeConfig] = {}
        self.mn_by_collateral_address: Dict[str, MasternodeConfig] = {}

        for mn in masternode_list:
            ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
            self.mn_by_collateral_tx[ident] = mn
            self.mn_by_collateral_address[mn.collateralAddress] = mn

        self.set_attr_protection()

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.utxos)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.utxos):
                utxo = self.utxos[row_idx]
                if utxo:
                    if role in (Qt.DisplayRole, Qt.EditRole):
                        c = self.col_by_index(col_idx)
                        if c:
                            field_name = c.name
                            if field_name == 'satoshis':
                                return app_utils.to_string(round(utxo.satoshis / 1e8, 8))
                            elif field_name == 'masternode':
                                if utxo.masternode:
                                    return utxo.masternode.name
                            else:
                                return app_utils.to_string(utxo.__getattribute__(field_name))
                    elif role == Qt.ForegroundRole:
                        if utxo.is_collateral:
                            return QColor(Qt.red)
                        elif utxo.coinbase_locked:
                            if col_idx == 1:
                                return QtGui.QColor('red')
                            else:
                                return QtGui.QColor('gray')

                    elif role == Qt.BackgroundRole:
                        if utxo.coinbase_locked:
                            return QtGui.QColor('lightgray')

                    elif role == Qt.TextAlignmentRole:
                        if col_idx in (0, 1):
                            return Qt.AlignRight

        return QVariant()

    def add_utxo(self, utxo: UtxoType):
        if not utxo.id in self.utxo_by_id:
            self.utxos.append(utxo)
            self.utxo_by_id[utxo.id] = utxo
            ident = utxo.txid + '-' + str(utxo.output_index)
            if ident in self.mn_by_collateral_tx:
                utxo.is_collateral = True
            mn = self.mn_by_collateral_address.get(utxo.address, None)
            if mn:
                utxo.masternode = mn

    def clear_utxos(self):
        self.utxos.clear()
        self.utxo_by_id.clear()

    def update_utxos(self, utxos_to_add: List[UtxoType], utxos_to_delete: List[Tuple[int, int]]):
        if utxos_to_delete:
            row_indexes_to_remove = []
            for utxo_id in utxos_to_delete:
                utxo = self.utxo_by_id.get(utxo_id)
                if utxo:
                    utxo_index = self.utxos.index(utxo)
                    if utxo_index not in row_indexes_to_remove:
                        row_indexes_to_remove.append(utxo_index)
                    del self.utxo_by_id[utxo_id]
            row_indexes_to_remove.sort(reverse=True)

            for group in consecutive_groups(row_indexes_to_remove, ordering=lambda x: -x):
                l = list(group)
                self.beginRemoveRows(QModelIndex(), l[-1], l[0]) # items are sorted in reverso order
                del self.utxos[l[-1]: l[0]+1]
                self.endRemoveRows()

        if utxos_to_add:
            row_idx = len(self.utxos)
            self.beginInsertRows(QModelIndex(), row_idx, row_idx + len(utxos_to_add) - 1)
            try:
                self.utxos.extend(utxos_to_add)
                for utxo in utxos_to_add:
                    self.add_utxo(utxo)
            finally:
                self.endInsertRows()

    def lessThan(self, col_index, left_row_index, right_row_index):
        col = self.col_by_index(col_index)
        if col:
            col_name = col.name
            reverse = False
            if col_name == 'time_str':
                col_name = 'confirmations'
                reverse = True

            if 0 <= left_row_index < len(self.utxos) and \
               0 <= right_row_index < len(self.utxos):
                left_utxo = self.utxos[left_row_index]
                right_prop = self.utxos[right_row_index]
                left_value = left_utxo.__getattribute__(col_name)
                right_value = right_prop.__getattribute__(col_name)
                if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
                    if not reverse:
                        return left_value < right_value
                    else:
                        return right_value < left_value
                elif isinstance(left_value, str) and isinstance(right_value, str):
                    left_value = left_value.lower()
                    right_value = right_value.lower()
                    if not reverse:
                        return left_value < right_value
                    else:
                        return right_value < left_value
        return False

    def filterAcceptsRow(self, source_row):
        will_show = True
        if 0 <= source_row < len(self.utxos):
            if self.hide_collateral_utxos:
                utxo = self.utxos[source_row]
                if utxo.is_collateral:
                    will_show = False
        return will_show

    def set_hide_collateral_utxos(self, hide):
        self.hide_collateral_utxos = hide
        self.proxy_model.invalidateFilter()

    def set_block_height(self, block_height: int):
        if block_height != self.block_height:
            log.debug('Block height updated to %s', block_height)
            self.block_height = block_height
            # if self.utxos:
            #     tl_index = self.index(0, self.col_index_by_name('confirmations'))
            #     br_index = self.index(len(self.utxos) - 1, self.col_index_by_name('confirmations'))
            #     self.view.dataChanged(tl_index, br_index, [Qt.DisplayRole, Qt.ForegroundRole, Qt.BackgroundColorRole])

class AccountListModel(QAbstractItemModel):
    def __init__(self, parent):
        QAbstractItemModel.__init__(self, parent)
        self.accounts: List[Bip44AccountType] = []

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            if section == 0:
                return ''
            elif section == 1:
                return 'Balance'
            elif section == 2:
                return 'Received'
        return ''

    def parent(self, index=None):
        try:
            if not index or not index.isValid():
                return QModelIndex()
            node = index.internalPointer()
            if isinstance(node, Bip44AccountType):
                return QModelIndex()
            else:
                acc_idx = self.accounts.index(node.bip44_account)
                return self.createIndex(acc_idx, 0, node.bip44_account)
        except Exception as e:
            log.exception('Exception while getting parent of index')
            raise

    def index(self, row, column, parent=None, *args, **kwargs):
        try:
            if not parent or not parent.isValid():
                if 0 <= row < len(self.accounts):
                    return self.createIndex(row, column, self.accounts[row])
                else:
                    return QModelIndex()
            parentNode = parent.internalPointer()
            if isinstance(parentNode, Bip44AccountType):
                addr = parentNode.address_by_index(row)
                if addr:
                    return self.createIndex(row, column, addr)
            return QModelIndex()
        except Exception as e:
            log.exception('Exception while creating index')
            raise

    def columnCount(self, parent=None, *args, **kwargs):
        return 3

    def rowCount(self, parent=None, *args, **kwargs):
        if not parent or not parent.isValid():
            return len(self.accounts)
        node = parent.internalPointer()
        if isinstance(node, Bip44AccountType):
            return len(node.addresses)
        else:
            return 0

    def data(self, index, role=None):
        if index.isValid():
            data = index.internalPointer()
            col = index.column()
            if data:
                if role in (Qt.DisplayRole, Qt.EditRole):
                    if col == 0:
                        if isinstance(data, Bip44AccountType):
                            return data.get_account_name()
                        else:
                            return f'/{data.address_index}: {data.address}'
                    elif col == 1:
                        b = data.balance
                        if b:
                            b = b/1e8
                        return b
                    elif col == 2:
                        b = data.received
                        if b:
                            b = b/1e8
                        return b

                elif role == Qt.ForegroundRole:
                    if isinstance(data, Bip44AccountType):
                        return data.get_account_name()
                    elif isinstance(data, AddressType):
                        if data.received == 0:
                            return QColor(Qt.lightGray)
                        elif data.balance == 0:
                            return QColor(Qt.gray)

                elif role == Qt.FontRole:
                    if isinstance(data, Bip44AccountType):
                        return data.get_account_name()
                    elif isinstance(data, AddressType):
                        font = QFont()
                        # if data.balance > 0:
                        #     font.setBold(True)
                        font.setPointSize(font.pointSize() - 2)
                        return font
        return QVariant()

    def removeRows(self, row, count, parent=None, *args, **kwargs):
        if parent is None or not parent.isValid():
            if row >=0 and row < len(self.accounts):
                self.beginRemoveRows(parent, row, row + count)
                for row_offs in range(count):
                    del self.accounts[row - row_offs]
                self.endRemoveRows()
            return True
        else:
            acc = parent.internalPointer()
            removed = False
            if acc:
                self.beginRemoveRows(parent, row, row + count)
                for row_offs in range(count):
                    removed = max(removed, acc.remove_address_by_index(row - row_offs))
                self.endRemoveRows()
            return removed

    def account_by_id(self, id: int) -> Optional[Bip44AccountType]:
        for a in self.accounts:
            if a.id == id:
                return a
        return None

    def account_index_by_id(self, id: int) -> Optional[int]:
        for idx, a in enumerate(self.accounts):
            if a.id == id:
                return idx
        return None

    def add_account(self, account: Bip44AccountType):
        existing_account = self.account_by_id(account.id)
        if not existing_account:
            self.accounts.append(account)
            self.modified = True
        else:
            if existing_account.update_from(account):
                self.modified = True

    def clear_accounts(self):
        self.accounts.clear()

    def sort_accounts(self):
        try:
            self.accounts.sort(key=lambda x: x.address_index)
        except Exception as e:
            pass


class WalletDlg(QDialog, ui_send_payout_dlg.Ui_SendPayoutDlg, WndUtils):
    error_signal = QtCore.pyqtSignal(str)
    thread_finished = QtCore.pyqtSignal()

    def __init__(self, main_ui, initial_mn_sel: int):
        """
        :param initial_mn_sel:
          if the value is from 0 to len(masternodes), show utxos for the masternode
            having the 'initial_mn' index in self.config.mastrnodes
          if the value is -1, show utxo for all masternodes
          if the value is None, show the default utxo source type
        """
        QDialog.__init__(self, parent=main_ui)
        WndUtils.__init__(self, main_ui.config)
        self.rawtransactions = {}
        self.masternodes = main_ui.config.masternodes
        self.masternode_addresses: List[Tuple[str, str]] = []  #  Tuple: address, bip32 path
        for idx, mn in enumerate(self.masternodes):
            self.masternode_addresses.append((mn.collateralAddress.strip(), mn.collateralBip32Path.strip()))
            log.debug(f'WalletDlg initial_mn_sel({idx}) addr - path: {mn.collateralAddress}-{mn.collateralBip32Path}')

        self.dashd_intf: DashdInterface = main_ui.dashd_intf
        self.db_intf: DBCache = main_ui.config.db_intf
        self.utxo_table_model = UtxoTableModel(self, self.masternodes)
        self.finishing = False  # true if closing window
        self.fetch_transactions_thread_ref: Optional[WorkerThread] = None
        self.fetch_transactions_thread_id = None
        self.fetch_transactions_lock = thread_utils.EnhRLock()
        self.accounts_lock = thread_utils.EnhRLock()
        self.last_txs_fetch_time = 0
        self.allow_fetch_transactions = True
        self.update_data_view_thread_ref: Optional[WorkerThread] = None
        self.update_data_view_thread_id = None
        self.last_utxos_source_hash = ''
        self.initial_mn_sel = initial_mn_sel

        # 1: masternode collateral address
        # 2: wallet account (the account number and base bip32 path are selected from the GUI by a user)
        # 3: bip32 path entered by a user from GUI, converted to address
        self.utxo_src_mode: Optional[int] = None

        # for self.utxo_src_mode == 1
        self.mn_src_index = None

        # for self.utxo_src_mode == 2
        self.hw_account_base_bip32_path = ''
        self.hw_selected_account_id = None  # bip44 account address id
        self.hw_selected_address_id = None  # if the account's address was selected (the index in the Bip44AccountType.addresses list)

        # for self.utxo_src_mode == 3
        self.hw_src_bip32_path = None
        self.hw_src_address = None

        self.sel_addresses_balance = 0.0
        self.sel_addresses_received = 0.0

        self.org_message = ''
        self.main_ui = main_ui
        self.grid_column_widths = []
        self.recipient_list_from_cache = []
        self.tab_transactions_model = None

        self.account_list_model = AccountListModel(self)
        self.load_data_event = threading.Event()
        self.fetch_txs_event = threading.Event()
        self.hw_session: HwSessionInfo = self.main_ui.hw_session

        self.bip44_wallet = Bip44Wallet(self.hw_session, self.db_intf, self.dashd_intf,
                                        self.app_config.dash_network)

        self.setupUi()

    def setupUi(self):
        ui_send_payout_dlg.Ui_SendPayoutDlg.setupUi(self, self)
        self.setWindowTitle('Transfer funds')
        self.closeEvent = self.closeEvent
        self.chbHideCollateralTx.setChecked(True)
        self.setIcon(self.btnCheckAll, 'check.png')
        self.setIcon(self.btnUncheckAll, 'uncheck.png')
        self.restore_cache_settings()

        self.utxo_table_model.set_hide_collateral_utxos(True)
        self.utxoTableView.setSortingEnabled(True)
        self.utxoTableView.setItemDelegate(ReadOnlyTableCellDelegate(self.utxoTableView))
        self.utxoTableView.verticalHeader().setDefaultSectionSize(
            self.utxoTableView.verticalHeader().fontMetrics().height() + 4)
        self.utxo_table_model.set_view(self.utxoTableView)

        self.listWalletAccounts.setModel(self.account_list_model)

        self.setup_transactions_table_view()
        self.chbHideCollateralTx.toggled.connect(self.chbHideCollateralTxToggled)

        self.cbo_src_masternodes.blockSignals(True)
        for mn in self.masternodes:
            mn_label = mn.name
            self.cbo_src_masternodes.addItem(mn_label)
        if len(self.masternodes) > 1:
            self.cbo_src_masternodes.addItem('<All Masternodes>')
        self.cbo_src_masternodes.blockSignals(False)

        if isinstance(self.initial_mn_sel, int):
            self.utxo_src_mode = 1
            if self.initial_mn_sel == -1:
                if self.cbo_src_masternodes.count() == len(self.masternodes) + 1:
                    self.mn_src_index = len(self.masternodes)
                else:
                    self.mn_src_index = 0
            else:
                if self.initial_mn_sel < len(self.masternodes):
                    self.mn_src_index = self.initial_mn_sel
                else:
                    self.mn_src_index = 0

        self.cbo_address_source_mode.blockSignals(True)
        if self.utxo_src_mode == 1:
            self.sw_address_source.setCurrentIndex(2)
            self.cbo_address_source_mode.setCurrentIndex(2)
        elif self.utxo_src_mode == 2:
            self.sw_address_source.setCurrentIndex(0)
            self.cbo_address_source_mode.setCurrentIndex(0)
        elif self.utxo_src_mode == 3:
            self.sw_address_source.setCurrentIndex(1)
            self.cbo_address_source_mode.setCurrentIndex(1)
        else:
            log.warning(f'Invalid value of self.utxo_src_mode: {self.utxo_src_mode}')
        self.cbo_address_source_mode.blockSignals(False)

        self.edt_src_bip32_path.blockSignals(True)
        self.edt_src_bip32_path.setText(self.hw_src_bip32_path)
        self.edt_src_bip32_path.blockSignals(False)

        if self.mn_src_index is None and len(self.masternodes) > 0:
            self.mn_src_index = 0

        if self.mn_src_index is not None and \
                self.mn_src_index >= 0 and self.mn_src_index < self.cbo_src_masternodes.count():
            self.cbo_src_masternodes.blockSignals(True)
            self.cbo_src_masternodes.setCurrentIndex(self.mn_src_index)
            self.cbo_src_masternodes.blockSignals(False)

        self.set_message("")
        self.set_message_2("")
        self.wdg_dest_adresses = SendFundsDestination(self.dest_widget, self, self.main_ui.config,
                                                      self.main_ui.hw_session)
        self.wdg_dest_adresses.resized_signal.connect(self.on_dest_addresses_resized)

        if isinstance(self.recipient_list_from_cache, list) and self.recipient_list_from_cache:
            try:
                self.wdg_dest_adresses.set_dest_addresses(self.recipient_list_from_cache)
            except Exception:
                pass

        self.lay_dest_address = QVBoxLayout(self.dest_widget)
        self.lay_dest_address.setContentsMargins(0, 0, 0, 0)
        self.lay_dest_address.addWidget(self.wdg_dest_adresses)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        self.btn_src_bip32_path.setText('\u270e')
        self.btn_src_bip32_path.setFixedSize(22, self.edt_src_bip32_path.sizeHint().height())
        self.display_bip32_base_path()
        self.lbl_hw_account_base_path.setStyleSheet('QLabel{font-size:10px}')
        self.utxoTableView.selectionModel().selectionChanged.connect(self.on_utxoTableView_selectionChanged)
        self.listWalletAccounts.selectionModel().selectionChanged.connect(self.on_listWalletAccounts_selectionChanged)
        self.listWalletAccounts.setItemDelegateForColumn(0, ReadOnlyTableCellDelegate(self.listWalletAccounts))

        # context menu actions:
        self.act_show_address_on_hw = QAction('Show address on hardware wallet', self)
        self.act_show_address_on_hw.triggered.connect(self.on_show_address_on_hw_triggered)
        self.listWalletAccounts.addAction(self.act_show_address_on_hw)

        # todo: for testing only:
        self.act_delete_account_data = QAction('Clear account data in cache', self)
        self.act_delete_account_data.triggered.connect(self.on_delete_account_triggered)
        self.listWalletAccounts.addAction(self.act_delete_account_data)

        self.act_delete_address_data = QAction('Clear address data in cache', self)
        self.act_delete_address_data.triggered.connect(self.on_delete_address_triggered)
        self.listWalletAccounts.addAction(self.act_delete_address_data)

        self.update_context_actions()
        self.update_data_view_thread_ref = self.run_thread(self, self.update_data_view_thread, ())

    def closeEvent(self, event):
        self.finishing = True
        self.allow_fetch_transactions = False
        self.load_data_event.set()
        self.fetch_txs_event.set()
        if self.fetch_transactions_thread_ref:
            self.fetch_transactions_thread_ref.wait(5000)
        if self.update_data_view_thread_ref:
            self.update_data_view_thread_ref.wait(5000)
        self.save_cache_settings()

    # todo: testing
    # def keyPressEvent(self, event):
    #     mods = int(event.modifiers())
    #     processed = False
    #
    #     if mods == int(Qt.ControlModifier) | int(Qt.AltModifier):
    #
    #         if ord('C') == event.key():
    #             self.main_ui.on_action_command_console_triggered(None)
    #             processed = True
    #
    #     if not processed:
    #         QDialog.keyPressEvent(self, event)

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)

        # main spliiter size
        self.splitterMain.setSizes(app_cache.get_value(CACHE_ITEM_MAIN_SPLITTER_SIZES, [100, 600], list))

        if self.initial_mn_sel is None:
            mode = app_cache.get_value(CACHE_ITEM_UTXO_SOURCE_MODE, 2, int)
            if mode in (1, 2, 3):
                self.utxo_src_mode = mode

        # base bip32 path:
        path = app_cache.get_value(CACHE_ITEM_HW_ACCOUNT_BASE_PATH.replace('%NETWORK%', self.app_config.dash_network),
                                   dash_utils.get_default_bip32_base_path(self.app_config.dash_network), str)
        if dash_utils.validate_bip32_path(path):
            self.hw_account_base_bip32_path = path
        else:
            self.hw_account_base_bip32_path = dash_utils.get_default_bip32_base_path(self.app_config.dash_network)

        # selected account id:
        self.hw_selected_account_id = app_cache.get_value(CACHE_ITEM_HW_SEL_ACCOUNT_ADDR_ID, 0x80000000, int)

        # bip32 path (utxo_src_mode 3)
        path = app_cache.get_value(CACHE_ITEM_HW_SRC_BIP32_PATH.replace('%NETWORK%', self.app_config.dash_network),
                                   dash_utils.get_default_bip32_path(self.app_config.dash_network), str)
        if dash_utils.validate_bip32_path(path):
            self.hw_src_bip32_path = path
        else:
            self.hw_src_bip32_path = dash_utils.get_default_bip32_path(self.app_config.dash_network)

        self.utxo_table_model.restore_col_defs(CACHE_ITEM_UTXO_COLS)

        sel_nasternode = app_cache.get_value(
            CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network), '', str)
        if sel_nasternode:
            if sel_nasternode == '<ALL>':
                self.mn_src_index = len(self.masternodes)
            else:
                for idx, mn in enumerate(self.masternodes):
                    if mn.name == sel_nasternode:
                        self.mn_src_index = idx
                        break

        # restore last list of used addresses
        enc_json_str = app_cache.get_value(CACHE_ITEM_LAST_RECIPIENTS.replace('%NETWORK%', self.app_config.dash_network), None, str)
        if enc_json_str:
            try:
                # hw encryption key may be not available so use the generated key to not save addresses as plain text
                self.encryption_key = base64.urlsafe_b64encode(self.app_config.hw_generated_key)
                fernet = Fernet(self.encryption_key)
                enc_json_str = bytes(enc_json_str, 'ascii')
                json_str = fernet.decrypt(enc_json_str)
                json_str = json_str.decode('ascii')
                self.recipient_list_from_cache = simplejson.loads(json_str)
            except Exception:
                log.exception('Cannot restore data from cache.')

    def save_cache_settings(self):
        app_cache.save_window_size(self)
        app_cache.set_value(CACHE_ITEM_MAIN_SPLITTER_SIZES, self.splitterMain.sizes())
        if self.initial_mn_sel is None:
            app_cache.set_value(CACHE_ITEM_UTXO_SOURCE_MODE, self.utxo_src_mode)
        app_cache.set_value(CACHE_ITEM_HW_ACCOUNT_BASE_PATH.replace('%NETWORK%', self.app_config.dash_network),
                            self.hw_account_base_bip32_path)
        app_cache.set_value(CACHE_ITEM_HW_SEL_ACCOUNT_ADDR_ID, self.hw_selected_account_id)
        app_cache.set_value(CACHE_ITEM_HW_SRC_BIP32_PATH.replace('%NETWORK%', self.app_config.dash_network),
                            self.hw_src_bip32_path)

        if self.mn_src_index is not None:
            # save the selected masternode name
            if self.mn_src_index >=0:
                if self.mn_src_index < len(self.masternodes):
                    app_cache.set_value(CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network),
                                        self.masternodes[self.mn_src_index].name)
                else:
                    app_cache.set_value(CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network),
                                        '<ALL>')

        self.utxo_table_model.save_col_defs(CACHE_ITEM_UTXO_COLS)

        # recipient list
        rcp_list = self.wdg_dest_adresses.get_recipients_list()
        rcp_data = ''
        if rcp_list:
            try:
                # hw encryption key may be not available so use the generated key to not save addresses as plain text
                self.encryption_key = base64.urlsafe_b64encode(self.app_config.hw_generated_key)
                fernet = Fernet(self.encryption_key)
                rcp_json_str = simplejson.dumps(rcp_list)
                enc_json_str = bytes(rcp_json_str, 'ascii')
                rcp_data = fernet.encrypt(enc_json_str)
                rcp_data = rcp_data.decode('ascii')
            except Exception:
                log.exception('Cannot save data to cache.')
        app_cache.set_value(CACHE_ITEM_LAST_RECIPIENTS.replace('%NETWORK%', self.app_config.dash_network), rcp_data)

    def setup_transactions_table_view(self):
        self.tabViewTransactions.setSortingEnabled(True)
        self.tx_model = TransactionsModel(self)
        self.tx_proxy_model = TransactionsProxyModel(self)
        # self.tabViewTransactions.sortByColumn(self.table_model.column_index_by_name('confirmations'), Qt.AscendingOrder)
        # self.restore_cache_settings()

        self.tx_proxy_model.setSourceModel(self.tx_model)
        self.tabViewTransactions.setModel(self.tx_proxy_model)
        self.tabViewTransactions.setItemDelegate(ReadOnlyTableCellDelegate(self.tabViewTransactions))
        self.tabViewTransactions.verticalHeader().setDefaultSectionSize(self.tabViewTransactions.verticalHeader().fontMetrics().height() + 4)

        for idx, col in enumerate(self.tx_model.columns):
            if not col.visible:
                self.tabViewTransactions.setColumnHidden(idx, True)

    @pyqtSlot(int)
    def on_cbo_address_source_mode_currentIndexChanged(self, index):
        self.sw_address_source.setCurrentIndex(index)
        if index == 0:
            self.utxo_src_mode = 2
        elif index == 1:
            self.utxo_src_mode = 3
        elif index == 2:
            self.utxo_src_mode = 1
        else:
            raise Exception('Invalid index.')

    @pyqtSlot(int)
    def on_cbo_src_masternodes_currentIndexChanged(self, index):
        self.mn_src_index = index

    @pyqtSlot(str)
    def on_lbl_hw_account_base_path_linkActivated(self, text):
        path, ok = QInputDialog.getText(self, 'Account base path query', 'Enter a new BIP32 base path:',
                                               text=self.hw_account_base_bip32_path)
        if ok:
            try:
                dash_utils.bip32_path_string_to_n(path)
                if self.hw_account_base_bip32_path != path:
                    self.hw_account_base_bip32_path = path
                    self.display_bip32_base_path()
            except Exception:
                self.errorMsg('Invalid BIP32 path')

    @pyqtSlot(bool)
    def on_btn_src_bip32_path_clicked(self, checked):
        path, ok = QInputDialog.getText(self, 'BIP32 path query', 'Enter a new BIP32 path:',
                                               text=self.hw_src_bip32_path)
        if ok:
            try:
                dash_utils.bip32_path_string_to_n(path)
                if self.hw_src_bip32_path != path:
                    self.hw_src_bip32_path = path
                    self.hw_src_address = ''  # will be retrieved in self.load_utxos
                    self.edt_src_bip32_path.setText(self.hw_src_bip32_path)
            except Exception as e:
                self.errorMsg('Invalid BIP32 path')

    def on_dest_addresses_resized(self):
        self.splitter.setSizes([1, self.wdg_dest_adresses.sizeHint().height()])

    def display_bip32_base_path(self):
        self.lbl_hw_account_base_path.setText(f'&nbsp;&nbsp;Base path: {self.hw_account_base_bip32_path} '
                                              f'(<a href="ch">change</a>)')

    def set_message(self, message):
        def set_msg(message):
            if not message:
                self.lbl_message.setVisible(False)
            else:
                self.lbl_message.setVisible(True)
                self.lbl_message.setText(message)

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_msg, message)
        else:
            set_msg(message)

    def set_message_2(self, message):
        def set_msg(message):
            if not message:
                self.lbl_message_2.setVisible(False)
            else:
                self.lbl_message_2.setVisible(True)
                self.lbl_message_2.setText(message)

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_msg, message)
        else:
            set_msg(message)

    @pyqtSlot(bool)
    def chbHideCollateralTxToggled(self, checked):
        self.utxo_table_model.set_hide_collateral_utxos(checked)

    @pyqtSlot(bool)
    def on_btnUncheckAll_clicked(self):
        self.utxoTableView.clearSelection()

    @pyqtSlot(bool)
    def on_btnCheckAll_clicked(self):
        sel = self.utxoTableView.selectionModel()
        # block_old = sel.blockSignals(True)
        sel_modified = False
        s = QItemSelection()
        for row_idx, utxo in enumerate(self.utxo_table_model.utxos):
            index = self.utxo_table_model.index(row_idx, 0)
            if not utxo.coinbase_locked:
                if not sel.isSelected(index):
                    sel_modified = True
                    s.select(index, index)
        if sel_modified:
            sel.select(s, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    @pyqtSlot(bool)
    def on_btnUtxoViewColumns_clicked(self):
        self.utxo_table_model.exec_columns_dialog(self)

    @pyqtSlot()
    def on_btnSend_clicked(self):
        """
        Sends funds to Dash address specified by user.
        """
        amount, utxos = self.get_selected_utxos()
        if len(utxos):
            try:
                connected = self.connect_hw()
                if not connected:
                    return
            except HardwareWalletCancelException:
                return

            bip32_to_address = {}  # for saving addresses read from HW by BIP32 path
            total_satoshis = 0
            coinbase_locked_exist = False

            # verify if:
            #  - utxo is the masternode collateral transation
            #  - the utxo Dash (signing) address matches the hardware wallet address for a given path
            for utxo_idx, utxo in enumerate(utxos):
                total_satoshis += utxo.satoshis
                log.info(f'UTXO satosis: {utxo.satoshis}')
                if utxo.is_collateral:
                    if self.queryDlg(
                            "Warning: you are going to transfer masternode's collateral (1000 Dash) transaction "
                            "output. Proceeding will result in broken masternode.\n\n"
                            "Do you really want to continue?",
                            buttons=QMessageBox.Yes | QMessageBox.Cancel,
                            default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                        return
                if utxo.coinbase_locked:
                    coinbase_locked_exist = True

                bip32_path = utxo.bip32_path
                if not bip32_path:
                    self.errorMsg(f'No BIP32 path for UTXO: {utxo.txid}. Cannot continue.')
                    return

                addr_hw = bip32_to_address.get(bip32_path, None)
                if not addr_hw:
                    addr_hw = get_address(self.main_ui.hw_session, bip32_path)
                    bip32_to_address[bip32_path] = addr_hw
                if addr_hw != utxo.address:
                    self.errorMsg("<html style=\"font-weight:normal\">Dash address inconsistency between UTXO "
                                  f"({utxo_idx+1}) and HW path: {bip32_path}.<br><br>"
                                  f"<b>HW address</b>: {addr_hw}<br>"
                                  f"<b>UTXO address</b>: {utxo.address}<br><br>"
                                  "Cannot continue.</html>")
                    return

            if coinbase_locked_exist:
                if self.queryDlg("Warning: you have selected at least one coinbase transaction without the "
                                 "required number of confirmations (100). Your transaction will be "
                                 "rejected by the network.\n\n"
                                 "Do you really want to continue?",
                        buttons=QMessageBox.Yes | QMessageBox.Cancel,
                        default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                    return
            try:
                dest_data = self.wdg_dest_adresses.get_tx_destination_data()
                if dest_data:
                    total_satoshis_actual = 0
                    for dd in dest_data:
                        total_satoshis_actual += dd.satoshis
                        log.info(f'dest amount: {dd.satoshis}')

                    fee = self.wdg_dest_adresses.get_tx_fee()
                    use_is = self.wdg_dest_adresses.get_use_instant_send()
                    log.info(f'fee: {fee}')
                    if total_satoshis != total_satoshis_actual + fee:
                        log.warning(f'total_satoshis ({total_satoshis}) != total_satoshis_real '
                                        f'({total_satoshis_actual}) + fee ({fee})')
                        log.warning(f'total_satoshis_real + fee: {total_satoshis_actual + fee}')

                        if abs(total_satoshis - total_satoshis_actual - fee) > 10:
                            raise Exception('Data validation failure')

                    try:
                        serialized_tx, amount_to_send = prepare_transfer_tx(
                            self.main_ui.hw_session, utxos, dest_data, fee, self.rawtransactions)
                    except HardwareWalletCancelException:
                        # user cancelled the operations
                        hw_intf.cancel_hw_operation(self.main_ui.hw_session.hw_client)
                        return
                    except Exception:
                        log.exception('Exception when preparing the transaction.')
                        raise

                    tx_hex = serialized_tx.hex()
                    log.info('Raw signed transaction: ' + tx_hex)
                    if len(tx_hex) > 90000:
                        self.errorMsg("Transaction's length exceeds 90000 bytes. Select less UTXOs and try again.")
                    else:
                        tx_dlg = TransactionDlg(self, self.main_ui.config, self.dashd_intf, tx_hex, use_is)
                        if tx_dlg.exec_():
                            pass  # todo: update list of utxos and transactions
            except Exception as e:
                log.exception('Unknown error occurred.')
                self.errorMsg(str(e))
        else:
            self.errorMsg('No UTXO to send.')

    @pyqtSlot()
    def on_btnClose_clicked(self):
        self.close()

    def reflect_ui_account_selection(self):
        idx = self.listWalletAccounts.currentIndex()
        old_sel = self.get_utxo_src_cfg_hash()
        if idx and idx.isValid():
            data = idx.internalPointer()  # data can by of Bip44AccountType or AddressType
            if isinstance(data, Bip44AccountType):
                self.hw_selected_address_id = None
                if idx and idx.row() < len(self.account_list_model.accounts):
                    self.hw_selected_account_id = self.account_list_model.accounts[idx.row()].id
                else:
                    self.hw_selected_account_id = None
            elif isinstance(data, AddressType):
                self.hw_selected_account_id = data.bip44_account.id
                self.hw_selected_address_id = data.id
            else:
                return

        if old_sel != self.get_utxo_src_cfg_hash():
            self.utxo_table_model.clear_utxos()
            self.reset_utxos_view()
            self.load_data_event.set()
            self.update_context_actions()

    def on_listWalletAccounts_selectionChanged(self):
        """Selected BIP44 account or address changed. """
        self.reflect_ui_account_selection()

    def update_context_actions(self):
        visible = False
        if self.hw_selected_address_id is not None:
            if self.hw_session.hw_type in (HWType.trezor, HWType.keepkey):
                visible = True
        self.act_delete_address_data.setVisible(visible)
        self.act_show_address_on_hw.setVisible(visible)
        if self.hw_selected_account_id is not None:
            self.act_delete_account_data.setVisible(True)
        else:
            self.act_delete_account_data.setVisible(False)

    def on_show_address_on_hw_triggered(self):
        if self.hw_selected_address_id is not None:
            a = self.account_list_model.account_by_id(self.hw_selected_account_id)
            if a:
                addr = a.address_by_id(self.hw_selected_address_id)
                if addr:
                    _a = hw_intf.get_address(self.hw_session, addr.path, True,
                                             f'Displaying address <b>{addr.address}</b>.<br>Click the confirmation button on'
                                             f' your device.')
                    if _a != addr.address:
                        raise Exception('Address inconsistency between db cache and device')

    def on_delete_account_triggered(self):
        if self.hw_selected_account_id is not None:
            index = self.listWalletAccounts.currentIndex()
            if index and index.isValid():
                node = index.internalPointer()
                if isinstance(node, Bip44AccountType):
                    acc = node
                elif isinstance(node, AddressType):
                    acc = node.bip44_account
                else:
                    raise Exception('No account selected.')

                if WndUtils.queryDlg(f"Do you really want to remove account '{acc.get_account_name()}' from cache?",
                                    buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                    default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
                    return

                fx_state = self.allow_fetch_transactions
                signals_state = self.listWalletAccounts.blockSignals(True)
                try:
                    self.allow_fetch_transactions = False
                    self.fetch_transactions_lock.acquire()
                    self.account_list_model.removeRow(index.row())
                    self.bip44_wallet.remove_account(acc.id)
                finally:
                    self.allow_fetch_transactions = fx_state
                    self.fetch_transactions_lock.release()
                    self.listWalletAccounts.blockSignals(signals_state)
                    self.reflect_ui_account_selection()

    def on_delete_address_triggered(self):
        if self.hw_selected_address_id is not None:
            index = self.listWalletAccounts.currentIndex()
            if index and index.isValid():
                acc = None
                acc_index = None
                addr = index.internalPointer()
                if isinstance(addr, AddressType):
                    acc_index = index.parent()
                    if acc_index.isValid():
                        acc = acc_index.internalPointer()

                if acc and acc_index:
                    if WndUtils.queryDlg(f"Do you really want to clear address '{addr.address}' data in cache?",
                                        buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                        default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
                        return

                    ftx_state = self.allow_fetch_transactions
                    signals_state = self.listWalletAccounts.blockSignals(True)
                    try:
                        self.allow_fetch_transactions = False
                        self.fetch_transactions_lock.acquire()
                        self.account_list_model.removeRow(index.row(), parent=acc_index)
                        self.bip44_wallet.remove_address(addr.id)
                    finally:
                        self.allow_fetch_transactions = ftx_state
                        self.fetch_transactions_lock.release()
                        self.listWalletAccounts.blockSignals(signals_state)
                        self.reflect_ui_account_selection()

    def get_utxo_src_cfg_hash(self):
        hash = str({self.utxo_src_mode})
        if self.utxo_src_mode == 1:
            hash = hash + f'{self.mn_src_index}'
        elif self.utxo_src_mode == 2:
            hash = hash + f':{self.hw_account_base_bip32_path}:{self.hw_selected_account_id}:' \
                          f'{self.hw_selected_address_id}'
        elif self.utxo_src_mode == 3:
            hash = hash + ':' + str(self.hw_src_bip32_path)
        return hash

    def reset_accounts_view(self):
        def reset():
            try:
                log.debug('Beginning reset_accounts_view.reset')
                first_item_index = self.listWalletAccounts.indexAt(self.listWalletAccounts.rect().topLeft() +
                                                                   QPoint(0, self.listWalletAccounts.header().height()-2))
                if first_item_index and first_item_index.isValid():
                    first_item = first_item_index.internalPointer()
                else:
                    first_item = None

                # save the expanded account list to restore them after reset
                expanded_account_ids = []
                for account_idx, acc in enumerate(self.account_list_model.accounts):
                    index = self.account_list_model.index(account_idx, 0)
                    if index and self.listWalletAccounts.isExpanded(index):
                        expanded_account_ids.append(acc.id)

                self.account_list_model.beginResetModel()
                self.account_list_model.endResetModel()

                for account_id in expanded_account_ids:
                    account_idx = self.account_list_model.account_index_by_id(account_id)
                    index = self.account_list_model.index(account_idx, 0)
                    if index:
                        self.listWalletAccounts.setExpanded(index, True)

                if len(self.account_list_model.accounts) > 0:
                    if self.hw_selected_account_id is None:
                        sel_acc = self.account_list_model.accounts[0]
                    else:
                        sel_acc = self.account_list_model.account_by_id(self.hw_selected_account_id)
                        if not sel_acc:
                            sel_acc = self.account_list_model.accounts[0]

                    self.hw_selected_account_id = sel_acc.id
                    account_idx = self.account_list_model.account_index_by_id(self.hw_selected_account_id)
                    if account_idx is not None:
                        acc = self.account_list_model.accounts[account_idx]
                        focus_set = False
                        if self.hw_selected_address_id is not None:
                            addr_idx = acc.address_index_by_id(self.hw_selected_address_id)
                            if addr_idx is not None:
                                account_index = self.account_list_model.index(account_idx, 0)
                                if account_index and account_index.isValid():
                                    self.listWalletAccounts.setCurrentIndex(self.account_list_model.index(addr_idx, 0,
                                                                                                          account_index))
                                    focus_set = True
                        if not focus_set:
                            self.listWalletAccounts.setCurrentIndex(self.account_list_model.index(account_idx, 0))
                else:
                    self.hw_selected_account_id = None

                if first_item:
                    # restore the first visible item
                    if isinstance(first_item, Bip44AccountType):
                        acc_idx = self.account_list_model.account_index_by_id(first_item.id)
                        if acc_idx is not None:
                            acc_index = self.account_list_model.index(acc_idx, 0)
                            if acc_index and acc_index.isValid():
                                self.listWalletAccounts.scrollTo(acc_index, hint=QAbstractItemView.PositionAtTop)
                    elif isinstance(first_item, AddressType):
                        acc = first_item.bip44_account
                        if acc:
                            acc_idx = self.account_list_model.account_index_by_id(acc.id)
                            if acc_idx is not None:
                                acc_index = self.account_list_model.index(acc_idx, 0)
                                if acc_index and acc_index.isValid():
                                    addr_idx = acc.address_index_by_id(first_item.id)
                                    if addr_idx is not None:
                                        addr_index = self.account_list_model.index(addr_idx, 0, acc_index)
                                        if addr_index and addr_index.isValid():
                                            self.listWalletAccounts.scrollTo(addr_index,
                                                                             hint=QAbstractItemView.PositionAtTop)
            finally:
                log.debug('Finished reset_accounts_view.reset')
        WndUtils.call_in_main_thread(reset)

    def reset_utxos_view(self):
        def reset():
            log.debug('Begin reset_utxos_view')
            self.utxo_table_model.beginResetModel()
            self.utxo_table_model.endResetModel()
            log.debug('Finished reset_utxos_view')
        WndUtils.call_in_main_thread(reset)

    def hw_connected(self):
        if self.hw_session.hw_type is not None and self.hw_session.hw_client is not None:
            return True
        else:
            return False

    def connect_hw(self):
        def connect():
            if self.main_ui.connect_hardware_wallet():
                self.app_config.initialize_hw_encryption(self.main_ui.hw_session)
                self.update_context_actions()
                return True
            return False
        if not self.hw_connected():
            return WndUtils.call_in_main_thread(connect)
        else:
            return True

    def get_utxo_generator(self, only_new) -> Generator[UtxoType, None, None]:
        list_utxos = None
        if self.utxo_src_mode == 2:
            if self.hw_selected_account_id is not None:
                if self.hw_selected_address_id is None:
                    # list utxos of the whole bip44 account
                    list_utxos = self.bip44_wallet.list_utxos_for_account(self.hw_selected_account_id, only_new)
                else:
                    # list utxos of the specific address
                    list_utxos = self.bip44_wallet.list_utxos_for_address(self.hw_selected_address_id)
        return list_utxos

    def update_data_view_thread(self, ctrl: CtrlObject):
        log.debug('Starting update_data_view_thread')
        try:
            self.update_data_view_thread_id = threading.current_thread()
            last_utxos_source_hash = ''
            last_hd_tree = ''
            accounts_loaded = False
            fetch_txs_launched = False

            while not ctrl.finish and not self.finishing:
                if self.utxo_src_mode != 1:
                    connected = self.connect_hw()
                    if not connected:
                        return

                    if last_hd_tree != self.hw_session.hd_tree_ident or not accounts_loaded:
                        # switched to another hw or another passphrase

                        self.accounts_lock.acquire()
                        try:
                            if accounts_loaded:
                                self.account_list_model.clear_accounts()

                            # load bip44 account list
                            for a in self.bip44_wallet.list_accounts():
                                self.account_list_model.add_account(a)

                            self.account_list_model.sort_accounts()
                            self.reset_accounts_view()
                        finally:
                            self.accounts_lock.release()

                        accounts_loaded = True
                        last_hd_tree = self.hw_session.hd_tree_ident

                cur_utxo_source_hash = self.get_utxo_src_cfg_hash()
                if last_utxos_source_hash != cur_utxo_source_hash:
                    # reload the data
                    last_utxos_source_hash = cur_utxo_source_hash

                    list_utxos = self.get_utxo_generator(False)
                    if len(self.utxo_table_model.utxos) > 0:
                        self.utxo_table_model.clear_utxos()

                    if list_utxos:
                        self.set_message_2('Loading data for display...')
                        log.debug('Fetching utxos from the database')
                        self.utxo_table_model.set_block_height(self.bip44_wallet.get_block_height())
                        for utxo in list_utxos:
                            self.utxo_table_model.add_utxo(utxo)
                        log.debug('Fetching of utxos finished')
                        self.set_message_2('Displaying data...')

                    if len(self.utxo_table_model.utxos) > 0:
                        log.debug(f'Displaying utxos. Count: {len(self.utxo_table_model.utxos)}.')
                        self.reset_utxos_view()
                    self.set_message_2('')

                if not self.fetch_transactions_thread_id and not fetch_txs_launched:
                    log.debug('Starting thread fetch_transactions_thread')
                    self.fetch_transactions_thread_ref = WndUtils.call_in_main_thread(WndUtils.run_thread, self, self.fetch_transactions_thread, ())
                    fetch_txs_launched = True

                self.load_data_event.wait(2)
                if self.load_data_event.is_set():
                    self.load_data_event.clear()

        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg(str(e))

        finally:
            self.update_data_view_thread_id = None
        log.debug('Finishing update_data_view_thread')

    def fetch_transactions_thread(self, ctrl: CtrlObject):
        def break_fetch_process():
            if not self.allow_fetch_transactions or self.finishing or ctrl.finish:
                log.debug('Breaking the fetch transactions routine...')
                return True
            else:
                return False

        log.debug('Starting fetch_transactions_thread')

        try:
            self.fetch_transactions_thread_id = threading.current_thread()
            self.last_txs_fetch_time = 0

            while not ctrl.finish and not self.finishing:
                if self.utxo_src_mode != 1:
                    connected = self.connect_hw()
                    if not connected:
                        return

                if self.last_txs_fetch_time == 0 or (time.time() - self.last_txs_fetch_time > FETCH_DATA_INTERVAL_SECONDS):
                    if self.utxo_src_mode != 1:
                        self.set_message('Fetching transactions...')

                        accounts_modified = False
                        self.fetch_transactions_lock.acquire()
                        self.accounts_lock.acquire()
                        try:
                            self.bip44_wallet.reset_tx_diffs()
                            self.bip44_wallet.fetch_all_accounts_txs(break_fetch_process)

                            # fetching transactions may result in 'new' bip44 accounts with a non-zero 'received' balance
                            self.bip44_wallet.reset_accounts_diffs()
                            for a in self.bip44_wallet.list_accounts():
                                pass

                            for a in self.bip44_wallet.accounts_modified:
                                self.account_list_model.add_account(a)
                                accounts_modified = True
                        finally:
                            self.accounts_lock.release()
                            self.fetch_transactions_lock.release()
                            self.last_txs_fetch_time = int(time.time())

                        if ctrl.finish or self.finishing:
                            break
                        else:
                            if accounts_modified:
                                self.account_list_model.sort_accounts()
                                self.reset_accounts_view()

                            list_utxos = self.get_utxo_generator(True)
                            if list_utxos:
                                self.utxo_table_model.set_block_height(self.bip44_wallet.get_block_height())
                                log.debug('Fetching new/removed utxos from the database')

                                new_utxos = []
                                for utxo in list_utxos:
                                    new_utxos.append(utxo)

                                removed_utxos = [x for x in self.bip44_wallet.utxos_removed]
                                if new_utxos or removed_utxos:
                                    WndUtils.call_in_main_thread(self.utxo_table_model.update_utxos, new_utxos, removed_utxos)

                                log.debug('Fetching of utxos finished')

                            self.set_message('')

                self.fetch_txs_event.wait(FETCH_DATA_INTERVAL_SECONDS)
                if self.fetch_txs_event.is_set():
                    self.fetch_txs_event.clear()

        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg(str(e))
        finally:
            self.fetch_transactions_thread_id = None
        log.debug('Finishing fetch_transactions_thread')

    @pyqtSlot()
    def on_btnLoadTransactions_clicked(self):
        self.last_txs_fetch_time = 0
        self.fetch_txs_event.set()

    def on_edtSourceBip32Path_returnPressed(self):
        self.on_btnLoadTransactions_clicked()

    def get_selected_utxos(self) -> Tuple[int, List[UtxoType]]:
        """
        :return: Tuple[int <total amount selected>, List[Dict] <list of the selected utxos>]
        """
        row_indexes = self.utxo_table_model.get_selected_rows()
        utxos = []
        amount = 0
        for row in row_indexes:
            if 0 <= row < len(self.utxo_table_model.utxos):
                utxo = self.utxo_table_model.utxos[row]
                utxos.append(utxo)
                amount += utxo.satoshis

        return amount, utxos

    def update_recipient_area_utxos(self):
        total_amount, utxos = self.get_selected_utxos()
        total_amount = round(total_amount / 1e8, 8)
        self.wdg_dest_adresses.set_input_amount(total_amount, len(utxos))

    def on_utxoTableView_selectionChanged(self, selected, deselected):
        self.update_recipient_area_utxos()
