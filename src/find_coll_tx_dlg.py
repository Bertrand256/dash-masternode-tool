#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import datetime
import logging
from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex
from PyQt5.QtWidgets import QMessageBox, QDialog, QLayout, QTableWidgetItem, QDialogButtonBox, QAbstractButton

import app_utils
import wnd_utils as wnd_utils
from dashd_intf import DashdIndexException
from ui import ui_find_coll_tx_dlg


# noinspection PyArgumentList,PyArgumentList
class FindCollateralTxDlg(QDialog, ui_find_coll_tx_dlg.Ui_FindCollateralTxDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf, dash_address, read_only):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, parent.config)
        self.main_wnd = parent
        self.dashd_intf = dashd_intf
        self.dash_address = dash_address
        self.utxos = []
        self.block_count = 0
        self.read_only = read_only
        self.setupUi()

    def setupUi(self):
        try:
            ui_find_coll_tx_dlg.Ui_FindCollateralTxDlg.setupUi(self, self)
            self.setWindowTitle('Find collateral transaction')
            self.edtAddress.setText(self.dash_address)
            self.lblMessage.setVisible(False)

            self.lblMessage.setVisible(True)
            self.lblMessage.setText('<span style="color:orange">Reading transactions, please wait...</span>')

            self.run_thread(self, self.load_utxos_thread, (), self.display_utxos)
            self.updateUi()
        except:
            logging.exception('Exception occurred')
            raise

    def updateUi(self):
        items = self.tableWidget.selectedItems()
        if not self.read_only and len(items) > 0:
            selected = True
        else:
            selected = False
        self.buttonBox.button(QDialogButtonBox.Apply).setEnabled(selected)

    def display_utxos(self):
        def item(value):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            return item

        self.tableWidget.setRowCount(len(self.utxos))
        for row, utxo in enumerate(self.utxos):
            self.tableWidget.setItem(row, 0, item(utxo.get('txid', None)))
            self.tableWidget.setItem(row, 1, item(str(utxo.get('outputIndex', None))))
            self.tableWidget.setItem(row, 2, item(utxo.get('time_str', None)))
            self.tableWidget.setItem(row, 3, item(str(utxo['confirmations'])))

        if len(self.utxos):
            self.tableWidget.resizeColumnsToContents()
            sh = self.sizeHint()
            sh.setWidth(sh.width() + 30)
            if sh.height() < 300:
                sh.setHeight(300)
            if sh.width() < 700:
                sh.setWidth(700)
            self.setBaseSize(sh)
            if self.read_only:
                msg = f'<span style="color:blue">Found 1000 Dash transaction(s):' \
                      f'</span>'
            else:
                msg = f'<span style="color:blue">Found 1000 Dash transaction(s). Click the "Apply" button to copy' \
                      f' the transaction id/index to the selected masternode configuration.</span>'

            self.lblMessage.setText(msg)
            self.lblMessage.setVisible(True)
            self.centerByWindow(self.main_wnd)
        else:
            self.lblMessage.setText('<span style="color:red">Found no unspent 1000 Dash transactions  '
                                    'sent to address %s.</span>' %
                                    self.dash_address)
            self.lblMessage.setVisible(True)

        self.updateUi()

    def load_utxos_thread(self, ctrl):
        try:
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    self.block_count = self.dashd_intf.getblockcount()
                    self.utxos = self.dashd_intf.getaddressutxos([self.dash_address])
                    self.utxos = [utxo for utxo in self.utxos if utxo['satoshis'] == 100000000000 ]

                    try:
                        # for each utxo read block time
                        for utxo in self.utxos:
                            blockhash = self.dashd_intf.getblockhash(utxo.get('height'))
                            bh = self.dashd_intf.getblockheader(blockhash)
                            utxo['time_str'] = app_utils.to_string(datetime.datetime.fromtimestamp(bh['time']))
                            utxo['confirmations'] = self.block_count - bh.get('height') + 1
                    except Exception as e:
                        self.errorMsg(str(e))

                except DashdIndexException as e:
                    self.errorMsg(str(e))

                except Exception as e:
                    self.errorMsg('Error occurred while calling getaddressutxos method: ' + str(e))
        except Exception as e:
            pass

    def getSelection(self):
        items = self.tableWidget.selectedItems()
        if len(items):
            row = items[0].row()
            return self.utxos[row]['txid'], self.utxos[row]['outputIndex']
        else:
            return None, None

    @pyqtSlot(QAbstractButton)
    def on_buttonBox_clicked(self, button):
        if button == self.buttonBox.button(QDialogButtonBox.Apply):
            self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.updateUi()

    @pyqtSlot(QModelIndex)
    def on_tableWidget_doubleClicked(self):
        if not self.read_only:
            self.accept()