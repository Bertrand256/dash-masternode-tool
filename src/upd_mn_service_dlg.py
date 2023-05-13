import ipaddress
import logging
from typing import Callable, Optional

from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.QtWidgets import QDialog
from bitcoinrpc.authproxy import JSONRPCException

import app_cache
from app_config import MasternodeConfig, AppConfig, InputKeyType, MasternodeType
from app_defs import FEE_DUFF_PER_BYTE
from dash_utils import validate_address, \
    generate_ed25519_private_key, ed25519_private_key_to_pubkey, \
    ed25519_public_key_to_platform_id, DASH_PLATFORM_DEFAULT_P2P_PORT, DASH_PLATFORM_DEFAULT_HTTP_PORT
from dashd_intf import DashdInterface
from ui import ui_upd_mn_service_dlg
from wnd_utils import WndUtils, ProxyStyleNoFocusRect, QDetectThemeChange, get_widget_font_color_green

CACHE_ITEM_SHOW_COMMANDS = 'UpdMnServiceDlg_ShowCommands'


class UpdMnServiceDlg(QDialog, QDetectThemeChange, ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg, WndUtils):
    def __init__(self,
                 main_dlg,
                 app_config: AppConfig,
                 dashd_intf: DashdInterface,
                 masternode: MasternodeConfig,
                 on_mn_config_updated_callback: Callable):
        QDialog.__init__(self, main_dlg)
        QDetectThemeChange.__init__(self)
        ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.on_mn_config_updated_callback = on_mn_config_updated_callback
        self.protx_hash = self.masternode.protx_hash
        self.actual_operator_pubkey = ""
        self.actual_operator_reward = 0
        self.new_operator_payout_address = ''
        self.prev_ip_port = self.masternode.ip + ':' + str(self.masternode.tcp_port)
        self.new_ip = ''
        self.new_port: Optional[int] = None
        self.platform_node_id: str = self.masternode.platform_node_id
        self.platform_node_id_private_key = self.masternode.platform_node_id_private_key
        self.platform_node_id_generated = False
        self.platform_p2p_port: Optional[int] = self.masternode.platform_p2p_port if \
            self.masternode.platform_p2p_port else DASH_PLATFORM_DEFAULT_P2P_PORT
        self.platform_http_port: Optional[int] = self.masternode.platform_http_port if \
            self.masternode.platform_http_port else DASH_PLATFORM_DEFAULT_HTTP_PORT
        self.upd_payout_active = False
        self.show_manual_commands = False
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg.setupUi(self, self)
        self.btnClose.hide()
        self.edtManualCommands.setStyle(ProxyStyleNoFocusRect())
        self.edtIP.setText(self.masternode.ip)
        self.edtPort.setText(str(self.masternode.tcp_port))
        self.restore_cache_settings()
        WndUtils.set_icon(self.parent, self.btnPlatformP2PPortSetDefault, 'restore@16px.png')
        WndUtils.set_icon(self.parent, self.btnPlatformHTTPPortSetDefault, 'restore@16px.png')
        self.edtPlatformNodeId.setText(self.platform_node_id)
        self.edtPlatformP2PPort.setText(str(self.platform_p2p_port) if self.platform_p2p_port else '')
        self.edtPlatformHTTPPort.setText(str(self.platform_http_port) if self.platform_http_port else '')
        platform_controls = (self.edtPlatformNodeId, self.edtPlatformP2PPort, self.edtPlatformHTTPPort,
                             self.btnGeneratePlatformId, self.btnPlatformP2PPortSetDefault,
                             self.btnPlatformHTTPPortSetDefault, self.lblPlatformNodeId, self.lblPlatformP2PPort,
                             self.lblPlatformHTTPPort)
        if self.masternode.masternode_type == MasternodeType.HPMN:
            for ctrl in platform_controls:
                ctrl.show()
        else:
            for ctrl in platform_controls:
                ctrl.hide()
        self.update_ctrls_state()
        self.minimize_dialog_height()
        self.read_data_from_network()
        self.update_manual_cmd_info()

    def closeEvent(self, event):
        self.save_cache_settings()

    def showEvent(self, QShowEvent):
        def apply():
            self.set_buttons_height()

        QTimer.singleShot(100, apply)

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)
        self.show_manual_commands = app_cache.get_value(CACHE_ITEM_SHOW_COMMANDS, False, bool)

    def save_cache_settings(self):
        app_cache.save_window_size(self)
        app_cache.set_value(CACHE_ITEM_SHOW_COMMANDS, self.show_manual_commands)

    def set_buttons_height(self):
        h = self.edtIP.height()
        for btn in (self.btnGeneratePlatformId, self.btnPlatformHTTPPortSetDefault, self.btnPlatformP2PPortSetDefault):
            btn.setFixedHeight(h)

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

    def onThemeChanged(self):
        self.update_styles()

    def update_styles(self):
        self.update_manual_cmd_info()

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        self.close()

    def read_data_from_network(self):
        try:
            protx = None
            if not self.protx_hash:
                for protx in self.dashd_intf.protx('list', 'registered', True):
                    protx_state = protx.get('state')
                    if (protx_state and protx_state.get(
                            'service') == self.masternode.ip + ':' + str(self.masternode.tcp_port)) or \
                            (protx.get('collateralHash') == self.masternode.collateral_tx and
                             str(protx.get('collateralIndex')) == str(self.masternode.collateral_tx_index)):
                        self.protx_hash = protx.get("proTxHash")
                        break
                if not self.protx_hash:
                    WndUtils.error_msg(
                        "Couldn't find protx hash for this masternode. Enter the protx hash value in your"
                        " configuration.\n\nAttempting to continue will fail.")

            if not protx:
                try:
                    protx = self.dashd_intf.protx('info', self.protx_hash)
                    status = protx.get('state', dict)
                    self.actual_operator_pubkey = status.get('pubKeyOperator')
                    self.actual_operator_reward = protx.get('operatorReward', 0)
                except Exception as e:
                    if str(e).find('not found') >= 0:
                        WndUtils.error_msg(
                            f'A protx transaction with this hash does not exist or is inactive: '
                            f'{self.protx_hash}.\n\nAttempting to continue will fail.')
                    else:
                        raise

        except Exception as e:
            logging.exception('An exception occurred while reading protx information')
            raise

    def update_ctrls_state(self):

        self.new_operator_payout_address = self.edtOperatorPayoutAddress.text()
        if not self.actual_operator_reward and self.new_operator_payout_address:
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
        try:
            self.show_manual_commands = (link == 'show')
            self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    def validate_data(self):
        if self.upd_payout_active:
            payout_address = self.edtOperatorPayoutAddress.text()
            if payout_address:
                if not validate_address(payout_address, self.app_config.dash_network):
                    raise Exception('Invalid payout Dash address')
                else:
                    self.new_operator_payout_address = payout_address
            else:
                self.new_operator_payout_address = ""

        if self.masternode.operator_key_type != InputKeyType.PRIVATE:
            raise Exception('The operator private key is required.')

        if self.masternode.get_operator_pubkey() != self.actual_operator_pubkey:
            raise Exception('The operator key from your configuration does not match the key published on the network.')

        self.new_ip = self.edtIP.text()
        if not self.new_ip:
            raise Exception("The IP address cannot be empty.")
        try:
            if self.new_ip:
                ipaddress.ip_address(self.new_ip)
        except Exception as e:
            self.edtIP.setFocus()
            raise Exception('Invalid masternode IP address: %s.' % str(e))

        if not self.edtPort.text():
            raise Exception("The TCP port cannot be empty.")
        try:
            if self.new_ip:
                self.new_port = int(self.edtPort.text())
            else:
                self.new_port = None
        except Exception:
            self.edtPort.setFocus()
            raise Exception('Invalid TCP port: should be integer.')

    def update_manual_cmd_info(self):
        try:
            green_color = get_widget_font_color_green(self.lblIP)
            self.validate_data()
            if self.masternode.masternode_type == MasternodeType.REGULAR:
                cmd = f'protx update_service "{self.protx_hash}" "{self.new_ip}:{str(self.new_port)}" ' \
                      f'"{self.masternode.operator_private_key}" "{self.new_operator_payout_address}" ' \
                      f'"<span style="color:{green_color}">feeSourceAddress</span>"'
            else:
                # HPMN
                cmd = f'protx update_service_hpmn "{self.protx_hash}" "{self.new_ip}:{str(self.new_port)}" ' \
                      f'"{self.masternode.operator_private_key}" "{self.platform_node_id}" {self.platform_p2p_port} ' \
                      f'{self.platform_http_port} "{self.new_operator_payout_address}" ' \
                      f'"<span style="color:{green_color}">feeSourceAddress</span>"'

            msg = '<ol>' \
                  '<li>Start a Dash Core wallet with sufficient funds to cover a transaction fee.</li>'
            msg += '<li>Execute the following command in the Dash Core debug console:<br><br>'
            msg += '  <code>' + cmd + '</code></li><br>'
            msg += f'Replace <span style="color:{green_color}">feeSourceAddress</span> with the address being the ' \
                   'source of the transaction fee.'
            msg += '</ol>'

        except Exception as e:
            msg = '<span style="color:red">Error: ' + str(e) + '</span>'

        self.edtManualCommands.setHtml(msg)

    @pyqtSlot(str)
    def on_edtOperatorPayoutAddress_textChanged(self, text):
        try:
            self.update_manual_cmd_info()
            self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    def on_edtPlatformNodeId_textChanged(self, text):
        try:
            self.platform_node_id = text
            self.update_manual_cmd_info()
            self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    def on_edtPlatformP2PPort_textChanged(self, text):
        try:
            self.platform_p2p_port = int(text)
            self.update_manual_cmd_info()
            self.update_ctrls_state()
        except Exception as e:
            self.error_msg(str(e), True)

    def on_edtPlatformHTTPPort_textChanged(self, text):
        try:
            self.platform_http_port = int(text)
            self.update_manual_cmd_info()
            self.update_ctrls_state()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnGeneratePlatformId_clicked(self, active):
        try:
            priv_key_hex = generate_ed25519_private_key()
            pub_key_hex = ed25519_private_key_to_pubkey(priv_key_hex)
            node_id = ed25519_public_key_to_platform_id(pub_key_hex)
            self.platform_node_id_private_key = priv_key_hex
            self.platform_node_id = node_id
            self.platform_node_id_generated = True
            self.edtPlatformNodeId.setText(node_id)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_btnPlatformP2PPortSetDefault_clicked(self):
        if self.edtPlatformP2PPort.text() != str(DASH_PLATFORM_DEFAULT_P2P_PORT):
            self.edtPlatformP2PPort.setText(str(DASH_PLATFORM_DEFAULT_P2P_PORT))

    @pyqtSlot()
    def on_btnPlatformHTTPPortSetDefault_clicked(self):
        if self.edtPlatformHTTPPort.text() != str(DASH_PLATFORM_DEFAULT_HTTP_PORT):
            self.edtPlatformHTTPPort.setText(str(DASH_PLATFORM_DEFAULT_HTTP_PORT))

    @pyqtSlot(bool)
    def on_btnSendUpdateTx_clicked(self, enabled):
        try:
            self.read_data_from_network()
            self.validate_data()
            self.send_upd_tx()
        except Exception as e:
            WndUtils.error_msg(str(e))

    def send_upd_tx(self):
        try:
            funding_address = ''
            if self.new_ip:
                dmn_new_ip_port = self.new_ip + ':' + str(self.new_port)
            else:
                dmn_new_ip_port = '"0"'

            if self.masternode.masternode_type == MasternodeType.REGULAR:
                protx_command = 'update_service'
            else:
                protx_command = 'update_service_hpmn'

            params = [protx_command,
                      self.protx_hash,
                      dmn_new_ip_port,
                      self.masternode.operator_private_key]

            if self.masternode.masternode_type == MasternodeType.HPMN:
                params.extend([self.platform_node_id, self.platform_p2p_port, self.platform_http_port])

            params.extend([self.new_operator_payout_address, funding_address])

            try:
                upd_service_support = self.dashd_intf.checkfeaturesupport('protx_' + protx_command,
                                                                          self.app_config.app_version)
                if not upd_service_support.get('enabled'):
                    if upd_service_support.get('message'):
                        raise Exception(upd_service_support.get('message'))
                    else:
                        raise Exception(f'The "protx {protx_command}" function is not supported by the RPC node '
                                        'you are connected to.')
                public_proxy_node = True

                active = self.app_config.feature_update_service_automatic.get_value()
                if not active:
                    msg = self.app_config.feature_update_service_automatic.get_message()
                    if not msg:
                        msg = f'The functionality of the automatic execution of the {protx_command} command on the ' \
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
                                    f"be estimated during the `{protx_command}` call")

            upd_tx_hash = self.dashd_intf.rpc_call(True, False, 'protx', *params)

            if upd_tx_hash:
                logging.info(f'protx {protx_command} successfully executed, tx hash: ' + upd_tx_hash)

                self.btnSendUpdateTx.setDisabled(True)
                self.edtOperatorPayoutAddress.setReadOnly(True)
                self.edtIP.setReadOnly(True)
                self.edtPort.setReadOnly(True)
                self.edtPlatformNodeId.setReadOnly(True)
                self.edtPlatformP2PPort.setReadOnly(True)
                self.edtPlatformHTTPPort.setReadOnly(True)
                self.btnGeneratePlatformId.setDisabled(True)
                self.btnPlatformHTTPPortSetDefault.setDisabled(True)
                self.btnPlatformP2PPortSetDefault.setDisabled(True)
                self.btnClose.show()

                url = self.app_config.get_block_explorer_tx()
                if url:
                    url = url.replace('%TXID%', upd_tx_hash)
                    upd_tx_hash = f'<a href="{url}">{upd_tx_hash}</a>'

                msg = f'The "protx {protx_command}" transaction has been successfully sent. ' \
                      f'Tx hash: {upd_tx_hash}. <br><br>' \
                      f'The new values will be visible on the network after the transaction is confirmed, i.e. in ' \
                      f'about 2.5 minutes.'

                if self.masternode.ip != self.new_ip or self.masternode.tcp_port != self.new_port or \
                        (self.masternode.masternode_type == MasternodeType.HPMN and
                         (self.masternode.platform_node_id != self.platform_node_id or
                          self.masternode.platform_p2p_port != self.platform_p2p_port or
                          self.masternode.platform_http_port != self.platform_http_port)):

                    self.masternode.ip = self.new_ip
                    self.masternode.tcp_port = self.new_port
                    self.masternode.platform_node_id_private_key = self.platform_node_id_private_key
                    self.masternode.platform_node_id = self.platform_node_id
                    self.masternode.platform_p2p_port = self.platform_p2p_port
                    self.masternode.platform_http_port = self.platform_http_port

                    if self.on_mn_config_updated_callback:
                        self.on_mn_config_updated_callback(self.masternode)

                WndUtils.info_msg(msg)

        except Exception as e:
            if str(e).find('protx-dup') >= 0:
                WndUtils.error_msg('The previous protx transaction has not been confirmed yet. Wait until it is '
                                   'confirmed before sending a new transaction.')
            else:
                logging.error('Exception occurred while sending protx update_service: ' + str(e))
                WndUtils.error_msg(str(e))
