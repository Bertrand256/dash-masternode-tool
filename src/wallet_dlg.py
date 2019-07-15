#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
import datetime
import os

import base64
import hashlib
import sys

import simplejson
import threading
import time
import logging
from functools import partial
from typing import Tuple, List, Optional, Dict, Generator, Callable
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSlot, QStringListModel, QItemSelectionModel, \
    QItemSelection, QSortFilterProxyModel, QAbstractItemModel, QModelIndex, QObject, QAbstractListModel, QPoint, QRect
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QDialog, QTableView, QHeaderView, QMessageBox, QSplitter, QVBoxLayout, QPushButton, \
    QItemDelegate, QLineEdit, QCompleter, QInputDialog, QLayout, QAction, QAbstractItemView, QStatusBar, QCheckBox, \
    QApplication
from cryptography.fernet import Fernet
import app_cache
import app_utils
import dash_utils
import hw_intf
from app_defs import HWType, DEBUG_MODE
from bip44_wallet import Bip44Wallet, Bip44Entry, BreakFetchTransactionsException, SwitchedHDIdentityException
from common import CancelException
from sign_message_dlg import SignMessageDlg
from ui.ui_wallet_dlg_options1 import Ui_WdgOptions1
from ui.ui_wdg_wallet_txes_filter import Ui_WdgWalletTxesFilter
from wallet_common import UtxoType, Bip44AccountType, Bip44AddressType, TxOutputType, TxType
from dashd_intf import DashdInterface, DashdIndexException
from db_intf import DBCache
from hw_common import HwSessionInfo, HWNotConnectedException
from thread_fun_dlg import WorkerThread, CtrlObject
from wallet_data_models import UtxoTableModel, MnAddressTableModel, AccountListModel, MnAddressItem, \
    TransactionTableModel, FILTER_AND, FILTER_OR, FILTER_OPER_EQ, FILTER_OPER_GTEQ, FILTER_OPER_LTEQ
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate, SpinnerWidget, HyperlinkItemDelegate, \
    LineEditTableCellDelegate
from ui import ui_wallet_dlg
from wallet_widgets import SendFundsDestination, WalletMnItemDelegate, WalletAccountItemDelegate, \
    TxSenderRecipientItemDelegate
from transaction_dlg import TransactionDlg


CACHE_ITEM_UTXO_SOURCE_MODE = 'WalletDlg_UtxoSourceMode'
CACHE_ITEM_HW_ACCOUNT_BASE_PATH = 'WalletDlg_UtxoSrc_HwAccountBasePath_%NETWORK%'
CACHE_ITEM_HW_SEL_ACCOUNT_ADDR_ID = 'WalletDlg_UtxoSrc_HwAccountId'
CACHE_ITEM_HW_SRC_BIP32_PATH = 'WalletDlg_UtxoSrc_HwBip32Path_%NETWORK%'
CACHE_ITEM_UTXO_SRC_MASTRNODE = 'WalletDlg_UtxoSrc_Masternode_%NETWORK%'
CACHE_ITEM_UTXO_COLS = 'WalletDlg_UtxoColumns'
CACHE_ITEM_TXS_COLS = 'WalletDlg_TxsColumns'
CACHE_ITEM_LAST_RECIPIENTS = 'WalletDlg_LastRecipients_%NETWORK%'
CACHE_ITEM_MAIN_SPLITTER_SIZES = 'WalletDlg_MainSplitterSizes'
CACHE_ITEM_SHOW_ACCOUNT_ADDRESSES = 'WalletDlg_ShowAccountAddresses'
CACHE_ITEM_SHOW_ZERO_BALANCE_ADDRESSES = 'WalletDlg_ShowZeroBalanceAddresses'
CACHE_ITEM_SHOW_NOT_USED_ADDRESSES = 'WalletDlg_ShowNotUsedAddresses'

FETCH_DATA_INTERVAL_SECONDS = 60
MAIN_VIEW_BIP44_ACCOUNTS = 1
MAIN_VIEW_MASTERNODE_LIST = 2


log = logging.getLogger('dmt.wallet_dlg')


