#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import datetime
import logging
from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex
from PyQt5.QtWidgets import QMessageBox, QDialog, QLayout, QTableWidgetItem, QDialogButtonBox
import wnd_utils as wnd_utils
from app_config import DATETIME_FORMAT
from dashd_intf import DashdIndexException
from ui import ui_find_coll_tx_dlg


class FindCollateralTxDlg(QDialog, ui_find_coll_tx_dlg.Ui_FindCollateralTxDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf, dash_address):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, parent.config)
        self.main_wnd = parent
        self.dashd_intf = dashd_intf
        self.dash_address = dash_address
        self.utxos = []
        self.block_count = 0
        self.setupUi()

    def setupUi(self):
        try:
            ui_find_coll_tx_dlg.Ui_FindCollateralTxDlg.setupUi(self, self)
            self.setWindowTitle('Find collateral transaction')
            self.edtAddress.setText(self.dash_address)
            self.lblMessage.setVisible(False)

            self.lblMessage.setVisible(True)
            self.lblMessage.setText('<b style="color:orange">Reading transactions, please wait...<b>')

            self.runInThread(self.load_utxos_thread, (), self.display_utxos)

            # self.threadFunctionDialog(self.load_utxos_thread, (), True, center_by_window=self.main_wnd)
            self.updateUi()
        except:
            logging.exception('Exception occurred')
            raise

    def updateUi(self):
        items = self.tableWidget.selectedItems()
        selected = len(items) > 0
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(selected)

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
            self.lblMessage.setVisible(False)
            self.centerByWindow(self.main_wnd)
        else:
            self.lblMessage.setText('<b style="color:red">Found no unspent transactions with 1000 Dash '
                                    'amount sent to address %s.<b>' %
                                    self.dash_address)
            self.lblMessage.setVisible(True)

        self.updateUi()

    def load_utxos_thread(self, ctrl):
        try:
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    # ctrl.dlg_config_fun(dlg_title="Loading unspent transaction outputs...",
                    #                     show_message=True,
                    #                     show_progress_bar=False)
                    # ctrl.display_msg_fun('<b>Loading unspent transaction outputs. Please wait...</b>')

                    self.block_count = self.dashd_intf.getblockcount()
                    self.utxos = self.dashd_intf.getaddressutxos([self.dash_address])
                    self.utxos = [utxo for utxo in self.utxos if utxo['satoshis'] == 100000000000 ]

                    try:
                        # for each utxo read block time
                        for utxo in self.utxos:
                            blockhash = self.dashd_intf.getblockhash(utxo.get('height'))
                            bh = self.dashd_intf.getblockheader(blockhash)
                            utxo['time_str'] = datetime.datetime.fromtimestamp(bh['time']).strftime(DATETIME_FORMAT)
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

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.updateUi()

    @pyqtSlot(QModelIndex)
    def on_tableWidget_doubleClicked(self):
        self.accept()