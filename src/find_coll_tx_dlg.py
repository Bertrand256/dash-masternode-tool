#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import logging
from typing import List, Optional, Literal, Callable, cast

from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex, QUrl, QVariant
from PyQt5.QtGui import QDesktopServices, QColor
from PyQt5.QtWidgets import QMessageBox, QDialog, QDialogButtonBox, QAbstractButton, \
    QTableView

import app_utils
import wnd_utils
from app_config import MasternodeConfig, MasternodeType, AppConfig
from bip44_wallet import UNCONFIRMED_TX_BLOCK_HEIGHT, Bip44Wallet, BreakFetchTransactionsException
from ext_item_model import TableModelColumn, ExtSortFilterItemModel
from ui import ui_find_coll_tx_dlg
from wallet_common import UtxoType
from thread_fun_dlg import CtrlObject
import hw_intf


class UtxosTableModel(ExtSortFilterItemModel):
    def __init__(self, parent, utxos: List[UtxoType], masternode_list: List[MasternodeConfig], tx_explorer_url: str):
        ExtSortFilterItemModel.__init__(self, parent, [
            TableModelColumn('address', 'Wallet address', True, 100),
            TableModelColumn('value', 'Value', True, 100),
            TableModelColumn('bip32_path', 'Wallet path', True, 100),
            TableModelColumn('assigned_to_mn', 'Assigned to MN', True, 100),
            TableModelColumn('time_stamp', 'TX date/time', True, 80),
            TableModelColumn('confirmations', 'Confirmations', True, 80),
            TableModelColumn('txid', 'TX hash', True, 140),
            TableModelColumn('output_index', 'TX index', True, 30),
        ], True, True)
        self.utxos: List[UtxoType] = utxos
        self.mn_by_collateral_tx = {}
        self.mn_by_collateral_address = {}
        self.tx_explorer_url = tx_explorer_url

        for mn in masternode_list:
            ident = mn.collateral_tx + '-' + str(mn.collateral_tx_index)
            self.mn_by_collateral_tx[ident] = mn
            self.mn_by_collateral_address[mn.collateral_address] = mn

        # assign masternodes to UTXOs
        for utxo in self.utxos:
            if not utxo.masternode:
                ident = utxo.txid + '-' + str(utxo.output_index)
                mn = self.mn_by_collateral_tx.get(ident)
                if mn:
                   utxo.masternode = mn

        self.set_attr_protection()

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.utxos)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def set_view(self, table_view: QTableView):
        super().set_view(table_view)
        link_delegate = wnd_utils.HyperlinkItemDelegate(table_view)
        link_delegate.linkActivated.connect(self.hyperlink_activated)
        table_view.setItemDelegateForColumn(self.col_index_by_name('txid'), link_delegate)

    def hyperlink_activated(self, link):
        QDesktopServices.openUrl(QUrl(link))

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.utxos):
                utxo = self.utxos[row_idx]
                if utxo:
                    if role in (Qt.DisplayRole, Qt.EditRole):
                        col = self.col_by_index(col_idx)
                        if col:
                            field_name = col.name
                            if field_name == 'address':
                                if utxo.address:
                                    return utxo.address
                                else:
                                    return '???'
                            elif field_name == 'value':
                                return round(utxo.satoshis / 1e8, 3)
                            elif field_name == 'bip32_path':
                                if utxo.address_obj:
                                    return utxo.address_obj.bip32_path
                                else:
                                    return '???'
                            elif field_name == 'assigned_to_mn':
                                return utxo.masternode.name if utxo.masternode else ''
                            elif field_name == 'txid':
                                if self.tx_explorer_url:
                                    url = self.tx_explorer_url.replace('%TXID%', utxo.txid)
                                    url = f'<a href="{url}">{utxo.txid}</a>'
                                    return url
                                else:
                                    return utxo.txid
                            elif field_name == 'output_index':
                                return utxo.output_index
                            elif field_name == 'time_stamp':
                                return utxo.time_str
                            elif field_name == 'confirmations':
                                if utxo.block_height == UNCONFIRMED_TX_BLOCK_HEIGHT:
                                    return 'Unconfirmed'
                                else:
                                    return app_utils.to_string(utxo.__getattribute__(field_name))
                            else:
                                return app_utils.to_string(utxo.__getattribute__(field_name))
                    elif role == Qt.ForegroundRole:
                        if utxo.is_collateral:
                            return QColor(Qt.red)
                        elif utxo.coinbase_locked:
                            if col_idx == 1:
                                return QColor('red')
                            else:
                                return QColor('gray')

                    elif role == Qt.BackgroundRole:
                        if utxo.coinbase_locked:
                            return QColor('lightgray')

                    elif role == Qt.TextAlignmentRole:
                        col = self.col_by_index(col_idx)
                        if col:
                            if col.name in ('satoshis', 'confirmations', 'output_index'):
                                return Qt.AlignRight

        return QVariant()

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
                right_utxo = self.utxos[right_row_index]
                if col_name == 'assigned_to_mn':
                    left_value = left_utxo.masternode.name if left_utxo.masternode else ''
                    right_value = right_utxo.masternode.name if right_utxo.masternode else ''
                else:
                    left_value = left_utxo.__getattribute__(col_name)
                    right_value = right_utxo.__getattribute__(col_name)

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


