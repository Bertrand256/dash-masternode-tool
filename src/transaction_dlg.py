#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-03
import sys

import re
from typing import Optional, Callable, Dict, List
import simplejson
import logging

from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QDialog, QMessageBox
from decimal import Decimal

from bitcoinrpc.authproxy import JSONRPCException

import app_cache
import app_utils
from app_config import AppConfig
from dashd_intf import DashdInterface
from ui.ui_transaction_dlg import Ui_TransactionDlg
from wallet_common import UtxoType, TxOutputType
from wnd_utils import WndUtils


CACHE_ITEM_DETAILS_WORD_WRAP = 'TransactionDlg_DetailsWordWrap'


log = logging.getLogger('dmt.transaction_dlg')


class TransactionDlg(QDialog, Ui_TransactionDlg, WndUtils):
    def __init__(self, parent: QDialog,
                 config: AppConfig,
                 dashd_intf: DashdInterface,
                 raw_transaction: str,
                 use_instant_send: bool,
                 tx_inputs: List[UtxoType],
                 tx_outputs: List[TxOutputType],
                 after_send_tx_callback: Callable[[dict], None],
                 decoded_transaction: Optional[dict] = None,
                 dependent_transactions: Optional[dict] = None,
                 ):
        QDialog.__init__(self, parent=parent)
        Ui_TransactionDlg.__init__(self)
        WndUtils.__init__(self, config)
        self.config = config
        self.parent = parent
        self.dashd_intf = dashd_intf
        self.transaction_sent = False
        self.raw_transaction = raw_transaction
        self.use_instant_send = use_instant_send
        self.tx_inputs = tx_inputs
        self.tx_outputs = tx_outputs
        self.tx_id = None  # will be decoded from rawtransaction
        self.tx_size = None  # as above
        self.decoded_transaction: Optional[dict] = decoded_transaction
        self.dependent_transactions = dependent_transactions  # key: txid, value: transaction dict
        self.after_send_tx_callback: Callable[[Dict], None] = after_send_tx_callback
        self.setupUi()

    def setupUi(self):
        Ui_TransactionDlg.setupUi(self, self)
        self.setWindowTitle('Transaction')
        self.chb_word_wrap.setChecked(app_cache.get_value(CACHE_ITEM_DETAILS_WORD_WRAP, False, bool))
        self.apply_word_wrap(self.chb_word_wrap.isChecked())
        self.edt_recipients.setOpenExternalLinks(True)
        self.edt_recipients.viewport().setAutoFillBackground(False)
        self.prepare_tx_view()

    def on_chb_word_wrap_toggled(self, checked):
        app_cache.set_value(CACHE_ITEM_DETAILS_WORD_WRAP, checked)
        self.apply_word_wrap(checked)

    def apply_word_wrap(self, checked):
        self.edt_raw_transaction.setWordWrapMode(0 if not checked else 1)

    def prepare_tx_view(self):
        def get_vout_value(vout: dict):
            val = vout.get('value')
            if not isinstance(val, (float, Decimal)):
                val = vout.get('valueSat')
                if val is not None:
                    val = round(val / 1e8, 8)
            return float(val)

        try:
            self.edt_recipients.clear()
            if not self.decoded_transaction:
                try:
                    self.decoded_transaction = self.dashd_intf.decoderawtransaction(self.raw_transaction)
                    self.decoded_transaction['hex'] = self.raw_transaction

                    # fill up the missing fields for this new (not yet unpublished) transaction which will
                    # be needed when registering pending transaction in cache
                    vins = self.decoded_transaction.get('vin')
                    if vins:
                        for idx, vin in enumerate(vins):
                            if idx < len(self.tx_inputs):
                                inp = self.tx_inputs[idx]
                                if not vin.get('valueSat'):
                                    vin['valueSat'] = inp.satoshis
                                if not vin.get('value'):
                                    vin['value'] = round(inp.satoshis / 1e8, 8)
                                if not vin.get('address'):
                                    vin['address'] = inp.address
                            else:
                                log.warning('Input index of the decoded transaction does not exist in the input list')

                except JSONRPCException as e:
                    if re.match('.*400 Bad Request', str(e)) and len(self.raw_transaction):
                        raise Exception('Error while decoding raw transaction: ' + str(e) + '.' +
                                        '\n\nProbable cause: size of the transation exceeded the RPC node limit.'
                                        '\n\nDecrease the number of inputs.')
                    else:
                        raise Exception('Error while decoding raw transaction: ' + str(e) + '.')
                except Exception as e:
                    raise Exception('Error while decoding raw transaction: ' +  str(e) + '.')

            if isinstance(self.decoded_transaction, dict):
                self.edt_raw_transaction.setPlainText(simplejson.dumps(self.decoded_transaction, indent=2))

                vout_list = self.decoded_transaction.get('vout')
                self.tx_size = self.decoded_transaction.get('size')
                self.tx_id = self.decoded_transaction.get('txid')

                if vout_list and isinstance(vout_list, list):

                    vin_list = self.decoded_transaction.get('vin')
                    if vin_list and isinstance(vin_list, list):
                        inputs_total = 0.0
                        for vin in vin_list:
                            txid = vin.get('txid')
                            txindex = vin.get('vout')

                            rawtx = None
                            if isinstance(self.dependent_transactions, dict):
                                rawtx = self.dependent_transactions.get(txid)

                            if not rawtx:
                                rawtx = self.dashd_intf.getrawtransaction(txid, 1)

                            if rawtx:
                                vlist = rawtx.get('vout')
                                val = None
                                for v in vlist:
                                    if v.get('n') == txindex:
                                        val = get_vout_value(v)
                                        break
                                if val is None:
                                    log.error(f'Couldn\'t find output {txindex} in source transaction {txid}')
                                else:
                                    inputs_total += val

                        if self.tx_size is not None:
                            if self.tx_size > 1024:
                                tx_size_str = f'{round(self.tx_size/1024, 2)} kB'
                            else:
                                tx_size_str = f'{self.tx_size} bytes'

                        # prepare the list of recipients
                        outputs_total = 0.0
                        recipients = ''
                        for row_idx, vout in enumerate(vout_list):
                            val = get_vout_value(vout)
                            outputs_total += val
                            spk = vout.get('scriptPubKey')
                            address = ''
                            if spk:
                                ads = spk.get('addresses')
                                if isinstance(ads, list) and len(ads) == 1:
                                    address = ads[0]
                                else:
                                    address = str(ads)

                            address_info = ''
                            if row_idx < len(self.tx_outputs):
                                tx_out = self.tx_outputs[row_idx]
                                if tx_out.address_ref:
                                    if tx_out.address_ref.is_change:
                                        address_info = f' (the change {tx_out.address_ref.bip32_path})'
                                    elif tx_out.address_ref.tree_id:
                                        address_info = f' (yours)'

                            if row_idx == 0:
                                recipients = f'<tr><td class="lbl"><p class="lbl">Recipients:</p></td><td>{address} {address_info}</td><td><p class="val">{app_utils.to_string(val)} Dash</p></td><td></td></tr>'
                            else:
                                recipients += f'<tr><td></td><td>{address} {address_info}</td><td><p class="val">{app_utils.to_string(val)} Dash</p></td><td></td></tr>'

                        fee = round(inputs_total - outputs_total, 8)

                        send_tx_row = ''
                        if self.transaction_sent:
                            url = self.config.get_block_explorer_tx()
                            if url:
                                url = url.replace('%TXID%', self.tx_id)
                                send_tx_row = f'<tr><td class="lbl"><p class="lbl">Transaction ID:</p></td><td><a href="{url}">{self.tx_id}</a></td></tr>'

                        if sys.platform in ('win32', 'linux'):
                            base_font_size = '11'
                            title_font_size = '17'
                        else:
                            base_font_size = '13'
                            title_font_size = '20'

                        if self.transaction_sent:
                            title = 'Transaction summary - sent'
                            subtitle = '<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; ' \
                                       'margin-right:0px; -qt-block-indent:0; text-indent:0px; ' \
                                       'background-color:#2eb82e;color:white; padding: 1px 3px 1px 3px; ' \
                                       f'border-radius: 3px;"><span style=" font-size:{base_font_size}pt;">' \
                                       'Transaction successfully sent...</span></p>'
                        else:
                            title = 'Transaction summary - ready to send'
                            subtitle = '<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; ' \
                                       'margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=' \
                                       f'"font-size:{base_font_size}pt;">Click the <b>&lt;Send transaction&gt;</b> button to ' \
                                       'broadcast the transaction.</span></p>'

                        summary = f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">
