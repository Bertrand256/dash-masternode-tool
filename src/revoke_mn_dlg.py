import ipaddress
import logging
from typing import Callable

from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.QtWidgets import QDialog, QMessageBox
from bitcoinrpc.authproxy import JSONRPCException

import app_cache
from app_config import MasternodeConfig, AppConfig, InputKeyType
from app_defs import FEE_DUFF_PER_BYTE
from dash_utils import validate_address
from dashd_intf import DashdInterface
from ui import ui_revoke_mn_dlg
from wnd_utils import WndUtils, ProxyStyleNoFocusRect


CACHE_ITEM_SHOW_COMMANDS = 'RevokeMnDlg_ShowCommands'


class RevokeMnDlg(QDialog, ui_revoke_mn_dlg.Ui_RevokeMnDlg, WndUtils):
    def __init__(self,
                 main_dlg,
                 app_config: AppConfig,
                 dashd_intf: DashdInterface,
                 masternode: MasternodeConfig):
        QDialog.__init__(self, main_dlg)
        ui_revoke_mn_dlg.Ui_RevokeMnDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.dmn_protx_hash = self.masternode.dmn_tx_hash
        self.dmn_actual_operator_pubkey = ""
        self.revocation_reason = 0
        self.show_manual_commands = False
        self.setupUi()

    def setupUi(self):
        ui_revoke_mn_dlg.Ui_RevokeMnDlg.setupUi(self, self)
        self.btnClose.hide()
        self.edtManualCommands.setStyle(ProxyStyleNoFocusRect())
        self.restore_cache_settings()
        self.update_ctrls_state()
        self.minimize_dialog_height()
        self.read_data_from_network()
        self.update_manual_cmd_info()

    def closeEvent(self, event):
        self.save_cache_settings()

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)
        self.show_manual_commands = app_cache.get_value(CACHE_ITEM_SHOW_COMMANDS, False, bool)

    def save_cache_settings(self):
        app_cache.save_window_size(self)
        app_cache.set_value(CACHE_ITEM_SHOW_COMMANDS, self.show_manual_commands)

    def minimize_dialog_height(self):
        def set():
            self.adjustSize()

        self.tm_resize_dlg = QTimer(self)
        self.tm_resize_dlg.setSingleShot(True)
        self.tm_resize_dlg.singleShot(100, set)

    def sizeHint(self):
        sh = QDialog.sizeHint(self)
        sh.setWidth(self.width())
        return sh

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        self.close()

    def read_data_from_network(self):
        try:
            protx = None
            if not self.dmn_protx_hash:
                for protx in self.dashd_intf.protx('list', 'registered', True):
                    protx_state = protx.get('state')
                    if (protx_state and protx_state.get(
                            'service') == self.masternode.ip + ':' + self.masternode.port) or \
                            (protx.get('collateralHash') == self.masternode.collateralTx and
                             str(protx.get('collateralIndex')) == str(self.masternode.collateralTxIndex)):
                        self.dmn_protx_hash = protx.get("proTxHash")
                        break
                if not self.dmn_protx_hash:
                    raise Exception("Couldn't find protx hash for this masternode. Enter the protx hash value in your"
                                    " configuration.")

            if not protx:
                try:
                    protx = self.dashd_intf.protx('info', self.dmn_protx_hash)
                except Exception as e:
                    if str(e).find('not found') >= 0:
                        raise Exception(f'A protx transaction with this hash does not exist or is inactive: '
                                        f'{self.dmn_protx_hash}.')
                    else:
                        raise

            status = protx.get('state', dict)
            self.dmn_actual_operator_pubkey = status.get('pubKeyOperator')
        except Exception as e:
            logging.exception('An exception occurred while reading protx information')
            raise

    def update_ctrls_state(self):

        if self.show_manual_commands:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="hide">Hide commands for manual execution</a>')
        else:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="show">Show commands for manual execution</a>')

        self.edtManualCommands.setVisible(self.show_manual_commands)

        self.minimize_dialog_height()

    @pyqtSlot(str)
    def on_lblManualCommands_linkActivated(self, link):
        self.show_manual_commands = (link == 'show')
        self.update_ctrls_state()

    def validate_data(self):
        if self.masternode.dmn_operator_key_type != InputKeyType.PRIVATE:
            raise Exception('The operator private key is required.')

        if self.masternode.get_dmn_operator_pubkey() != self.dmn_actual_operator_pubkey:
            raise Exception('The operator key from your configuration does not match the key published on the network.')

        self.revocation_reason = self.cboReason.currentIndex()

    def update_manual_cmd_info(self):
        try:
            self.validate_data()
            cmd = f'protx revoke "{self.dmn_protx_hash}" "{self.masternode.dmn_operator_private_key}" ' \
                f'{self.revocation_reason} "<span style="color:green">feeSourceAddress</span>"'
            msg = '<ol>' \
                  '<li>Start a Dash Core wallet with sufficient funds to cover a transaction fee.</li>'
            msg += '<li>Execute the following command in the Dash Core debug console:<br><br>'
            msg += '  <code style=\"background-color:#e6e6e6\">' + cmd + '</code></li><br>'
            msg += 'Replace <span style="color:green">feeSourceAddress</span> with the address being the ' \
                   'source of the transaction fee.'
            msg += '</ol>'

        except Exception as e:
            msg = '<span style="color:red">Error: ' + str(e) +'</span>'

        self.edtManualCommands.setHtml(msg)

    @pyqtSlot(int)
    def on_cboReason_currentIndexChanged(self, index):
        self.update_manual_cmd_info()

    @pyqtSlot(bool)
    def on_btnSendRevokeTx_clicked(self, enabled):
        self.read_data_from_network()
        self.validate_data()
        self.send_revoke_tx()

    def send_revoke_tx(self):
        try:
            funding_address = ''

            params = ['revoke',
                      self.dmn_protx_hash,
                      self.masternode.dmn_operator_private_key,
                      self.revocation_reason,
                      funding_address]

            try:
                revoke_support = self.dashd_intf.checkfeaturesupport('protx_revoke',
                                                                          self.app_config.app_version)
                if not revoke_support.get('enabled'):
                    if revoke_support.get('message'):
                        raise Exception(revoke_support.get('message'))
                    else:
                        raise Exception('The \'protx_revoke\' function is not supported by the RPC node '
                                        'you are connected to.')
                public_proxy_node = True

                active = self.app_config.feature_revoke_operator_automatic.get_value()
                if not active:
                    msg = self.app_config.feature_revoke_operator_automatic.get_message()
                    if not msg:
                        msg = 'The functionality of the automatic execution of the revoke command on the ' \
                              '"public" RPC nodes is inactive. Use the manual method or contact the program author ' \
                              'for details.'
                    raise Exception(msg)

            except JSONRPCException as e:
                public_proxy_node = False

            if not public_proxy_node:
                try:
                    # find an address to be used as the source of the transaction fees
                    min_fee = round(1024 * FEE_DUFF_PER_BYTE / 1e8, 8)
                    balances = self.dashd_intf.listaddressbalances(min_fee)
                    bal_list = []
                    for addr in balances:
                        bal_list.append({'address': addr, 'amount': balances[addr]})
                    bal_list.sort(key=lambda x: x['amount'])
                    if not bal_list:
                        raise Exception("No address can be found in the node's wallet with sufficient funds to "
                                        "cover the transaction fees.")
                    params[5] = bal_list[0]['address']
                except JSONRPCException as e:
                    logging.warning("Couldn't list the node address balances. We assume you are using a "
                                    "public RPC node and the funding address for the transaction fee will "
                                    "be estimated during the `update_registrar` call")

            upd_tx_hash = self.dashd_intf.rpc_call(True, False, 'protx', *params)

            if upd_tx_hash:
                logging.info('revoke successfully executed, tx hash: ' + upd_tx_hash)

                self.btnSendRevokeTx.setDisabled(True)
                self.cboReason.setDisabled(True)
                self.btnClose.show()

                url = self.app_config.get_block_explorer_tx()
                if url:
                    url = url.replace('%TXID%', upd_tx_hash)
                    upd_tx_hash = f'<a href="{url}">{upd_tx_hash}</a>'

                msg = 'The revoke transaction has been successfully sent. ' \
                     f'Tx hash: {upd_tx_hash}. <br><br>' \
                     f'The new values ​​will be visible on the network after the transaction is confirmed, i.e. in ' \
                     f'about 2.5 minutes.'

                WndUtils.infoMsg(msg)

        except Exception as e:
            if str(e).find('protx-dup') >= 0:
                WndUtils.errorMsg('The previous protx transaction has not been confirmed yet. Wait until it is '
                         'confirmed before sending a new transaction.')
            else:
                logging.error('Exception occurred while sending protx revoke: ' + str(e))
                WndUtils.errorMsg(str(e))