class WalletUtxosListDlg(QDialog, ui_find_coll_tx_dlg.Ui_ListCollateralTxsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, app_config: AppConfig, read_only, utxo_value_to_find: float,
                 utxos: List[UtxoType]):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, app_config)
        self.app_config = app_config
        self.main_wnd = parent
        self.utxos = utxos
        self.utxo_value_to_find: float = utxo_value_to_find
        self.block_count = 0
        self.read_only = read_only
        self.utxos_table_model = UtxosTableModel(self, utxos, self.app_config.masternodes,
                                                 self.app_config.get_block_explorer_tx())
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        try:
            ui_find_coll_tx_dlg.Ui_ListCollateralTxsDlg.setupUi(self, self)
            self.setWindowTitle('Find unspent transaction outputs')
            self.utxos_table_model.set_view(self.collsTableView)
            self.collsTableView.setSortingEnabled(True)
            self.collsTableView.setItemDelegate(wnd_utils.ReadOnlyTableCellDelegate(self.collsTableView))
            self.collsTableView.verticalHeader().setDefaultSectionSize(
                self.collsTableView.verticalHeader().fontMetrics().height() + 4)
            self.collsTableView.horizontalHeader().setSortIndicator(
                self.utxos_table_model.col_index_by_name('time_stamp'), Qt.DescendingOrder)
            self.collsTableView.selectionModel().selectionChanged.connect(self.on_collsTableView_selectionChanged)

            for idx, col in enumerate(self.utxos_table_model.columns()):
                if col.name != 'txid':
                    self.collsTableView.resizeColumnToContents(idx)

            self.updateUi()
            self.display_title()
        except:
            logging.exception('Exception occurred')
            raise

    def updateUi(self):
        idx = self.collsTableView.currentIndex()
        if not self.read_only and idx.isValid():
            selected = True
        else:
            selected = False
        self.buttonBox.button(QDialogButtonBox.Apply).setEnabled(selected)

    def display_title(self):
        if len(self.utxos):
            if self.read_only:
                msg = f'<span>Found 1000 Firo transaction(s):</span>'
            else:
                msg = f'<span><b>Select the appropriate UTXO then press the &lt;Apply&gt; button or ' \
                      f'double click on the corresponding row.</b></span>'

            self.lblMessage.setText(msg)
            self.lblMessage.setVisible(True)
        else:
            self.lblMessage.setText('<span style="color:red"><b>Found no unspent 1000 Firo transactions in your '
                                    'wallet</b></span>')
            self.lblMessage.setVisible(True)

    def get_selected_utxo(self):
        sel_rows = self.utxos_table_model.selected_rows()
        if sel_rows:
            rows = [x for x in sel_rows]
            return self.utxos[rows[0]]
        return None

    @pyqtSlot(QAbstractButton)
    def on_buttonBox_clicked(self, button):
        if button == self.buttonBox.button(QDialogButtonBox.Apply):
            self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    @pyqtSlot()
    def on_collsTableView_selectionChanged(self):
        self.updateUi()

    @pyqtSlot(QModelIndex)
    def on_collsTableView_doubleClicked(self):
        if not self.read_only:
            self.accept()

    @staticmethod
    def select_utxo_from_wallet_dialog(
            parent_dialog,
            utxo_value_to_find: float,
            app_config: AppConfig,
            dashd_intf: 'DashdInterface',
            limit_utxos_to_address: Optional[str],
            hw_session: hw_intf.HwSessionInfo,
            apply_utxo_fun: Callable,
            auto_apply_if_one: bool = True
    ) -> bool:
        try:
            break_scanning = False

            if not hw_session.connect_hardware_wallet():
                return False

            def do_break_scanning():
                nonlocal break_scanning
                break_scanning = True
                return False

            def check_break_scanning():
                nonlocal break_scanning
                return break_scanning

            bip44_wallet = Bip44Wallet(app_config.hw_coin_name, hw_session,
                                       app_config.db_intf, dashd_intf,
                                       app_config.dash_network)

            utxos = wnd_utils.WndUtils.run_thread_dialog(
                WalletUtxosListDlg.find_utxos_in_wallet_thread,
                (bip44_wallet, utxo_value_to_find, check_break_scanning, limit_utxos_to_address),
                True, force_close_dlg_callback=do_break_scanning)

            if utxos:
                if len(utxos) == 1 and auto_apply_if_one:
                    apply_utxo_fun(utxos[0])
                else:
                    dlg = WalletUtxosListDlg(parent_dialog, app_config, False, utxo_value_to_find, utxos)
                    if dlg.exec_():
                        utxo = dlg.get_selected_utxo()
                        if utxo:
                            apply_utxo_fun(utxo)
            else:
                return False
            return True
        except Exception as e:
            raise

    @staticmethod
    def find_utxos_in_wallet_thread(ctrl: CtrlObject,
                                    bip44_wallet: Bip44Wallet,
                                    utxo_value_to_find: int,
                                    check_break_scanning_ext: Callable[[], bool],
                                    limit_utxos_to_address: str):
        utxos = []
        break_scanning = False
        txes_cnt = 0
        msg = f'Scanning wallet transactions for {utxo_value_to_find} Dash UTXOs.<br>' \
              'This may take a while (<a href="break">break</a>)....'
        ctrl.dlg_config(dlg_title="Scanning wallet", show_progress_bar=False)
        ctrl.display_msg(msg)

        def check_break_scanning():
            nonlocal break_scanning
            if break_scanning:
                # stop the scanning process if the dialog finishes or the address/bip32path has been found
                raise BreakFetchTransactionsException()
            if check_break_scanning_ext is not None and check_break_scanning_ext():
                raise BreakFetchTransactionsException()

        def fetch_txes_feedback(tx_cnt: int):
            nonlocal msg, txes_cnt
            txes_cnt += tx_cnt
            ctrl.display_msg(msg + '<br><br>' + 'Number of transactions fetched so far: ' + str(txes_cnt))

        def on_msg_link_activated(link: str):
            nonlocal break_scanning
            if link == 'break':
                break_scanning = True

        lbl = ctrl.get_msg_label_control()
        if lbl:
            def set():
                lbl.setOpenExternalLinks(False)
                lbl.setTextInteractionFlags(lbl.textInteractionFlags() & ~Qt.TextSelectableByMouse)
                lbl.linkActivated.connect(on_msg_link_activated)
                lbl.repaint()

            wnd_utils.WndUtils.call_in_main_thread(set)

        try:
            bip44_wallet.on_fetch_account_txs_feedback = fetch_txes_feedback
            addr = bip44_wallet.scan_wallet_for_address(limit_utxos_to_address, check_break_scanning,
                                                        feedback_fun=fetch_txes_feedback)

            if addr and addr.tree_id == bip44_wallet.get_tree_id():
                bip44_wallet.fetch_addresses_txs([addr], check_break_scanning)
                for utxo in bip44_wallet.list_utxos_for_addresses(
                        [addr.id], filter_by_satoshis=int(utxo_value_to_find * 1e8)):
                    utxos.append(utxo)

            if not utxos:
                bip44_wallet.fetch_all_accounts_txs(check_break_scanning)
                for utxo in bip44_wallet.list_utxos_for_account(
                        account_id=None, filter_by_satoshis=int(utxo_value_to_find * 1e8)):
                    utxos.append(utxo)

        except BreakFetchTransactionsException:
            return None
        return utxos