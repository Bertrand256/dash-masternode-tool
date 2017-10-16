#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import datetime
import logging
import random
from operator import itemgetter
import binascii
import os
from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSlot
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QTableView, QHeaderView, QMessageBox
import app_cache as cache
from app_config import MIN_TX_FEE, DATETIME_FORMAT, HWType
from dashd_intf import DashdInterface, DashdIndexException
from hw_intf import prepare_transfer_tx, get_address
from wnd_utils import WndUtils
from ui import ui_send_payout_dlg
from hw_common import HardwareWalletPinException
from app_config import SCREENSHOT_MODE


class PaymentTableModel(QAbstractTableModel):
    def __init__(self, parent, hide_collaterals_utxos, checked_changed_callback, parent_wnd):
        QAbstractTableModel.__init__(self, parent)
        self.checked = False
        self.utxos = []
        self.hide_collaterals_utxos = hide_collaterals_utxos
        self.checked_changed_callback = checked_changed_callback
        self.parent_wnd = parent_wnd
        self.columns = [
            # field_name, column header, visible, default col width
            ('satoshis', 'Amount (Dash)', True, 100),
            ('confirmations', 'Confirmations', True, 100),
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
                            if SCREENSHOT_MODE and field_name in ('address','txid'):
                                if field_name == 'address':
                                    return 'XkpD5B71qGFW6XvHVpnbPzbDQE19yfXjT8'
                                elif field_name == 'txid':
                                    return binascii.b2a_hex(os.urandom(32)).decode('ascii')
                            else:
                                return str(utxo.get(field_name, ''))
                    elif role == Qt.ForegroundRole:
                        if utxo['collateral']:
                            return QColor(Qt.red)
                        elif utxo['coinbase_locked']:
                            if col == 2:
                                return QtGui.QColor('red')
                            else:
                                return QtGui.QColor('gray')
                    elif role == Qt.BackgroundRole:
                        if utxo['coinbase_locked']:
                            return QtGui.QColor('lightgray')
        return QVariant()

    def setData(self, index, value, role=None):
        changed = False
        if index.isValid() and role == QtCore.Qt.CheckStateRole:
            row = index.row()
            utxo = self.getUtxo(row)
            if utxo:
                if value == QtCore.Qt.Checked:
                    if not utxo['coinbase_locked']:
                        utxo['checked'] = True
                        changed = True
                    else:
                        self.parent_wnd.warnMsg('This UTXO has less than 100 confirmations and cannot be sent.')
                else:
                    utxo['checked'] = False
                    changed = True

        if changed:
            self.dataChanged.emit(index, index)
            # notify - sum amount has changed
            if self.checked_changed_callback:
                self.checked_changed_callback()
            return True
        else:
            return False

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

        self.utxos = sorted(utxos, key=itemgetter('height'), reverse=True)

        for utxo in utxos:
            if utxo_assigned_to_collateral(utxo):
                utxo['collateral'] = True
                utxo['checked'] = False
            else:
                utxo['collateral'] = False
                if not utxo['coinbase_locked']:
                    utxo['checked'] = True
                else:
                    utxo['checked'] = False

            utxo['mn'] = mn_by_address(utxo['address'])

        self.beginResetModel()
        self.endResetModel()
        if self.checked_changed_callback:
            self.checked_changed_callback()


class SendPayoutDlg(QDialog, ui_send_payout_dlg.Ui_SendPayoutDlg, WndUtils):
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
        QDialog.__init__(self)
        WndUtils.__init__(self, main_ui.config)
        assert isinstance(utxos_source, list)
        assert isinstance(main_ui.dashd_intf, DashdInterface)
        self.utxos_source = utxos_source
        self.dashd_intf = main_ui.dashd_intf
        self.table_model = None
        self.source_address_mode = False
        self.utxos = []
        self.masternodes = main_ui.config.masternodes
        self.org_message = ''
        self.main_ui = main_ui
        self.setupUi()

    def setupUi(self):
        ui_send_payout_dlg.Ui_SendPayoutDlg.setupUi(self, self)
        assert isinstance(self.tableView, QTableView)
        self.resize(cache.get_value('WndPayoutWidth', 800, int),
                                cache.get_value('WndPayoutHeight', 460, int))
        self.setWindowTitle('Transfer funds')
        self.closeEvent = self.closeEvent
        self.chbHideCollateralTx.setChecked(True)
        self.edtDestAddress.setText(cache.get_value('WndPayoutPaymentAddress', '', str))
        self.edtDestAddress.textChanged.connect(self.edtDestAddressChanged)
        self.setIcon(self.btnCheckAll, 'check.png')
        self.setIcon(self.btnUncheckAll, 'uncheck.png')

        self.table_model = PaymentTableModel(None, self.chbHideCollateralTx.isChecked(), self.onUtxoCheckChanged, self)
        self.tableView.setModel(self.table_model)
        self.tableView.horizontalHeader().resizeSection(0, 35)
        self.tableView.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.tableView.verticalHeader().setDefaultSectionSize(self.tableView.verticalHeader().fontMetrics().height() + 6)

        # set utxo table default column widths
        cws = cache.get_value('WndPayoutColWidths', self.table_model.getDefaultColWidths(), list)
        for col, w in enumerate(cws):
            self.tableView.setColumnWidth(col, w)

        self.chbHideCollateralTx.toggled.connect(self.chbHideCollateralTxToggled)
        self.resizeEvent = self.resizeEvent

        if self.main_ui.config.hw_type == HWType.ledger_nano_s:
            self.pnlSourceAddress.setVisible(False)
            self.org_message = '<span style="color:red">Sending funds controlled by Ledger Nano S wallets not ' \
                               'supported yet.</span>'
            self.setMessage(self.org_message)
            self.load_utxos()
            self.btnSend.setEnabled(False)
        elif len(self.utxos_source):
            self.pnlSourceAddress.setVisible(False)
            self.org_message = 'List of Unspent Transaction Outputs <i>(UTXOs)</i> for specified address(es). ' \
                               'Select checkboxes for the UTXOs you wish to transfer.'
            self.setMessage(self.org_message)
            self.load_utxos()
        else:
            self.setMessage("")
            self.source_address_mode = True
            self.edtSourceBip32Path.setText(cache.get_value('SourceBip32Path', '', str))

    def closeEvent(self, event):
        w = self.size().width()
        h = self.size().height()
        cache.set_value('WndPayoutWidth', w)
        cache.set_value('WndPayoutHeight', h)
        # save column widths
        widths = []
        for col in range(self.table_model.columnCount()):
            widths.append(self.tableView.columnWidth(col))
        cache.set_value('WndPayoutColWidths', widths)
        if self.source_address_mode:
            cache.set_value('SourceBip32Path', self.edtSourceBip32Path.text())

    def setMessage(self, message):
        if not message:
            self.lblMessage.setVisible(False)
        else:
            self.lblMessage.setVisible(True)
            self.lblMessage.setText(message)

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

    @pyqtSlot(bool)
    def on_btnUncheckAll_clicked(self):
        for utxo in self.utxos:
            utxo['checked'] = False
        self.table_model.beginResetModel()
        self.table_model.endResetModel()
        self.onUtxoCheckChanged()

    @pyqtSlot(bool)
    def on_btnCheckAll_clicked(self):
        for utxo in self.utxos:
            if not utxo['coinbase_locked']:
                utxo['checked'] = True
        self.table_model.beginResetModel()
        self.table_model.endResetModel()
        self.onUtxoCheckChanged()

    @pyqtSlot()
    def on_btnSend_clicked(self):
        """
        Sends funds to Dash address specified by user.
        """
        utxos = self.table_model.getSelectedUtxos()
        if len(utxos):
            address = self.edtDestAddress.text()
            if address:
                if not self.main_ui.connectHardwareWallet():
                    return

                bip32_to_address = {}  # for saving addresses read from HW by BIP32 path

                # check if user selected masternode collateral transaction; if so display warning
                # also check if UTXO dash address matches address of BIP32 path in HW
                for utxo_idx, utxo in enumerate(utxos):
                    if utxo['collateral']:
                        if self.queryDlg(
                                "Warning: you are going to transfer Masternode's collateral (1000 Dash) transaction "
                                "output. Proceeding will result in broken Masternode.\n\n"
                                "Do you really want to continue?",
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                            return
                    bip32_path = utxo.get('bip32_path', None)
                    if not bip32_path:
                        self.errorMsg('No BIP32 path for UTXO: %s. Cannot continue.' % utxo['txid'])
                        return

                    addr_hw = bip32_to_address.get(bip32_path, None)
                    if not addr_hw:
                        addr_hw = get_address(self.main_ui, bip32_path)
                        bip32_to_address[bip32_path] = addr_hw
                    if addr_hw != utxo['address']:
                        self.errorMsg("Dash address inconsistency between UTXO (%d) and a HW's path: %s.\n\n"
                                     "<b>HW address</b>: %s\n"
                                     "<b>UTXO address</b>: %s\n\n"
                                     "Cannot continue." %
                                      (utxo_idx+1, bip32_path, addr_hw, utxo['address']))
                        return

                try:
                    if self.dashd_intf.validateaddress(address).get('isvalid', False):
                        fee = self.edtTxFee.value() * 1e8

                        try:
                            serialized_tx, amount_to_send = prepare_transfer_tx(self.main_ui, utxos, address, fee)
                        except Exception:
                            logging.exception('Exception when preparing the transaction.')
                            raise

                        tx_hex = serialized_tx.hex()
                        if len(tx_hex) > 90000:
                            self.errorMsg("Transaction's length exceeds 90000 bytes. Select less UTXOs and try again.")
                        else:
                            if SCREENSHOT_MODE:
                                self.warnMsg('Inside screenshot mode')

                            if self.queryDlg('Broadcast signed transaction?\n\n'
                                             '<b>Destination address</b>: %s\n'
                                             '<b>Amount to send</b>: %s Dash\n'
                                             '<b>Fee</b>: %s Dash\n'
                                             '<b>Size</b>: %d bytes' % ( address, str(round(amount_to_send / 1e8, 8)),
                                                                  str(round(fee / 1e8, 8) ),
                                                                  len(tx_hex)/2),
                                             buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                             default_button=QMessageBox.Yes) == QMessageBox.Yes:

                                # decoded_tx = self.dashd_intf.decoderawtransaction(tx_hex)

                                if SCREENSHOT_MODE:
                                    txid = '2195aecd5575e37fedf30e6a7ae317c6ba3650a004dc7e901210ac454f61a2e8'
                                else:
                                    txid = self.dashd_intf.sendrawtransaction(tx_hex)

                                if txid:
                                    block_explorer = self.main_ui.config.block_explorer_tx
                                    if block_explorer:
                                        url = block_explorer.replace('%TXID%', txid)
                                        message = 'Transaction sent. TX ID: <a href="%s">%s</a>' % (url, txid)
                                    else:
                                        message = 'Transaction sent. TX ID: %s' % txid

                                    logging.info('Sent transaction: ' + txid)
                                    self.infoMsg(message)
                                else:
                                    self.errorMsg('Problem with sending transaction: no txid returned')
                    else:
                        self.errorMsg('Invalid destination Dash address (%s).' % address)
                except Exception as e:
                    self.errorMsg(str(e))
            else:
                self.errorMsg('Missing destination Dash address.')
        else:
            self.errorMsg('No UTXO to send.')

    @pyqtSlot()
    def on_btnClose_clicked(self):
        self.close()

    def load_utxos(self):
        self.utxos = []
        self.threadFunctionDialog(self.load_utxos_thread, (), True, center_by_window=self.main_ui)
        self.table_model.setUtxos(self.utxos, self.masternodes)

        if len(self.utxos):
            for utxo in self.utxos:
                if utxo['coinbase_locked']:
                    self.setMessage(self.org_message + '<br><span style="color:red">There are UTXOs with not enough '
                                                       'confirmations (100) to spend them.</span>')
                    break

    def load_utxos_thread(self, ctrl):
        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            try:
                ctrl.dlg_config_fun(dlg_title="Loading Unspent Transaction Outputs...", show_message=True,
                                    show_progress_bar=False)
                ctrl.display_msg_fun('<b>Loading Unspent Transaction Outputs. Please wait...</b>')
                addresses = []
                for a in self.utxos_source:
                    if a[0] and a[0] not in addresses:
                        addresses.append(a[0])

                if len(addresses):
                    self.utxos = self.dashd_intf.getaddressutxos(addresses)

                try:
                    # for each utxo read block time
                    cur_block_height = self.dashd_intf.getblockcount()

                    for idx, utxo in enumerate(self.utxos):
                        blockhash = self.dashd_intf.getblockhash(utxo.get('height'))
                        bh = self.dashd_intf.getblockheader(blockhash)
                        utxo['time_str'] = datetime.datetime.fromtimestamp(bh['time']).strftime(DATETIME_FORMAT)
                        utxo['confirmations'] = cur_block_height - bh.get('height') + 1
                        utxo['coinbase_locked'] = False

                        try:
                            rawtx = self.dashd_intf.getrawtransaction(utxo.get('txid'), utxo.get('outputIndex'))
                            if rawtx:
                                if not isinstance(rawtx, dict):
                                    decodedtx = self.dashd_intf.decoderawtransaction(rawtx)
                                else:
                                    decodedtx = rawtx

                                if decodedtx:
                                    vin = decodedtx.get('vin')
                                    if len(vin) == 1 and vin[0].get('coinbase') and utxo['confirmations'] < 100:
                                        utxo['coinbase_locked'] = True
                        except Exception:
                            logging.exception('Error while verifying transaction coinbase')

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
                    self.errorMsg(str(e))

            except DashdIndexException as e:
                self.errorMsg(str(e))

            except Exception as e:
                self.errorMsg('Error occurred while calling getaddressutxos method: ' + str(e))

    @pyqtSlot()
    def on_btnLoadTransactions_clicked(self):
        if not self.main_ui.connectHardwareWallet():
            return

        try:
            path = self.edtSourceBip32Path.text()
            if path:
                # check if address mathes address read from bip32 path
                try:
                    address = get_address(self.main_ui, path)
                    if not address:
                        self.errorMsg("Couldn't read address for the specified BIP32 path: %s." % path)
                    self.utxos_source = [(address, path)]
                    self.load_utxos()
                    if len(self.utxos) == 0:
                        self.setMessage('<span style="color:red">There is no Unspent Transaction Outputs '
                                        '<i>(UTXOs)</i> for this address: %s.</span>' % address)
                    else:
                        self.setMessage('Unspent Transaction Outputs <i>(UTXOs)</i> for: %s.</span>' %
                                        address)

                except HardwareWalletPinException as e:
                    raise

                except Exception as e:
                    logging.exception('Exception while reading address for BIP32 path (%s).' % path)
                    self.errorMsg('Invalid BIP32 path.')
                    self.edtSourceBip32Path.setFocus()
            else:
                self.errorMsg('Enter the BIP32 path.')
                self.edtSourceBip32Path.setFocus()
        except Exception:
            logging.exception('Exception while loading unspent transaction outputs.')
            raise

    def on_edtSourceBip32Path_returnPressed(self):
        self.on_btnLoadTransactions_clicked()
