#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import datetime
from PyQt5 import QtCore
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, QThread
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QTableView, QStyledItemDelegate, QItemDelegate, QStyleOptionButton, QStyle, \
    QApplication, QHeaderView, QMessageBox
from PyQt5.uic.properties import QtGui
from decimal import Decimal
from operator import itemgetter
from src import wnd_send_payout_base
from src.dashd_intf import DashdInterface, DashdIndexException
from src.hw_intf import prepare_transfer_tx
from src.wnd_utils import WaitWidget, WndUtils
from src.app_config import MIN_TX_FEE
from src import app_cache as cache


class PaymentTableModel(QAbstractTableModel):
    def __init__(self, parent, hide_collaterals_utxos, checked_changed_callback):
        QAbstractTableModel.__init__(self, parent)
        self.checked = False
        self.utxos = []
        self.hide_collaterals_utxos = hide_collaterals_utxos
        self.checked_changed_callback = checked_changed_callback
        self.columns = [
            # field_name, column header, visible, default col width
            ('satoshis', 'Amount (Dash)', True, 100),
            ('time_str', 'TX Date/Time', True, 140),
            ('mn', 'Masternode', True, 80),
            ('address', 'Address', True, 140),
            ('txid', 'TX ID', True, 220),
            ('outputIndex', 'TX Idx', True, 40)
        ]

    def setHideCollateralsUtxos(self, hide):
        self.hide_collaterals_utxos = hide
        self.beginResetModel()
        self.endResetModel()

    def columnCount(self, parent=None, *args, **kwargs):
        return len(self.columns) + 1

    def rowCount(self, parent=None, *args, **kwargs):
        rows = 0
        for utxo in self.utxos:
            if not self.hide_collaterals_utxos or not utxo.get('collateral', False):
                rows += 1
        return rows

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            if section > 0:  # section 0 - checkboxes
                if section - 1 < len(self.columns):
                    return self.columns[section - 1][1]
            return ''
        else:
            return "Row"

    def getDefaultColWidths(self):
        widths = [col[3] for col in self.columns]
        widths.insert(0, 35)  # col width for checkbox column
        return widths

    def flags(self, index):
        if index.column() == 0:
            ret = Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
        else:
            ret = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return ret

    def getUtxo(self, index):
        """
        Returns utxo by its index. If self.hide_collaterals_utxos is True, utxo with 'collateral' value 
        set to True is skipped.
        :return: utxo dict
        """
        cur_idx = 0
        for utxo in self.utxos:
            if self.hide_collaterals_utxos and utxo.get('collateral', False):
                continue
            if cur_idx == index:
                return utxo
            cur_idx += 1
        return None

    def data(self, index, role=None):
        if index.isValid():
            col = index.column()
            row = index.row()
            if row < len(self.utxos):
                utxo = self.getUtxo(row)
                if utxo:
                    if col == 0:
                        # select tx checbox
                        if role == Qt.CheckStateRole:
                            return QVariant(Qt.Checked if utxo.get('checked', False) else Qt.Unchecked)
                    elif role == Qt.DisplayRole:
                        field_name = self.columns[col-1][0]
                        if field_name == 'satoshis':
                            return str(round(utxo['satoshis'] / 1e8, 8))
                        else:
                            return str(utxo.get(field_name, ''))
                    # elif role == QtCore.Qt.FontRole:
                    elif role == Qt.ForegroundRole:
                        if utxo['collateral']:
                            return QColor(Qt.red)
        return QVariant()

    def setData(self, index, value, role=None):
        if index.isValid() and role == QtCore.Qt.CheckStateRole:
            row = index.row()
            utxo = self.getUtxo(row)
            if utxo:
                if value == QtCore.Qt.Checked:
                    utxo['checked'] = True
                else:
                    utxo['checked'] = False
        self.dataChanged.emit(index, index)
        # notify - sum amount has changed
        if self.checked_changed_callback:
            self.checked_changed_callback()
        return True

    def getCheckedSumAmount(self):
        # sum amount of all checked utxos
        amount = 0
        for utxo in self.utxos:
            if self.hide_collaterals_utxos and utxo.get('collateral', False):
                continue
            if utxo['checked']:
                amount += utxo['satoshis']
        return amount

    def getSelectedUtxos(self):
        utxos = []
        for utxo in self.utxos:
            if self.hide_collaterals_utxos and utxo.get('collateral', False):
                continue
            if utxo['checked']:
                utxos.append(utxo)
        return utxos

    def setUtxos(self, utxos, masternodes):
        def utxo_assigned_to_collateral(utxo):
            for mn in masternodes:
                if mn.collateralTx == utxo['txid'] and str(mn.collateralTxIndex) == str(utxo['outputIndex']):
                    return True
            return False
        def mn_by_address(address):
            for mn in masternodes:
                if mn.collateralAddress == address:
                    return mn.name
            return ''

        for utxo in utxos:
            if utxo_assigned_to_collateral(utxo):
                utxo['collateral'] = True
                utxo['checked'] = False
            else:
                utxo['collateral'] = False
                utxo['checked'] = True
            utxo['mn'] = mn_by_address(utxo['address'])

        self.utxos = sorted(utxos, key=itemgetter('height'), reverse=True)
        self.beginResetModel()
        self.endResetModel()
        if self.checked_changed_callback:
            self.checked_changed_callback()


