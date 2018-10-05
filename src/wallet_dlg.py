#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import base64
import hashlib
import simplejson
import threading
import time
import logging
from functools import partial
from typing import Tuple, List, Optional, Dict, Generator, Callable
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
from wallet_common import UtxoType, Bip44AccountType, AddressType, TxOutputType
from dashd_intf import DashdInterface, DashdIndexException
from db_intf import DBCache
from hw_common import HardwareWalletCancelException, HwSessionInfo
from hw_intf import prepare_transfer_tx, get_address
from ext_item_model import ExtSortFilterTableModel, TableModelColumn
from thread_fun_dlg import WorkerThread, CtrlObject
from tx_history_widgets import TransactionsModel, TransactionsProxyModel
from wallet_data_models import UtxoTableModel, MnAddressTableModel, AccountListModel, MnAddressItem
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate
from ui import ui_wallet_dlg
from wallet_widgets import SendFundsDestination, WalletMnItemDelegate, WalletAccountItemDelegate
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


class BreakFetchTransactionsException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, *kwargs)


class WalletDlg(QDialog, ui_wallet_dlg.Ui_WalletDlg, WndUtils):
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

        self.main_ui = main_ui
        self.hw_session: HwSessionInfo = self.main_ui.hw_session
        self.rawtransactions = {}
        self.masternodes = main_ui.config.masternodes
        self.masternode_addresses: List[Tuple[str, str]] = []  #  Tuple: address, bip32 path
        for idx, mn in enumerate(self.masternodes):
            self.masternode_addresses.append((mn.collateralAddress.strip(), mn.collateralBip32Path.strip()))
            log.debug(f'WalletDlg initial_mn_sel({idx}) addr - path: {mn.collateralAddress}-{mn.collateralBip32Path}')

        self.dashd_intf: DashdInterface = main_ui.dashd_intf
        self.db_intf: DBCache = main_ui.config.db_intf
        self.bip44_wallet = Bip44Wallet(self.hw_session, self.db_intf, self.dashd_intf,
                                        self.app_config.dash_network)

        self.utxo_table_model = UtxoTableModel(self, self.masternodes)
        self.mn_model = MnAddressTableModel(self, self.masternodes, self.bip44_wallet)
        self.finishing = False  # true if closing window
        self.data_thread_ref: Optional[WorkerThread] = None
        self.last_txs_fetch_time = 0
        self.allow_fetch_transactions = True
        self.update_data_view_thread_ref: Optional[WorkerThread] = None
        self.last_utxos_source_hash = ''
        self.initial_mn_sel = initial_mn_sel

        # for self.utxo_src_mode == 1
        self.hw_account_base_bip32_path = ''
        self.hw_selected_account_id = None  # bip44 account address id
        self.hw_selected_address_id = None  # if the account's address was selected (the index in the Bip44AccountType.addresses list)

        # 1: wallet account (the account number and base bip32 path are selected from the GUI by a user)
        # 2: masternode collateral address
        self.utxo_src_mode: Optional[int] = None
        self.cur_utxo_src_hash = ''  # hash of the currently selected utxo source mode

        # for self.utxo_src_mode == 2
        self.selected_mns: List[MnAddressItem] = []

        self.sel_addresses_balance = 0.0
        self.sel_addresses_received = 0.0

        self.org_message = ''
        self.grid_column_widths = []
        self.recipient_list_from_cache = []
        self.tab_transactions_model = None

        self.account_list_model = AccountListModel(self)
        self.data_thread_event = threading.Event()

        self.setupUi()

    def setupUi(self):
        ui_wallet_dlg.Ui_WalletDlg.setupUi(self, self)
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
        # Display a sort indicator on the header - initial sorting (by the number of confirmations) will be performed
        # during the selection data from cache in an appropriate order, that is faster than sorting in a table view
        self.utxoTableView.horizontalHeader().setSortIndicator(
            self.utxo_table_model.col_index_by_name('confirmations'), Qt.AscendingOrder)
        self.utxo_table_model.set_view(self.utxoTableView)

        self.accountsListView.setModel(self.account_list_model)

        self.mn_model.set_view(self.mnListView)
        self.mnListView.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.mn_view_restore_selection()

        self.setup_transactions_table_view()
        self.chbHideCollateralTx.toggled.connect(self.chbHideCollateralTxToggled)

        self.cboAddressSourceMode.blockSignals(True)
        if self.utxo_src_mode == 1:
            self.swAddressSource.setCurrentIndex(0)
            self.cboAddressSourceMode.setCurrentIndex(0)
        elif self.utxo_src_mode == 2:
            self.swAddressSource.setCurrentIndex(1)
            self.cboAddressSourceMode.setCurrentIndex(1)
        else:
            log.warning(f'Invalid value of self.utxo_src_mode: {self.utxo_src_mode}')
        self.cboAddressSourceMode.blockSignals(False)

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

        self.utxoTableView.selectionModel().selectionChanged.connect(self.on_utxoTableView_selectionChanged)
        self.accountsListView.selectionModel().selectionChanged.connect(self.on_accountsListView_selectionChanged)
        self.accountsListView.setItemDelegateForColumn(0, WalletAccountItemDelegate(self.accountsListView))
        self.mnListView.selectionModel().selectionChanged.connect(self.on_viewMasternodes_selectionChanged)
        self.mnListView.setItemDelegateForColumn(0, WalletMnItemDelegate(self.mnListView))

        # context menu actions:
        self.act_show_address_on_hw = QAction('Show address on hardware wallet', self)
        self.act_show_address_on_hw.triggered.connect(self.on_show_address_on_hw_triggered)
        self.accountsListView.addAction(self.act_show_address_on_hw)

        # todo: for testing only:
        self.act_delete_account_data = QAction('Clear account data in cache', self)
        self.act_delete_account_data.triggered.connect(self.on_delete_account_triggered)
        self.accountsListView.addAction(self.act_delete_account_data)

        self.act_delete_address_data = QAction('Clear address data in cache', self)
        self.act_delete_address_data.triggered.connect(self.on_delete_address_triggered)
        self.accountsListView.addAction(self.act_delete_address_data)

        self.update_context_actions()
        self.start_threads()

    def closeEvent(self, event):
        self.finishing = True
        self.allow_fetch_transactions = False
        self.stop_threads()
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

        self.utxo_table_model.restore_col_defs(CACHE_ITEM_UTXO_COLS)

        # restore the selected masternodes
        sel_hashes = app_cache.get_value(
            CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network), [], list)
        for hash in sel_hashes:
            mni = self.mn_model.get_mn_by_addr_hash(hash)
            if mni and mni not in self.selected_mns:
                self.selected_mns.append(mni)

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

        # save the selected masternodes; as a mn identifier we choose the hashed masternode address
        sel_hashes = []
        for mna in self.selected_mns:
            if mna.address.address:
                h = hashlib.sha256(bytes(mna.address.address, 'utf-8')).hexdigest()
                sel_hashes.append(h)
        app_cache.set_value(CACHE_ITEM_UTXO_SRC_MASTRNODE.replace('%NETWORK%', self.app_config.dash_network),
                            sel_hashes)

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

    def stop_threads(self):
        self.finishing = True
        self.data_thread_event.set()
        if self.data_thread_ref:
            self.data_thread_ref.wait(5000)

    def start_threads(self):
        self.finishing = False
        if not self.data_thread_ref:
            self.data_thread_ref = self.run_thread(self, self.data_thread, ())

    def setup_transactions_table_view(self):
        self.tabViewTransactions.setSortingEnabled(True)
        self.tx_model = TransactionsModel(self)
        self.tx_proxy_model = TransactionsProxyModel(self)
        self.tx_proxy_model.setSourceModel(self.tx_model)
        self.tabViewTransactions.setModel(self.tx_proxy_model)
        self.tabViewTransactions.setItemDelegate(ReadOnlyTableCellDelegate(self.tabViewTransactions))
        self.tabViewTransactions.verticalHeader().setDefaultSectionSize(self.tabViewTransactions.verticalHeader().fontMetrics().height() + 4)

        for idx, col in enumerate(self.tx_model.columns):
            if not col.visible:
                self.tabViewTransactions.setColumnHidden(idx, True)

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

    @pyqtSlot(int)
    def on_cboAddressSourceMode_currentIndexChanged(self, index):
        self.swAddressSource.setCurrentIndex(index)
        if index == 0:
            self.utxo_src_mode = 1
            self.connect_hw()
        elif index == 1:
            self.utxo_src_mode = 2
        else:
            raise Exception('Invalid index.')
        self.on_utxo_src_hash_changed()
        self.data_thread_event.set()

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

    @pyqtSlot()
    def on_btnSend_clicked(self):
        """
        Sends funds to Dash address specified by user.
        """
        amount, tx_inputs = self.get_selected_utxos()
        if len(tx_inputs):
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
            for utxo_idx, utxo in enumerate(tx_inputs):
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
                tx_outputs = self.wdg_dest_adresses.get_tx_destination_data()
                if tx_outputs:
                    total_satoshis_actual = 0
                    for dd in tx_outputs:
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
                            self.main_ui.hw_session, tx_inputs, tx_outputs, fee, self.rawtransactions)
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
                        after_send_tx_fun = partial(self.process_after_sending_transaction, tx_inputs, tx_outputs)
                        tx_dlg = TransactionDlg(self, self.main_ui.config, self.dashd_intf, tx_hex, use_is,
                                                after_send_tx_fun)
                        tx_dlg.exec_()
            except Exception as e:
                log.exception('Unknown error occurred.')
                self.errorMsg(str(e))
        else:
            self.errorMsg('No UTXO to send.')

    def process_after_sending_transaction(self, inputs: List[UtxoType], outputs: List[TxOutputType], tx_json: Dict):
        def break_call():
            # It won't be called since the upper method is called from within the main thread, but we need this
            # to make it compatible with the argument list of self.call_fun_monitor_txs
            return self.finishing

        fun_to_call = partial(self.bip44_wallet.register_spending_transaction, inputs, outputs, tx_json)
        self.call_fun_monitor_txs(fun_to_call, break_call)

    @pyqtSlot()
    def on_btnClose_clicked(self):
        self.close()

    def reflect_ui_account_selection(self):
        idx = self.accountsListView.currentIndex()
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
        self.on_utxo_src_hash_changed()

        if old_sel != self.get_utxo_src_cfg_hash():
            # todo: this shouldn't be needed
            # with self.utxo_table_model:
            #     self.utxo_table_model.beginResetModel()
            #     try:
            #         self.utxo_table_model.clear_utxos()
            #         self.reset_utxos_view()
            #     finally:
            #         self.utxo_table_model.endResetModel()
            self.data_thread_event.set()
            self.update_context_actions()

    def on_accountsListView_selectionChanged(self):
        """Selected BIP44 account or address changed. """
        self.reflect_ui_account_selection()

    def on_viewMasternodes_selectionChanged(self):
        with self.mn_model:
            self.selected_mns.clear()
            for mni in self.mn_model.selected_data_items():
                if mni.address:
                    self.selected_mns.append(mni)
            self.on_utxo_src_hash_changed()
            self.data_thread_event.set()

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
            index = self.accountsListView.currentIndex()
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
                signals_state = self.accountsListView.blockSignals(True)
                with self.account_list_model:
                    self.allow_fetch_transactions = False
                    self.account_list_model.removeRow(index.row())
                    self.bip44_wallet.remove_account(acc.id)
                    self.allow_fetch_transactions = fx_state
                    self.accountsListView.blockSignals(signals_state)
                    self.reflect_ui_account_selection()

    def on_delete_address_triggered(self):
        if self.hw_selected_address_id is not None:
            index = self.accountsListView.currentIndex()
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
                    signals_state = self.accountsListView.blockSignals(True)
                    with self.account_list_model:
                        self.allow_fetch_transactions = False
                        self.account_list_model.removeRow(index.row(), parent=acc_index)
                        self.bip44_wallet.remove_address(addr.id)
                        self.allow_fetch_transactions = ftx_state
                        self.accountsListView.blockSignals(signals_state)
                        self.reflect_ui_account_selection()

    def get_utxo_src_cfg_hash(self):
        hash = str({self.utxo_src_mode}) + ':'
        if self.utxo_src_mode == 1:
            hash = hash + f'{self.hw_account_base_bip32_path}:{self.hw_selected_account_id}:' \
                          f'{self.hw_selected_address_id}'
        elif self.utxo_src_mode == 2:
            for mni in self.selected_mns:
                hash += str(mni.address.id) + ':'
        return hash

    def on_utxo_src_hash_changed(self):
        self.cur_utxo_src_hash = self.get_utxo_src_cfg_hash()

    def reset_accounts_view(self):
        def reset():
            try:
                log.debug('Beginning reset_accounts_view.reset')
                first_item_index = self.accountsListView.indexAt(self.accountsListView.rect().topLeft() +
                                                                 QPoint(0, self.accountsListView.header().height() - 2))
                if first_item_index and first_item_index.isValid():
                    first_item = first_item_index.internalPointer()
                else:
                    first_item = None

                # save the expanded account list to restore them after reset
                expanded_account_ids = []
                for account_idx, acc in enumerate(self.account_list_model.accounts):
                    index = self.account_list_model.index(account_idx, 0)
                    if index and self.accountsListView.isExpanded(index):
                        expanded_account_ids.append(acc.id)

                self.account_list_model.beginResetModel()
                self.account_list_model.endResetModel()

                for account_id in expanded_account_ids:
                    account_idx = self.account_list_model.account_index_by_id(account_id)
                    index = self.account_list_model.index(account_idx, 0)
                    if index:
                        self.accountsListView.setExpanded(index, True)

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
                                    self.accountsListView.setCurrentIndex(self.account_list_model.index(addr_idx, 0,
                                                                                                        account_index))
                                    focus_set = True
                        if not focus_set:
                            self.accountsListView.setCurrentIndex(self.account_list_model.index(account_idx, 0))
                else:
                    self.hw_selected_account_id = None

                if first_item:
                    # restore the first visible item
                    if isinstance(first_item, Bip44AccountType):
                        acc_idx = self.account_list_model.account_index_by_id(first_item.id)
                        if acc_idx is not None:
                            acc_index = self.account_list_model.index(acc_idx, 0)
                            if acc_index and acc_index.isValid():
                                self.accountsListView.scrollTo(acc_index, hint=QAbstractItemView.PositionAtTop)
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
                                            self.accountsListView.scrollTo(addr_index,
                                                                           hint=QAbstractItemView.PositionAtTop)
            finally:
                log.debug('Finished reset_accounts_view.reset')
        WndUtils.call_in_main_thread(reset)

    # def reset_utxos_view(self):
    #     def reset():
    #         log.debug('Begin reset_utxos_view')
    #         with self.utxo_table_model:
    #             self.utxo_table_model.beginResetModel()
    #             self.utxo_table_model.endResetModel()
    #         log.debug('Finished reset_utxos_view')
    #     WndUtils.call_in_main_thread(reset)
    #
    def hw_connected(self):
        if self.hw_session.hw_type is not None and self.hw_session.hw_client is not None:
            return True
        else:
            return False

    def disconnect_hw(self):
        self.main_ui.disconnect_hardware_wallet()

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
        if self.utxo_src_mode == 1:
            if self.hw_selected_account_id is not None:
                if self.hw_selected_address_id is None:
                    # list utxos of the whole bip44 account
                    list_utxos = self.bip44_wallet.list_utxos_for_account(self.hw_selected_account_id, only_new)
                else:
                    # list utxos of the specific address
                    list_utxos = self.bip44_wallet.list_utxos_for_addresses([self.hw_selected_address_id], only_new)
        elif self.utxo_src_mode == 2:
            address_ids = []
            for mni in self.selected_mns:
                if mni.address:
                    address_ids.append(mni.address.id)
            list_utxos = self.bip44_wallet.list_utxos_for_addresses(address_ids)
        else:
            raise Exception('Invalid utxo_src_mode')
        return list_utxos

    def data_thread(self, ctrl: CtrlObject):
        def check_break_fetch_process():
            if not self.allow_fetch_transactions or self.finishing or ctrl.finish or \
                last_hd_tree != self.hw_session.hd_tree_ident or \
                last_utxos_source_hash != self.cur_utxo_src_hash:
                raise BreakFetchTransactionsException('Break fetch transactions')

        log.debug('Starting fetch_transactions_thread')
        try:
            if self.utxo_src_mode == 1:
                self.connect_hw()

            self.last_txs_fetch_time = 0
            last_utxos_source_hash = ''
            last_hd_tree = ''

            while not ctrl.finish and not self.finishing:
                hw_error = False
                if self.utxo_src_mode == 1:  # the hw accounts view needs an hw connection
                    if not self.hw_connected():
                        hw_error = True

                    if not hw_error:
                        if last_hd_tree != self.hw_session.hd_tree_ident:
                            # not read hw accounts yet or switched to another hw/used another passphrase

                            with self.account_list_model:
                                self.account_list_model.clear_accounts()

                                # load the bip44 account list
                                for a in self.bip44_wallet.list_accounts():
                                    self.account_list_model.add_account(a)

                                self.account_list_model.sort_accounts()
                                self.reset_accounts_view()

                            last_hd_tree = self.hw_session.hd_tree_ident

                if not hw_error:
                    if self.finishing:
                        break

                    if last_utxos_source_hash != self.cur_utxo_src_hash:
                        # reload the utxo view
                        last_utxos_source_hash = self.cur_utxo_src_hash

                        list_utxos = self.get_utxo_generator(False)
                        if len(self.utxo_table_model.utxos) > 0:
                            with self.utxo_table_model:
                                self.utxo_table_model.beginResetModel()
                                self.utxo_table_model.clear_utxos()
                                self.utxo_table_model.endResetModel()

                        if list_utxos:
                            self.set_message_2('Loading data for display...')
                            log.debug('Fetching utxos from the database')
                            self.utxo_table_model.set_block_height(self.bip44_wallet.get_block_height())

                            t = time.time()
                            self.utxo_table_model.beginResetModel()
                            try:
                                with self.utxo_table_model:
                                    for utxo in list_utxos:
                                        if self.finishing:
                                            break
                                        self.utxo_table_model.add_utxo(utxo)
                            finally:
                                self.utxo_table_model.endResetModel()
                            log.debug('Reset UTXO model time: %s', time.time() - t)

                            log.debug('Fetching of utxos finished')
                            self.set_message_2('Displaying data...')

                        self.set_message_2('')

                    if self.last_txs_fetch_time == 0 or (time.time() - self.last_txs_fetch_time > FETCH_DATA_INTERVAL_SECONDS):
                        if self.allow_fetch_transactions:
                            self.set_message('Fetching transactions...')
                            if self.utxo_src_mode == 1:
                                fun_to_call = partial(self.bip44_wallet.fetch_all_accounts_txs, check_break_fetch_process)
                            elif self.utxo_src_mode == 2:
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
                                    self.call_fun_monitor_txs(fun_to_call, check_break_fetch_process)
                                    self.last_txs_fetch_time = int(time.time())
                                except BreakFetchTransactionsException:
                                    # the purpose of this exception is to break the fetch routine only
                                    pass

                                if not ctrl.finish and not self.finishing:
                                    self.set_message('')

                self.data_thread_event.wait(1)
                if self.data_thread_event.is_set():
                    self.data_thread_event.clear()

        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg(str(e))
        finally:
            self.data_thread_ref = None
        log.debug('Finishing fetch_transactions_thread')

    def call_fun_monitor_txs(self, function_to_call: Callable, check_break_execution_callback: Callable):
        """
        Call a (wallet) function which can result in adding/removing UTXOs and/or adding/removing
        transactions - those changes will be reflected in GUI after the call completes.
        :return:
        """
        accounts_modified = False
        with self.account_list_model:
            self.bip44_wallet.reset_tx_diffs()
            function_to_call()

            # fetching transactions may result in 'new' bip44 accounts with a non-zero 'received' balance
            self.bip44_wallet.reset_accounts_diffs()
            for a in self.bip44_wallet.list_accounts():
                pass

            for a in self.bip44_wallet.accounts_modified:
                self.account_list_model.add_account(a)
                accounts_modified = True

        if not check_break_execution_callback():
            if accounts_modified:
                self.account_list_model.sort_accounts()
                self.reset_accounts_view()

            list_utxos = self.get_utxo_generator(True)
            if list_utxos:
                self.utxo_table_model.set_block_height(self.bip44_wallet.get_block_height())

                new_utxos = []
                for utxo in list_utxos:
                    new_utxos.append(utxo)

                removed_utxos = [x for x in self.bip44_wallet.utxos_removed]

                if new_utxos or removed_utxos:
                    with self.utxo_table_model:
                        WndUtils.call_in_main_thread(self.utxo_table_model.update_utxos, new_utxos, removed_utxos)

    @pyqtSlot()
    def on_btnLoadTransactions_clicked(self):
        self.last_txs_fetch_time = 0
        self.data_thread_event.set()

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

    @pyqtSlot()
    def on_btnReconnectHW_clicked(self):
        self.allow_fetch_transactions = False

        # clear the utxo model data
        with self.utxo_table_model:
            self.utxo_table_model.beginResetModel()
            self.utxo_table_model.clear_utxos()
            self.utxo_table_model.endResetModel()

        # todo: clear transactions model

        # clear the account model data
        self.account_list_model.beginResetModel()
        self.account_list_model.clear_accounts()
        self.account_list_model.endResetModel()

        self.disconnect_hw()
        self.bip44_wallet.clear()
        self.allow_fetch_transactions = True
        if self.connect_hw():
            self.data_thread_event.set()