class WalletDlg(QDialog, ui_wallet_dlg.Ui_WalletDlg, WndUtils):
    error_signal = QtCore.pyqtSignal(str)
    thread_finished = QtCore.pyqtSignal()

    def __init__(self, main_ui, initial_mn_sel: int):
        """
        :param initial_mn_sel:
          if the value is from 0 to len(masternodes), show utxos for the masternode
            having the 'initial_mn' index in self.app_config.mastrnodes
          if the value is -1, show utxo for all masternodes
          if the value is None, show the default utxo source type
        """
        QDialog.__init__(self, parent=main_ui)
        WndUtils.__init__(self, main_ui.app_config)

        self.main_ui = main_ui
        self.hw_session: HwSessionInfo = self.main_ui.hw_session
        self.hw_connection_established = False
        self.masternodes = main_ui.app_config.masternodes
        self.masternode_addresses: List[Tuple[str, str]] = []  #  Tuple: address, bip32 path
        for idx, mn in enumerate(self.masternodes):
            self.masternode_addresses.append((mn.collateralAddress.strip(), mn.collateralBip32Path.strip()))
            log.debug(f'WalletDlg initial_mn_sel({idx}) addr - path: {mn.collateralAddress}-{mn.collateralBip32Path}')

        self.dashd_intf: DashdInterface = main_ui.dashd_intf
        self.db_intf: DBCache = main_ui.app_config.db_intf
        self.bip44_wallet = Bip44Wallet(self.app_config.hw_coin_name, self.hw_session, self.db_intf, self.dashd_intf,
                                        self.app_config.dash_network)
        self.bip44_wallet.on_account_added_callback = self.on_bip44_account_added
        self.bip44_wallet.on_account_data_changed_callback = self.on_bip44_account_changed
        self.bip44_wallet.on_account_address_added_callback = self.on_bip44_account_address_added
        self.bip44_wallet.on_address_data_changed_callback = self.on_bip44_account_address_changed

        self.utxo_table_model = UtxoTableModel(self, self.masternodes, main_ui.app_config.get_block_explorer_tx())
        self.mn_model = MnAddressTableModel(self, self.masternodes, self.bip44_wallet)
        self.tx_table_model = TransactionTableModel(self, main_ui.app_config.get_block_explorer_tx())

        self.bip44_wallet.blockheight_changed.connect(self.tx_table_model.set_blockheight)

        self.finishing = False  # true if this window is closing
        self.data_thread_ref: Optional[WorkerThread] = None
        self.display_thread_ref: Optional[WorkerThread] = None
        self.last_txs_fetch_time = 0
        self.allow_fetch_transactions = True
        self.enable_synch_with_main_thread = True  # if False threads cannot synchronize with the main thread
        self.update_data_view_thread_ref: Optional[WorkerThread] = None
        self.initial_mn_sel = initial_mn_sel

        # for self.utxo_src_mode == 1
        self.hw_account_base_bip32_path = ''
        self.hw_selected_account_id = None  # bip44 account address id
        self.hw_selected_address_id = None  # if the account's address was selected (the index in the Bip44AccountType.addresses list)

        # 1: wallet account (the account number and base bip32 path are selected from the GUI by a user)
        # 2: masternode collateral address
        self.utxo_src_mode: Optional[int] = None
        self.cur_utxo_src_hash = None  # hash of the currently selected utxo source mode
        self.cur_hd_tree_id = None
        self.cur_hd_tree_ident = None

        # for self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST
        self.selected_mns: List[MnAddressItem] = []

        self.sel_addresses_balance = 0.0
        self.sel_addresses_received = 0.0

        self.org_message = ''
        self.grid_column_widths = []
        self.recipient_list_from_cache = []
        self.tab_transactions_model = None

        self.account_list_model = AccountListModel(self)
        self.data_thread_event = threading.Event()
        self.display_thread_event = threading.Event()

        self.accounts_view_show_individual_addresses = False
        self.accounts_view_show_zero_balance_addesses = False
        self.accounts_view_show_not_used_addresses = False
        self.wdg_loading_txs_animation = None

        # display thread data:
        self.dt_last_addr_selection_hash_for_utxo = ''
        self.dt_last_addr_selection_hash_for_txes = ''
        self.dt_last_hd_tree_id = None

        self.setupUi()

    def setupUi(self):
        ui_wallet_dlg.Ui_WalletDlg.setupUi(self, self)
        self.setWindowTitle('Transfer funds')
        self.closeEvent = self.closeEvent
        self.chbHideCollateralTx.setChecked(True)
        self.setIcon(self.btnCheckAll, 'check.png')
        self.setIcon(self.btnUncheckAll, 'uncheck.png')
        self.restore_cache_settings()
        self.splitterMain.setStretchFactor(0, 0)
        self.splitterMain.setStretchFactor(1, 1)

        self.utxo_table_model.set_hide_collateral_utxos(True)
        self.utxoTableView.setSortingEnabled(True)
        self.utxoTableView.setItemDelegate(ReadOnlyTableCellDelegate(self.utxoTableView))
        self.utxoTableView.verticalHeader().setDefaultSectionSize(
            self.utxoTableView.verticalHeader().fontMetrics().height() + 4)
        # Display a sort indicator on the header - initial sorting (by the number of confirmations) will be performed
        # during the selection data from cache in an appropriate order, that is faster than sorting in a table view
        self.utxoTableView.horizontalHeader().setSortIndicator(
            self.utxo_table_model.col_index_by_name('confirmations'), Qt.AscendingOrder)
        self.utxo_table_model.set_view(self.utxoTableView)
        
        self.txesTableView.setSortingEnabled(True)
        self.txesTableView.setItemDelegate(ReadOnlyTableCellDelegate(self.txesTableView))
        self.txesTableView.verticalHeader().setDefaultSectionSize(
            self.txesTableView.verticalHeader().fontMetrics().height() + 4)
        self.txesTableView.horizontalHeader().setSortIndicator(
            self.tx_table_model.col_index_by_name('confirmations'), Qt.AscendingOrder)
        self.txesTableView.setItemDelegateForColumn(self.tx_table_model.col_index_by_name('recipient'),
                                                    TxSenderRecipientItemDelegate(self.txesTableView, is_sender=False))
        self.txesTableView.setItemDelegateForColumn(self.tx_table_model.col_index_by_name('senders'),
                                                    TxSenderRecipientItemDelegate(self.txesTableView, is_sender=True))
        self.txesTableView.setItemDelegateForColumn(
            self.tx_table_model.col_index_by_name('label'),
            LineEditTableCellDelegate(self.txesTableView, self.app_config.get_app_img_dir()))
        self.tx_table_model.set_view(self.txesTableView)

        self.account_list_model.set_view(self.accountsListView)

        self.mn_model.set_view(self.mnListView)
        self.mnListView.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.mn_view_restore_selection()

        self.chbHideCollateralTx.toggled.connect(self.chbHideCollateralTxToggled)

        self.cboAddressSourceMode.blockSignals(True)
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            self.swAddressSource.setCurrentIndex(0)
            self.cboAddressSourceMode.setCurrentIndex(0)
        elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
            self.swAddressSource.setCurrentIndex(1)
            self.cboAddressSourceMode.setCurrentIndex(1)
        else:
            log.warning(f'Invalid value of self.utxo_src_mode: {self.utxo_src_mode}')
        self.cboAddressSourceMode.blockSignals(False)

        self.set_message("")
        self.wdg_dest_adresses = SendFundsDestination(self.dest_widget, self, self.main_ui.app_config,
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

        self.utxoTableView.selectionModel().selectionChanged.connect(self.on_utxoTableView_selectionChanged)
        self.accountsListView.selectionModel().selectionChanged.connect(self.on_accountsListView_selectionChanged)
        self.accountsListView.setItemDelegateForColumn(0, WalletAccountItemDelegate(self.accountsListView))
        self.mnListView.selectionModel().selectionChanged.connect(self.on_viewMasternodes_selectionChanged)
        self.mnListView.setItemDelegateForColumn(0, WalletMnItemDelegate(self.mnListView))

        # setup the options widget of the accounts list panel
        l = self.pageAccountsListView.layout()
        self.wdg_accounts_view_options = QtWidgets.QWidget()
        self.ui_accounts_view_options = Ui_WdgOptions1()
        self.ui_accounts_view_options.setupUi(self.wdg_accounts_view_options)
        self.ui_accounts_view_options.btnApply.clicked.connect(self.on_btnAccountsViewOptionsApply_clicked)
        l.insertWidget(0, self.wdg_accounts_view_options)
        self.wdg_accounts_view_options.hide()

        # setup the filter widget of the transactions tab
        l  = self.tabTransactions.layout()
        self.wdg_txes_filter = QtWidgets.QWidget()
        self.ui_txes_filter = Ui_WdgWalletTxesFilter()
        self.ui_txes_filter.setupUi(self.wdg_txes_filter)
        l.insertWidget(1, self.wdg_txes_filter)
        self.ui_txes_filter.btnApply.clicked.connect(self.apply_txes_filter)

        self.setIcon(self.btnSetHwIdentityLabel, 'label@16px.png')
        self.setIcon(self.btnPurgeHwIdentity, 'delete@16px.png')
        self.setIcon(self.btnFetchTransactions, 'autorenew@16px.png')
        self.setIcon(self.btnViewModeOptions, 'settings@16px.png')
        self.setIcon(self.btnTxesTabFilter, 'filter@16px.png')

        # context menu actions:
        # show address on hardware wallet
        self.act_show_address_on_hw = QAction('Show address', self)
        self.act_show_address_on_hw.triggered.connect(self.on_show_address_on_hw_triggered)
        self.main_ui.setIcon(self.act_show_address_on_hw, 'eye@16px.png')
        self.accountsListView.addAction(self.act_show_address_on_hw)
        # copy address to clipboard
        self.act_copy_address = QAction('Copy address', self)
        self.act_copy_address.triggered.connect(self.on_act_copy_address_triggered)
        self.main_ui.setIcon(self.act_copy_address, 'content-copy@16px.png')
        self.accountsListView.addAction(self.act_copy_address)
        # sign message
        self.act_sign_message_for_address = QAction('Sign message', self)
        self.act_sign_message_for_address.triggered.connect(self.on_act_sign_message_for_address_triggered)
        self.main_ui.setIcon(self.act_sign_message_for_address, 'sign.png')
        self.accountsListView.addAction(self.act_sign_message_for_address)
        # set label for address/account:
        self.act_set_entry_label = QAction('Set label', self)
        self.act_set_entry_label.triggered.connect(self.on_act_set_entry_label_triggered)
        self.main_ui.setIcon(self.act_set_entry_label, 'label@16px.png')
        self.accountsListView.addAction(self.act_set_entry_label)
        # show next fresh(unused) address
        self.act_show_account_next_fresh_address = QAction('Reveal next fresh address', self)
        self.act_show_account_next_fresh_address.triggered.connect(self.on_show_account_next_fresh_address_triggered)
        self.accountsListView.addAction(self.act_show_account_next_fresh_address)
        # show account
        self.act_show_account = QAction('Add account', self)
        self.act_show_account.triggered.connect(self.on_act_show_account_triggered)
        self.main_ui.setIcon(self.act_show_account, 'eye@16px.png', force_color_change='#0066cc')
        self.accountsListView.addAction(self.act_show_account)
        # show account
        self.act_hide_account = QAction('Hide account', self)
        self.act_hide_account.triggered.connect(self.on_act_hide_account_triggered)
        self.main_ui.setIcon(self.act_hide_account, 'eye-crossed-out@16px.png', force_color_change='#0066cc')
        self.accountsListView.addAction(self.act_hide_account)

        # for testing:
        # self.act_delete_account_data = QAction('Clear account data in cache', self)
        # self.act_delete_account_data.triggered.connect(self.on_delete_account_triggered)
        # self.accountsListView.addAction(self.act_delete_account_data)
        #
        # self.act_delete_address_data = QAction('Clear address data in cache', self)
        # self.act_delete_address_data.triggered.connect(self.on_delete_address_triggered)
        # self.accountsListView.addAction(self.act_delete_address_data)
        #
        # self.act_delete_address_data1 = QAction('Clear address data in cache', self)
        # self.act_delete_address_data1.triggered.connect(self.on_delete_address_triggered)
        # self.mnListView.addAction(self.act_delete_address_data1)
        # for testing, end

        self.update_ui_show_individual_addresses()
        self.update_ui_view_mode_options()
        self.address_souce_update_ui()
        self.prepare_txes_filter()
        self.show_hide_txes_filter()
        self.update_context_actions()

        self.hw_session.sig_hw_connected.connect(self.on_connect_hw)
        self.hw_session.sig_hw_disconnected.connect(self.on_disconnect_hw)
        if self.hw_session.hw_type is not None and self.hw_session.hw_client is not None:
            # hw is initially connected
            self.on_connect_hw()

        self.start_threads()

    def closeEvent(self, event):
        self.finishing = True
        self.allow_fetch_transactions = False
        self.enable_synch_with_main_thread = False
        self.stop_threads()
        self.save_cache_settings()

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)

        # main spliiter size
        self.splitterMain.setSizes(app_cache.get_value(CACHE_ITEM_MAIN_SPLITTER_SIZES, [100, 600], list))

        mode = app_cache.get_value(CACHE_ITEM_UTXO_SOURCE_MODE, MAIN_VIEW_BIP44_ACCOUNTS, int)
        if mode in (MAIN_VIEW_BIP44_ACCOUNTS, MAIN_VIEW_MASTERNODE_LIST):
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

        self.utxo_table_model.restore_col_defs(CACHE_ITEM_UTXO_COLS)
        self.tx_table_model.restore_col_defs(CACHE_ITEM_TXS_COLS)

        # restore the selected masternodes
        if self.initial_mn_sel is None:
            sel_hashes = app_cache.get_value(
                CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network), [], list)
            for hash in sel_hashes:
                mni = self.mn_model.get_mn_by_addr_hash(hash)
                if mni and mni not in self.selected_mns:
                    self.selected_mns.append(mni)
        else:
            try:
                mni = self.mn_model.data_by_row_index(self.initial_mn_sel)
                self.selected_mns.append(mni)
            except Exception:
                pass

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

        self.accounts_view_show_individual_addresses = app_cache.get_value(CACHE_ITEM_SHOW_ACCOUNT_ADDRESSES, True,
                                                                           bool)
        self.accounts_view_show_zero_balance_addesses = app_cache.get_value(CACHE_ITEM_SHOW_ZERO_BALANCE_ADDRESSES,
                                                                            False, bool)
        self.accounts_view_show_not_used_addresses = app_cache.get_value(CACHE_ITEM_SHOW_NOT_USED_ADDRESSES,
                                                                        False, bool)
        self.account_list_model.show_zero_balance_addresses = self.accounts_view_show_zero_balance_addesses
        self.account_list_model.show_not_used_addresses = self.accounts_view_show_not_used_addresses

    def save_cache_settings(self):
        app_cache.save_window_size(self)
        app_cache.set_value(CACHE_ITEM_MAIN_SPLITTER_SIZES, self.splitterMain.sizes())
        app_cache.set_value(CACHE_ITEM_UTXO_SOURCE_MODE, self.utxo_src_mode)
        app_cache.set_value(CACHE_ITEM_HW_ACCOUNT_BASE_PATH.replace('%NETWORK%', self.app_config.dash_network),
                            self.hw_account_base_bip32_path)
        app_cache.set_value(CACHE_ITEM_HW_SEL_ACCOUNT_ADDR_ID, self.hw_selected_account_id)

        # save the selected masternodes; as a mn identifier we choose the hashed masternode address
        sel_hashes = []
        for mna in self.selected_mns:
            if mna.address.address:
                h = hashlib.sha256(bytes(mna.address.address, 'utf-8')).hexdigest()
                sel_hashes.append(h)
        app_cache.set_value(CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network),
                            sel_hashes)

        self.utxo_table_model.save_col_defs(CACHE_ITEM_UTXO_COLS)
        self.tx_table_model.save_col_defs(CACHE_ITEM_TXS_COLS)

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
        app_cache.set_value(CACHE_ITEM_SHOW_ACCOUNT_ADDRESSES, self.accounts_view_show_individual_addresses)
        app_cache.set_value(CACHE_ITEM_SHOW_ZERO_BALANCE_ADDRESSES, self.accounts_view_show_zero_balance_addesses)
        app_cache.set_value(CACHE_ITEM_SHOW_NOT_USED_ADDRESSES, self.accounts_view_show_not_used_addresses)

    def stop_threads(self):
        self.finishing = True
        self.data_thread_event.set()
        self.display_thread_event.set()
        if self.data_thread_ref:
            self.data_thread_ref.wait(5000)
        if self.display_thread_ref:
            self.display_thread_ref.wait(5000)

    def start_threads(self):
        self.finishing = False
        self.update_hw_info()
        if not self.display_thread_ref:
            self.display_thread_ref = self.run_thread(self, self.display_thread, ())
        if not self.data_thread_ref:
            self.data_thread_ref = self.run_thread(self, self.data_thread, ())

    def mn_view_restore_selection(self):
        """Restores selection in the masternodes view (on the left side) using values from the self.selected_mns list.
        """
        sel = QItemSelection()
        for mni in self.selected_mns:
            row_idx = self.mn_model.get_mn_index(mni)
            if row_idx is not None:
                source_row_idx = self.mn_model.index(row_idx, 0)
                dest_index = self.mn_model.mapFromSource(source_row_idx)
                sel.select(dest_index, dest_index)
        self.mnListView.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.update_details_tab()

    def address_souce_update_ui(self):
        self.btnViewModeOptions.setEnabled(True if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS else False)

    def hw_call_wrapper(self, func):
        def call(*args, **kwargs):
            try:
                ret = func(*args, **kwargs)
            except HWNotConnectedException:
                self.on_disconnect_hw()
                raise
            return ret

        return call

    @pyqtSlot(int)
    def on_cboAddressSourceMode_currentIndexChanged(self, index):
        self.swAddressSource.setCurrentIndex(index)

        with self.utxo_table_model:
            self.utxo_table_model.beginResetModel()
            self.utxo_table_model.clear_utxos()
            self.utxo_table_model.endResetModel()

        with self.tx_table_model:
            self.tx_table_model.beginResetModel()
            self.tx_table_model.clear_txes()
            self.tx_table_model.endResetModel()

        if index == 0:
            self.utxo_src_mode = MAIN_VIEW_BIP44_ACCOUNTS
            self.connect_hw()
        elif index == 1:
            self.utxo_src_mode = MAIN_VIEW_MASTERNODE_LIST
        else:
            raise Exception('Invalid index.')
        self.on_utxo_src_hash_changed()
        self.display_thread_event.set()
        self.update_ui_view_mode_options()
        self.address_souce_update_ui()

    def on_dest_addresses_resized(self):
        self.splitter.setSizes([1, self.wdg_dest_adresses.sizeHint().height()])

    def set_message(self, message):
        def set_msg(message):
            if not message:
                self.lbl_message.setVisible(False)
            else:
                self.lbl_message.setVisible(True)
                self.lbl_message.setText(message)

        if threading.current_thread() != threading.main_thread():
            if self.enable_synch_with_main_thread:
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
        sel_modified = False
        s = QItemSelection()
        with self.utxo_table_model:
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

    @pyqtSlot(bool)
    def on_btnTxesViewColumns_clicked(self):
        self.tx_table_model.exec_columns_dialog(self)

    @pyqtSlot()
    def on_btnSend_clicked(self):
        """
        Sends funds to Dash address specified by user.
        """
        try:
            self.allow_fetch_transactions = False
            self.enable_synch_with_main_thread = False

            amount, tx_inputs = self.get_selected_utxos()
            if len(tx_inputs):
                try:
                    connected = self.connect_hw()
                    if not connected:
                        return
                except CancelException:
                    return

                bip32_to_address = {}  # for saving addresses read from HW by BIP32 path
                total_satoshis_inputs = 0
                coinbase_locked_exist = False

                # verify if:
                #  - utxo is the masternode collateral transation
                #  - the utxo Dash (signing) address matches the hardware wallet address for a given path
                for utxo_idx, utxo in enumerate(tx_inputs):
                    total_satoshis_inputs += utxo.satoshis
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
                        addr_hw = self.hw_call_wrapper(hw_intf.get_address)(self.main_ui.hw_session, bip32_path)
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
                    tx_outputs = self.wdg_dest_adresses.get_tx_destination_data()
                    if tx_outputs:
                        total_satoshis_outputs = 0
                        for dd in tx_outputs:
                            total_satoshis_outputs += dd.satoshis
                            dd.address_ref = self.bip44_wallet.get_address_item(dd.address, False)

                        fee = self.wdg_dest_adresses.get_tx_fee()
                        change = round(total_satoshis_inputs - total_satoshis_outputs - fee, 0)
                        if change:
                            if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                                # find first unused address of the change for the current account
                                acc = None
                                if self.hw_selected_account_id:
                                    acc = self.account_list_model.account_by_id(self.hw_selected_account_id)
                                if not acc:
                                    raise Exception('Cannot find the current account')
                                else:
                                    change_addr = self.bip44_wallet.find_xpub_first_unused_address(acc, 1)
                                    if not change_addr:
                                        raise Exception('Cannot find the account change address')
                            elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
                                # in the masternode view, address for the change will be taken fron the first input
                                change_addr = self.bip44_wallet.get_address_item(tx_inputs[0].address, True)
                            else:
                                raise Exception('Implement')

                            if change_addr:
                                out = TxOutputType()
                                out.address = change_addr.address
                                out.bip32_path = change_addr.bip32_path
                                out.satoshis = change
                                out.address_ref = change_addr
                                tx_outputs.append(out)

                        use_is = self.wdg_dest_adresses.get_use_instant_send()

                        try:
                            serialized_tx, amount_to_send = self.hw_call_wrapper(hw_intf.sign_tx)\
                                (self.main_ui.hw_session, tx_inputs, tx_outputs, fee)
                        except HWNotConnectedException:
                            raise
                        except CancelException:
                            # user cancelled the operations
                            return
                        except Exception:
                            log.exception('Exception when preparing the transaction.')
                            raise

                        tx_hex = serialized_tx.hex()
                        log.info('Raw signed transaction: ' + tx_hex)
                        if len(tx_hex) > 90000:
                            self.errorMsg("Transaction's length exceeds 90000 bytes. Select less UTXOs and try again.")
                        else:
                            after_send_tx_fun = partial(self.process_after_sending_transaction, tx_inputs, tx_outputs)
                            tx_dlg = TransactionDlg(self, self.main_ui.app_config, self.dashd_intf, tx_hex, use_is,
                                                    tx_inputs, tx_outputs, self.cur_hd_tree_id, self.hw_session,
                                                    after_send_tx_fun, fn_show_address_on_hw=self.show_address_on_hw)
                            tx_dlg.exec_()
                except Exception as e:
                    log.exception('Unknown error occurred.')
                    self.errorMsg(str(e))
            else:
                self.errorMsg('No UTXO to send.')
        finally:
            self.allow_fetch_transactions = True
            self.enable_synch_with_main_thread = True

    def process_after_sending_transaction(self, inputs: List[UtxoType], outputs: List[TxOutputType], tx_json: Dict):
        def break_call():
            # It won't be called since the upper method is called from within the main thread, but we need this
            # to make it compatible with the argument list of self.call_fun_monitor_txs
            return self.finishing

        fun_to_call = partial(self.bip44_wallet.register_spending_transaction, inputs, outputs, tx_json)

        try:
            self.allow_fetch_transactions = False
            self.enable_synch_with_main_thread = False

            self.call_fun_monitor_txs(fun_to_call, break_call)
        finally:
            self.allow_fetch_transactions = True
            self.enable_synch_with_main_thread = True

    @pyqtSlot()
    def on_btnClose_clicked(self):
        self.close()

    def reflect_ui_account_selection(self):
        view_index = self.accountsListView.currentIndex()
        if view_index and view_index.isValid():
            index = self.account_list_model.mapToSource(view_index)
            data = index.internalPointer()  # data can by of Bip44AccountType or Bip44AddressType
            if isinstance(data, Bip44AccountType):
                self.hw_selected_address_id = None
                if index and index.row() < len(self.account_list_model.accounts):
                    self.hw_selected_account_id = self.account_list_model.accounts[index.row()].id
                else:
                    self.hw_selected_account_id = None
            elif isinstance(data, Bip44AddressType):
                self.hw_selected_account_id = data.bip44_account.id
                self.hw_selected_address_id = data.id
            else:
                return
        else:
            self.hw_selected_account_id = None
            self.hw_selected_address_id = None

        self.update_context_actions()
        self.update_details_tab()
        self.on_utxo_src_hash_changed()

    def reflect_data_account_selection(self):
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            if self.hw_selected_account_id is not None and self.cur_hd_tree_id:
                if self.hw_selected_address_id is None:
                    # account selected
                    with self.account_list_model:
                        idx = self.account_list_model.account_index_by_id(self.hw_selected_account_id)
                        if idx is not None:
                            index = self.account_list_model.index(idx, 0)
                            self.accountsListView.setCurrentIndex(index)

    def on_accountsListView_selectionChanged(self):
        """Selected BIP44 account or address changed. """
        self.reflect_ui_account_selection()
        self.display_thread_event.set()

    def on_viewMasternodes_selectionChanged(self):
        with self.mn_model:
            self.selected_mns.clear()
            for mni in self.mn_model.selected_data_items():
                if mni.address:
                    self.selected_mns.append(mni)
            self.on_utxo_src_hash_changed()
            self.display_thread_event.set()
            self.update_details_tab()

    def update_context_actions(self):

        if self.hw_connection_established and self.hw_selected_address_id is not None:
            visible = True
        else:
            visible = False

        self.act_show_address_on_hw.setVisible(visible)
        self.act_copy_address.setVisible(visible)
        self.act_sign_message_for_address.setVisible(visible)

        if self.hw_connection_established and (self.hw_selected_account_id is not None or
                                               self.hw_selected_address_id is not None):
            enabled = True
        else:
            enabled = False
        self.act_set_entry_label.setVisible(enabled)

        self.act_hide_account.setVisible(self.hw_connection_established and self.hw_selected_account_id is not None
                                         and self.hw_selected_address_id is None)
        self.act_show_account_next_fresh_address.setVisible(self.hw_connection_established and
                                                            self.hw_selected_account_id is not None)

        self.act_show_account.setVisible(self.hw_connection_established)

        # self.act_delete_address_data.setVisible(visible)
        # if self.hw_selected_account_id is not None:
        #     self.act_delete_account_data.setVisible(True)
        # else:
        #     self.act_delete_account_data.setVisible(False)

    def show_address_on_hw(self, addr: Bip44AddressType):
        try:
            _a = self.hw_call_wrapper(hw_intf.get_address)\
                (self.hw_session, addr.bip32_path, True,
                 f'Displaying address <b>{addr.address}</b>.<br>Click the confirmation button on your device.')
            if _a != addr.address:
                raise Exception('Address inconsistency between db cache and device')
        except HWNotConnectedException:
            raise
        except CancelException:
            return

    def on_show_address_on_hw_triggered(self):
        if self.hw_selected_address_id is not None:
            a = self.account_list_model.account_by_id(self.hw_selected_account_id)
            if a:
                addr = a.address_by_id(self.hw_selected_address_id)
                if addr:
                    self.show_address_on_hw(addr)

    def on_act_copy_address_triggered(self):
        addr = None
        if self.hw_selected_address_id is not None:
            a = self.account_list_model.account_by_id(self.hw_selected_account_id)
            if a:
                addr = a.address_by_id(self.hw_selected_address_id)
                if addr:
                    # for security purposes get the address from hardware wallet and compare it to the one
                    # read from db cache
                    addr_hw = self.hw_call_wrapper(hw_intf.get_address)(self.hw_session, addr.bip32_path, False)
                    if addr_hw != addr.address:
                        self.errorMsg('Inconsistency between the wallet cache and the hardware wallet data occurred. '
                                      'Please clear the wallet cache.')
                        return
                    clipboard = QApplication.clipboard()
                    clipboard.setText(addr.address)
        if not addr:
            WndUtils.warnMsg('Couldn\'t copy the selected address.')

    def on_act_sign_message_for_address_triggered(self):
        addr = None
        if self.hw_selected_address_id is not None:
            acc = self.account_list_model.account_by_id(self.hw_selected_account_id)
            if acc:
                addr = acc.address_by_id(self.hw_selected_address_id)
                if addr and addr.bip32_path and addr.address:
                    ui = SignMessageDlg(self.main_ui, self.hw_session, addr.bip32_path, addr.address)
                    ui.exec_()
        if not addr:
            WndUtils.warnMsg('Couldn\'t copy the selected address.')

    def on_delete_account_triggered(self):
        if self.hw_selected_account_id is not None:
            view_index = self.accountsListView.currentIndex()
            if view_index and view_index.isValid():
                index = self.account_list_model.mapToSource(view_index)
                node = index.internalPointer()
                if isinstance(node, Bip44AccountType):
                    acc = node
                elif isinstance(node, Bip44AddressType):
                    acc = node.bip44_account
                else:
                    raise Exception('No account selected.')

                if WndUtils.queryDlg(f"Do you really want to remove account '{acc.get_account_name()}' from cache?",
                                    buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                    default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
                    return

                fx_state = self.allow_fetch_transactions
                signals_state = self.accountsListView.blockSignals(True)
                with self.account_list_model:
                    self.allow_fetch_transactions = False
                    self.account_list_model.remove_account(index.row())
                    self.bip44_wallet.remove_account(acc.id)
                    self.allow_fetch_transactions = fx_state
                    self.accountsListView.blockSignals(signals_state)
                    self.reflect_ui_account_selection()

    def on_delete_address_triggered(self):
        """For testing only"""
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            if self.hw_selected_address_id is not None:
                view_index = self.accountsListView.currentIndex()
                if view_index and view_index.isValid():
                    index = self.account_list_model.mapToSource(view_index)
                    acc = None
                    acc_index = None
                    addr = index.internalPointer()
                    if isinstance(addr, Bip44AddressType):
                        acc_view_index = view_index.parent()
                        if acc_view_index.isValid():
                            acc_index = self.account_list_model.mapToSource(acc_view_index)
                            acc = acc_index.internalPointer()

                    if acc and acc_index:
                        if WndUtils.queryDlg(f"Do you really want to clear address '{addr.address}' data in cache?",
                                            buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                            default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
                            return

                        ftx_state = self.allow_fetch_transactions
                        signals_state = self.accountsListView.blockSignals(True)
                        with self.account_list_model:
                            self.allow_fetch_transactions = False
                            self.account_list_model.removeRow(index.row(), parent=acc_index)
                            self.bip44_wallet.remove_address(addr.id)
                            self.allow_fetch_transactions = ftx_state
                            self.accountsListView.blockSignals(signals_state)
                            self.reflect_ui_account_selection()
        elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
            if self.selected_mns:
                mns_str = ','.join([mn.masternode.name for mn in self.selected_mns])
                if WndUtils.queryDlg(f"Do you really want to clear transactions cache data for masternodes: '{mns_str}'?",
                                    buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                    default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
                    return
                for mn in self.selected_mns:
                    self.bip44_wallet.remove_address(mn.address.id)
                    with self.utxo_table_model:
                        self.utxo_table_model.beginResetModel()
                        self.utxo_table_model.clear_utxos()
                        self.utxo_table_model.endResetModel()

                    with self.tx_table_model:
                        self.tx_table_model.beginResetModel()
                        self.tx_table_model.clear_utxos()
                        self.tx_table_model.endResetModel()

    @pyqtSlot()
    def on_show_account_next_fresh_address_triggered(self):
        view_index = self.accountsListView.currentIndex()
        if view_index and view_index.isValid():
            index = self.account_list_model.mapToSource(view_index)
            acc = None
            data = index.internalPointer()
            if isinstance(data, Bip44AddressType):
                acc_view_index = view_index.parent()
                if acc_view_index.isValid():
                    acc_index = self.account_list_model.mapToSource(acc_view_index)
                    acc = acc_index.internalPointer()
            elif isinstance(data, Bip44AccountType):
                acc = data
            if acc:
                self.account_list_model.increase_account_fresh_addr_count(acc, 1)

    def get_utxo_src_cfg_hash(self):
        hash = str({self.utxo_src_mode}) + ':'
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            hash = hash + f'{self.cur_hd_tree_id}:{self.hw_account_base_bip32_path}:{self.hw_selected_account_id}:' \
                          f'{self.hw_selected_address_id}'
        elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
            for mni in self.selected_mns:
                hash += str(mni.address.id) + ':'
        return hash

    def on_utxo_src_hash_changed(self):
        self.cur_utxo_src_hash = self.get_utxo_src_cfg_hash()

    def fetch_transactions(self):
        self.last_txs_fetch_time = 0
        self.data_thread_event.set()

    def update_hw_info(self):
        img_path = os.path.join(self.app_config.app_dir if self.app_config.app_dir else '', 'img')
        if sys.platform == 'win32':
            h = self.pnl_input.height()
            img_size_str = f'height="{h}" width="{h}"'
        else:
            img_size_str = ''

        self.btnFetchTransactions.setVisible(self.hw_connected() or self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST)
        if not self.hw_connected():
            t = f'<table><tr><td>Hardware wallet <span>not connected</span></td>' \
                f'<td> (<a href="hw-connect">connect</a>)</td></tr></table>'
            self.btnSetHwIdentityLabel.hide()
            self.btnPurgeHwIdentity.hide()
        else:
            ht = HWType.get_desc(self.hw_session.hw_type)
            id, label = self.bip44_wallet.get_hd_identity_info()
            if label:
                label = f'<td> as <i>{label}</i></td>'
            else:
                label = f'<td> as <i>Identity #{str(id)}</i></td>'
            t = f'<table><tr><td>Connected to {ht}</td><td> (<a href="hw-disconnect">disconnect</a>)</td>' \
                f'{label}</tr></table>'
            self.btnSetHwIdentityLabel.show()
            self.btnPurgeHwIdentity.show()
        self.lblHW.setText(t)

    def on_lblHW_linkHovered(self, link):
        if link == 'hw-disconnect':
            self.lblHW.setToolTip('Disconnect hardware wallet')
        elif link == 'hw-connect':
            self.lblHW.setToolTip('Connect to hardware wallet')
            self.lblHW.setToolTip('')

    def on_lblHW_linkActivated(self, link):
        if link == 'hd-identity-label':
            self.set_hd_identity_label()
        elif link == 'hw-disconnect':
            self.disconnect_hw()
        elif link == 'hw-connect':
            self.connect_hw()
        elif link == 'hd-identity-delete':
            self.delete_hd_identity()
        elif link == 'tx-fetch':
            self.fetch_transactions()
        elif link == 'hw-alter-identity':
            if self.hw_connected():
                self.main_ui.disconnect_hardware_wallet()
                self.main_ui.connect_hardware_wallet()
        self.update_hw_info()

    @pyqtSlot(bool)
    def on_btnSetHwIdentityLabel_clicked(self):
        self.set_hd_identity_label()

    @pyqtSlot(bool)
    def on_btnPurgeHwIdentity_clicked(self):
        self.delete_hd_identity()

    @pyqtSlot(bool)
    def on_btnFetchTransactions_clicked(self):
        self.fetch_transactions()

    def set_hd_identity_label(self):
        if self.hw_connected():
            id, label = self.bip44_wallet.get_hd_identity_info()

            label, ok = QInputDialog.getText(self, 'Identity label', 'Enter label for current hw identity', text=label)
            if ok:
                self.bip44_wallet.set_label_for_hw_identity(id, label)
                self.update_hw_info()

    def delete_hd_identity(self):
        if WndUtils.queryDlg(f"Do you really want to purge the current identity from cache?",
                             buttons=QMessageBox.Yes | QMessageBox.Cancel,
                             default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
            return
        id, _ = self.bip44_wallet.get_hd_identity_info()
        if id:
            self.bip44_wallet.delete_hd_identity(id)
            self.disconnect_hw()

    def hw_connected(self):
        if self.hw_session.hw_type is not None and self.hw_session.hw_client is not None and \
                self.hw_connection_established:
            return True
        else:
            return False

    def on_connect_hw(self):
        if self.hw_session.hw_type is not None and self.hw_session.hw_client:
            aft_saved = self.allow_fetch_transactions
            esmt_saved = self.enable_synch_with_main_thread
            self.allow_fetch_transactions = False
            self.enable_synch_with_main_thread = False

            try:
                tree_ident = self.hw_session.get_hd_tree_ident(self.app_config.hw_coin_name)
                if self.cur_hd_tree_ident != tree_ident:
                    if self.cur_hd_tree_ident:
                        self.on_disconnect_hw()  #hw identity has been changed

                    self.cur_hd_tree_ident = tree_ident
                    self.cur_hd_tree_id, _ = self.bip44_wallet.get_hd_identity_info()
                    self.hw_connection_established = True
                    self.update_hw_info()
                    self.on_utxo_src_hash_changed()
                    self.hw_selected_account_id = None
                    self.hw_selected_address_id = None
                    self.update_context_actions()
                    self.cur_utxo_src_hash = None
                    self.enable_synch_with_main_thread = True
                    self.dt_last_addr_selection_hash_for_utxo = ''
                    self.dt_last_addr_selection_hash_for_txes = ''
                    self.dt_last_hd_tree_id = None
            finally:
                self.allow_fetch_transactions = aft_saved
                self.enable_synch_with_main_thread = esmt_saved

    def on_disconnect_hw(self):
        aft_saved = self.allow_fetch_transactions
        self.allow_fetch_transactions = False
        esmt_saved = self.enable_synch_with_main_thread
        self.enable_synch_with_main_thread = False

        try:
            if self.cur_hd_tree_ident:
                if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                    # clear the utxo model data
                    with self.utxo_table_model:
                        self.utxo_table_model.beginResetModel()
                        self.utxo_table_model.clear_utxos()
                        self.utxo_table_model.endResetModel()

                    # and the txes model data
                    with self.tx_table_model:
                        self.tx_table_model.beginResetModel()
                        self.tx_table_model.clear_txes()
                        self.tx_table_model.endResetModel()

                # clear the account model data
                with self.account_list_model:
                    self.account_list_model.beginResetModel()
                    self.account_list_model.clear_accounts()
                    self.account_list_model.endResetModel()

                self.hw_connection_established = False
                self.bip44_wallet.clear()
                # reload mn addresses into the address cache cleared by the call ^
                self.mn_model.load_mn_addresses_in_bip44_wallet(self.bip44_wallet)
                self.hw_selected_account_id = None
                self.hw_selected_address_id = None
                self.cur_hd_tree_id = None
                self.cur_hd_tree_ident = None
                self.cur_utxo_src_hash = None
                self.hide_loading_tx_animation()
                self.update_context_actions()
                self.update_details_tab()
                self.update_hw_info()
                self.set_message('')
        finally:
            self.allow_fetch_transactions = aft_saved
            self.enable_synch_with_main_thread = esmt_saved

    def connect_hw(self):
        def connect():
            if self.main_ui.connect_hardware_wallet():
                aft_saved = self.allow_fetch_transactions
                esmt_saved = self.enable_synch_with_main_thread
                self.allow_fetch_transactions = False
                self.enable_synch_with_main_thread = False

                try:
                    self.on_connect_hw()
                finally:
                    self.allow_fetch_transactions = aft_saved
                    self.enable_synch_with_main_thread = esmt_saved

                self.display_thread_event.set()
                self.fetch_transactions()
                return True
            else:
                if self.hw_connected():
                    self.on_disconnect_hw()
                return False

        if threading.current_thread() != threading.main_thread():
            if self.enable_synch_with_main_thread:
                return WndUtils.call_in_main_thread(connect)
            else:
                return False
        else:
            return connect()

    def disconnect_hw(self):
        aft_saved = self.allow_fetch_transactions
        self.allow_fetch_transactions = False
        esmt_saved = self.enable_synch_with_main_thread
        self.enable_synch_with_main_thread = False

        try:
            self.on_disconnect_hw()
            self.main_ui.disconnect_hardware_wallet()
        finally:
            self.allow_fetch_transactions = aft_saved
            self.enable_synch_with_main_thread = esmt_saved

    def get_utxo_list_generator(self, only_new) -> Generator[UtxoType, None, None]:
        list_utxos = None
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            if self.hw_selected_account_id is not None and self.cur_hd_tree_id:
                if self.hw_selected_address_id is None:
                    # list utxos of the whole bip44 account
                    list_utxos = self.bip44_wallet.list_utxos_for_account(self.hw_selected_account_id, only_new)
                else:
                    # list utxos of the specific address
                    list_utxos = self.bip44_wallet.list_utxos_for_addresses([self.hw_selected_address_id], only_new)
        elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
            address_ids = []
            for mni in self.selected_mns:
                if mni.address and not mni.address.id in address_ids:
                    address_ids.append(mni.address.id)
            list_utxos = self.bip44_wallet.list_utxos_for_addresses(address_ids)
        else:
            raise Exception('Invalid utxo_src_mode')
        return list_utxos

    def get_txs_list_generator(self, only_new) -> Generator[TxType, None, None]:
        list_txs = None
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            if self.hw_selected_account_id is not None and self.cur_hd_tree_id:
                if self.hw_selected_address_id is None:
                    # list utxos of the whole bip44 account
                    list_txs = self.bip44_wallet.list_txs(self.hw_selected_account_id, None, only_new)
                else:
                    # list utxos of the specific address
                    list_txs = self.bip44_wallet.list_txs(None, [self.hw_selected_address_id], only_new)
        elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
            address_ids = []
            for mni in self.selected_mns:
                if mni.address and not mni.address.id in address_ids:
                    address_ids.append(mni.address.id)
            list_txs = self.bip44_wallet.list_txs(None, address_ids, only_new)
        else:
            raise Exception('Invalid utxo_src_mode')
        return list_txs

    def display_thread(self, ctrl: CtrlObject):
        self.dt_last_hd_tree_id = None
        log.debug('Starting display_thread')

        def subscribe_for_tx_activity_notificatoins():
            if self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
                addr_ids = []
                for a in self.selected_mns:
                    if a.address.id not in addr_ids:
                        addr_ids.append(a.address.id)
                self.bip44_wallet.subscribe_addresses_for_txes(addr_ids, True)
            elif self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                if self.hw_selected_address_id is not None:
                    self.bip44_wallet.subscribe_addresses_for_txes([self.hw_selected_address_id], True)
                elif self.hw_selected_account_id is not None:
                    self.bip44_wallet.subscribe_accounts_for_txes([self.hw_selected_account_id], True)
                else:
                    self.bip44_wallet.subscribe_addresses_for_txes([], True)  # clear tx subscriptions

        try:
            self.last_txs_fetch_time = 0
            self.dt_last_addr_selection_hash_for_utxo = ''
            self.dt_last_addr_selection_hash_for_txes = ''

            while not ctrl.finish and not self.finishing:
                hw_error = False

                if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:  # the hw accounts view needs an hw connection
                    if not self.hw_connected():
                        hw_error = True
                        self.dt_last_hd_tree_id = None

                    if not hw_error:
                        if self.dt_last_hd_tree_id != self.cur_hd_tree_id:
                            # not read hw accounts yet or switched to another hw/used another passphrase

                            log.debug('About to start listing accounts')
                            with self.account_list_model:
                                log.debug('Listing accounts')
                                for a in self.bip44_wallet.list_accounts():
                                    pass
                                log.debug('Finished listing accounts')
                            WndUtils.call_in_main_thread(self.reflect_data_account_selection)
                            self.dt_last_hd_tree_id = self.cur_hd_tree_id

                if not hw_error:
                    if self.finishing:
                        break

                    if self.detailsTab.currentIndex() == self.detailsTab.indexOf(self.tabSend):
                        # current tab: the list of utxos

                        if self.dt_last_addr_selection_hash_for_utxo != self.cur_utxo_src_hash:
                            # reload the utxo view
                            self.dt_last_addr_selection_hash_for_utxo = self.cur_utxo_src_hash
                            subscribe_for_tx_activity_notificatoins()

                            list_utxos_generator = self.get_utxo_list_generator(False)

                            # pause the fetch process to avoid waiting for the data do be displayed
                            self.allow_fetch_transactions = False
                            try:
                                with self.utxo_table_model:
                                    self.utxo_table_model.beginResetModel()
                                    self.utxo_table_model.clear_utxos()
                                    self.utxo_table_model.endResetModel()
                            finally:
                                self.allow_fetch_transactions = True

                            if list_utxos_generator:
                                log.debug('Reading utxos from database')
                                self.utxo_table_model.set_block_height(self.bip44_wallet.get_block_height())

                                t = time.time()
                                self.utxo_table_model.beginResetModel()

                                # pause the fetch process to avoid waiting for the data do be displayed
                                self.allow_fetch_transactions = False
                                try:
                                    with self.utxo_table_model:
                                        for utxo in list_utxos_generator:
                                            if self.finishing:
                                                break
                                            self.utxo_table_model.add_utxo(utxo)
                                finally:
                                    self.utxo_table_model.endResetModel()
                                    self.allow_fetch_transactions = True

                                log.debug('Reading of utxos finished, time: %s', time.time() - t)

                    elif self.detailsTab.currentIndex() == self.detailsTab.indexOf(self.tabTransactions):
                        # current tab: the list of transactions

                        if self.dt_last_addr_selection_hash_for_txes != self.cur_utxo_src_hash:

                            list_txs_generator = self.get_txs_list_generator(False)
                            if list_txs_generator:
                                subscribe_for_tx_activity_notificatoins()
                                log.debug('Reading transactions from database')

                                self.dt_last_addr_selection_hash_for_txes = self.cur_utxo_src_hash

                                self.allow_fetch_transactions = False
                                try:
                                    with self.tx_table_model:
                                        self.tx_table_model.beginResetModel()
                                        self.tx_table_model.clear_txes()
                                        self.tx_table_model.endResetModel()
                                finally:
                                    self.allow_fetch_transactions = True

                                t = time.time()
                                self.tx_table_model.beginResetModel()
                                self.allow_fetch_transactions = False
                                try:
                                    with self.tx_table_model:
                                        for utxo in list_txs_generator:
                                            if self.finishing:
                                                break
                                            self.tx_table_model.add_tx(utxo)
                                finally:
                                    self.tx_table_model.endResetModel()
                                    self.allow_fetch_transactions = True

                                log.debug('Reading of transactions finished, time: %s', time.time() - t)
                            else:
                                log.debug('Empty list_utxos_generator')

                self.display_thread_event.wait(10)
                if self.display_thread_event.is_set():
                    self.display_thread_event.clear()

        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg('An unknown error occurred, please close and reopen the window. Details: ' + str(e))
        finally:
            self.display_thread_ref = None
        log.debug('Finishing display_thread')

    def data_thread(self, ctrl: CtrlObject):
        last_hd_tree_id = None

        def check_break_fetch_process():
            if not self.allow_fetch_transactions or self.finishing or ctrl.finish or \
                (self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS and last_hd_tree_id != self.cur_hd_tree_id):
                raise BreakFetchTransactionsException('Break fetch transactions')

        log.debug('Starting data_thread')
        try:
            if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                self.connect_hw()

            self.last_txs_fetch_time = 0

            while not ctrl.finish and not self.finishing:
                hw_error = False
                if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:  # the hw accounts view needs an hw connection
                    if not self.hw_connected():
                        hw_error = True

                if not hw_error:
                    if self.finishing:
                        break

                    if self.last_txs_fetch_time == 0 or (time.time() - self.last_txs_fetch_time > FETCH_DATA_INTERVAL_SECONDS):
                        if self.allow_fetch_transactions:
                            self.set_message('Fetching transactions...')
                            self.show_loading_tx_animation()

                            if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                                fun_to_call = partial(self.bip44_wallet.fetch_all_accounts_txs, check_break_fetch_process)
                            elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
                                addresses = []
                                with self.mn_model:
                                    for mni in self.mn_model.mn_items:
                                        if mni.address:
                                            addresses.append(mni.address)
                                fun_to_call = partial(self.bip44_wallet.fetch_addresses_txs, addresses, check_break_fetch_process)
                            else:
                                fun_to_call = None

                            if fun_to_call:
                                try:
                                    last_hd_tree_id = self.cur_hd_tree_id
                                    self.call_fun_monitor_txs(fun_to_call, check_break_fetch_process)
                                    self.last_txs_fetch_time = int(time.time())
                                except BreakFetchTransactionsException:
                                    # the purpose of this exception is to break the fetch routine only
                                    pass

                                if not ctrl.finish and not self.finishing:
                                    self.hide_loading_tx_animation()
                                    self.set_message('')

                self.data_thread_event.wait(1)
                if self.data_thread_event.is_set():
                    self.data_thread_event.clear()

        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg('An unknown error occurred, please close and reopen the window. Details: ' + str(e))
        finally:
            self.data_thread_ref = None
        log.debug('Finishing data_thread')

    def call_fun_monitor_txs(self, function_to_call: Callable, check_break_execution_callback: Callable):
        """
        Call a (wallet) function which can result in adding/removing UTXOs and/or adding/removing
        transactions - those changes will be reflected in GUI after the call completes.
        :return:
        """
        def invalidate_accounts_filter():
            with self.account_list_model:
                self.account_list_model.invalidateFilter()

        try:
            log.debug('Calling %s', str(function_to_call))
            self.account_list_model.reset_modified()
            with self.account_list_model:
                self.bip44_wallet.reset_tx_diffs()
                function_to_call()

            if not check_break_execution_callback():
                if self.account_list_model.data_modified:
                    if self.enable_synch_with_main_thread:
                        WndUtils.call_in_main_thread_ext(invalidate_accounts_filter, skip_if_main_thread_locked=True)

                list_utxos = self.get_utxo_list_generator(True)
                if list_utxos:
                    self.utxo_table_model.set_block_height(self.bip44_wallet.get_block_height())

                    added_utxos = []
                    removed_utxos = []
                    modified_utxos = []
                    self.bip44_wallet.get_utxos_diff(added_utxos, modified_utxos, removed_utxos)

                    if (added_utxos or modified_utxos or removed_utxos) and \
                            (self.enable_synch_with_main_thread or
                             threading.current_thread() == threading.main_thread()):

                        with self.utxo_table_model:
                            WndUtils.call_in_main_thread(self.utxo_table_model.update_utxos, added_utxos,
                                                         modified_utxos, removed_utxos)

        except BreakFetchTransactionsException:
            raise
        except HWNotConnectedException as e:
            log.error('Hardware wallet has been disconnected.')
            if not self.finishing:
                WndUtils.call_in_main_thread(self.disconnect_hw)
                WndUtils.warnMsg(str(e))
        except SwitchedHDIdentityException:
            if self.hw_connection_established and not self.finishing:
                # reconnect if the hw was connected before and the hd identity has changed in the meantime
                WndUtils.warnMsg('The window data will be reloaded because the hardware wallet identity has changed.')
                WndUtils.call_in_main_thread(self.connect_hw)
        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg(str(e))
        finally:
            log.debug('Finished calling %s', str(function_to_call))

    def on_bip44_account_added(self, account: Bip44AccountType):
        """
        Called back from self.bip44_wallet after adding an item to the list of bip44 accounts. It is
        used in 'accounts view' mode for the subsequent display of read accounts.
        :param account: the account being added.
        """
        if not self.finishing:
            def fun():
                if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                    self.account_list_model.add_account(account)

            log.debug('Adding account %s', account.id)
            if threading.current_thread() != threading.main_thread():
                if self.enable_synch_with_main_thread:
                    WndUtils.call_in_main_thread_ext(fun, skip_if_main_thread_locked=True)
            else:
                fun()

    def on_bip44_account_changed(self, account: Bip44AccountType):
        """
        Called back from self.bip44_wallet after modification of a bip44 account data (description, balance, received,
        addresses)
        :param account: the account being modified.
        """
        if not self.finishing:
            def fun():
                if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                    self.account_list_model.account_data_changed(account)

            log.debug('Account modified %s', account.id)
            if threading.current_thread() != threading.main_thread():
                if self.enable_synch_with_main_thread:
                    WndUtils.call_in_main_thread_ext(fun, skip_if_main_thread_locked=True)
            else:
                fun()

    def on_bip44_account_address_added(self, account: Bip44AccountType, address: Bip44AddressType):
        if not self.finishing:
            def fun():
                if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
                    self.account_list_model.add_account_address(account, address)

            if threading.current_thread() != threading.main_thread():
                if self.enable_synch_with_main_thread:
                    WndUtils.call_in_main_thread_ext(fun, skip_if_main_thread_locked=True)
            else:
                fun()

    def on_bip44_account_address_changed(self, account: Bip44AccountType, address: Bip44AddressType):
        if not self.finishing:
            def fun():
                if account:
                    self.account_list_model.address_data_changed(account, address)
                self.mn_model.address_data_changed(address)

            if threading.current_thread() != threading.main_thread():
                if self.enable_synch_with_main_thread:
                    WndUtils.call_in_main_thread_ext(fun, skip_if_main_thread_locked=True)
            else:
                fun()

    def on_edtSourceBip32Path_returnPressed(self):
        self.on_btnLoadTransactions_clicked()

    def get_selected_utxos(self) -> Tuple[int, List[UtxoType]]:
        """
        :return: Tuple[int <total amount selected>, List[Dict] <list of the selected utxos>]
        """
        with self.utxo_table_model:
            row_indexes = self.utxo_table_model.selected_rows()
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

    def show_loading_tx_animation(self):
        if not self.wdg_loading_txs_animation:
            def show():
                size = min(self.wdgSpinner.height(), self.wdgSpinner.width())
                g = self.wdgSpinner.geometry()
                g.setWidth(size)
                g.setHeight(size)
                self.wdgSpinner.setGeometry(g)
                self.wdg_loading_txs_animation = SpinnerWidget(self.wdgSpinner, size, '', 11)
                self.wdg_loading_txs_animation.show()

            if threading.current_thread() != threading.main_thread():
                if self.enable_synch_with_main_thread:
                    WndUtils.call_in_main_thread_ext(show, skip_if_main_thread_locked=True)
            else:
                show()

    def hide_loading_tx_animation(self):
        if self.wdg_loading_txs_animation:
            def hide():
                self.wdg_loading_txs_animation.hide()
                del self.wdg_loading_txs_animation
                self.wdg_loading_txs_animation = None

            if threading.current_thread() != threading.main_thread():
                if self.enable_synch_with_main_thread:
                    WndUtils.call_in_main_thread_ext(hide, skip_if_main_thread_locked=True)
            else:
                hide()

    def update_details_tab(self):
        def set_text(text):
            self.edtDetailsAddress.setPlainText(text)
            textEdit = self.edtDetailsAddress

            font = textEdit.document().defaultFont()  # or another font if you change it
            fontMetrics = QtGui.QFontMetrics(font)  # a QFontMetrics based on our font
            textSize = fontMetrics.size(0, text)
            textHeight = textSize.height()  # constant may need to be tweaked
            textEdit.setFixedHeight(max(textHeight, self.edtDetailsReceived.height()))

        addr_str = ''
        addr_lbl = ''
        addr_path = ''
        balance = 0
        received = 0
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            if self.hw_selected_address_id:
                addr_lbl = 'Address'
                acc = self.account_list_model.account_by_id(self.hw_selected_account_id)
                if acc:
                    addr = acc.address_by_id(self.hw_selected_address_id)
                    if addr:
                        addr_path = addr.bip32_path
                        addr_str = addr.address
                        balance = addr.balance
                        received = addr.received

                        # for security reasons get the address from hardware wallet and compare it to the one
                        # read from db cache
                        addr_hw = self.hw_call_wrapper(hw_intf.get_address)(self.hw_session, addr.bip32_path, False)
                        if addr_hw != addr.address:
                            addr_str = 'Address inconsistency. Please clear the wallet cache.'

            elif self.hw_selected_account_id:
                addr_lbl = 'XPUB'
                addr = self.account_list_model.account_by_id(self.hw_selected_account_id)
                if addr:
                    addr_path = addr.bip32_path
                    addr_str = addr.xpub
                    balance = addr.balance
                    received = addr.received
        elif self.utxo_src_mode == MAIN_VIEW_MASTERNODE_LIST:
            addr_lbl = 'Address'
            addr_path = ', '.join([mn.address.bip32_path for mn in self.selected_mns if mn.address.bip32_path is not None])
            addr_str = ', '.join([mn.address.address for mn in self.selected_mns if mn.address.address is not None])
            balance = sum([mn.address.balance for mn in self.selected_mns])
            received = sum([mn.address.received for mn in self.selected_mns])

        html = f"""<head>
<style type="text/css">
    .lbl {{font-weight: bold; text-align: right; padding-right:6px; white-space:nowrap}}
</style>
</head>
<body>
<table>
<tr><td class="lbl">{addr_lbl}</td><td>{addr_str}</td></tr>
<tr><td class="lbl">Path</td><td>{addr_path}</td></tr>
<tr><td class="lbl">Balance</td><td>{app_utils.to_string(balance/1e8)} Dash</td></tr>
<tr><td class="lbl">Received</td><td>{app_utils.to_string(received/1e8)} Dash</td></tr>
</table>
</body>
"""
        self.edtDetailsAddress.setText(html)

    def on_act_set_entry_label_triggered(self):
        entry = None
        if self.hw_selected_address_id:
            acc = self.account_list_model.account_by_id(self.hw_selected_account_id)
            if acc:
                entry = acc.address_by_id(self.hw_selected_address_id)
        elif self.hw_selected_account_id:
            entry = self.account_list_model.account_by_id(self.hw_selected_account_id)

        if entry:
            label, ok = QInputDialog.getText(self, 'Enter new label', 'Enter new label', text = entry.label)
            if ok:
                fx_state = self.allow_fetch_transactions
                with self.account_list_model:
                    self.allow_fetch_transactions = False
                    self.bip44_wallet.set_label_for_entry(entry, label)
                    self.allow_fetch_transactions = fx_state

    def on_act_show_account_triggered(self):
        fx_state = self.allow_fetch_transactions
        self.allow_fetch_transactions = False
        try:
            with self.account_list_model:
                index = self.account_list_model.get_first_unused_bip44_account_index()
                if index >= 0x80000000:
                    index -= 0x80000000
                else:
                    index = 0
        finally:
            self.allow_fetch_transactions = fx_state

        account_nr, ok = QInputDialog.getInt(self, 'Enter value',
                                             'Enter the account number (1-based) you want to show:',
                                             value=index + 1, min=1)
        if ok:
            fx_state = self.allow_fetch_transactions
            self.allow_fetch_transactions = False
            try:
                with self.account_list_model:
                    acc = self.account_list_model.account_by_bip44_index(0x80000000 + account_nr - 1)
                    if acc:
                        acc.status = 1
                        refresh_txes = False
                        self.bip44_wallet.set_account_status(acc, acc.status)
                    else:
                        acc = self.bip44_wallet.force_show_account(account_nr - 1, None)
                        refresh_txes = True
                    self.account_list_model.account_data_changed(acc)
            finally:
                self.allow_fetch_transactions = fx_state

            self.account_list_model.invalidateFilter()

            if acc:
                self.hw_selected_account_id = acc.id
                self.hw_selected_address_id = None
                self.on_utxo_src_hash_changed()
                self.reflect_data_account_selection()
                self.display_thread_event.set()

                if refresh_txes:
                    self.fetch_transactions()

    def on_act_hide_account_triggered(self):
        if self.hw_selected_account_id is not None and self.hw_selected_address_id is None:
            acc = self.account_list_model.account_by_id(self.hw_selected_account_id)

            if acc:
                if WndUtils.queryDlg(f"Do you really want to hide account '{acc.get_account_name()}'?",
                                    buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                    default_button=QMessageBox.Cancel, icon=QMessageBox.Information) != QMessageBox.Yes:
                    return

                fx_state = self.allow_fetch_transactions
                self.allow_fetch_transactions = False
                signals_state = self.accountsListView.blockSignals(True)
                try:
                    with self.account_list_model:
                        acc.status = 2
                        self.bip44_wallet.set_account_status(acc, acc.status)
                        self.allow_fetch_transactions = fx_state
                        self.accountsListView.blockSignals(signals_state)
                        # self.reflect_ui_account_selection()
                finally:
                    self.allow_fetch_transactions = fx_state

    def update_ui_show_individual_addresses(self):
        if not self.accounts_view_show_individual_addresses:
            self.accountsListView.collapseAll()
            self.accountsListView.setItemsExpandable(False)
            self.accountsListView.setRootIsDecorated(False)
        else:
            self.accountsListView.setItemsExpandable(True)
            self.accountsListView.setRootIsDecorated(True)

    def update_ui_view_mode_options(self):
        if self.utxo_src_mode == MAIN_VIEW_BIP44_ACCOUNTS:
            self.lblViewModeOptions.show()
        else:
            self.lblViewModeOptions.hide()

    @pyqtSlot(bool)
    def on_btnViewModeOptions_clicked(self, checked):
        if checked:
            self.wdg_accounts_view_options.show()
            self.ui_accounts_view_options.chbShowAddresses.setChecked(self.accounts_view_show_individual_addresses)
            self.ui_accounts_view_options.chbShowZeroBalanceAddresses.setChecked(self.accounts_view_show_zero_balance_addesses)
            self.ui_accounts_view_options.chbShowNotUsedAddresses.setChecked(self.accounts_view_show_not_used_addresses)
            self.update_ui_view_mode_options()
        else:
            self.wdg_accounts_view_options.hide()

    def on_btnAccountsViewOptionsApply_clicked(self):
        self.accounts_view_show_individual_addresses = self.ui_accounts_view_options.chbShowAddresses.isChecked()
        self.accounts_view_show_zero_balance_addesses = self.ui_accounts_view_options.chbShowZeroBalanceAddresses.isChecked()
        self.accounts_view_show_not_used_addresses = self.ui_accounts_view_options.chbShowNotUsedAddresses.isChecked()

        with self.account_list_model:
            self.account_list_model.show_zero_balance_addresses = self.accounts_view_show_zero_balance_addesses
            self.account_list_model.show_not_used_addresses = self.accounts_view_show_not_used_addresses
            self.account_list_model.invalidateFilter()
        self.update_ui_show_individual_addresses()
        self.wdg_accounts_view_options.hide()
        self.btnViewModeOptions.setChecked(False)
        self.update_ui_view_mode_options()

    def on_detailsTab_currentChanged(self, index):
        self.display_thread_event.set()

    @pyqtSlot(bool)
    def on_btnSelectAllMasternodes_clicked(self, checked):
        sel = self.mnListView.selectionModel()
        sel_modified = False
        s = QItemSelection()
        with self.mn_model:
            for row_idx, mni in enumerate(self.mn_model.mn_items):
                index = self.mn_model.index(row_idx, 0)
                sel_modified = True
                s.select(index, index)
            if sel_modified:
                sel.select(s, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def save_tx_comment(self, a):
        pass

    def prepare_txes_filter(self):
        self.ui_txes_filter.edtDate.setDate(datetime.datetime.now())
        pass

    def apply_txes_filter(self):
        def text_to_oper(text):
            if text == '>=':
                o = FILTER_OPER_GTEQ
            elif text == '<=':
                o = FILTER_OPER_LTEQ
            elif text == '=':
                o = FILTER_OPER_EQ
            else:
                o = None
            return o

        m = self.tx_table_model
        ui = self.ui_txes_filter
        m.filter_type = FILTER_OR if ui.rbFilterTypeOr.isChecked() else FILTER_AND
        m.filter_incoming = ui.chbTypeIncoming.isChecked()
        m.filter_outgoing = ui.chbTypeOutgoing.isChecked()
        m.filter_coinbase = ui.chbTypeCoinbase.isChecked()
        m.filter_amount_oper = None
        m.filter_date_oper = None
        m.filter_recipient = None
        m.filter_sender = None
        if ui.cboAmountOper.currentText():
            try:
                m.filter_amount_value = int(float(ui.edtAmountValue.text()) * 1e8)
                m.filter_amount_oper = text_to_oper(ui.cboAmountOper.currentText())
            except Exception as e:
                self.errorMsg('Invalid amount value')
                ui.edtAmountValue.setFocus()
                return

        if ui.cboDateOper.currentText():
            try:
                dt = ui.edtDate.date()
                m.filter_date_value = int(datetime.datetime(*dt.getDate()).timestamp())
                m.filter_date_oper = text_to_oper(ui.cboDateOper.currentText())
            except Exception as e:
                self.errorMsg('Invalid amount value')
                ui.edtAmountValue.setFocus()
                return

        if ui.edtRecipientAddress.text():
            m.filter_recipient = ui.edtRecipientAddress.text().strip()

        if ui.edtSenderAddress.text():
            m.filter_sender = ui.edtSenderAddress.text().strip()

        m.invalidateFilter()


    def show_hide_txes_filter(self, show=None):
        if show is None:
            show = self.btnTxesTabFilter.isChecked()
        if show:
            self.wdg_txes_filter.show()
            self.btnTxesTabFilter.setToolTip('Hide filter')
        else:
            self.wdg_txes_filter.hide()
            self.btnTxesTabFilter.setToolTip('Show filter')

    @pyqtSlot(bool)
    def on_btnTxesTabFilter_clicked(self, checked):
        self.show_hide_txes_filter(checked)