class Ui_DialogSendPayout(QThread, wnd_send_payout_base.Ui_DialogSendPayout, WndUtils):
    error_signal = QtCore.pyqtSignal(str)
    thread_finished = QtCore.pyqtSignal()

    def __init__(self, utxos_source, main_ui):
        """
        Constructor
        :param utxos_source: list of tuples (dash address, bip32 path) - from which
            we'll list all unspent outputs
        :param masternodes: list of masternodes in configuration; used for checking if txid/index 
            is assigned to mn's collateral 
        """
        QThread.__init__(self)
        assert isinstance(utxos_source, list)
        assert isinstance(main_ui.dashd_intf, DashdInterface)
        self.utxos_source = utxos_source
        self.dashd_intf = main_ui.dashd_intf
        self.table_model = None
        self.utxos = []
        self.masternodes = main_ui.config.masternodes
        self.main_ui = main_ui

    def setupUi(self, DialogSendPayout):
        wnd_send_payout_base.Ui_DialogSendPayout.setupUi(self, DialogSendPayout)
        assert isinstance(self.tableView, QTableView)
        DialogSendPayout.resize(cache.get_value('WndPayoutWidth', 800, int),
                                cache.get_value('WndPayoutHeight', 460, int))
        DialogSendPayout.setWindowTitle('Transfer funds')
        DialogSendPayout.closeEvent = self.closeEvent
        self.window = DialogSendPayout
        self.chbHideCollateralTx.setChecked(True)
        self.btnClose.clicked.connect(self.btnCloseClick)
        self.btnSend.clicked.connect(self.btnSendClick)
        self.edtDestAddress.setText(cache.get_value('WndPayoutPaymentAddress', '', str))
        self.edtDestAddress.textChanged.connect(self.edtDestAddressChanged)

        self.table_model = PaymentTableModel(None, self.chbHideCollateralTx.isChecked(), self.onUtxoCheckChanged)
        self.tableView.setModel(self.table_model)
        self.tableView.horizontalHeader().resizeSection(0, 35)
        self.tableView.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.tableView.verticalHeader().setDefaultSectionSize(self.tableView.verticalHeader().fontMetrics().height() + 6)

        # set utxo table default column widths
        cws = cache.get_value('WndPayoutColWidths', self.table_model.getDefaultColWidths(), list)
        for col, w in enumerate(cws):
            self.tableView.setColumnWidth(col, w)

        self.chbHideCollateralTx.toggled.connect(self.chbHideCollateralTxToggled)
        DialogSendPayout.resizeEvent = self.resizeEvent

        # check dashd_intf connection to avoid showing message boxes within thread
        # TODO: messageboxes from inside a thread
        self.waitWidget = None
        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            self.waitWidget = WaitWidget(self.tableView)
            self.waitWidget.show()
            self.error_signal.connect(WndUtils.errorMsg)
            self.thread_finished.connect(self.threadFinished)
            self.start()

    def closeEvent(self, event):
        w = self.window.size().width()
        h = self.window.size().height()
        cache.set_value('WndPayoutWidth', w)
        cache.set_value('WndPayoutHeight', h)
        # save column widths
        widths = []
        for col in range(self.table_model.columnCount()):
            widths.append(self.tableView.columnWidth(col))
        cache.set_value('WndPayoutColWidths', widths)

    def edtDestAddressChanged(self):
        # save payment address to cache
        cache.set_value('WndPayoutPaymentAddress', self.edtDestAddress.text())

    def chbHideCollateralTxToggled(self):
        self.table_model.setHideCollateralsUtxos(self.chbHideCollateralTx.isChecked())

    def onUtxoCheckChanged(self):
        self.lblAmount.setText(str(round(self.table_model.getCheckedSumAmount() / 1e8, 8)))

        # estimate transaction fee
        utxos = self.table_model.getSelectedUtxos()
        fee = round((len(utxos) * 148 + 33 - 10) / 1000) * MIN_TX_FEE
        if not fee:
            fee = MIN_TX_FEE
        self.edtTxFee.setValue(round(fee / 1e8, 8))

    def btnSendClick(self):
        """test
        Sends funds to Dash address specified by user.
        """
        utxos = self.table_model.getSelectedUtxos()
        if len(utxos):
            # check if user selected masternode collateral transaction; if so display warning
            for utxo in utxos:
                if utxo['collateral']:
                    if self.queryDlg("Warning: you are going to transfer Masternode's collateral (1000 Dash) transaction "
                                     "output. Proceeding will result in broken Masternode.\n\n"
                                     "Do you really want to continue?",
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                     default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                        return

            address = self.edtDestAddress.text()
            if address:
                if self.dashd_intf.validateaddress(address).get('isvalid', False):
                    try:
                        fee = self.edtTxFee.value() * 1e8
                        serialized_tx, amount_to_send = prepare_transfer_tx(self.main_ui, utxos, address, fee)
                        tx_hex = serialized_tx.hex()
                        if len(tx_hex) > 90000:
                            self.errorMsg("Transaction's length exceeds 90000 bytes. Select less utxo's and try again.")
                        else:
                            if self.queryDlg('Broadcast signed transaction?\n\n'
                                             'Destination address: %s\n'
                                             'Amount to send: %s Dash\nFee: %s Dash\n'
                                             'Size: %d bytes' % ( address, str(round(amount_to_send / 1e8, 8)),
                                                                  str(round(fee / 1e8, 8) ),
                                                                  len(tx_hex)/2),
                                             buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                             default_button=QMessageBox.Yes) == QMessageBox.Yes:

                                decoded_tx = self.dashd_intf.decoderawtransaction(tx_hex)
                                txid = self.dashd_intf.sendrawtransaction(tx_hex)
                                if txid:
                                    self.infoMsg('Transaction sent. ID: ' + txid)
                                else:
                                    self.errorMsg('Problem with sending transaction: no txid returned')

                    except Exception as e:
                        self.errorMsg(str(e))
                else:
                    self.errorMsg('Invalid destination Dash address (%s).' % address)
            else:
                self.errorMsg('Missing destination Dash address.')
        else:
            self.errorMsg('No utxo to send.')

    def btnCloseClick(self):
        self.window.close()

    def resizeEvent(self, event):
        if self.waitWidget:
            self.waitWidget.resize(event.size())
        event.accept()

    def threadFinished(self):
        if self.waitWidget:
            self.waitWidget.hide()
        self.table_model.setUtxos(self.utxos, self.masternodes)

    def run(self):
        try:
            addresses = []
            for a in self.utxos_source:
                if a[0] and a[0] not in addresses:
                    addresses.append(a[0])

            if len(addresses):
                self.utxos = self.dashd_intf.getaddressutxos(addresses)

            try:
                # for each utxo read block time
                for utxo in self.utxos:
                    blockhash = self.dashd_intf.getblockhash(utxo.get('height'))
                    bh = self.dashd_intf.getblockheader(blockhash)
                    utxo['time_str'] = datetime.datetime.fromtimestamp(bh['time']).strftime('%Y-%m-%d %H:%M')

                    # for a given utxo dash address find its bip32 path
                    found = False
                    for a in self.utxos_source:
                        if a[0] == utxo['address']:
                            utxo['bip32_path'] = a[1]
                            found = True
                            break
                    if not found:
                        raise Exception('UTXO address mismatch')

            except Exception as e:
                self.error_signal.emit(str(e))

        except DashdIndexException as e:
            self.error_signal.emit(str(e))

        except Exception as e:
            self.error_signal.emit('Error occurred while calling getaddressutxos method: ' + str(e))

        self.thread_finished.emit()