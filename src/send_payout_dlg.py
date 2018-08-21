#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
import base64
import datetime
import simplejson
import threading
import time
import logging
import math
from functools import partial
from typing import Tuple, List, Optional, Dict
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSlot, QStringListModel, QItemSelectionModel, \
    QItemSelection, QSortFilterProxyModel, QAbstractItemModel, QModelIndex, QObject, QAbstractListModel
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QTableView, QHeaderView, QMessageBox, QSplitter, QVBoxLayout, QPushButton, \
    QItemDelegate, QLineEdit, QCompleter, QInputDialog, QLayout
from cryptography.fernet import Fernet
import app_cache
import app_utils
import dash_utils
import hw_intf
from app_config import MasternodeConfig
from app_defs import HWType
from bip44_wallet import Bip44Wallet, UtxoType, Bip44AccountType
from dashd_intf import DashdInterface, DashdIndexException
from db_intf import DBCache
from hw_common import HardwareWalletCancelException, HwSessionInfo
from hw_intf import prepare_transfer_tx, get_address
from table_model_column import TableModelColumns, TableModelColumn
from thread_fun_dlg import WorkerThread, CtrlObject
from tx_history_widgets import TransactionsModel, TransactionsProxyModel
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate
from ui import ui_send_payout_dlg
from send_funds_widgets import SendFundsDestination
from transaction_dlg import TransactionDlg


CACHE_ITEM_UTXO_SOURCE_MODE = 'WalletDlg_UtxoSourceMode'
CACHE_ITEM_HW_ACCOUNT_BASE_PATH = 'WalletDlg_UtxoSrc_HwAccountBasePath_%NETWORK%'
CACHE_ITEM_HW_ACCOUNT_ADDR_INDEX = 'WalletDlg_UtxoSrc_HwAccountAddressIndex'
CACHE_ITEM_HW_SRC_BIP32_PATH = 'WalletDlg_UtxoSrc_HwBip32Path_%NETWORK%'
CACHE_ITEM_UTXO_SRC_MASTRNODE = 'WalletDlg_UtxoSrc_Masternode_%NETWORK%'
CACHE_ITEM_UTXO_COLS = 'WalletDlg_UtxoColumns'
CACHE_ITEM_LAST_RECIPIENTS = 'WalletDlg_LastRecipients_%NETWORK%'
CACHE_ITEM_MAIN_SPLITTER_SIZES = 'WalletDlg_MainSplitterSizes'
FETCH_DATA_INTERVAL_SECONDS = 30


class UtxoTableModel(QAbstractTableModel):
    def __init__(self, parent, parent_wnd, masternode_list: List[MasternodeConfig]):
        QAbstractTableModel.__init__(self, parent)
        self.checked = False
        self.utxos: List[UtxoType] = []
        self.utxo_by_id: Dict[int, UtxoType] = {}
        self.parent_wnd = parent_wnd
        self.view = None
        self.columns = TableModelColumns(columns=[
            TableModelColumn('satoshis', 'Amount (Dash)', True, 100),
            TableModelColumn('confirmations', 'Confirmations', True, 100),
            TableModelColumn('bip32_path', 'Path', True, 100),
            TableModelColumn('time_str', 'TX Date/Time', True, 140),
            TableModelColumn('address', 'Address', True, 140),
            TableModelColumn('masternode', 'Masternode', False, 40),
            TableModelColumn('txid', 'TX ID', True, 220),
            TableModelColumn('output_index', 'TX Idx', True, 40)
        ])

        self.mn_by_collateral_tx: Dict[str, MasternodeConfig] = {}
        self.mn_by_collateral_address: Dict[str, MasternodeConfig] = {}

        for mn in masternode_list:
            ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
            self.mn_by_collateral_tx[ident] = mn
            self.mn_by_collateral_address[mn.collateralAddress] = mn

    def set_table_view(self, view: QTableView):
        self.columns.set_table_view(view)
        self.columns.apply_to_view()

    def column_index_by_name(self, name: str) -> Optional[int]:
        return self.columns.col_index_by_name(name)

    def columnCount(self, parent=None, *args, **kwargs):
        return self.columns.col_count()

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.utxos)

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            col = self.columns.col_by_index(section)
            if col:
                return col.caption
            return ''
        else:
            return "Row"

    def getDefaultColWidths(self):
        return [c.initial_width for c in self.columns.columns()]

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
                        c = self.columns.col_by_index(col_idx)
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


