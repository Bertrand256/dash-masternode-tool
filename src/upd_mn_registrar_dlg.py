import logging
from typing import Callable

from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.QtWidgets import QDialog
from bitcoinrpc.authproxy import JSONRPCException

import app_cache
from app_config import MasternodeConfig, AppConfig, InputKeyType
from app_defs import FEE_DUFF_PER_BYTE
from dash_utils import wif_privkey_to_address, generate_wif_privkey, generate_bls_privkey, validate_address, \
    bls_privkey_to_pubkey, validate_wif_privkey
from dashd_intf import DashdInterface
from ui import ui_upd_mn_registrar_dlg
from wnd_utils import WndUtils, ProxyStyleNoFocusRect

CACHE_ITEM_SHOW_COMMANDS = 'UpdMnRegistrarDlg_ShowCommands'


class UpdMnRegistrarDlg(QDialog, ui_upd_mn_registrar_dlg.Ui_UpdMnRegistrarDlg, WndUtils):
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
        ui_upd_mn_registrar_dlg.Ui_UpdMnRegistrarDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.on_upd_success_callback = on_upd_success_callback
        self.dmn_operator_key_type = InputKeyType.PRIVATE
        self.dmn_voting_key_type = InputKeyType.PRIVATE
        self.dmn_protx_hash = self.masternode.dmn_tx_hash
        self.dmn_owner_address = ""
        self.dmn_prev_operator_pubkey = ""
        self.dmn_prev_voting_address = ""
        self.dmn_prev_payout_address = ""
        self.dmn_new_operator_pubkey = ""
        self.dmn_new_operator_privkey = ""
        self.dmn_new_voting_address = ""
        self.dmn_new_voting_privkey = ""
        self.dmn_new_payout_address = ""
        self.show_upd_payout = show_upd_payout
        self.show_upd_operator = show_upd_operator
        self.show_upd_voting = show_upd_voting
        self.show_manual_commands = False
        self.setupUi()

    def setupUi(self):
        ui_upd_mn_registrar_dlg.Ui_UpdMnRegistrarDlg.setupUi(self, self)
        self.btnClose.hide()
        self.edtManualCommands.setStyle(ProxyStyleNoFocusRect())
        self.restore_cache_settings()
        self.update_ctrls_state()
        self.minimize_dialog_height()
        self.read_data_from_network()
        self.process_initial_data()
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
            self.dmn_prev_operator_pubkey = status.get('pubKeyOperator')
            self.dmn_prev_voting_address = status.get('votingAddress')
            self.dmn_prev_payout_address = status.get('payoutAddress')
            self.dmn_owner_address = status.get('ownerAddress')

        except Exception as e:
            logging.exception('An exception occurred while reading protx information')
            raise

    def process_initial_data(self):
        try:
            # if the operator key from the current mn configuration doesn't match the key stored on the network
            # use the key from the configuration as an initial value
            if self.masternode.get_dmn_operator_pubkey() != self.dmn_prev_operator_pubkey:
                if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                    self.edtOperatorKey.setText(self.masternode.dmn_operator_private_key)
                else:
                    self.edtOperatorKey.setText(self.masternode.dmn_operator_public_key)
                self.dmn_operator_key_type = self.masternode.dmn_operator_key_type

            # if the voting key from the current mn configuration doesn't match the key stored on the network
            # use the key from the configuration as an initial value
            if self.masternode.get_dmn_voting_public_address(self.app_config.dash_network) != \
                    self.dmn_prev_voting_address:
                if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                    self.edtVotingKey.setText(self.masternode.dmn_voting_private_key)
                else:
                    self.edtVotingKey.setText(self.masternode.dmn_voting_address)
                self.dmn_voting_key_type = self.masternode.dmn_voting_key_type

        except Exception as e:
            logging.exception('An exception occurred while processing the initial data')
            raise

    def update_ctrls_state(self):

        def style_to_color(style: str) -> str:
            if style == 'hl1':
                color = 'color:#00802b'
            else:
                color = ''
            return color

        def get_label_text(prefix:str, key_type: str, tooltip_anchor: str, style: str):
            lbl = prefix + ' ' + \
                  {'privkey': 'private key', 'pubkey': 'public key', 'address': 'Dash address'}.get(key_type, '???')

            change_mode = f'(<a href="{tooltip_anchor}">use {tooltip_anchor}</a>)'
            return f'<table style="float:right;{style_to_color(style)}"><tr><td><b>{lbl}</b></td><td>{change_mode}' \
                f'</td></tr></table>'

        self.edtPayoutAddress.setToolTip('Enter a new payout Dash address.')

        if self.dmn_operator_key_type == InputKeyType.PRIVATE:
            key_type, tooltip_anchor, placeholder_text = ('privkey', 'pubkey', 'Enter a new operator private key.')
            style = ''
        else:
            key_type, tooltip_anchor, placeholder_text = ('pubkey', 'privkey', 'Enter a new operator public key.')
            style = 'hl1'
        self.lblOperatorKey.setText(get_label_text('Operator', key_type, tooltip_anchor, style))
        self.edtOperatorKey.setToolTip(placeholder_text)

        if self.dmn_voting_key_type == InputKeyType.PRIVATE:
            key_type, tooltip_anchor, placeholder_text = ('privkey','address', 'Enter a new voting private key.')
            style = ''
        else:
            key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter a new voting Dash address.')
            style = 'hl1'
        self.lblVotingKey.setText(get_label_text('Voting', key_type, tooltip_anchor, style))
        self.edtVotingKey.setToolTip(placeholder_text)

        self.lblPayoutAddress.setVisible(self.show_upd_payout)
        self.edtPayoutAddress.setVisible(self.show_upd_payout)

        self.lblOperatorKey.setVisible(self.show_upd_operator)
        self.edtOperatorKey.setVisible(self.show_upd_operator)
        self.btnGenerateOperatorKey.setVisible(self.show_upd_operator and
                                               self.dmn_operator_key_type == InputKeyType.PRIVATE)

        self.lblVotingKey.setVisible(self.show_upd_voting)
        self.edtVotingKey.setVisible(self.show_upd_voting)
        self.btnGenerateVotingKey.setVisible(self.show_upd_voting and self.dmn_voting_key_type == InputKeyType.PRIVATE)

        if self.show_manual_commands:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="hide">Hide commands for manual execution</a>')
        else:
            self.lblManualCommands.setText('<a style="text-decoration:none" '
                                           'href="show">Show commands for manual execution</a>')

        self.edtManualCommands.setVisible(self.show_manual_commands)

        self.lblMessage.setText('<span style="color:#ff6600">By clicking <span style="font-weight:800">&lt;Send '
                                'Update Transaction&gt;</span> you agree to send the owner private key to '
                                'the remote RPC node which is necessary to automatically execute the required command ('
                                'read notes <a href="https://github.com/Bertrand256/dash-masternode-tool/blob/'
                                'master/doc/deterministic-mn-migration.md#automatic-method-using-public-rpc-'
                                'nodes-m1">here</a>). If you do not agree, follow the manual steps.</span>')
        self.minimize_dialog_height()

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        if self.dmn_operator_key_type == InputKeyType.PRIVATE:
            self.dmn_operator_key_type = InputKeyType.PUBLIC
        else:
            self.dmn_operator_key_type = InputKeyType.PRIVATE
        self.edtOperatorKey.setText('')
        self.update_ctrls_state()

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        if self.dmn_voting_key_type == InputKeyType.PRIVATE:
            self.dmn_voting_key_type = InputKeyType.PUBLIC
        else:
            self.dmn_voting_key_type = InputKeyType.PRIVATE
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
            tt = 'Change input type to Dash address'
        else:
            tt = 'Change input type to private key'
        self.lblVotingKey.setToolTip(tt)

    @pyqtSlot(str)
    def on_lblManualCommands_linkActivated(self, link):
        self.show_manual_commands = (link == 'show')
        self.update_ctrls_state()

    @pyqtSlot(bool)
    def on_btnGenerateOperatorKey_clicked(self, active):
        self.edtOperatorKey.setText(generate_bls_privkey())

    @pyqtSlot(bool)
    def on_btnGenerateVotingKey_clicked(self, active):
        k = generate_wif_privkey(self.app_config.dash_network, compressed=True)
        self.edtVotingKey.setText(k)

    def validate_data(self):
        payout_address = self.edtPayoutAddress.text()
        if payout_address:
            if not validate_address(payout_address, self.app_config.dash_network):
                raise Exception('Invalid payout Dash address')
            else:
                self.dmn_new_payout_address = payout_address
        else:
            self.dmn_new_payout_address = self.dmn_prev_payout_address

        key = self.edtOperatorKey.text().strip()
        if key:
            if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                self.dmn_new_operator_privkey = key

                try:
                    b = bytes.fromhex(self.dmn_new_operator_privkey)
                    if len(b) != 32:
                        raise Exception('invalid length (' + str(len(b)) + ')')
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    raise Exception('Invalid operator private key: ' + str(e))

                try:
                    self.dmn_new_operator_pubkey = bls_privkey_to_pubkey(self.dmn_new_operator_privkey)
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    raise Exception('Invalid operator private key: ' + str(e))
            else:
                self.dmn_new_operator_pubkey = key
                self.dmn_new_operator_privkey = ''
                try:
                    b = bytes.fromhex(self.dmn_new_operator_pubkey)
                    if len(b) != 48:
                        raise Exception('invalid length (' + str(len(b)) + ')')
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    raise Exception('Invalid operator public key: ' + str(e))
        else:
            self.dmn_new_operator_pubkey = self.dmn_prev_operator_pubkey
            self.dmn_new_operator_privkey = ''

        key = self.edtVotingKey.text().strip()
        if key:
            if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                self.dmn_new_voting_privkey = key
                if not validate_wif_privkey(self.dmn_new_voting_privkey, self.app_config.dash_network):
                    self.edtVotingKey.setFocus()
                    raise Exception('Invalid voting private key.')
                else:
                    self.dmn_new_voting_address = wif_privkey_to_address(self.dmn_new_voting_privkey,
                                                                         self.app_config.dash_network)
            else:
                self.dmn_new_voting_address = key
                self.dmn_new_voting_privkey = ''
                if not validate_address(self.dmn_new_voting_address, self.app_config.dash_network):
                    self.edtVotingKey.setFocus()
                    raise Exception('Invalid voting Dash address.')
        else:
            self.dmn_new_voting_address = self.dmn_prev_voting_address
            self.dmn_new_voting_privkey = ''

    def update_manual_cmd_info(self):
        try:
            self.validate_data()
            changed = (self.show_upd_payout and bool(self.edtPayoutAddress.text())) or \
                      (self.show_upd_operator and bool(self.edtOperatorKey.text())) or \
                      (self.show_upd_voting and bool(self.edtVotingKey.text()))

            if changed:
                cmd = f'protx update_registrar "{self.dmn_protx_hash}" "{self.dmn_new_operator_pubkey}" ' \
                    f'"{self.dmn_new_voting_address}" "{self.dmn_new_payout_address}" ' \
                    f'"<span style="color:green">feeSourceAddress</span>"'
                msg = "<ol>" \
                      "<li>Start a Dash Core wallet with sufficient funds to cover a transaction fee.</li>"
                msg += "<li>Import the owner private key into the Dash Core wallet if you haven't done this " \
                       "before (<a href=\"https://github.com/Bertrand256/dash-masternode-tool/blob/master/doc/" \
                       "deterministic-mn-migration.md#can-i-modify-the-payout-address-without-resetting-the-" \
                       "place-in-the-payment-queue\">details</a>).</li>"
                msg += "<li>Execute the following command in the Dash Core debug console:<br><br>"
                msg += "  <code style=\"background-color:#e6e6e6\">" + cmd + '</code></li><br>'
                msg += 'Replace <span style="color:green">feeSourceAddress</span> with the address being the ' \
                       'source of the transaction fee.'
                msg += "</ol>"
            else:
                msg = '<span style="">No data has been changed yet.</span>'

        except Exception as e:
            msg = '<span style="color:red">Error: ' + str(e) +'</span>'

        self.edtManualCommands.setHtml(msg)

    @pyqtSlot(str)
    def on_edtPayoutAddress_textChanged(self, text):
        self.update_manual_cmd_info()

    @pyqtSlot(str)
    def on_edtVotingKey_textChanged(self, text):
        self.update_manual_cmd_info()

    @pyqtSlot(str)
    def on_edtOperatorKey_textChanged(self, text):
        self.update_manual_cmd_info()

    @pyqtSlot(bool)
    def on_btnSendUpdateTx_clicked(self, enabled):
        self.read_data_from_network()
        self.validate_data()
        if self.dmn_prev_payout_address == self.dmn_new_payout_address and \
            self.dmn_prev_operator_pubkey == self.dmn_new_operator_pubkey and \
            self.dmn_prev_voting_address == self.dmn_new_voting_address:
            WndUtils.warnMsg('Nothing is changed compared to the data stored in the Dash network.')
        else:
            self.send_upd_tx()

    def send_upd_tx(self):
        # verify the owner key used in the configuration
        if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE and self.masternode.dmn_owner_private_key:
            owner_address = wif_privkey_to_address(self.masternode.dmn_owner_private_key,
                                                   self.app_config.dash_network)
            if owner_address != self.dmn_owner_address:
                raise Exception('Inconsistency of the owner key between the app configuration and the data '
                                'on the Dash network.')
        else:
            raise Exception('To use this feature, you need to have the owner private key in your masternode '
                            'configuration.')

        try:
            funding_address = ''
            params = ['update_registrar',
                      self.dmn_protx_hash,
                      self.dmn_new_operator_pubkey,
                      self.dmn_new_voting_address,
                      self.dmn_new_payout_address,
                      funding_address]

            try:
                upd_reg_support = self.dashd_intf.checkfeaturesupport('protx_update_registrar',
                                                                      self.app_config.app_version)
                if not upd_reg_support.get('enabled'):
                    if upd_reg_support.get('message'):
                        raise Exception(upd_reg_support.get('message'))
                    else:
                        raise Exception('The \'protx_update_registrar\' function is not supported by the RPC node '
                                        'you are connected to.')
                public_proxy_node = True

                active = self.app_config.feature_update_registrar_automatic.get_value()
                if not active:
                    msg = self.app_config.feature_update_registrar_automatic.get_message()
                    if not msg:
                        msg = 'The functionality of the automatic execution of the update_registrar command on the ' \
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
                params.append(self.masternode.dmn_owner_private_key)

            upd_tx_hash = self.dashd_intf.rpc_call(True, False, 'protx', *params)

            if upd_tx_hash:
                logging.info('update_registrar successfully executed, tx hash: ' + upd_tx_hash)
                changed = False
                if self.dmn_new_voting_address != self.dmn_prev_voting_address:
                    changed = self.masternode.dmn_voting_key_type != self.dmn_voting_key_type
                    self.masternode.dmn_voting_key_type = self.dmn_voting_key_type
                    if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                        changed = changed or self.masternode.dmn_voting_private_key != self.dmn_new_voting_privkey
                        self.masternode.dmn_voting_private_key = self.dmn_new_voting_privkey
                    else:
                        changed = changed or self.masternode.dmn_voting_address != self.dmn_new_voting_address
                        self.masternode.dmn_voting_address = self.dmn_new_voting_address

                if self.dmn_new_operator_pubkey != self.dmn_prev_operator_pubkey:
                    changed = changed or self.masternode.dmn_operator_key_type != self.dmn_operator_key_type
                    self.masternode.dmn_operator_key_type = self.dmn_operator_key_type
                    if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                        changed = changed or self.masternode.dmn_operator_private_key != self.dmn_new_operator_privkey
                        self.masternode.dmn_operator_private_key = self.dmn_new_operator_privkey
                    else:
                        changed = changed or self.masternode.dmn_operator_public_key != self.dmn_new_operator_pubkey
                        self.masternode.dmn_operator_public_key = self.dmn_new_operator_pubkey

                if self.on_upd_success_callback:
                    self.on_upd_success_callback(self.masternode)

                self.btnSendUpdateTx.setDisabled(True)
                self.edtPayoutAddress.setReadOnly(True)
                self.edtOperatorKey.setReadOnly(True)
                self.edtVotingKey.setReadOnly(True)
                self.btnGenerateOperatorKey.setDisabled(True)
                self.btnGenerateVotingKey.setDisabled(True)
                self.btnClose.show()

                url = self.app_config.get_block_explorer_tx()
                if url:
                    url = url.replace('%TXID%', upd_tx_hash)
                    upd_tx_hash = f'<a href="{url}">{upd_tx_hash}</a>'

                msg = 'The update_registrar transaction has been successfully sent. ' \
                     f'Tx hash: {upd_tx_hash}. <br><br>' \
                     f'The new values ​​will be visible on the network after the transaction is confirmed, i.e. in ' \
                     f'about 2.5 minutes.'

                if changed:
                    msg += '<br><br>The app configuration has been updated accordingly.'

                WndUtils.infoMsg(msg)
        except Exception as e:
            if str(e).find('protx-dup') >= 0:
                WndUtils.errorMsg('The previous protx transaction has not been confirmed yet. Wait until it is '
                         'confirmed before sending a new transaction.')
            else:
                logging.error('Exception occurred while sending protx update_registrar.')
                WndUtils.errorMsg(str(e))
