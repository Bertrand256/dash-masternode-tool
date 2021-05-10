#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import datetime
import logging
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex, QUrl, QVariant
from PyQt5.QtGui import QDesktopServices, QColor
from PyQt5.QtWidgets import QMessageBox, QDialog, QLayout, QTableWidgetItem, QDialogButtonBox, QAbstractButton, \
    QTableView

import app_utils
import wnd_utils as wnd_utils
from app_config import MasternodeConfig, AppConfig
from bip44_wallet import UNCONFIRMED_TX_BLOCK_HEIGHT
from dashd_intf import DashdIndexException
from ext_item_model import ExtSortFilterTableModel, TableModelColumn
from ui import ui_find_coll_tx_dlg
from wallet_common import UtxoType


class CollTxsTableModel(ExtSortFilterTableModel):
    def __init__(self, parent, utxos: List[UtxoType], masternode_list: List[MasternodeConfig], tx_explorer_url: str):
        ExtSortFilterTableModel.__init__(self, parent, [
            TableModelColumn('address', 'Wallet address', True, 100),
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
            ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
            self.mn_by_collateral_tx[ident] = mn
            self.mn_by_collateral_address[mn.collateralAddress] = mn

        self.set_attr_protection()

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.utxos)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def set_view(self, table_view: QTableView):
        super().set_view(table_view)
        link_delagate = wnd_utils.HyperlinkItemDelegate(table_view)
        link_delagate.linkActivated.connect(self.hyperlink_activated)
        table_view.setItemDelegateForColumn(self.col_index_by_name('txid'), link_delagate)

    def hyperlink_activated(self, link):
        QDesktopServices.openUrl(QUrl(link))

    def get_utxo_mn_assignement(self, utxo: UtxoType) -> Optional[MasternodeConfig]:
        ident = utxo.txid + '-' + str(utxo.output_index)
        mn = self.mn_by_collateral_tx.get(ident)
        if not mn:
            mn = self.mn_by_collateral_address.get(utxo.address)
        return mn

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
                            elif field_name == 'bip32_path':
                                if utxo.address_obj:
                                    return utxo.address_obj.bip32_path
                                else:
                                    return '???'
                            elif field_name == 'assigned_to_mn':
                                mn = self.get_utxo_mn_assignement(utxo)
                                return mn.name if mn else ''
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
                    mn = self.get_utxo_mn_assignement(left_utxo)
                    left_value = mn.name if mn else ''
                    mn = self.get_utxo_mn_assignement(right_utxo)
                    right_value = mn.name if mn else ''
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


class ListCollateralTxsDlg(QDialog, ui_find_coll_tx_dlg.Ui_ListCollateralTxsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, edited_masternode: MasternodeConfig, app_config: AppConfig, read_only,
                 utxos: List[UtxoType]):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, app_config)
        self.app_config = app_config
        self.main_wnd = parent
        self.utxos = utxos
        self.edited_masternode: MasternodeConfig = edited_masternode
        self.block_count = 0
        self.read_only = read_only
        self.collaterals_table_model = CollTxsTableModel(self, utxos, self.app_config.masternodes,
                                                         self.app_config.get_block_explorer_tx())
        self.setupUi()

    def setupUi(self):
        try:
            ui_find_coll_tx_dlg.Ui_ListCollateralTxsDlg.setupUi(self, self)
            self.setWindowTitle('Find collateral transaction')
            self.collaterals_table_model.set_view(self.collsTableView)
            self.collsTableView.setSortingEnabled(True)
            self.collsTableView.setItemDelegate(wnd_utils.ReadOnlyTableCellDelegate(self.collsTableView))
            self.collsTableView.verticalHeader().setDefaultSectionSize(
                self.collsTableView.verticalHeader().fontMetrics().height() + 4)
            self.collsTableView.horizontalHeader().setSortIndicator(
                self.collaterals_table_model.col_index_by_name('time_stamp'), Qt.DescendingOrder)
            self.collsTableView.selectionModel().selectionChanged.connect(self.on_collsTableView_selectionChanged)

            for idx, col in enumerate(self.collaterals_table_model.columns()):
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
        sel_rows = self.collaterals_table_model.selected_rows()
        if sel_rows:
            rows = [x for x in sel_rows]
            return self.utxos[rows[0]]
        return None

    def check_accept_selections(self) -> bool:
        utxo = self.get_selected_utxo()
        if utxo:
            mn = self.collaterals_table_model.get_utxo_mn_assignement(utxo)
            if mn:
                if mn != self.edited_masternode and self.edited_masternode:
                    if wnd_utils.WndUtils.queryDlg(
                        "Do you really want to use the utxo that is already assigned to another masternode configuration?",
                        buttons=QMessageBox.Yes | QMessageBox.Cancel,
                        default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                        return False
            return True
        return False

    @pyqtSlot(QAbstractButton)
    def on_buttonBox_clicked(self, button):
        if button == self.buttonBox.button(QDialogButtonBox.Apply):
            if self.check_accept_selections():
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
            if self.check_accept_selections():
                self.accept()
