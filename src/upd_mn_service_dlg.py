import ipaddress
import logging
from typing import Callable

from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.QtWidgets import QDialog, QMessageBox
from bitcoinrpc.authproxy import JSONRPCException

import app_cache
from app_config import MasternodeConfig, AppConfig, InputKeyType
from app_defs import FEE_DUFF_PER_BYTE
from dash_utils import wif_privkey_to_address, generate_wif_privkey, generate_bls_privkey, validate_address, \
    bls_privkey_to_pubkey, validate_wif_privkey
from dashd_intf import DashdInterface
from ui import ui_upd_mn_service_dlg
from wnd_utils import WndUtils, ProxyStyleNoFocusRect


CACHE_ITEM_SHOW_COMMANDS = 'UpdMnServiceDlg_ShowCommands'


class UpdMnServiceDlg(QDialog, ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg, WndUtils):
    def __init__(self,
                 main_dlg,
                 app_config: AppConfig,
                 dashd_intf: DashdInterface,
                 masternode: MasternodeConfig,
                 on_mn_config_updated_callback: Callable):
        QDialog.__init__(self, main_dlg)
        ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.on_mn_config_updated_callback = on_mn_config_updated_callback
        self.dmn_protx_hash = self.masternode.dmn_tx_hash
        self.dmn_actual_operator_pubkey = ""
        self.dmn_actual_operator_reward = 0
        self.dmn_new_operator_payout_address = ''
        self.dmn_prev_ip_port = self.masternode.ip + ':' + str(self.masternode.port)
        self.dmn_new_ip = ''
        self.dmn_new_port = ''
        self.upd_payout_active = False
        self.show_manual_commands = False
        self.setupUi()

    def setupUi(self):
        ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg.setupUi(self, self)
        self.btnClose.hide()
        self.edtManualCommands.setStyle(ProxyStyleNoFocusRect())
        self.edtIP.setText(self.masternode.ip)
        self.edtPort.setText(self.masternode.port)
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
            self.dmn_actual_operator_reward = protx.get('operatorReward', 0)

        except Exception as e:
            logging.exception('An exception occurred while reading protx information')
            raise

    def update_ctrls_state(self):

        self.dmn_new_operator_payout_address = self.edtOperatorPayoutAddress.text()
        if not self.dmn_actual_operator_reward and self.dmn_new_operator_payout_address:
            self.lblOperatorPayoutMsg.setText('<span style="color:red">Separate reward for the operator has not '
                                              'been configured. If you continue the update service operation will '
                                              'fail.</span>')
            self.lblOperatorPayoutMsg.setVisible(True)
        else:
            self.lblOperatorPayoutMsg.setText('')
            self.lblOperatorPayoutMsg.setVisible(False)

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
        if self.upd_payout_active:
            payout_address = self.edtOperatorPayoutAddress.text()
            if payout_address:
                if not validate_address(payout_address, self.app_config.dash_network):
                    raise Exception('Invalid payout Dash address')
                else:
                    self.dmn_new_operator_payout_address = payout_address
            else:
                self.dmn_new_operator_payout_address = ""

        if self.masternode.dmn_operator_key_type != InputKeyType.PRIVATE:
            raise Exception('The operator private key is required.')

        if self.masternode.get_dmn_operator_pubkey() != self.dmn_actual_operator_pubkey:
            raise Exception('The operator key from your configuration does not match the key published on the network.')

        self.dmn_new_ip = self.edtIP.text()
        if not self.dmn_new_ip:
            raise Exception("The IP address cannot be empty.")
        try:
            if self.dmn_new_ip:
                ipaddress.ip_address(self.dmn_new_ip)
        except Exception as e:
            self.edtIP.setFocus()
            raise Exception('Invalid masternode IP address: %s.' % str(e))

        if not self.edtPort.text():
            raise Exception("The TCP port cannot be empty.")
        try:
            if self.dmn_new_ip:
                self.dmn_new_port = int(self.edtPort.text())
            else:
                self.dmn_new_port = None
        except Exception:
            self.edtPort.setFocus()
            raise Exception('Invalid TCP port: should be integer.')

    def update_manual_cmd_info(self):
        try:
            self.validate_data()
            cmd = f'protx update_service "{self.dmn_protx_hash}" "{self.dmn_new_ip}:{str(self.dmn_new_port)}" ' \
                f'"{self.masternode.dmn_operator_private_key}" "{self.dmn_new_operator_payout_address}" ' \
                f'"<span style="color:green">feeSourceAddress</span>"'
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

    @pyqtSlot(str)
    def on_edtOperatorPayoutAddress_textChanged(self, text):
        self.update_manual_cmd_info()
        self.update_ctrls_state()

    @pyqtSlot(bool)
    def on_btnSendUpdateTx_clicked(self, enabled):
        self.read_data_from_network()
        self.validate_data()
        self.send_upd_tx()

    def send_upd_tx(self):
        try:
            funding_address = ''
            if self.dmn_new_ip:
                dmn_new_ip_port = self.dmn_new_ip + ':' + str(self.dmn_new_port)
            else:
                dmn_new_ip_port = '"0"'

            params = ['update_service',
                      self.dmn_protx_hash,
                      dmn_new_ip_port,
                      self.masternode.dmn_operator_private_key,
                      self.dmn_new_operator_payout_address,
                      funding_address]

            try:
                upd_service_support = self.dashd_intf.checkfeaturesupport('protx_update_service',
                                                                          self.app_config.app_version)
                if not upd_service_support.get('enabled'):
                    if upd_service_support.get('message'):
                        raise Exception(upd_service_support.get('message'))
                    else:
                        raise Exception('The \'protx_update_service\' function is not supported by the RPC node '
                                        'you are connected to.')
                public_proxy_node = True

                active = self.app_config.feature_update_service_automatic.get_value()
                if not active:
                    msg = self.app_config.feature_update_service_automatic.get_message()
                    if not msg:
                        msg = 'The functionality of the automatic execution of the update_service command on the ' \
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
                logging.info('update_service successfully executed, tx hash: ' + upd_tx_hash)

                self.btnSendUpdateTx.setDisabled(True)
                self.edtOperatorPayoutAddress.setReadOnly(True)
                self.edtIP.setReadOnly(True)
                self.edtPort.setReadOnly(True)
                self.btnClose.show()

                url = self.app_config.get_block_explorer_tx()
                if url:
                    url = url.replace('%TXID%', upd_tx_hash)
                    upd_tx_hash = f'<a href="{url}">{upd_tx_hash}</a>'

                msg = 'The update_service transaction has been successfully sent. ' \
                     f'Tx hash: {upd_tx_hash}. <br><br>' \
                     f'The new values ​​will be visible on the network after the transaction is confirmed, i.e. in ' \
                     f'about 2.5 minutes.'

                if bool(dmn_new_ip_port) and self.dmn_prev_ip_port != dmn_new_ip_port:
                    msg += '\n\nYou have changed the masternode IP/port. Do you want to automatically update ' \
                           'this in the app configuration?'

                    if self.queryDlg(msg, buttons=QMessageBox.Yes | QMessageBox.No, default_button=QMessageBox.Yes,
                                     icon=QMessageBox.Information) == QMessageBox.Yes:
                        self.masternode.ip = self.dmn_new_ip
                        self.masternode.port = str(self.dmn_new_port)

                        if self.on_mn_config_updated_callback:
                            self.on_mn_config_updated_callback(self.masternode)
                else:
                    WndUtils.infoMsg(msg)

        except Exception as e:
            if str(e).find('protx-dup') >= 0:
                WndUtils.errorMsg('The previous protx transaction has not been confirmed yet. Wait until it is '
                         'confirmed before sending a new transaction.')
            else:
                logging.error('Exception occurred while sending protx update_service: ' + str(e))
                WndUtils.errorMsg(str(e))