class UtxoListProxyModel(QSortFilterProxyModel):
    """ Proxy for UTXO filtering/sorting. """

    def __init__(self, parent):
        super().__init__(parent)
        self.utxo_model: UtxoTableModel = None
        self.hide_collateral_utxos = True

    def filterAcceptsRow(self, source_row, source_parent):
        will_show = True

        if 0 <= source_row < len(self.utxo_model.utxos):
            if self.hide_collateral_utxos:
                utxo = self.utxo_model.utxos[source_row]
                if utxo.is_collateral:
                    will_show = False
        return will_show

    def setSourceModel(self, source_model):
        self.utxo_model = source_model
        super().setSourceModel(source_model)

    def set_hide_collateral_utxos(self, hide):
        self.hide_collateral_utxos = hide
        self.invalidateFilter()

    def lessThan(self, left, right):
        col_index = left.column()
        col = self.utxo_model.columns.col_by_index(col_index)
        if col:
            col_name = col.name
            reverse = False
            if col_name == 'time_str':
                col_name = 'confirmations'
                reverse = True
            left_row_index = left.row()

            if 0 <= left_row_index < len(self.utxo_model.utxos):
                left_utxo = self.utxo_model.utxos[left_row_index]
                right_row_index = right.row()

                if 0 <= right_row_index < len(self.utxo_model.utxos):
                    right_prop = self.utxo_model.utxos[right_row_index]
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
            return super().lessThan(left, right)


