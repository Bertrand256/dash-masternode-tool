import logging
from typing import Callable

from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.QtWidgets import QDialog, QMessageBox, QLabel, QApplication
from bitcoinrpc.authproxy import JSONRPCException

import app_cache
import dash_utils
from app_config import MasternodeConfig, AppConfig, InputKeyType
from app_defs import FEE_DUFF_PER_BYTE
from dash_utils import wif_privkey_to_address, generate_wif_privkey, generate_bls_privkey, validate_address, \
    bls_privkey_to_pubkey, bls_privkey_to_pubkey_legacy, validate_wif_privkey
from dashd_intf import DashdInterface
from ui import ui_upd_mn_registrar_dlg
from wnd_utils import WndUtils, ProxyStyleNoFocusRect, QDetectThemeChange, get_widget_font_color_blue, \
    get_widget_font_color_green
from wallet_dlg import WalletDlg, WalletDisplayMode

CACHE_ITEM_SHOW_COMMANDS = 'UpdMnRegistrarDlg_ShowCommands'


class UpdMnRegistrarDlg(QDialog, QDetectThemeChange, ui_upd_mn_registrar_dlg.Ui_UpdMnRegistrarDlg, WndUtils):
    def __init__(self,
                 main_dlg,
                 app_config: AppConfig,
                 dashd_intf: DashdInterface,
                 masternode: MasternodeConfig,
                 on_upd_success_callback: Callable,
                 show_upd_payout: bool,
                 show_upd_operator: bool,
                 show_upd_voting: bool):
        QDialog.__init__(self, main_dlg)
        QDetectThemeChange.__init__(self)
        ui_upd_mn_registrar_dlg.Ui_UpdMnRegistrarDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.updating_ui = False
        self.on_upd_success_callback = on_upd_success_callback
        self.operator_key_type = InputKeyType.PRIVATE
        self.operator_key_generated_here: bool = False
        self.new_bls_scheme_active: bool = app_config.feature_new_bls_scheme.get_value()
        self.legacy_operator_key: bool = False  # it's only used if self.new_bls_scheme_active is True,
                                                # that is - the v19 fork is active
        self.update_registrar_rpc_command: str = ''
        self.voting_key_type = InputKeyType.PRIVATE
        self.dmn_protx_hash = self.masternode.protx_hash
        self.owner_address = ""
        self.dmn_prev_operator_pubkey = ""
        self.dmn_prev_voting_address = ""
        self.dmn_prev_payout_address = ""
        self.dmn_new_operator_pubkey = ""
        self.dmn_new_operator_privkey = ""
        self.dmn_new_voting_address = ""
        self.dmn_new_voting_privkey = ""
        self.dmn_new_payout_address = ""
        self.general_err_msg = ''
        self.owner_key_err_msg = ''
        self.payout_address_err_msg = ''
        self.operator_key_err_msg = ''
        self.voting_key_err_msg = ''
        self.show_upd_payout = show_upd_payout
        self.show_upd_operator = show_upd_operator
        self.show_upd_voting = show_upd_voting
        self.show_manual_commands = False
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        ui_upd_mn_registrar_dlg.Ui_UpdMnRegistrarDlg.setupUi(self, self)
        self.updating_ui = True
        self.btnClose.hide()
        self.edtManualCommands.setStyle(ProxyStyleNoFocusRect())
        WndUtils.set_icon(self, self.btnCopyCommandText, 'content-copy@16px.png')
        if self.show_upd_payout:
            self.setWindowTitle("Update payout address")
        elif self.show_upd_voting:
            self.setWindowTitle("Update voting key")
        elif self.show_upd_operator:
            self.setWindowTitle("Update operator key")
        if not self.new_bls_scheme_active:
            self.chbLegacyOperatorKey.hide()
        else:
            self.chbLegacyOperatorKey.show()
        self.restore_cache_settings()
        try:
            self.read_data_from_network()
        except Exception as e:
            WndUtils.error_msg(str(e))
        self.process_initial_data()
        self.update_manual_cmd_info()
        self.updating_ui = False
        self.update_ctrls_state()
        self.minimize_dialog_height()
        cl = QApplication.clipboard()
        cl.changed.connect(self.strip_clipboard_contents)

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

    def strip_clipboard_contents(self, mode):
        """ Remove leading/trailing spaces and newline characters from a text copied do clipboard."""
        try:
            cl = QApplication.clipboard()
            t = cl.text()
            if t and t.strip() != t:
                # QClipboard.blockSignals not working with QT 5.15 on Windows, so we need the above additional
                # protection to avoid infinite loop when setting a new clipboard value
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

    def set_buttons_height(self):
        try:
            h = self.edtPayoutAddress.height()
            for ctrl in (self.btnChooseAddressFromWallet, self.btnGenerateOperatorKey, self.btnGenerateVotingKey):
                ctrl.setFixedHeight(h)
        except Exception as e:
            logging.exception(str(e))

    def read_data_from_network(self):
        try:
            protx = None
            if not self.dmn_protx_hash:
                for protx in self.dashd_intf.protx('list', 'registered', True):
                    protx_state = protx.get('state')
                    if (protx_state and protx_state.get(
                            'service') == self.masternode.ip + ':' + str(self.masternode.tcp_port)) or \
                            (protx.get('collateralHash') == self.masternode.collateral_tx and
                             str(protx.get('collateralIndex')) == str(self.masternode.collateral_tx_index)):
                        self.dmn_protx_hash = protx.get("proTxHash")
                        break
                if not self.dmn_protx_hash:
                    self.general_err_msg = "Couldn't find protx hash for this masternode. Enter the protx hash " \
                                           "value in your masternode configuration."

            if not protx:
                try:
                    protx = self.dashd_intf.protx('info', self.dmn_protx_hash)
                except Exception as e:
                    if str(e).find('not found') >= 0:
                        self.general_err_msg = 'A protx transaction from your configuration does not exist or is ' \
                                               'inactive.'
                    else:
                        raise

            if protx:
                status = protx.get('state', dict)
                self.dmn_prev_operator_pubkey = status.get('pubKeyOperator')
                self.dmn_prev_voting_address = status.get('votingAddress')
                self.dmn_prev_payout_address = status.get('payoutAddress')
                self.owner_address = status.get('ownerAddress')

        except Exception as e:
            logging.exception('An exception occurred while reading protx information')
            self.general_err_msg = 'Error when verifying masternode protx hash.'

    def process_initial_data(self):
        try:
            if self.dmn_prev_payout_address:
                self.edtPayoutAddress.setText(self.dmn_prev_payout_address)

            pub_operator = self.masternode.get_operator_pubkey(self.app_config.feature_new_bls_scheme.get_value())
            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                self.edtOperatorKey.setText(self.masternode.operator_private_key)
            else:
                self.edtOperatorKey.setText(pub_operator)
            self.operator_key_type = self.masternode.operator_key_type

            # if the voting key from the current mn configuration doesn't match the key stored on the network
            # use the key from the configuration as an initial value
            voting_addr = self.masternode.get_voting_public_address(self.app_config.dash_network)
            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                self.edtVotingKey.setText(self.masternode.voting_private_key)
            else:
                self.edtVotingKey.setText(voting_addr)
            self.voting_key_type = self.masternode.voting_key_type

        except Exception as e:
            logging.exception('An exception occurred while processing the initial data')
            raise

    def update_ctrls_state(self):
        blue_color = get_widget_font_color_blue(self.lblPayoutAddress)

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
                  {'privkey': 'private key', 'pubkey': 'public key', 'address': 'address'}.get(key_type, '???')

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

        self.edtPayoutAddress.setToolTip('Enter a new payout address.')

        if self.operator_key_type == InputKeyType.PRIVATE:
            key_type, tooltip_anchor, placeholder_text = ('privkey', 'pubkey', 'Enter a new operator private key.')
            style = ''
        else:
            key_type, tooltip_anchor, placeholder_text = ('pubkey', 'privkey', 'Enter a new operator public key.')
            style = 'hl1'
        set_key_related_label(self.lblOperatorKey, 'Operator', key_type, tooltip_anchor, style)
        self.edtOperatorKey.setToolTip(placeholder_text)

        if self.voting_key_type == InputKeyType.PRIVATE:
            key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter a new voting private key.')
            style = ''
        else:
            key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter a new voting address.')
            style = 'hl1'
        set_key_related_label(self.lblVotingKey, 'Voting', key_type, tooltip_anchor, style)
        self.edtVotingKey.setToolTip(placeholder_text)

        self.lblPayoutAddress.setVisible(self.show_upd_payout)
        self.edtPayoutAddress.setVisible(self.show_upd_payout)
        self.btnChooseAddressFromWallet.setVisible(self.show_upd_payout)
        self.lblPayoutAddressMsg.setVisible(self.show_upd_payout)

        self.lblOperatorKey.setVisible(self.show_upd_operator)
        self.edtOperatorKey.setVisible(self.show_upd_operator)
        self.btnGenerateOperatorKey.setVisible(self.show_upd_operator and
                                               self.operator_key_type == InputKeyType.PRIVATE)
        self.lblOperatorKeyMsg.setVisible(self.show_upd_operator)

        self.lblVotingKey.setVisible(self.show_upd_voting)
        self.edtVotingKey.setVisible(self.show_upd_voting)
        self.btnGenerateVotingKey.setVisible(self.show_upd_voting and self.voting_key_type == InputKeyType.PRIVATE)
        self.lblVotingKeyMsg.setVisible(self.show_upd_voting)

        if self.show_manual_commands:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="hide">Hide commands for manual execution</a>')
        else:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="show">Show commands for manual execution</a>')

        self.btnCopyCommandText.setVisible(self.show_manual_commands)
        self.edtManualCommands.setVisible(self.show_manual_commands)

        self.lblMessage.setText('<span style="color:#ff6600">By clicking <span style="font-weight:800">&lt;Send '
                                'Update Transaction&gt;</span> you agree to send the owner private key to '
                                'the remote RPC node which is necessary to automatically execute the required command ('

                                'read notes <a href="https://github.com/firoorg/firo-masternode-tool/blob/master'
                                '/doc/deterministic-mn-migration.md#automatic-method-using-public-rpc-nodes-m1">'
                                'here</a>). If you do not agree, follow the manual steps.</span>')
        gen_msg = ''
        if self.general_err_msg:
            gen_msg = self.general_err_msg
        if self.owner_key_err_msg:
            if gen_msg:
                gen_msg += '<br>'
            gen_msg += self.owner_key_err_msg
        set_info_label(self.lblGeneralErrorMsg, gen_msg, 'error')

        if self.show_upd_payout:
            if self.payout_address_err_msg:
                set_info_label(self.lblPayoutAddressMsg, self.payout_address_err_msg, 'error')
            else:
                set_info_label(self.lblPayoutAddressMsg, "The Firo address to which the owner's part of the masternode"
                                                         " reward is to be sent.", "info")

        if self.show_upd_operator:
            set_info_label(self.lblOperatorKeyMsg, self.operator_key_err_msg, 'error')

        if self.show_upd_voting:
            set_info_label(self.lblVotingKeyMsg, self.voting_key_err_msg, 'error')

        self.minimize_dialog_height()

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        if self.operator_key_type == InputKeyType.PRIVATE:
            self.operator_key_type = InputKeyType.PUBLIC
        else:
            self.operator_key_type = InputKeyType.PRIVATE
        self.edtOperatorKey.setText('')
        self.update_ctrls_state()

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        if self.voting_key_type == InputKeyType.PRIVATE:
            self.voting_key_type = InputKeyType.PUBLIC
        else:
            self.voting_key_type = InputKeyType.PRIVATE
        self.edtVotingKey.setText('')
        self.update_ctrls_state()

    @pyqtSlot(str)
    def on_lblOperatorKey_linkHovered(self, link):
        if link == 'pubkey':
            tt = 'Change input type to public key'
        else:
            tt = 'Change input type to private key'
        self.lblOperatorKey.setToolTip(tt)

    @pyqtSlot(str)
    def on_lblVotingKey_linkHovered(self, link):
        if link == 'address':
            tt = 'Change input type to Firo address'
        else:
            tt = 'Change input type to private key'
        self.lblVotingKey.setToolTip(tt)

    @pyqtSlot(str)
    def on_lblManualCommands_linkActivated(self, link):
        self.show_manual_commands = (link == 'show')
        self.update_ctrls_state()

    @pyqtSlot(bool)
    def on_btnGenerateOperatorKey_clicked(self, active):
        try:
            self.edtOperatorKey.setText(generate_bls_privkey())
            self.operator_key_generated_here = True
            self.chbLegacyOperatorKey.setChecked(False)
            self.update_manual_cmd_info()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnChooseAddressFromWallet_clicked(self, active):
        try:
            if self.show_upd_payout:
                self.main_dlg.main_view.stop_threads()
                ui = WalletDlg(self, self.main_dlg.hw_session, initial_mn_sel=None,
                               display_mode=WalletDisplayMode.SELECT_ADDRESS)
                if ui.exec_():
                    addr = ui.get_selected_wallet_address()
                    if addr:
                        self.edtPayoutAddress.setText(addr)
                    self.update_manual_cmd_info()
                else:
                    pass
        except Exception as e:
            self.error_msg(str(e), True)
        finally:
            self.main_dlg.main_view.resume_threads()

    @pyqtSlot(bool)
    def on_btnGenerateVotingKey_clicked(self, active):
        k = generate_wif_privkey(self.app_config.dash_network, compressed=True)
        self.edtVotingKey.setText(k)

    @pyqtSlot(bool)
    def on_chbLegacyOperatorKey_toggled(self, checked):
        try:
            self.legacy_operator_key = checked
            if not self.updating_ui:
                self.validate_data()
                self.update_ctrls_state()
                self.update_manual_cmd_info()
        except Exception as e:
            self.error_msg(str(e), True)

    def validate_data(self) -> bool:
        errors_occurred = False

        if self.show_upd_payout:
            self.payout_address_err_msg = ''
            payout_address = self.edtPayoutAddress.text()
            if payout_address:
                if not validate_address(payout_address, self.app_config.dash_network):
                    self.payout_address_err_msg = 'Invalid payout Dash address'
                    errors_occurred = True
                else:
                    self.dmn_new_payout_address = payout_address
        else:
            self.dmn_new_payout_address = ''

        self.update_registrar_rpc_command = 'update_registrar'
        if self.new_bls_scheme_active:
            self.legacy_operator_key = self.chbLegacyOperatorKey.isChecked()
            if self.legacy_operator_key:
                # Use the "update_registrar_legacy" call only when v19 fork is active, otherwise the "update_registrar"
                # call is used and basically does the same
                self.update_registrar_rpc_command = 'update_registrar_legacy'
        else:
            self.legacy_operator_key = True

        if self.show_upd_operator:
            key = self.edtOperatorKey.text().strip()
            if key:
                self.operator_key_err_msg = ''
                if self.operator_key_type == InputKeyType.PRIVATE:
                    self.dmn_new_operator_privkey = key
                    if not dash_utils.validate_bls_privkey(self.dmn_new_operator_privkey, not self.legacy_operator_key and
                                                           self.app_config.feature_new_bls_scheme.get_value()):
                        self.operator_key_err_msg = 'Invalid operator private key'
                        self.edtOperatorKey.setFocus()
                        errors_occurred = True
                    try:
                        self.dmn_new_operator_pubkey = bls_privkey_to_pubkey(
                            self.dmn_new_operator_privkey, not self.legacy_operator_key and
                                                           self.app_config.feature_new_bls_scheme.get_value())
                    except Exception as e:
                        self.edtOperatorKey.setFocus()
                        self.operator_key_err_msg = 'Invalid operator private key: ' + str(e)
                        errors_occurred = True
                else:
                    self.dmn_new_operator_pubkey = key
                    self.dmn_new_operator_privkey = ''
                    new_bls_scheme = not self.legacy_operator_key and self.app_config.feature_new_bls_scheme.get_value()
                    if not dash_utils.validate_bls_pubkey(self.dmn_new_operator_pubkey, new_bls_scheme):
                        self.operator_key_err_msg = 'Invalid operator public key'
                        errors_occurred = True
            else:
                self.dmn_new_operator_pubkey = self.dmn_prev_operator_pubkey
                self.dmn_new_operator_privkey = ''
        else:
            self.dmn_new_operator_pubkey = ''
            self.dmn_new_operator_privkey = ''

        if self.show_upd_voting:
            key = self.edtVotingKey.text().strip()
            self.voting_key_err_msg = ''
            if key:
                if self.voting_key_type == InputKeyType.PRIVATE:
                    self.dmn_new_voting_privkey = key
                    if not validate_wif_privkey(self.dmn_new_voting_privkey, self.app_config.dash_network):
                        self.edtVotingKey.setFocus()
                        self.voting_key_err_msg = 'Invalid voting private key.'
                        errors_occurred = True
                    else:
                        self.dmn_new_voting_address = wif_privkey_to_address(self.dmn_new_voting_privkey,
                                                                             self.app_config.dash_network)
                else:
                    self.dmn_new_voting_address = key
                    self.dmn_new_voting_privkey = ''
                    if not validate_address(self.dmn_new_voting_address, self.app_config.dash_network):
                        self.edtVotingKey.setFocus()
                        self.voting_key_err_msg = 'Invalid voting Dash address.'
                        errors_occurred = True
            else:
                self.dmn_new_voting_address = self.dmn_prev_voting_address
                self.dmn_new_voting_privkey = ''
        else:
            self.dmn_new_voting_address = ''
            self.dmn_new_voting_privkey = ''

        self.owner_key_err_msg = ''
        if self.masternode.owner_key_type != InputKeyType.PRIVATE or not self.masternode.owner_private_key:
            self.owner_key_err_msg = "To use this feature, you need to have the owner private key in your " \
                                     "masternode configuration, but you don't."
            errors_occurred = True

        return not errors_occurred

    def get_manual_cmd_text(self, fee_source_info=None) -> str:
        cmd = f'protx {self.update_registrar_rpc_command} "{self.dmn_protx_hash}" ' \
              f'"{self.dmn_new_operator_pubkey}" ' \
              f'"{self.dmn_new_voting_address}" "{self.dmn_new_payout_address}" '

        if fee_source_info:
            cmd += fee_source_info
        else:
            cmd += '"feeSourceAddress"'
        return cmd

    def update_manual_cmd_info(self):
        try:
            self.validate_data()
            green_color = get_widget_font_color_green(self.lblVotingKey)
            cmd = self.get_manual_cmd_text(
                fee_source_info=f'"<span style="color:{green_color}">feeSourceAddress</span>"')

            msg = "<ol>" \
                  "<li>Start a Dash Core wallet with sufficient funds to cover a transaction fee.</li>"
            msg += "<li>Import the owner private key into the Dash Core wallet if you haven't done this " \
                   "before.</li>"
            msg += "<li>Execute the following command in the Dash Core debug console:<br><br>"
            msg += "  <code>" + cmd + '</code></li><br>'
            msg += f'Replace <span style="color:{green_color}">feeSourceAddress</span> with the address being the ' \
                   'source of the transaction fee.'
            msg += "</ol>"
        except Exception as e:
            msg = '<span style="color:red">Error: ' + str(e) + '</span>'

        self.edtManualCommands.setHtml(msg)

    @pyqtSlot(str)
    def on_edtPayoutAddress_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_ctrls_state()
                self.update_manual_cmd_info()
        except Exception as e:
            logging.exception(str(e))

    @pyqtSlot(str)
    def on_edtVotingKey_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_ctrls_state()
                self.update_manual_cmd_info()
        except Exception as e:
            logging.exception(str(e))

    @pyqtSlot(str)
    def on_edtOperatorKey_textChanged(self, text):
        try:
            if not self.updating_ui:
                self.validate_data()
                self.update_ctrls_state()
                self.update_manual_cmd_info()
        except Exception as e:
            logging.exception(str(e))

    @pyqtSlot(bool)
    def on_btnCopyCommandText_clicked(self):
        cmd = self.get_manual_cmd_text()
        cl = QApplication.clipboard()
        cl.setText(cmd)

    @pyqtSlot(bool)
    def on_btnSendUpdateTx_clicked(self, enabled):
        try:
            if self.validate_data():
                if not ((self.show_upd_payout and self.dmn_prev_payout_address != self.dmn_new_payout_address) or
                        (self.show_upd_operator and self.dmn_prev_operator_pubkey != self.dmn_new_operator_pubkey) or
                        (self.show_upd_voting and self.dmn_prev_voting_address != self.dmn_new_voting_address)):

                    if WndUtils.query_dlg('Nothing is changed compared to the data stored in the Firo network. Do you '
                                          'really want to continue?',
                                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                          default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == \
                            QMessageBox.Cancel:
                        return
                self.send_upd_tx()
            else:
                WndUtils.error_msg("Unable to continue due to unmet conditions.")
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def send_upd_tx(self):
        # verify the owner key used in the configuration
        if self.masternode.owner_key_type == InputKeyType.PRIVATE and self.masternode.owner_private_key:
            owner_address = wif_privkey_to_address(self.masternode.owner_private_key,
                                                   self.app_config.dash_network)
            if owner_address != self.owner_address:
                if WndUtils.query_dlg(
                        'Inconsistency of the owner key between the app configuration and the data '
                        'on the Firo network.\nDo you really want to continue?',
                        buttons=QMessageBox.Yes | QMessageBox.Cancel,
                        default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                    return
        else:
            WndUtils.error_msg('To use this feature, you need to have the owner private key in your masternode '
                               'configuration.')
            return

        try:
            funding_address = ''

            params = [self.update_registrar_rpc_command,
                      self.dmn_protx_hash,
                      self.dmn_new_operator_pubkey,
                      self.dmn_new_voting_address,
                      self.dmn_new_payout_address,
                      funding_address]

            try:
                upd_reg_support = self.dashd_intf.checkfeaturesupport('protx_' + self.update_registrar_rpc_command,
                                                                      self.app_config.app_version)
                if not upd_reg_support.get('enabled'):
                    if upd_reg_support.get('message'):
                        raise Exception(upd_reg_support.get('message'))
                    else:
                        raise Exception(f'The \'protx_{self.update_registrar_rpc_command}\' function is not '
                                        f'supported by the RPC node you are connected to.')
                public_proxy_node = True

                active = self.app_config.feature_update_registrar_automatic.get_value()
                if not active:
                    msg = self.app_config.feature_update_registrar_automatic.get_message()
                    if not msg:
                        msg = f'The functionality of the automatic execution of the ' \
                              f'{self.update_registrar_rpc_command} command on the ' \
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
            else:
                params.append(self.masternode.owner_private_key)

            upd_tx_hash = self.dashd_intf.rpc_call(True, False, 'protx', *params)

            if upd_tx_hash:
                logging.info(f'{self.update_registrar_rpc_command} successfully executed, tx hash: ' + upd_tx_hash)
                changed = False

                if self.show_upd_voting and self.dmn_new_voting_address and \
                        self.dmn_new_voting_address != self.dmn_prev_voting_address:

                    changed = self.masternode.voting_key_type != self.voting_key_type
                    self.masternode.voting_key_type = self.voting_key_type
                    if self.voting_key_type == InputKeyType.PRIVATE:
                        changed = changed or self.masternode.voting_private_key != self.dmn_new_voting_privkey
                        self.masternode.voting_private_key = self.dmn_new_voting_privkey
                    else:
                        changed = changed or self.masternode.voting_address != self.dmn_new_voting_address
                        self.masternode.voting_address = self.dmn_new_voting_address

                if self.show_upd_operator and self.dmn_new_operator_pubkey and \
                        self.dmn_new_operator_pubkey != self.dmn_prev_operator_pubkey:

                    changed = changed or self.masternode.operator_key_type != self.operator_key_type
                    self.masternode.operator_key_type = self.operator_key_type
                    if self.operator_key_type == InputKeyType.PRIVATE:
                        changed = changed or self.masternode.operator_private_key != self.dmn_new_operator_privkey
                        self.masternode.operator_private_key = self.dmn_new_operator_privkey
                    else:
                        changed = changed or self.masternode.operator_public_key != self.dmn_new_operator_pubkey
                        self.masternode.operator_public_key = self.dmn_new_operator_pubkey

                if self.on_upd_success_callback:
                    self.on_upd_success_callback(self.masternode)

                self.btnSendUpdateTx.setDisabled(True)
                self.edtPayoutAddress.setReadOnly(True)
                self.edtOperatorKey.setReadOnly(True)
                self.edtVotingKey.setReadOnly(True)
                self.btnGenerateOperatorKey.setDisabled(True)
                self.btnGenerateVotingKey.setDisabled(True)
                self.btnChooseAddressFromWallet.setDisabled(True)
                self.btnClose.show()

                url = self.app_config.get_block_explorer_tx()
                if url:
                    url = url.replace('%TXID%', upd_tx_hash)
                    upd_tx_hash = f'<a href="{url}">{upd_tx_hash}</a>'

                msg = f'The {self.update_registrar_rpc_command} transaction has been successfully sent. ' \
                      f'Tx hash: {upd_tx_hash}. <br><br>' \
                      f'The new values ​​will be visible on the network after the transaction is confirmed, ' \
                      f'i.e. in about 2.5 minutes.'

                if changed:
                    msg += '<br><br>The app configuration has been updated accordingly.'

                WndUtils.info_msg(msg)
        except Exception as e:
            if str(e).find('protx-dup') >= 0:
                WndUtils.error_msg('The previous protx transaction has not been confirmed yet. Wait until it is '
                                   'confirmed before sending a new transaction.')
            else:
                logging.error('Exception occurred while sending protx update_registrar.')
                WndUtils.error_msg(str(e), True)
