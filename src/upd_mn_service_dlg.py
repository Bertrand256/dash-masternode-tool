import ipaddress
import logging
from typing import Callable, Optional

from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.QtWidgets import QDialog, QLabel, QApplication
from bitcoinrpc.authproxy import JSONRPCException

import app_cache
from app_config import MasternodeConfig, AppConfig, InputKeyType, MasternodeType
from app_defs import FEE_DUFF_PER_BYTE
from dash_utils import validate_address, \
    generate_ed25519_private_key, ed25519_private_key_to_pubkey, \
    ed25519_public_key_to_platform_id, DASH_PLATFORM_DEFAULT_P2P_PORT, DASH_PLATFORM_DEFAULT_HTTP_PORT, \
    validate_ed25519_privkey, ed25519_private_key_to_platform_node_id, validate_platform_node_id, \
    ed25519_private_key_to_tenderdash
from dashd_intf import DashdInterface
from ui import ui_upd_mn_service_dlg
from wnd_utils import WndUtils, ProxyStyleNoFocusRect, QDetectThemeChange, get_widget_font_color_green, \
    get_widget_font_color_blue
from wallet_dlg import WalletDlg, WalletDisplayMode

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
        self.main_dlg: 'MainWindow' = main_dlg
        self.updating_ui = True
        self.masternode = masternode
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.on_mn_config_updated_callback = on_mn_config_updated_callback
        self.protx_hash = self.masternode.protx_hash
        self.actual_operator_pubkey = ""
        self.actual_operator_reward = 0
        self.new_operator_payout_address = ''
        self.prev_ip_port = self.masternode.ip + ':' + str(self.masternode.tcp_port)
        self.ip = ''
        self.tcp_port: Optional[int] = None
        self.platform_node_key_type = self.masternode.platform_node_key_type
        if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
            self.platform_node_private_key = self.masternode.get_platform_node_private_key_for_editing()
            self.platform_node_id = ''
        else:
            self.platform_node_id: str = self.masternode.platform_node_id
            self.platform_node_private_key = ''
        self.platform_node_key_generated = False
        self.platform_p2p_port: Optional[int] = self.masternode.platform_p2p_port if \
            self.masternode.platform_p2p_port else DASH_PLATFORM_DEFAULT_P2P_PORT
        self.platform_http_port: Optional[int] = self.masternode.platform_http_port if \
            self.masternode.platform_http_port else DASH_PLATFORM_DEFAULT_HTTP_PORT

        self.operator_key_err_msg = ''
        self.protx_not_found_err_msg = ''
        self.ip_port_validation_err_msg = ''
        self.payout_address_validation_err_msg = ''
        self.platform_node_id_validation_err_msg = ''
        self.platform_ports_validation_err_msg = ''

        self.show_manual_commands = False
        self.setupUi(self)
        self.updating_ui = False

    def setupUi(self, dialog: QDialog):
        ui_upd_mn_service_dlg.Ui_UpdMnServiceDlg.setupUi(self, self)
        self.btnClose.hide()
        self.edtManualCommands.setStyle(ProxyStyleNoFocusRect())
        self.edtIP.setText(self.masternode.ip)
        self.edtPort.setText(str(self.masternode.tcp_port))
        self.restore_cache_settings()
        WndUtils.set_icon(self.parent, self.btnPlatformP2PPortSetDefault, 'restore@16px.png')
        WndUtils.set_icon(self.parent, self.btnPlatformHTTPPortSetDefault, 'restore@16px.png')
        WndUtils.set_icon(self, self.btnCopyCommandText, 'content-copy@16px.png')
        if self.masternode.masternode_type == MasternodeType.HPMN:
            if self.platform_node_key_type == InputKeyType.PRIVATE:
                self.edtPlatformNodeKey.setText(self.platform_node_private_key)
            else:
                self.edtPlatformNodeKey.setText(self.platform_node_id)
        self.edtPlatformP2PPort.setText(str(self.platform_p2p_port) if self.platform_p2p_port else '')
        self.edtPlatformHTTPPort.setText(str(self.platform_http_port) if self.platform_http_port else '')

        platform_controls = (self.edtPlatformNodeKey, self.edtPlatformP2PPort, self.edtPlatformHTTPPort,
                             self.btnGeneratePlatformNodeKey, self.btnPlatformP2PPortSetDefault,
                             self.btnPlatformHTTPPortSetDefault, self.lblPlatformNodeKey, self.lblPlatformP2PPort,
                             self.lblPlatformHTTPPort)
        if self.masternode.masternode_type == MasternodeType.HPMN:
            for ctrl in platform_controls:
                ctrl.show()
        else:
            for ctrl in platform_controls:
                ctrl.hide()
        self.lblIPMsg.hide()
        self.lblOperatorPayoutMsg.hide()
        self.lblPlatformNodeKeyMsg.hide()
        self.lblPlatformPortsMsg.hide()
        self.lineIPMsg.hide()
        self.lineOperatorPayoutMsg.hide()
        self.linePlatformNodeKeyMsg.hide()
        self.minimize_dialog_height()
        self.read_data_from_network()
        self.update_manual_cmd_info()
        self.update_ctrls_state()
        cl = QApplication.clipboard()
        cl.changed.connect(self.strip_clipboard_contents)

    def closeEvent(self, event):
        self.save_cache_settings()

    def showEvent(self, QShowEvent):
        def apply():
            self.set_buttons_height()

        QTimer.singleShot(100, apply)

    def set_buttons_height(self):
        try:
            h = self.edtIP.height()
            for ctrl in (self.btnChooseAddressFromWallet, self.btnPlatformP2PPortSetDefault,
                         self.btnPlatformHTTPPortSetDefault, self.btnGeneratePlatformNodeKey):
                ctrl.setFixedHeight(h)
        except Exception as e:
            logging.exception(str(e))

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

    def onThemeChanged(self):
        self.update_styles()

    def update_styles(self):
        self.update_manual_cmd_info()

    def strip_clipboard_contents(self, _):
        """ Remove leading/trailing spaces and newline characters from a text copied do clipboard."""
        try:
            cl = QApplication.clipboard()
            t = cl.text()
            if t:
                cl.blockSignals(True)
                try:
                    cl.setText(t.strip())
                finally:
                    cl.blockSignals(False)
        except Exception as e:
            logging.exception(str(e))

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
                    self.protx_not_found_err_msg = "Couldn't find protx hash for this masternode. Enter the " \
                                                   "protx hash value in your masternode configuration."

            if not protx:
                try:
                    protx = self.dashd_intf.protx('info', self.protx_hash)
                    status = protx.get('state', dict)
                    self.actual_operator_pubkey = status.get('pubKeyOperator')
                    self.actual_operator_reward = protx.get('operatorReward', 0)
                except Exception as e:
                    if str(e).find('not found') >= 0:
                        self.protx_not_found_err_msg = 'A protx transaction from your configuration does not ' \
                                                       'exist or is inactive.'
                    else:
                        raise
        except Exception as e:
            logging.exception('An exception occurred while reading protx information')
            self.protx_not_found_err_msg = 'Error when verifying masternode protx hash.'

    def update_ctrls_state(self):
        blue_color = get_widget_font_color_blue(self.lblIPMsg)

        def style_to_color(style: str) -> str:
            if style == 'hl1':
                color = 'color:#00802b'
            elif style == 'error':
                color = 'color:red'
            elif style == 'info':
                color = 'color:' + blue_color
            else:
                color = ''
            return color

        def set_key_related_label(lbl_ctrl: QLabel, prefix: str, key_type: str, tooltip_anchor: str, style: str):
            lbl = prefix + ' ' + \
                  {'privkey': 'private key',
                   'platform_node_id': 'Node Id'}.get(key_type, '???')

            change_mode = f'(<a href="{tooltip_anchor}">use {tooltip_anchor}</a>)'
            msg = f'<table style="float:right;{style_to_color(style)}"><tr><td><b>{lbl}</b></td><td>{change_mode}' \
                  f'</td></tr></table>'
            lbl_ctrl.setText(msg)

        def set_info_label(lbl_ctrl: QLabel, msg: str, style: str):
            if msg:
                msg_html = f'<span style="{style_to_color(style)}">{msg}</span>'
                lbl_ctrl.setText(msg_html)
                lbl_ctrl.show()
            else:
                lbl_ctrl.hide()

        if self.masternode:
            if self.platform_node_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'node id',
                                                              'Enter the Platform Node private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('platform_node_id', 'privkey',
                                                              'Enter the Platform Node Id')
                style = 'hl1'
            set_key_related_label(self.lblPlatformNodeKey, 'Platform Node', key_type, tooltip_anchor, style)
            self.edtPlatformNodeKey.setPlaceholderText(placeholder_text)

        self.new_operator_payout_address = self.edtOperatorPayoutAddress.text()
        if self.show_manual_commands:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="hide">Hide commands for manual execution</a>')
        else:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="show">Show commands for manual execution</a>')

        self.edtManualCommands.setVisible(self.show_manual_commands)
        self.btnCopyCommandText.setVisible(self.show_manual_commands)
        if self.masternode.masternode_type == MasternodeType.HPMN:
            if self.platform_node_key_type == InputKeyType.PRIVATE:
                self.btnGeneratePlatformNodeKey.setVisible(True)
            else:
                self.btnGeneratePlatformNodeKey.setVisible(False)

        gen_msg = ''
        if self.operator_key_err_msg:
            gen_msg = self.operator_key_err_msg
        if self.protx_not_found_err_msg:
            if gen_msg:
                gen_msg += '<br>'
            gen_msg += self.protx_not_found_err_msg
        set_info_label(self.lblGeneralErrorMsg, gen_msg, 'error')

        if self.ip_port_validation_err_msg:
            set_info_label(self.lblIPMsg, self.ip_port_validation_err_msg, 'error')
        else:
            set_info_label(self.lblIPMsg, '', 'info')

        if self.payout_address_validation_err_msg:
            msg = self.payout_address_validation_err_msg
            style = 'error'
        else:
            msg = 'Dash address for operator reward. Fill in only if the option to split the masternode payout ' \
                  'between owner and operator was set when registering masternode. Otherwise, leave it blank.'
            style = 'info'
        set_info_label(self.lblOperatorPayoutMsg, msg, style)
        self.lineOperatorPayoutMsg.setVisible(self.lblOperatorPayoutMsg.isVisible() and
                                              self.masternode.masternode_type == MasternodeType.HPMN)

        msg = ''
        style = ''
        if self.masternode.masternode_type == MasternodeType.HPMN:
            if self.platform_node_id_validation_err_msg:
                msg = self.platform_node_id_validation_err_msg
                style = 'error'
            else:
                if self.platform_node_key_type == InputKeyType.PRIVATE:
                    if self.platform_node_key_generated:
                        msg = 'Platform Node private key was generated here. Once registration is complete, ' \
                              'copy the associated Ed25519 private key into the Tenderdash configuration.'
                    else:
                        msg = 'Enter the Platform Node private key generated by Tenderdash, or ' \
                              'generate it here, then copy it into the Tenderdash configuration.'
                    style = 'info'
                else:
                    msg = 'Enter the Platform Node Id generated from the Tenderdash private key.'
                    style = 'info'

        set_info_label(self.lblPlatformNodeKeyMsg, msg, style)
        self.linePlatformNodeKeyMsg.setVisible(self.lblPlatformNodeKeyMsg.isVisible())

        if self.platform_ports_validation_err_msg:
            set_info_label(self.lblPlatformPortsMsg, self.platform_ports_validation_err_msg, 'error')
        else:
            set_info_label(self.lblPlatformPortsMsg, '', 'info')

        self.minimize_dialog_height()

    @pyqtSlot(str)
    def on_lblManualCommands_linkActivated(self, link):
        try:
            self.show_manual_commands = (link == 'show')
            self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    def validate_data(self) -> bool:
        errors_occurred = False

        if self.masternode.operator_key_type != InputKeyType.PRIVATE:
            self.operator_key_err_msg = 'The operator private key is required.'
            errors_occurred = True
        else:
            self.operator_key_err_msg = ''

        payout_address = self.edtOperatorPayoutAddress.text()

        self.payout_address_validation_err_msg = ''
        if payout_address:
            if not validate_address(payout_address, self.app_config.dash_network):
                self.payout_address_validation_err_msg = 'Invalid payout Dash address'
                errors_occurred = True
            else:
                self.new_operator_payout_address = payout_address
        else:
            self.new_operator_payout_address = ""

        if not self.actual_operator_reward and self.new_operator_payout_address:
            self.payout_address_validation_err_msg = 'Separate reward for the operator has not been configured. ' \
                                                     'If you continue, the update service operation will fail.'

        self.ip_port_validation_err_msg = ''
        self.ip = self.edtIP.text()
        if not self.ip:
            self.ip_port_validation_err_msg = 'The IP address cannot be empty.'
            errors_occurred = True
        try:
            if self.ip:
                ipaddress.ip_address(self.ip)
        except Exception as e:
            self.edtIP.setFocus()
            self.ip_port_validation_err_msg = 'Invalid masternode IP address: %s.' % str(e)
            errors_occurred = True

        if not self.edtPort.text():
            self.ip_port_validation_err_msg = "The TCP port cannot be empty."
            errors_occurred = True
        try:
            if self.ip:
                self.tcp_port = int(self.edtPort.text())
                if not (1 <= self.tcp_port <= 65535):
                    self.ip_port_validation_err_msg = 'Masternode TCP port is invalid.'
            else:
                self.tcp_port = None
        except Exception:
            self.edtPort.setFocus()
            self.ip_port_validation_err_msg = 'Invalid TCP port: should be integer.'
            errors_occurred = True

        self.platform_node_id_validation_err_msg = ''
        if self.masternode.masternode_type == MasternodeType.HPMN:
            node_key = self.edtPlatformNodeKey.text().strip()
            if self.platform_node_key_type == InputKeyType.PRIVATE:
                if not node_key:
                    self.platform_node_id_validation_err_msg = 'Platform node private key or node id is required.'
                    errors_occurred = True
                else:
                    if not validate_ed25519_privkey(node_key):
                        self.platform_node_id_validation_err_msg = \
                            'The Platform private key is invalid. It should be an Ed25519 private key.'
                        errors_occurred = True
                    else:
                        self.platform_node_id = ed25519_private_key_to_platform_node_id(node_key)
                        self.platform_node_private_key = node_key
            else:
                if not node_key:
                    self.platform_node_id_validation_err_msg = 'Platform node id is required.'
                    errors_occurred = True
                else:
                    if not validate_platform_node_id(node_key):
                        self.platform_node_id_validation_err_msg = 'Platform node id should be a 20-byte hexadecimal ' \
                                                                   'string.'
                        errors_occurred = True
                    else:
                        self.platform_node_id = node_key

            if self.platform_node_id_validation_err_msg:
                errors_occurred = True

            self.platform_ports_validation_err_msg = ''
            p2p_port = self.edtPlatformP2PPort.text().strip()
            if not p2p_port:
                self.platform_ports_validation_err_msg = 'Platform P2P port is required.'
            else:
                try:
                    p2p_port = int(p2p_port)
                    if not (1 <= p2p_port <= 65535):
                        self.platform_ports_validation_err_msg = 'Platform P2P port is invalid'
                    self.platform_p2p_port = p2p_port
                except Exception:
                    self.platform_ports_validation_err_msg = 'Platform P2P port must be a valid TCP port [1-65535].'

            http_port = self.edtPlatformHTTPPort.text().strip()
            if not http_port:
                if self.platform_ports_validation_err_msg:
                    self.platform_ports_validation_err_msg += ' '
                self.platform_ports_validation_err_msg += 'Platform HTTP port is required.'
            else:
                try:
                    http_port = int(http_port)
                    if not (1 <= http_port <= 65535):
                        if self.platform_ports_validation_err_msg:
                            self.platform_ports_validation_err_msg += ' '
                        self.platform_ports_validation_err_msg = 'Platform HTTP port is invalid'
                    self.platform_http_port = http_port
                except Exception:
                    if self.platform_ports_validation_err_msg:
                        self.platform_ports_validation_err_msg += ' '
                    self.platform_ports_validation_err_msg += 'Platform HTTP port must be a valid TCP port [1-65535].'

            if self.platform_ports_validation_err_msg:
                errors_occurred = True

        return not errors_occurred

    def get_manual_cmd_text(self, fee_source_info=None) -> str:
        self.validate_data()
        if self.masternode.masternode_type == MasternodeType.REGULAR:
            cmd = f'protx update_service "{self.protx_hash}" "{self.ip}:{str(self.tcp_port)}" ' \
                  f'"{self.masternode.operator_private_key}" "{self.new_operator_payout_address}" '
        else:
            # HPMN
            cmd = f'protx update_service_hpmn "{self.protx_hash}" "{self.ip}:{str(self.tcp_port)}" ' \
                  f'"{self.masternode.operator_private_key}" "{self.platform_node_id}" {self.platform_p2p_port} ' \
                  f'{self.platform_http_port} "{self.new_operator_payout_address}" '
        if fee_source_info:
            cmd += fee_source_info
        else:
            cmd += '"feeSourceAddress"'
        return cmd

    def update_manual_cmd_info(self):
        try:
            green_color = get_widget_font_color_green(self.lblIP)
            self.validate_data()
            cmd = self.get_manual_cmd_text(
                fee_source_info=f'"<span style="color:{green_color}">feeSourceAddress</span>"')

            msg = ''
            msg += '<ol>' \
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
    def on_lblPlatformNodeKey_linkActivated(self, _):
        if self.platform_node_key_type == InputKeyType.PRIVATE:
            self.platform_node_key_type = InputKeyType.PUBLIC
            self.platform_node_private_key = self.edtPlatformNodeKey.text()
            self.edtPlatformNodeKey.setText(self.platform_node_id)
        else:
            self.platform_node_key_type = InputKeyType.PRIVATE
            self.platform_node_id = self.edtPlatformNodeKey.text()
            self.edtPlatformNodeKey.setText(self.platform_node_private_key)
        self.update_ctrls_state()
        self.update_manual_cmd_info()

    @pyqtSlot(str)
    def on_edtIP_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_manual_cmd_info()
                self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    @pyqtSlot(str)
    def on_edtPort_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_manual_cmd_info()
                self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    @pyqtSlot(str)
    def on_edtOperatorPayoutAddress_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_manual_cmd_info()
                self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    @pyqtSlot(bool)
    def on_btnChooseAddressFromWallet_clicked(self, active):
        try:
            self.main_dlg.main_view.stop_threads()
            ui = WalletDlg(self, self.main_dlg.hw_session, initial_mn_sel=None,
                           display_mode=WalletDisplayMode.SELECT_ADDRESS)
            if ui.exec_():
                addr = ui.get_selected_wallet_address()
                if addr:
                    self.edtOperatorPayoutAddress.setText(addr)
        except Exception as e:
            self.error_msg(str(e), True)
        finally:
            self.main_dlg.main_view.resume_threads()

    def on_edtPlatformNodeKey_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_manual_cmd_info()
                self.update_ctrls_state()
        except Exception as e:
            logging.exception(str(e))

    def on_edtPlatformP2PPort_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_manual_cmd_info()
                self.update_ctrls_state()
        except Exception as e:
            self.error_msg(str(e), True)

    def on_edtPlatformHTTPPort_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_manual_cmd_info()
                self.update_ctrls_state()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnGeneratePlatformNodeKey_clicked(self, active):
        if self.platform_node_key_type == InputKeyType.PRIVATE:
            priv_key_hex = generate_ed25519_private_key()
            priv_key_hex = ed25519_private_key_to_tenderdash(priv_key_hex)
            self.platform_node_key_generated = True
            self.edtPlatformNodeKey.setText(priv_key_hex)

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
            if self.validate_data():
                self.send_upd_tx()
            else:
                WndUtils.error_msg("Unable to continue due to unmet conditions.")
        except Exception as e:
            WndUtils.error_msg(str(e))

    @pyqtSlot(bool)
    def on_btnCopyCommandText_clicked(self):
        cmd = self.get_manual_cmd_text()
        cl = QApplication.clipboard()
        cl.setText(cmd)

    def send_upd_tx(self):
        try:
            funding_address = ''
            if self.ip:
                dmn_new_ip_port = self.ip + ':' + str(self.tcp_port)
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
                self.edtPlatformNodeKey.setReadOnly(True)
                self.edtPlatformP2PPort.setReadOnly(True)
                self.edtPlatformHTTPPort.setReadOnly(True)
                self.btnGeneratePlatformNodeKey.setDisabled(True)
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

                self.masternode.ip = self.ip
                self.masternode.tcp_port = int(self.tcp_port)
                if self.masternode.masternode_type == MasternodeType.HPMN:
                    self.masternode.platform_node_key_type = self.platform_node_key_type
                    if self.platform_node_key_type == InputKeyType.PRIVATE:
                        self.masternode.platform_node_private_key = self.platform_node_private_key
                    else:
                        self.masternode.platform_node_id = self.platform_node_id
                    self.masternode.platform_p2p_port = int(self.platform_p2p_port)
                    self.masternode.platform_http_port = int(self.platform_http_port)

                if self.masternode.is_modified() and self.on_mn_config_updated_callback:
                    self.on_mn_config_updated_callback(self.masternode)

                WndUtils.info_msg(msg)

        except Exception as e:
            if str(e).find('protx-dup') >= 0:
                WndUtils.error_msg('The previous protx transaction has not been confirmed yet. Wait until it is '
                                   'confirmed before sending a new transaction.')
            else:
                logging.error('Exception occurred while sending protx update_service: ' + str(e))
                WndUtils.error_msg(str(e))