<html><head><meta name="qrichtext" content="1" /><style type="text/css">
td.lbl{{text-align: right;vertical-align: top}} p.lbl{{margin: 0 5px 0 0; font-weight: bold}} p.val{{margin: 0 0 0 8px; color: navy}}
</style></head><body style="font-size:{base_font_size}pt; font-weight:400; font-style:normal; margin-left:10px;margin-right:10px;">
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-size:{title_font_size}pt; font-weight:600;">{title}</span></p>
<p style="-qt-paragraph-type:empty; margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px; font-size:{base_font_size}pt;"><br /></p>
{subtitle}
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">
 <table>
    {send_tx_row}
    <tr><td class="lbl"><p class="lbl">Total amount:</p></td><td>{app_utils.to_string(inputs_total)} Dash</td><td></td></tr>
    <tr><td class="lbl"><p class="lbl">Fee:</p></td><td>{app_utils.to_string(fee)} Dash</td><td></td></tr>
    <tr><td class="lbl"><p class="lbl">Transaction size:</p></td><td>{tx_size_str}</td><td></td></tr>
    <tr><td class="lbl"><p class="lbl">InstantSend:</p></td><td>{'YES' if self.use_instant_send else 'NO'}</td><td></td></tr>
    {recipients}
 </table></p></body></html>"""

                        self.edt_recipients.setText(summary)
                    else:
                        raise Exception('Empty \'vin\' list in the decoded transaction.')
                else:
                    raise Exception('Empty \'vout\' list in the decoded transaction.')
            else:
                raise Exception('Error: could\'t parse tha raw transaction.')
        except Exception as e:
            log.exception("Unhandled exception occurred.")
            raise

    @pyqtSlot(bool)
    def on_btn_details_clicked(self, enabled):
        idx = (self.stacket_widget.currentIndex() + 1) % 2
        self.stacket_widget.setCurrentIndex(idx)
        self.btn_details.setText({0: 'Show Details', 1: 'Hide Details'}.get(idx))

    @pyqtSlot(bool)
    def on_btn_broadcast_clicked(self):
        try:
            log.debug('Broadcasting raw transaction: ' + self.raw_transaction)
            txid = self.dashd_intf.sendrawtransaction(self.raw_transaction, self.use_instant_send)
            if txid != self.tx_id:
                log.warning('TXID returned by sendrawtransaction differs from the original txid')
                self.tx_id = txid
            log.info('Transaction sent, txid: ' + txid)
            self.transaction_sent = True
            self.btn_broadcast.setEnabled(False)
            self.prepare_tx_view()
            if self.after_send_tx_callback:
                self.after_send_tx_callback(self.decoded_transaction)
        except Exception as e:
            log.exception(f'Exception occurred while broadcasting transaction. '
                              f'Transaction size: {self.tx_size} bytes.')
            self.errorMsg('An error occurred while sending transation: '+ str(e))

    @pyqtSlot(bool)
    def on_btn_close_clicked(self, enabled):
        if self.transaction_sent:
            self.accept()
        else:
            self.reject()

