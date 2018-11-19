#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-11
import base64
import json
import logging
import time
from functools import partial
from typing import List
import ipaddress

from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import QDialog
from bitcoinrpc.authproxy import EncodeDecimal

import hw_intf
from app_config import MasternodeConfig, AppConfig
from bip44_wallet import Bip44Wallet, BreakFetchTransactionsException
from dash_utils import generate_bls_privkey, generate_wif_privkey, validate_address, wif_privkey_to_address, \
    validate_wif_privkey, bls_privkey_to_pubkey
from dashd_intf import DashdInterface
from hw_common import HardwareWalletCancelException
from thread_fun_dlg import CtrlObject
from ui import ui_reg_masternode_dlg
from wallet_common import Bip44AccountType, Bip44AddressType
from wnd_utils import WndUtils


STEP_MN_DATA = 1
STEP_DASHD_TYPE = 2
STEP_AUTOMATIC_RPC_NODE = 3
STEP_MANUAL_OWN_NODE = 4

NODE_TYPE_PUBLIC_RPC = 1
NODE_TYPE_OWN = 2


log = logging.getLogger('dmt.reg_masternode')


class RegMasternodeDlg(QDialog, ui_reg_masternode_dlg.Ui_RegMasternodeDlg, WndUtils):
    def __init__(self, main_dlg, config: AppConfig, dashd_intf: DashdInterface, masternode: MasternodeConfig):
        QDialog.__init__(self, main_dlg)
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = config
        self.dashd_intf = dashd_intf
        self.style = '<style>.info{color:darkblue} .warning{color:red} .error{background-color:red;color:white}</style>'
        self.operator_reward_saved = None
        self.operator_pkey_old: str = None
        self.voting_pkey_old: str = None
        self.operator_pkey_generated: str = None
        self.voting_pkey_generated: str = None
        self.current_step = STEP_MN_DATA
        self.step_stack: List[int] = []
        self.proregtx_prepare_thread_ref = None
        self.deterministic_mns_spork_active = False
        self.dmn_collateral_tx: str = None
        self.dmn_collateral_tx_index: int = None
        self.dmn_collateral_tx_address: str = None
        self.dmn_collateral_tx_address_path: str = None
        self.dmn_ip: str = None
        self.dmn_tcp_port: int = None
        self.dmn_owner_payout_addr: str = None
        self.dmn_operator_reward: int = 0
        self.dmn_owner_privkey: str = None
        self.dmn_owner_address: str = None
        self.dmn_operator_privkey: str = None
        self.dmn_operator_pubkey: str = None
        self.dmn_voting_privkey: str = None
        self.dmn_voting_address: str = None
        if self.masternode:
            self.dmn_collateral_tx_address_path = self.masternode.collateralBip32Path
        self.bip44_wallet = Bip44Wallet(self.app_config.hw_coin_name, self.main_dlg.hw_session,
                                        self.app_config.db_intf, self.dashd_intf, self.app_config.dash_network)
        self.finishing = False
        self.setupUi()

    def setupUi(self):
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.setupUi(self, self)
        self.edtCollateralTx.setText(self.masternode.collateralTx)
        self.edtCollateralIndex.setText(self.masternode.collateralTxIndex)
        self.edtIP.setText(self.masternode.ip)
        self.edtPort.setText(self.masternode.port)
        self.edtPayoutAddress.setText(self.masternode.collateralAddress)
        self.edtOwnerKey.setText(self.masternode.privateKey)
        self.chbWholeMNReward.setChecked(True)
        self.generate_keys()
        self.determine_spork_15_active()
        self.update_ctrl_state()
        self.update_step_tab_ui()

    def generate_keys(self):
        """ Generate new operator and voting keys if were not provided before."""
        if not self.operator_pkey_old:
            self.operator_pkey_generated = generate_bls_privkey()
            self.edtOperatorKey.setText(self.operator_pkey_generated)

        if not self.voting_pkey_old:
            if self.deterministic_mns_spork_active:
                self.voting_pkey_generated = generate_wif_privkey(self.app_config.dash_network, compressed=True)
            else:
                self.voting_pkey_generated = self.edtOwnerKey.text()
            self.edtVotingKey.setText(self.voting_pkey_generated)

    def determine_spork_15_active(self):
        value = self.dashd_intf.get_spork_value(15)
        if value is not None:
            height = self.dashd_intf.getblockcount()
            if height >= value:
                self.deterministic_mns_spork_active = True
            else:
                self.deterministic_mns_spork_active = False

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnGenerateOwnerKey_clicked(self, active):
        k = generate_wif_privkey(self.app_config.dash_network, compressed=True)
        self.edtOwnerKey.setText(k)

    @pyqtSlot(bool)
    def on_btnGenerateOperatorKey_clicked(self, active):
        self.edtOperatorKey.setText(generate_bls_privkey())
        self.edtOperatorKey.repaint()  # qt 5.11.3 has issue with automatic repainting after setText on mac

    @pyqtSlot(bool)
    def on_btnGenerateVotingKey_clicked(self, active):
        k = generate_wif_privkey(self.app_config.dash_network, compressed=True)
        self.edtVotingKey.setText(k)

    def set_ctrl_message(self, control, message: str, style: str):
        if message:
            control.setText(f'{self.style}<span class="{style}">{message}</span>')
            # control.repaint()
        else:
            control.setVisible(False)

    def update_fields_info(self, show_invalid_data_msg: bool):
        """
        :param show_data_invalid_msg: if the argument is true and the data is invalid, an error message is shown
            below the control; the argument is set to True if before moving to the next step there are some errors
            found in the data provided by the user.
        """
        self.upd_collateral_tx_info(show_invalid_data_msg)
        self.upd_ip_info(show_invalid_data_msg)
        self.upd_payout_addr_info(show_invalid_data_msg)
        self.upd_oper_reward_info(show_invalid_data_msg)
        self.upd_owner_key_info(show_invalid_data_msg)
        self.upd_operator_key_info(show_invalid_data_msg)
        self.upd_voting_key_info(show_invalid_data_msg)

    def upd_collateral_tx_info(self, show_invalid_data_msg: bool):
        """
        :param show_data_invalid_msg: if the argument is true and the data is invalid, an error message is shown
            below the control; the argument is set to True if before moving to the next step there are some errors
            found in the data provided by the user.
        """
        msg = ''
        style = 'info'
        self.set_ctrl_message(self.lblCollateralTxMsg, msg, style)

    def upd_ip_info(self, show_invalid_data_msg: bool):
        """
        :param show_data_invalid_msg: if the argument is true and the data is invalid, an error message is shown
            below the control; the argument is set to True if before moving to the next step there are some errors
            found in the data provided by the user.
        """
        if self.edtIP.text():
            msg = 'You can leave the IP address and port fields empty if you want to delegate the operator ' \
                  'role to a hosting service and you don\'t know the IP address and port in advance ' \
                  '(<a href=\"https\">read more</a>).'
            style = 'info'
        else:
            msg = 'If don\'t set the IP address and port fields, the masternode operator will ' \
                  'have to issue a ProUpServTx transaction using Dash wallet (<a href=\"https\">read more</a>).'
            style = 'warning'
        self.set_ctrl_message(self.lblIPMsg, msg, style)

    def upd_payout_addr_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if self.edtPayoutAddress.text():
            msg = 'The owner\'s payout address can be set to any valid Dash address - it no longer ' \
                  'has to be the same as the collateral address.'
            style = 'info'
        else:
            if show_invalid_data_msg:
                msg = 'You have to set a valid payout address.'
                style = 'error'
        self.set_ctrl_message(self.lblPayoutMsg, msg, style)

    def upd_oper_reward_info(self, show_invalid_data_msg: bool):
        if self.chbWholeMNReward.isChecked():
            msg = 'Here you can specify how much of the masternode earnings will go to the ' \
                  'masternode operator.'
            style = 'info'
        else:
            msg = 'The masternode operator will have to specify his reward payee address in a ProUpServTx ' \
                  'transaction, otherwise the full reward will go to the masternode owner.'
            style = 'warning'
        self.set_ctrl_message(self.lblOperatorRewardMsg, msg, style)

    def upd_owner_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if self.edtOwnerKey.text():
            if self.masternode and self.masternode.privateKey.strip() == self.edtOwnerKey.text().strip():
                msg = 'This is your old masternode private key that can be used as the owner key. Despite this, now ' \
                      'is a good opportunity to generate a new one by clicking the button on the right. ' \
                      'If you are sure that the old key has not been disclosed, you can keep it unchanged.'
            else:
                msg = 'The owner key has the highest authority to control your masternode, so keep it safe and secret.'
            style = 'info'
        else:
            if show_invalid_data_msg:
                msg = 'The owner key value is required.'
                style = 'error'
        self.set_ctrl_message(self.lblOwnerMsg, msg, style)

    def upd_operator_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if self.edtOperatorKey.text():
            if not self.operator_pkey_old and self.edtOperatorKey.text().strip() == self.operator_pkey_generated:
                msg = 'This is a newly generated operator BLS private key. You can generate a new one (by clicking ' \
                      'the button on the right) or you can enter your own one.'
            else:
                msg = ''
            style = 'info'
        else:
            if show_invalid_data_msg:
                msg = 'The operator key value is required.'
                style = 'error'
        self.set_ctrl_message(self.lblOperatorMsg, msg, style)

    def upd_voting_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if self.edtVotingKey.text():
            msg = ''
            if not self.voting_pkey_old and self.edtVotingKey.text().strip() == self.voting_pkey_generated:
                style = 'info'
                if self.deterministic_mns_spork_active:
                    msg = 'This is a newly generated private key for voting. You can generate a new one ' \
                          '(by pressing the button on the right) or you can enter your own one. You can also use the ' \
                          'owner key, although it is not recommended.'
                else:
                    msg = 'Note: SPORK 15 isn\'t active yet, which means that the voting key must be equal to the' \
                          ' owner key.'
                    style = 'warning'
        else:
            if show_invalid_data_msg:
                msg = 'The voting key value is required.'
                style = 'error'
        self.set_ctrl_message(self.lblVotingMsg, msg, style)

    def get_dash_node_type(self):
        if self.rbDMTDashNodeType.isChecked():
            return NODE_TYPE_PUBLIC_RPC
        elif self.rbOwnDashNodeType.isChecked():
            return NODE_TYPE_OWN
        else:
            return None

    def upd_node_type_info(self):
        nt = self.get_dash_node_type()
        if nt is None:
            msg = 'Masternode registration involves the need to send a transaction (ProRegTx) from the Dash-Qt program, ' \
                  'which has sufficient funds for transaction fees.'
        elif nt == NODE_TYPE_PUBLIC_RPC:
            msg = 'The transaction (ProRegTx) will be sent via the RPC node prepared by the program\'s author. ' \
                  'If the transaction fails (eg due to running out of funds for transaction fees), you will have ' \
                  'to use your own Dash wallet.'
        elif nt == NODE_TYPE_OWN:
            msg = 'To complete the next steps you will need to prepare your own Dash wallet and ensure that it has ' \
                  'sufficient (though small) funds for transaction fees.'
        self.lblDashNodeTypeMessage.setText(msg)


    def update_ctrl_state(self):
        self.edtOperatorReward.setDisabled(self.chbWholeMNReward.isChecked())

    @pyqtSlot(str)
    def on_edtIP_textChanged(self, text):
        self.upd_ip_info(False)

    @pyqtSlot(str)
    def on_edtPayoutAddress_textChanged(self, text):
        self.upd_payout_addr_info(False)

    @pyqtSlot(bool)
    def on_chbWholeMNReward_toggled(self, checked):
        if checked:
            self.operator_reward_saved = self.edtOperatorReward.value()
            self.edtOperatorReward.setValue(0.0)
        else:
            if not self.operator_reward_saved is None:
                self.edtOperatorReward.setValue(self.operator_reward_saved)
        self.update_ctrl_state()
        self.upd_oper_reward_info(False)

    @pyqtSlot(str)
    def on_edtOwnerKey_textChanged(self, text):
        self.upd_owner_key_info(False)

    @pyqtSlot(str)
    def on_edtOperatorKey_textChanged(self, text):
        self.upd_operator_key_info(False)

    @pyqtSlot(str)
    def on_edtVotingKey_textChanged(self, text):
        self.upd_voting_key_info(False)

    def update_step_tab_ui(self):
        self.btnContinue.setEnabled(False)

        if self.current_step == STEP_MN_DATA:
            self.stackedWidget.setCurrentIndex(0)
            self.update_fields_info(False)
            self.btnContinue.setEnabled(True)

        elif self.current_step == STEP_DASHD_TYPE:
            self.stackedWidget.setCurrentIndex(1)
            self.upd_node_type_info()
            self.btnContinue.setEnabled(True)

        elif self.current_step == STEP_AUTOMATIC_RPC_NODE:
            self.stackedWidget.setCurrentIndex(2)
            self.upd_node_type_info()
            self.btnContinue.setEnabled(False)

        elif self.current_step == STEP_MANUAL_OWN_NODE:
            self.stackedWidget.setCurrentIndex(3)
            self.upd_node_type_info()
            self.btnContinue.setEnabled(False)

        else:
            raise Exception('Invalid step')

        self.btnBack.setEnabled(len(self.step_stack) > 0)
        self.btnContinue.repaint()
        self.btnBack.repaint()

    def verify_data(self):
        self.dmn_collateral_tx = self.edtCollateralTx.text()
        try:
            self.dmn_collateral_tx_index = int(self.edtCollateralIndex.text())
            if self.dmn_collateral_tx_index < 0:
                raise Exception('Invalid transaction index')
        except Exception:
            self.edtCollateralIndex.setFocus()
            raise Exception('Invalid collateral transaction index: should be integer greater or equal 0.')

        try:
            self.dmn_ip = self.edtIP.text()
            ipaddress.ip_address(self.dmn_ip)
        except Exception as e:
            self.edtIP.setFocus()
            raise Exception('Invalid masternode IP address: %s.' % str(e))

        try:
            self.dmn_tcp_port = int(self.edtPort.text())
        except Exception:
            self.edtPort.setFocus()
            raise Exception('Invalid TCP port: should be integer.')

        self.dmn_owner_payout_addr = self.edtPayoutAddress.text()
        if not validate_address(self.dmn_owner_payout_addr, self.app_config.dash_network):
            self.edtPayoutAddress.setFocus()
            raise Exception('Invalid owner payout address.')

        if self.chbWholeMNReward.isChecked():
            self.dmn_operator_reward = 0
        else:
            self.dmn_operator_reward = self.edtOperatorReward.value()
            if self.dmn_operator_reward > 100 or self.dmn_operator_reward < 0:
                self.edtOperatorReward.setFocus()
                raise Exception('Invalid operator reward value: should be a value between 0 and 100.')

        self.dmn_owner_privkey = self.edtOwnerKey.text()
        if not validate_wif_privkey(self.dmn_owner_privkey, self.app_config.dash_network):
            self.edtOwnerKey.setFocus()
            raise Exception('Invalid owner private key.')
        else:
            self.dmn_owner_address = wif_privkey_to_address(self.dmn_owner_privkey, self.app_config.dash_network)

        try:
            self.dmn_operator_privkey = self.edtOperatorKey.text()
            self.dmn_operator_pubkey = bls_privkey_to_pubkey(self.dmn_operator_privkey)
        except Exception as e:
            self.edtOperatorKey.setFocus()
            raise Exception('Invalid operator private key: ' + str(e))

        self.dmn_voting_privkey = self.edtVotingKey.text()
        if not validate_wif_privkey(self.dmn_voting_privkey, self.app_config.dash_network):
            self.edtVotingKey.setFocus()
            raise Exception('Invalid voting private key.')
        else:
            self.dmn_voting_address = wif_privkey_to_address(self.dmn_voting_privkey, self.app_config.dash_network)

        self.btnContinue.setEnabled(False)
        self.btnContinue.repaint()
        ret = WndUtils.run_thread_dialog(self.get_collateral_tx_address_thread, (), True)
        self.btnContinue.setEnabled(True)
        self.btnContinue.repaint()
        return ret


    def get_collateral_tx_address_thread(self, ctrl: CtrlObject):
        break_scanning = False
        ctrl.dlg_config_fun(dlg_title="Validating collateral transaction.", show_progress_bar=False)
        ctrl.display_msg_fun('Verifyinig collateral transaction...')

        def check_break_scanning():
            nonlocal break_scanning
            if self.finishing or break_scanning:
                # stop the scanning process if the dialog finishes or the address/bip32path has been found
                raise BreakFetchTransactionsException()

        def fetch_txes_feeback(org_message: str, msg: str):
            ctrl.display_msg_fun(org_message + '<br><br>' + msg)

        def on_msg_link_activated(link: str):
            nonlocal break_scanning
            if link == 'break':
                break_scanning = True

        try:
            tx = self.dashd_intf.getrawtransaction(self.dmn_collateral_tx, 1)
        except Exception as e:
            raise Exception('Cannot get the collateral transaction due to the following errror: ' + str(e))

        vouts = tx.get('vout')
        if vouts:
            if self.dmn_collateral_tx_index < len(vouts):
                vout = vouts[self.dmn_collateral_tx_index]
                spk = vout.get('scriptPubKey')
                if not spk:
                    raise Exception(f'The collateral transaction ({self.dmn_collateral_tx}) output '
                                    f'({self.dmn_collateral_tx_index}) doesn\'t have value in the scriptPubKey '
                                    f'field.')
                ads = spk.get('addresses')
                if not ads or len(ads) < 0:
                    raise Exception('The collateral transaction output doesn\'t have the Dash address assigned.')
                self.dmn_collateral_tx_address = ads[0]
            else:
                raise Exception(f'Transaction {self.dmn_collateral_tx} doesn\'t have output with index: '
                                f'{self.dmn_collateral_tx_index}')
        else:
            raise Exception('Invalid collateral transaction')

        ctrl.display_msg_fun('Verifying the collateral transaction address on your hardware wallet.')
        if not self.main_dlg.connect_hardware_wallet():
            return False

        if self.dmn_collateral_tx_address_path:
            addr = hw_intf.get_address(self.main_dlg.hw_session, self.dmn_collateral_tx_address_path)
            msg = ''
            if addr != self.dmn_collateral_tx_address:
                log.warning(
                    f'The address returned by the hardware wallet ({addr}) for the BIP32 path '
                    f'{self.dmn_collateral_tx_address_path} differs from the address stored the mn configuration '
                    f'(self.dmn_collateral_tx_address). Need to scan wallet for a correct BIP32 path.')

                msg = '<span style="color:red">The BIP32 path of the collateral address from your mn config is incorret.<br></span>' \
                      f'Trying to find the BIP32 path of the address {self.dmn_collateral_tx_address} in your wallet.' \
                      f'<br>This can take a while (<a href="break">break</a>)...'
                self.dmn_collateral_tx_address_path = ''
        else:
            msg = 'Looking for a BIP32 path of the Dash address related to the masternode collateral.<br>' \
                  'This can take a while (<a href="break">break</a>)....'

        if not self.dmn_collateral_tx_address_path and not self.finishing:
            lbl = ctrl.get_msg_label_control()
            if lbl:
                def set():
                    lbl.setOpenExternalLinks(False)
                    lbl.setTextInteractionFlags(lbl.textInteractionFlags() & ~Qt.TextSelectableByMouse)
                    lbl.linkActivated.connect(on_msg_link_activated)
                    lbl.repaint()
                WndUtils.call_in_main_thread(set)

            ctrl.display_msg_fun(msg)


            # fetch the transactions that involved the addresses stored in the wallet - during this
            # all the used addresses are revealed
            addr = self.bip44_wallet.scan_wallet_for_address(self.dmn_collateral_tx_address, check_break_scanning,
                                                             partial(fetch_txes_feeback, msg))
            if not addr:
                if not break_scanning:
                    WndUtils.errorMsg(f'Couldn\'t find a BIP32 path of the collateral address ({self.dmn_collateral_tx_address}).')
                return False
            else:
                self.dmn_collateral_tx_address_path = addr.bip32_path

        return True

    def next_step(self):
        cs = None
        if self.current_step == STEP_MN_DATA:
            if self.verify_data():
                cs = STEP_DASHD_TYPE
            else:
                return
        elif self.current_step == STEP_DASHD_TYPE:
            if self.get_dash_node_type() == NODE_TYPE_PUBLIC_RPC:
                cs = STEP_AUTOMATIC_RPC_NODE
            elif self.get_dash_node_type() == NODE_TYPE_OWN:
                cs = STEP_MANUAL_OWN_NODE
            else:
                raise Exception('You have to choose one of the two options.')
        else:
            raise Exception('Invalid step')

        self.step_stack.append(self.current_step)
        self.current_step = cs
        self.update_step_tab_ui()

        if self.current_step == STEP_AUTOMATIC_RPC_NODE:
            self.start_automatic_process()

    def previous_step(self):
        if self.step_stack:
            self.current_step = self.step_stack.pop()
        else:
            raise Exception('Invalid step')
        self.update_step_tab_ui()

    @pyqtSlot(bool)
    def on_btnContinue_clicked(self, active):
        self.next_step()

    @pyqtSlot(bool)
    def on_btnBack_clicked(self, active):
        self.previous_step()

    @pyqtSlot(bool)
    def on_rbDMTDashNodeType_toggled(self, active):
        self.upd_node_type_info()

    def start_automatic_process(self):
        self.btnContinue.setEnabled(False)
        self.btnContinue.repaint()
        self.lblProtxTransaction1.hide()
        self.lblProtxTransaction2.hide()
        self.lblProtxTransaction3.hide()
        self.lblProtxTransaction4.hide()
        self.btnBack.setEnabled(False)
        self.btnBack.repaint()
        self.btnCancel.setEnabled(False)
        self.btnCancel.repaint()
        self.run_thread(self, self.proregtx_prepare_thread, (), on_thread_finish=self.finished_automatic_process)

    def finished_automatic_process(self):
        self.btnCancel.setEnabled(True)
        self.btnCancel.repaint()
        self.update_step_tab_ui()

    def proregtx_prepare_thread(self, ctrl):
        log.debug('Starting proregtx_prepare_thread')
        def set_text(widget, text: str):
            def call(widget, text):
                widget.setText(text)
                widget.repaint()
                widget.setVisible(True)
            WndUtils.call_in_main_thread(call, widget, text)

        try:
            # preparing protx message
            set_text(self.lblProtxTransaction1, '<b>1. Calling the <code>protx register_prepare</code> method on a remote node...</b>')
            call_ret = self.dashd_intf.protx(
                'register_prepare', self.dmn_collateral_tx, self.dmn_collateral_tx_index,
                self.dmn_ip + ':' + str(self.dmn_tcp_port), self.dmn_owner_privkey, self.dmn_operator_pubkey,
                self.dmn_voting_address, str(round(self.dmn_operator_reward, 2)), self.dmn_owner_payout_addr )

            call_ret_str = json.dumps(call_ret, default=EncodeDecimal)
            msg_to_sign = call_ret.get('signMessage', '')
            protx_tx = call_ret.get('tx')
            log.debug('register_prepare returned: ' + call_ret_str)
            set_text(self.lblProtxTransaction1, '<b>1. Calling the <code>protx register_prepare</code> method on a '
                                                'remote node.</b> <span style="color:green">Success.</span>')

            set_text(self.lblProtxTransaction2, '<b>Message to be signed:</b><br><code>' + msg_to_sign + '</code>')
            try:
                prep_tx_decoded = self.dashd_intf.decoderawtransaction(protx_tx)
            except Exception as e:
                log.exception('Couldn\'t decode raw transaction')

            # signing message:
            set_text(self.lblProtxTransaction3, '<b>2. Signing message with hardware wallet...</b>')
            payload_sig_str = ''
            try:
                sig = WndUtils.call_in_main_thread(
                    hw_intf.hw_sign_message, self.main_dlg.hw_session, self.dmn_collateral_tx_address_path,
                    msg_to_sign, 'Click the confirmation button on your hardware wallet to sign a protx payload '
                                 'message.')

                if sig.address != self.dmn_collateral_tx_address:
                    log.error(f'Protx payload signature address mismatch. Is: {sig.address}, should be: '
                              f'{self.dmn_collateral_tx_address}.')
                    raise Exception(f'Protx payload signature address mismatch. Is: {sig.address}, should be: '
                                    f'{self.dmn_collateral_tx_address}.')
                else:
                    sig_bin = base64.b64encode(sig.signature)
                    payload_sig_str = sig_bin.decode('ascii')
                    set_text(self.lblProtxTransaction3, '<b>2. Signing message with hardware wallet.</b> '
                                                        '<span style="color:green">Success.</span>')
            except HardwareWalletCancelException as e:
                set_text(self.lblProtxTransaction3,
                         '<b>2. Signing message with hardware wallet.</b> <span style="color:red">Cancelled.</span>')
                return
            except Exception as e:
                log.exception('Signature failed.')
                set_text(self.lblProtxTransaction3,
                         '<b>2. Signing message with hardware wallet.</b> <span style="color:red">Failed.</span>')
                return

            # submitting signed transaction
            set_text(self.lblProtxTransaction4, '<b>3. Submitting the signed protx transaction to the remote node...</b>')
            try:
                call_ret = self.dashd_intf.protx('register_submit', protx_tx, payload_sig_str)
                log.debug('protx register_submit returned: ' + str(call_ret))
            except Exception as e:
                log.exception('protx register_submit failed')
                set_text(self.lblProtxTransaction4,
                         '<b>3. Submitting the signed protx transaction to the remote node.</b> '
                         f'<span style="color:red">Failed with error: {str(e)}</span>')

        except Exception as e:
            log.exception('Exception occurred')
            WndUtils.errorMsg(str(e))