class AccountListModel(QAbstractListModel):
    def __init__(self, parent):
        QAbstractItemModel.__init__(self, parent)
        self.accounts: List[Bip44AccountType] = []
        self.modified = False

    def columnCount(self, parent=None, *args, **kwargs):
        return 1

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.accounts)

    def data(self, index, role=None):
        if index.isValid():
            row = index.row()
            if row < len(self.accounts):
                account = self.accounts[row]
                if account:
                    if role in (Qt.DisplayRole, Qt.EditRole):
                        return account.get_account_name()
        return QVariant()

    def reset_modified(self):
        self.modified = False

    def account_by_id(self, id: int) -> Optional[Bip44AccountType]:
        for a in self.accounts:
            if a.id == id:
                return a
        return None

    def account_by_address_index(self, address_index: int) -> Optional[Bip44AccountType]:
        for a in self.accounts:
            if a.address_index == address_index:
                return a
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
        self.accounts.sort(key=lambda x: x.address_index)


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
            logging.debug(f'WalletDlg initial_mn_sel({idx}) addr - path: {mn.collateralAddress}-{mn.collateralBip32Path}')

        self.dashd_intf: DashdInterface = main_ui.dashd_intf
        self.db_intf: DBCache = main_ui.config.db_intf
        self.utxo_table_model = UtxoTableModel(None, self, self.masternodes)
        self.finishing = False  # true if closing window
        self.load_utxos_thread_ref: Optional[WorkerThread] = None
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
        self.hw_account_address_index = None  # bip44 account address index; for account #1 (1-based) the values is 0x80000000

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

        self.utxoTableView.setSortingEnabled(True)
        self.utxo_proxy = UtxoListProxyModel(self)
        self.utxo_proxy.set_hide_collateral_utxos(True)
        self.utxo_proxy.setSourceModel(self.utxo_table_model)
        self.utxoTableView.setModel(self.utxo_proxy)
        self.utxoTableView.setItemDelegate(ReadOnlyTableCellDelegate(self.utxoTableView))
        self.utxoTableView.verticalHeader().setDefaultSectionSize(self.utxoTableView.verticalHeader().fontMetrics().height() + 4)
        self.utxo_table_model.columns.set_table_view(self.utxoTableView, columns_movable=True,
                                                     sorting_column='confirmations',
                                                     sorting_order=Qt.AscendingOrder)

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
            logging.warning(f'Invalid value of self.utxo_src_mode: {self.utxo_src_mode}')
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

        self.fetch_transactions_thread_id = None
        self.update_data_view_thread_id = None
        self.run_thread(self, self.update_data_view_thread, ())

    def closeEvent(self, event):
        self.finishing = True
        self.load_data_event.set()
        self.fetch_txs_event.set()
        self.save_cache_settings()

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

        # account number:
        nr = app_cache.get_value(CACHE_ITEM_HW_ACCOUNT_ADDR_INDEX, 0x80000000, int)
        if nr < 0:
            nr = 0x80000000
        self.hw_account_address_index = nr

        # bip32 path (utxo_src_mode 3)
        path = app_cache.get_value(CACHE_ITEM_HW_SRC_BIP32_PATH.replace('%NETWORK%', self.app_config.dash_network),
                                   dash_utils.get_default_bip32_path(self.app_config.dash_network), str)
        if dash_utils.validate_bip32_path(path):
            self.hw_src_bip32_path = path
        else:
            self.hw_src_bip32_path = dash_utils.get_default_bip32_path(self.app_config.dash_network)

        self.utxo_table_model.columns.restore_col_defs(CACHE_ITEM_UTXO_COLS)

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
                logging.exception('Cannot restore data from cache.')

    def save_cache_settings(self):
        app_cache.save_window_size(self)
        app_cache.set_value(CACHE_ITEM_MAIN_SPLITTER_SIZES, self.splitterMain.sizes())
        if self.initial_mn_sel is None:
            app_cache.set_value(CACHE_ITEM_UTXO_SOURCE_MODE, self.utxo_src_mode)
        app_cache.set_value(CACHE_ITEM_HW_ACCOUNT_BASE_PATH.replace('%NETWORK%', self.app_config.dash_network),
                            self.hw_account_base_bip32_path)
        app_cache.set_value(CACHE_ITEM_HW_ACCOUNT_ADDR_INDEX, self.hw_account_address_index)
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

        self.utxo_table_model.columns.save_col_defs(CACHE_ITEM_UTXO_COLS)

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
                logging.exception('Cannot save data to cache.')
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
        self.load_utxos()

    @pyqtSlot(int)
    def on_cbo_src_masternodes_currentIndexChanged(self, index):
        self.mn_src_index = index
        self.load_utxos()

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
                    self.load_utxos()
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
                    self.load_utxos()
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
        self.utxo_proxy.set_hide_collateral_utxos(checked)

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
            if not utxo['coinbase_locked'] and not utxo.get('spent_date'):
                if not sel.isSelected(index):
                    sel_modified = True
                    s.select(index, index)
        if sel_modified:
            sel.select(s, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    @pyqtSlot(bool)
    def on_btnUtxoViewColumns_clicked(self):
        self.utxo_table_model.columns.exec_columns_dialog(self)

    @pyqtSlot()
    def on_btnSend_clicked(self):
        """
        Sends funds to Dash address specified by user.
        """
        pass
        # amount, utxos = self.get_selected_utxos()
        # if len(utxos):
        #      try:
        #         if not self.main_ui.connect_hardware_wallet():
        #             return
        #     except HardwareWalletCancelException:
        #         return
        #
        #     bip32_to_address = {}  # for saving addresses read from HW by BIP32 path
        #     total_satoshis = 0
        #     coinbase_locked_exist = False
        #
        #     # verify if:
        #     #  - utxo is the masternode collateral transation
        #     #  - the utxo Dash (signing) address matches the hardware wallet address for a given path
        #     for utxo_idx, utxo in enumerate(utxos):
        #         total_satoshis += utxo['satoshis']
        #         logging.info(f'UTXO satosis: {utxo["satoshis"]}')
        #         if utxo.is_collateral:
        #             if self.queryDlg(
        #                     "Warning: you are going to transfer masternode's collateral (1000 Dash) transaction "
        #                     "output. Proceeding will result in broken masternode.\n\n"
        #                     "Do you really want to continue?",
        #                     buttons=QMessageBox.Yes | QMessageBox.Cancel,
        #                     default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
        #                 return
        #         if utxo['coinbase_locked']:
        #             coinbase_locked_exist = True
        #
        #         bip32_path = utxo.get('bip32_path', None)
        #         if not bip32_path:
        #             self.errorMsg('No BIP32 path for UTXO: %s. Cannot continue.' % utxo['txid'])
        #             return
        #
        #         addr_hw = bip32_to_address.get(bip32_path, None)
        #         if not addr_hw:
        #             addr_hw = get_address(self.main_ui.hw_session, bip32_path)
        #             bip32_to_address[bip32_path] = addr_hw
        #         if addr_hw != utxo['address']:
        #             self.errorMsg("<html style=\"font-weight:normal\">Dash address inconsistency between UTXO (%d) and HW path: %s.<br><br>"
        #                          "<b>HW address</b>: %s<br>"
        #                          "<b>UTXO address</b>: %s<br><br>"
        #                          "Cannot continue.</html>" %
        #                           (utxo_idx+1, bip32_path, addr_hw, utxo['address']))
        #             return
        #
        #     if coinbase_locked_exist:
        #         if self.queryDlg(
        #                 "Warning: you have selected at least one coinbase transaction without the required number of "
        #                 "confirmations (100). Your transaction will probably be rejected by the network.\n\n"
        #                 "Do you really want to continue?",
        #                 buttons=QMessageBox.Yes | QMessageBox.Cancel,
        #                 default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
        #             return
        #     try:
        #         dest_data = self.wdg_dest_adresses.get_tx_destination_data()
        #         if dest_data:
        #             total_satoshis_actual = 0
        #             for dd in dest_data:
        #                 total_satoshis_actual += dd[1]
        #                 logging.info(f'dest amount: {dd[1]}')
        #
        #             fee = self.wdg_dest_adresses.get_tx_fee()
        #             use_is = self.wdg_dest_adresses.get_use_instant_send()
        #             logging.info(f'fee: {fee}')
        #             if total_satoshis != total_satoshis_actual + fee:
        #                 logging.warning(f'total_satoshis ({total_satoshis}) != total_satoshis_real '
        #                                 f'({total_satoshis_actual}) + fee ({fee})')
        #                 logging.warning(f'total_satoshis_real + fee: {total_satoshis_actual + fee}')
        #
        #                 if abs(total_satoshis - total_satoshis_actual - fee) > 10:
        #                     raise Exception('Data validation failure')
        #
        #             try:
        #                 serialized_tx, amount_to_send = prepare_transfer_tx(
        #                     self.main_ui.hw_session, utxos, dest_data, fee, self.rawtransactions)
        #             except HardwareWalletCancelException:
        #                 # user cancelled the operations
        #                 hw_intf.cancel_hw_operation(self.main_ui.hw_session.hw_client)
        #                 return
        #             except Exception:
        #                 logging.exception('Exception when preparing the transaction.')
        #                 raise
        #
        #             tx_hex = serialized_tx.hex()
        #             logging.info('Raw signed transaction: ' + tx_hex)
        #             if len(tx_hex) > 90000:
        #                 self.errorMsg("Transaction's length exceeds 90000 bytes. Select less UTXOs and try again.")
        #             else:
        #                 tx_dlg = TransactionDlg(self, self.main_ui.config, self.dashd_intf, tx_hex, use_is)
        #                 if tx_dlg.exec_():
        #                     amount, sel_utxos = self.get_selected_utxos()
        #                     if sel_utxos:
        #                         # mark and uncheck all spent utxox
        #                         for utxo_idx, utxo in enumerate(sel_utxos):
        #                             utxo['spent_date'] = time.time()
        #
        #                         self.utxo_table_model.beginResetModel()
        #                         self.utxo_table_model.endResetModel()
        #     except Exception as e:
        #         logging.exception('Unknown error occurred.')
        #         self.errorMsg(str(e))
        # else:
        #     self.errorMsg('No UTXO to send.')

    @pyqtSlot()
    def on_btnClose_clicked(self):
        self.close()

    def on_listWalletAccounts_selectionChanged(self):
        """Selected BIP44 account changed. """
        idx = self.listWalletAccounts.currentIndex()
        if idx and idx.row() < len(self.account_list_model.accounts):
            self.hw_account_address_index = self.account_list_model.accounts[idx.row()].address_index
        else:
            self.hw_account_address_index = None

        self.utxo_table_model.clear_utxos()
        self.reset_utxos_view()
        self.load_data_event.set()

    def get_utxo_src_cfg_hash(self):
        hash = str({self.utxo_src_mode})
        if self.utxo_src_mode == 1:
            hash = hash + f'{self.mn_src_index}'
        elif self.utxo_src_mode == 2:
            hash = hash + f':{self.hw_account_base_bip32_path}:{self.hw_account_address_index}'
        elif self.utxo_src_mode == 3:
            hash = hash + ':' + str(self.hw_src_bip32_path)
        return hash

    def reset_accounts_view(self):
        def reset():
            self.account_list_model.beginResetModel()
            self.account_list_model.endResetModel()

            if len(self.account_list_model.accounts) > 0:
                if self.hw_account_address_index is None:
                    sel_acc = self.account_list_model.accounts[0]
                else:
                    sel_acc = self.account_list_model.account_by_address_index(self.hw_account_address_index)
                    if not sel_acc:
                        sel_acc = self.account_list_model.accounts[0]

                self.hw_account_address_index = sel_acc.address_index
                idx = self.account_list_model.accounts.index(sel_acc)
                old_state = self.listWalletAccounts.selectionModel().blockSignals(True)
                try:
                    self.listWalletAccounts.setCurrentIndex(self.account_list_model.index(idx))
                finally:
                    self.listWalletAccounts.selectionModel().blockSignals(old_state)
            else:
                self.hw_account_address_index = None

        WndUtils.call_in_main_thread(reset)

    def reset_utxos_view(self):
        def reset():
            self.utxo_table_model.beginResetModel()
            self.utxo_table_model.endResetModel()
        WndUtils.call_in_main_thread(reset)

    def connect_hw(self):
        def connect():
            if self.main_ui.connect_hardware_wallet():
                self.app_config.initialize_hw_encryption(self.main_ui.hw_session)
                return True
            return False
        return WndUtils.call_in_main_thread(connect)

    def update_data_view_thread(self, ctrl: CtrlObject):
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
                        if accounts_loaded:
                            self.account_list_model.clear_accounts()

                        # load bip44 account list
                        self.account_list_model.reset_modified()
                        for a in self.bip44_wallet.list_accounts():
                            self.account_list_model.add_account(a)

                        if self.account_list_model.modified:
                            self.account_list_model.sort_accounts()
                            self.reset_accounts_view()

                        accounts_loaded = True
                        last_hd_tree = self.hw_session.hd_tree_ident

                cur_utxo_source_hash = self.get_utxo_src_cfg_hash()
                if last_utxos_source_hash != cur_utxo_source_hash:
                    # reload the data
                    list_utxos = None
                    if self.utxo_src_mode == 2:
                        if self.hw_account_address_index is not None:
                            list_utxos = self.bip44_wallet.list_bip32_account_utxos(self.hw_account_address_index)

                    if len(self.utxo_table_model.utxos) > 0:
                        self.utxo_table_model.clear_utxos()

                    if list_utxos:
                        for utxo in list_utxos:
                            self.utxo_table_model.add_utxo(utxo)

                        last_utxos_source_hash = cur_utxo_source_hash

                    if len(self.utxo_table_model.utxos) > 0:
                        self.reset_utxos_view()

                if not self.fetch_transactions_thread_id and not fetch_txs_launched:
                    WndUtils.call_in_main_thread(WndUtils.run_thread, self, self.fetch_transactions_thread, ())
                    fetch_txs_launched = True

                self.load_data_event.wait(2)
                if self.load_data_event.is_set():
                    self.load_data_event.clear()

        except Exception as e:
            logging.exception('Exception occurred')
            WndUtils.errorMsg(str(e))

        finally:
            self.update_data_view_thread_id = None
        logging.info('Finishing update_data_view_thread')

    def fetch_transactions_thread(self, ctrl: CtrlObject):
        try:
            self.fetch_transactions_thread_id = threading.current_thread()
            last_txs_fetch_time = 0

            while not ctrl.finish and not self.finishing:
                if self.utxo_src_mode != 1:
                    connected = self.connect_hw()
                    if not connected:
                        return

                if last_txs_fetch_time == 0 or (time.time() - last_txs_fetch_time > FETCH_DATA_INTERVAL_SECONDS):
                    self.bip44_wallet.fetch_all_accounts_txs()
                    last_txs_fetch_time = int(time.time())

                    # fetching transactions may result in 'new' bip44 accounts with a non-zero 'received' balance
                    self.account_list_model.reset_modified()
                    for a in self.bip44_wallet.list_accounts():
                        self.account_list_model.add_account(a)

                    if self.account_list_model.modified:
                        self.account_list_model.sort_accounts()
                        self.reset_accounts_view()

                self.load_data_event.wait(2)
                if self.load_data_event.is_set():
                    self.load_data_event.clear()

        except Exception as e:
            logging.exception('Exception occurred')
            WndUtils.errorMsg(str(e))
        finally:
            self.fetch_transactions_thread_id = None
        logging.info('Finishing fetch_transactions_thread')

    def load_utxos2(self):
        new_utxos = []
        existing_utxos = []
        def apply_utxos(new_utxos: List[dict], existing_utxos: List[dict]):
            # check if the utxos source configuration changed while executing thread
            # if so, reexecute thread
            if self.finishing:
                return
            self.set_message('')

            if self.utxo_src_mode == 1:
                if self.mn_src_index is not None and self.mn_src_index < len(self.masternode_addresses) and \
                        self.mn_src_index >= 0:
                    msg = f'<b>Balance:</b> {self.sel_addresses_balance} Dash&nbsp;&nbsp;&nbsp;<b>Received:</b> {self.sel_addresses_received} Dash&nbsp;&nbsp;&nbsp;<b>Address:</b> {self.masternode_addresses[self.mn_src_index][0]}'
                    self.set_message_2(msg)
                else:
                    msg = f'<b>Balance:</b> {self.sel_addresses_balance} Dash&nbsp;&nbsp;&nbsp;<b>Received:</b> {self.sel_addresses_received} Dash'
                    self.set_message_2(msg)
            elif self.utxo_src_mode == 2:
                msg = f'<b>Balance:</b> {self.sel_addresses_balance} Dash&nbsp;&nbsp;&nbsp;<b>Received:</b> {self.sel_addresses_received} Dash'
                self.set_message_2(msg)
            elif self.utxo_src_mode in (1, 3):
                msg = f'<b>Balance:</b> {self.sel_addresses_balance} Dash&nbsp;&nbsp;&nbsp;<b>Received:</b> {self.sel_addresses_received} Dash&nbsp;&nbsp;&nbsp;<b>Address:</b> {self.hw_src_address}'
                self.set_message_2(msg)

            cur_utxos_src_hash = self.get_utxo_src_cfg_hash()
            if cur_utxos_src_hash == self.last_utxos_source_hash:
                try:
                    # remove all utxos that no longer exist in the netwotk
                    change_addresses: UtxoSrcAddrList = []
                    change_addresses_dict = {}

                    # for idx in reversed(range(len(self.utxos))):
                    #     u = self.utxos[idx]
                    #     if u not in existing_utxos:
                    #         # del self.utxos_dict[self.utxos[idx]['key']]
                    #         # del self.utxos[idx]
                    #         pass
                    #     else:
                    #         if not change_addresses_dict.get(u['address']):
                    #             change_addresses.append((u['address'], u['bip32_path']))
                    #             change_addresses_dict[u['address']] = 1

                    # add all new utxos
                    # for u in new_utxos:
                    #     # self.utxos.append(u)
                    #     # self.utxos_dict[u['key']] = u
                    #     if not change_addresses_dict.get(u['address']):
                    #         change_addresses.append((u['address'], u['bip32_path']))
                    #         change_addresses_dict[u['address']] = 1

                    # self.utxos.sort(key=itemgetter('height'), reverse=True)
                    # self.utxo_table_model.setUtxos(self.utxos, self.masternodes)
                    # self.wdg_dest_adresses.set_change_addresses(change_addresses)
                finally:
                    self.load_utxos_thread_ref = None
            else:
                self.last_utxos_source_hash = self.get_utxo_src_cfg_hash()

                new_utxos.clear()
                existing_utxos.clear()
                self.load_utxos_thread_ref = self.run_thread(
                    self, self.load_utxos_thread, (new_utxos, existing_utxos),
                    on_thread_finish=partial(apply_utxos, new_utxos, existing_utxos))

        try:
            if self.utxo_src_mode == 1 or \
                    (self.main_ui.connect_hardware_wallet() and
                     self.app_config.initialize_hw_encryption(self.main_ui.hw_session)):

                if self.last_utxos_source_hash != self.get_utxo_src_cfg_hash():
                    # clear current utxo data in grid
                    # self.utxos.clear()
                    # self.utxos_dict.clear()
                    # self.utxo_table_model.setUtxos(self.utxos, self.masternodes)
                    self.update_recipient_area_utxos()

                if not self.load_utxos_thread_ref:
                    # remember what input addresses configuration was when starting
                    self.last_utxos_source_hash = self.get_utxo_src_cfg_hash()

                    self.load_utxos_thread_ref = self.run_thread(
                        self, self.load_utxos_thread, (new_utxos, existing_utxos),
                        on_thread_finish=partial(apply_utxos, new_utxos, existing_utxos))
                else:
                    if self.last_utxos_source_hash != self.get_utxo_src_cfg_hash():
                        # source utxos configuration changed: stop the thread and execute again
                        self.load_utxos_thread_ref.stop()
        except HardwareWalletCancelException:
            pass

    def load_utxos(self, ctrl: CtrlObject = None):

        # if not self.finishing and not ctrl.finish:
        #     self.set_message(f'Reading unspent transaction outputs...')

        def list_utxos(thread_ctrl: CtrlObject):
            try:
                if self.utxo_src_mode == 1:
                    pass
                elif self.utxo_src_mode == 2:

                    for utxo in self.bip44_wallet.list_bip32_account_utxos(self.hw_account_address_index):
                        yield utxo

                elif self.utxo_src_mode == 3:
                    pass

            except Exception as e:
                logging.exception('Exception occurred')
                raise

        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:

            if self.main_ui.connect_hardware_wallet() and \
                self.app_config.initialize_hw_encryption(self.main_ui.hw_session):

                cnt1 = len(self.utxo_table_model.utxos)
                for utxo in list_utxos(ctrl):
                    self.utxo_table_model.add_utxo(utxo)
                cnt2 = len(self.utxo_table_model.utxos)

                row_count = cnt2 - cnt1
                if row_count:
                    # self.utxo_table_model.insertRows(cnt1, cnt2-cnt1)
                    self.utxo_table_model.beginResetModel()
                    self.utxo_table_model.endResetModel()

    def load_utxos_thread_old(self, ctrl: CtrlObject, new_utxos_out, existing_utxos_out):
        """
        Thread gets UTXOs from the network and returns the new items (not existing in the self.utxo list)
        :param ctrl:
        :param new_utxos_out: Here will be returned all the new UTXOs.
        :param existing_utxos_out: In this list will be returned all UTXOs which existed in the self.utxo list before
        """
        ADDRESS_CHUNK = 10
        if not self.finishing and not ctrl.finish:
            self.set_message(f'Reading unspent transaction outputs...')

        def get_addresses_to_scan(self, thread_ctrl: CtrlObject, addr_scan_ctrl: dict):
            """
            :param self:
            :param addr_scan_ctrl: (only for self.utxo_src_mode == 2) penultimate element of bip32 path to scan, used
                to switch sanning between normal and change addresses
            :return: yield List[Tuple[str (address), str (bip32 path)]]
            """
            try:
                if self.utxo_src_mode == 1:

                    if self.mn_src_index is not None:
                        if self.mn_src_index == len(self.masternode_addresses):
                            # show addresses of all masternodes
                            # prepare a unique list of mn addresses
                            tmp_addresses = []
                            addr_path_pairs = []
                            for x in self.masternode_addresses:
                                if x[0] not in tmp_addresses:
                                    tmp_addresses.append(x[0])
                                    addr_path_pairs.append((x[0], x[1]))

                            for chunk_nr in range(int(math.ceil(len(addr_path_pairs) / ADDRESS_CHUNK))):
                                if self.finishing or thread_ctrl.finish:
                                    return
                                yield [x for x in addr_path_pairs[
                                                  chunk_nr * ADDRESS_CHUNK : (chunk_nr + 1) * ADDRESS_CHUNK] if x[0] and x[1]]
                        elif self.mn_src_index < len(self.masternode_addresses) and self.mn_src_index >= 0:
                            if self.finishing or thread_ctrl.finish:
                                return
                            if self.masternode_addresses[self.mn_src_index][0] and \
                                self.masternode_addresses[self.mn_src_index][1]:
                                yield [self.masternode_addresses[self.mn_src_index]]

                elif self.utxo_src_mode == 2:
                    # hw wallet account: scan all addresses and change addresses for a specific account
                    # stop when a defined number of subsequent address has balance 0

                    addr_count = 0
                    addr_n = dash_utils.bip32_path_string_to_n(self.hw_account_base_bip32_path)
                    db_cur = self.db_intf.get_cursor()

                    try:
                        bip32_path_n = addr_n[:] + [self.hw_account_address_index + 0x80000000, 0, 0]
                        cur_addr_buf = []
                        last_level2_nr = addr_scan_ctrl.get('level2')
                        while True:
                            restart_iteration = False
                            for nr in range(1000):
                                if self.finishing or thread_ctrl.finish:
                                    return
                                if last_level2_nr != addr_scan_ctrl.get('level2'):
                                    last_level2_nr = addr_scan_ctrl.get('level2')
                                    restart_iteration = True
                                    break
                                bip32_path_n[-2] = addr_scan_ctrl.get('level2')
                                bip32_path_n[-1] = nr

                                cur_addr = hw_intf.get_address_ext(self.main_ui.hw_session, bip32_path_n, db_cur,
                                                                   self.app_config.hw_encrypt_string,
                                                                   self.app_config.hw_decrypt_string)

                                bip32_path = dash_utils.bip32_path_n_to_string(bip32_path_n)
                                cur_addr_buf.append((cur_addr, bip32_path))
                                addr_count += 1
                                if len(cur_addr_buf) >= ADDRESS_CHUNK:
                                    yield cur_addr_buf
                                    cur_addr_buf.clear()
                            if restart_iteration:
                                continue
                            if cur_addr_buf:
                                yield cur_addr_buf
                            break
                    finally:
                        if db_cur.connection.total_changes > 0:
                            self.db_intf.commit()
                        self.db_intf.release_cursor()

                elif self.utxo_src_mode == 3:

                    db_cur = self.db_intf.get_cursor()
                    try:
                        # address from a specific bip32 path
                        bip32_path_n = dash_utils.bip32_path_string_to_n(self.hw_src_bip32_path)
                        cur_addr = hw_intf.get_address_ext(self.main_ui.hw_session, bip32_path_n, db_cur,
                                                           self.app_config.hw_encrypt_string,
                                                           self.app_config.hw_decrypt_string)
                        self.hw_src_address = cur_addr
                        yield [(cur_addr, self.hw_src_bip32_path)]

                    finally:
                        if db_cur.connection.total_changes > 0:
                            self.db_intf.commit()
                        self.db_intf.release_cursor()

            except Exception as e:
                logging.exception('Exception occurred')
                raise

        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            tm_begin = time.time()
            try:
                cur_block_height = self.dashd_intf.getblockcount()
                self.sel_addresses_balance = 0
                self.sel_addresses_received = 0
                addr_count = 0
                utxos_count = 0
                addr_scan_ctrl = {'level2': 0}  # the one before last elemnt of bip32 paths to scan (0: normal address,
                                                # 1: change address

                for addr_path_chunk in get_addresses_to_scan(self, ctrl, addr_scan_ctrl):
                    try:
                        if self.finishing or ctrl.finish:
                            break

                        addr_chunk = []
                        addr_to_bip32 = {}
                        logging.debug(f'Got BIP32path-address pair chunk: {len(addr_path_chunk)}')
                        for a, p in addr_path_chunk:
                            addr_chunk.append(a)
                            addr_to_bip32[a] = p
                            logging.debug(f'Adding BIP32path-address pair for UTXO load: {p} - {a}')

                        balance = self.dashd_intf.getaddressbalance(addr_chunk)
                        if balance.get('received') == 0:
                            if addr_scan_ctrl['level2'] == 0:
                                addr_scan_ctrl['level2'] = 1  # switch to change addresses
                                continue
                            else:
                                break
                        else:
                            self.sel_addresses_received += balance.get('received')

                        if balance.get('balance') > 0:
                            self.sel_addresses_balance += balance.get('balance')
                            # get utxos for addresses
                            uxs = self.dashd_intf.getaddressutxos(addr_chunk)
                            utxos_count += len(uxs)

                            addr_count += len(addr_path_chunk)
                            for idx, utxo in enumerate(uxs):
                                if self.finishing or ctrl.finish:
                                    return

                                utxo_key = utxo['txid'] + '-' + str(utxo['outputIndex'])
                                # cached_utxo = self.utxos_dict.get(utxo_key)
                                if not cached_utxo:
                                    blockhash = self.dashd_intf.getblockhash(utxo.get('height'))
                                    bh = self.dashd_intf.getblockheader(blockhash)
                                    utxo['key'] = utxo_key
                                    utxo['time_str'] = app_utils.to_string(datetime.datetime.fromtimestamp(bh['time']))
                                    utxo['confirmations'] = cur_block_height - utxo.get('height') + 1
                                    utxo['coinbase_locked'] = False
                                    utxo['bip32_path'] = addr_to_bip32.get(utxo['address'])
                                    if not utxo['bip32_path']:
                                        logging.warning(f'BIP32 path not found for address: {utxo["address"]}')

                                    try:
                                        # verify whether it's a coinbase transaction and if so,if it has
                                        # enough confirmations to spend
                                        rawtx = self.dashd_intf.getrawtransaction(utxo.get('txid'), 1)
                                        if rawtx:
                                            self.rawtransactions[utxo.get('txid')] = rawtx['hex']
                                            vin = rawtx.get('vin')
                                            if len(vin) == 1 and vin[0].get('coinbase') and utxo['confirmations'] < 100:
                                                utxo['coinbase_locked'] = True
                                    except Exception:
                                        logging.exception('Error while verifying transaction coinbase')

                                    new_utxos_out.append(utxo)
                                else:
                                    cached_utxo['confirmations'] = cur_block_height - utxo.get('height') + 1
                                    if cached_utxo['coinbase_locked']:
                                        cached_utxo['coinbase_locked'] = (cached_utxo['confirmations'] < 100)
                                    existing_utxos_out.append(cached_utxo)

                            if not self.finishing and not ctrl.finish:
                                self.set_message(f'Reading unspent transaction outputs... '
                                                 f'Address count: {addr_count}, UTXOs count: {utxos_count}')
                    except Exception as e:
                        logging.exception('Exception occurred')
                        raise

                self.sel_addresses_balance = round(self.sel_addresses_balance / 1e8, 8)
                self.sel_addresses_received = round(self.sel_addresses_received / 1e8, 8)

                tm_diff = time.time() - tm_begin
                logging.info(f'load_utxos_thread exec time: {tm_diff} s')
            except DashdIndexException as e:
                self.errorMsg(str(e))

            except Exception as e:
                self.errorMsg('Error occurred while calling getaddressutxos method: ' + str(e))

    @pyqtSlot()
    def on_btnLoadTransactions_clicked(self):
        self.load_utxos()

    def on_edtSourceBip32Path_returnPressed(self):
        self.on_btnLoadTransactions_clicked()

    def get_selected_utxos(self) -> Tuple[int, List[Dict]]:
        """
        :return: Tuple[int <total amount selected>, List[Dict] <list of the selected utxos>]
        """
        sel = self.utxoTableView.selectionModel()
        utxos = []
        rows = sel.selectedRows()
        amount = 0
        for row in rows:
            source_row = self.utxo_proxy.mapToSource(row)
            row_idx = source_row.row()
            if 0 <= row_idx < len(self.utxo_table_model.utxos):
                utxo = self.utxo_table_model.utxos[row_idx]
                utxos.append(utxo)
                amount += utxo.satoshis

        return amount, utxos

    def update_recipient_area_utxos(self):
        total_amount, utxos = self.get_selected_utxos()
        total_amount = round(total_amount / 1e8, 8)
        self.wdg_dest_adresses.set_input_amount(total_amount, len(utxos))

    def on_utxoTableView_selectionChanged(self, selected, deselected):
        self.update_recipient_area_utxos()
