#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-11
import base64
import json
import logging
import time
from collections import namedtuple
from enum import Enum
from functools import partial
from typing import List, Union, Callable
import ipaddress

from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import pyqtSlot, Qt, QTimerEvent, QTimer
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QDialog, QApplication, QToolButton, QAction, QWidget
from bitcoinrpc.authproxy import EncodeDecimal, JSONRPCException

import app_cache
import app_defs
import hw_intf
from app_config import MasternodeConfig, AppConfig, InputKeyType
from app_defs import FEE_DUFF_PER_BYTE
from bip44_wallet import Bip44Wallet, BreakFetchTransactionsException, find_wallet_addresses
from common import CancelException
from dash_utils import generate_bls_privkey, generate_wif_privkey, validate_address, wif_privkey_to_address, \
    validate_wif_privkey, bls_privkey_to_pubkey
from dashd_intf import DashdInterface
from thread_fun_dlg import CtrlObject
from ui import ui_reg_masternode_dlg
from wallet_common import Bip44AccountType, Bip44AddressType
from wnd_utils import WndUtils


STEP_MN_DATA = 1
STEP_DASHD_TYPE = 2
STEP_AUTOMATIC_RPC_NODE = 3
STEP_MANUAL_OWN_NODE = 4
STEP_SUMMARY = 5

NODE_TYPE_PUBLIC_RPC = 1
NODE_TYPE_OWN = 2


CACHE_ITEM_SHOW_FIELD_HINTS = 'RegMasternodeDlg_ShowFieldHints'


log = logging.getLogger('dmt.reg_masternode')


class RegMasternodeDlg(QDialog, ui_reg_masternode_dlg.Ui_RegMasternodeDlg, WndUtils):
    def __init__(self, main_dlg, config: AppConfig, dashd_intf: DashdInterface, masternode: MasternodeConfig,
                 on_proregtx_success_callback: Callable):
        QDialog.__init__(self, main_dlg)
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = config
        self.dashd_intf:DashdInterface = dashd_intf
        self.on_proregtx_success_callback = on_proregtx_success_callback
        self.style = '<style>.info{color:darkblue} .warning{color:#ff6600} .error{background-color:red;color:white}</style>'
        self.operator_reward_saved = None
        self.owner_pkey_generated: str = None
        self.operator_pkey_generated: str = None
        self.voting_pkey_generated: str = None
        self.current_step = STEP_MN_DATA
        self.step_stack: List[int] = []
        self.proregtx_prepare_thread_ref = None
        self.deterministic_mns_spork_active = True
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
        self.dmn_owner_key_type = InputKeyType.PRIVATE
        self.dmn_operator_key_type = InputKeyType.PRIVATE
        self.dmn_voting_key_type = InputKeyType.PRIVATE

        self.collateral_validation_err_msg = ''
        self.ip_port_validation_err_msg = ''
        self.payout_address_validation_err_msg = ''
        self.operator_reward_validation_err_msg = ''
        self.owner_key_validation_err_msg = ''
        self.operator_key_validation_err_msg = ''
        self.voting_key_validation_err_msg = ''

        self.dmn_reg_tx_hash = ''
        self.manual_signed_message = False
        self.last_manual_prepare_string: str = None
        self.wait_for_confirmation_timer_id = None
        self.show_field_hinds = True
        self.summary_info = []
        if self.masternode:
            self.dmn_collateral_tx_address_path = self.masternode.collateralBip32Path
        self.bip44_wallet = Bip44Wallet(self.app_config.hw_coin_name, self.main_dlg.hw_session,
                                        self.app_config.db_intf, self.dashd_intf, self.app_config.dash_network)
        self.finishing = False
        self.setupUi()

    def setupUi(self):
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.setupUi(self, self)
        self.closeEvent = self.closeEvent
        self.restore_cache_settings()
        self.edtCollateralTx.setText(self.masternode.collateralTx)
        if self.masternode.collateralTx:
            sz = self.edtCollateralTx.fontMetrics().size(0, self.masternode.collateralTx + '000')
            self.edtCollateralTx.setMinimumWidth(sz.width())
        self.edtCollateralIndex.setText(self.masternode.collateralTxIndex)
        self.edtIP.setText(self.masternode.ip)
        self.edtPort.setText(self.masternode.port)
        self.edtPayoutAddress.setText(self.masternode.collateralAddress)
        self.chbWholeMNReward.setChecked(True)
        self.lblProtxSummary2.linkActivated.connect(self.save_summary_info)
        self.lblCollateralTxMsg.sizePolicy().setHeightForWidth(True)
        self.prepare_keys()
        self.btnClose.hide()
        self.setIcon(self.btnManualFundingAddressPaste, 'content-paste@16px.png')
        self.setIcon(self.btnManualProtxPrepareCopy, 'content-copy@16px.png')
        self.setIcon(self.btnManualProtxPrepareResultPaste, 'content-paste@16px.png')
        self.setIcon(self.btnManualProtxSubmitCopy, 'content-copy@16px.png')
        self.setIcon(self.btnManualTxHashPaste, 'content-paste@16px.png')
        self.setIcon(self.btnSummaryDMNOperatorKeyCopy, 'content-copy@16px.png')
        self.edtSummaryDMNOperatorKey.setStyleSheet("QLineEdit{background-color: white} "
                                                    "QLineEdit:read-only{background-color: white}")
        doc_url = app_defs.get_doc_url('deterministic-mn-migration.md')
        if doc_url:
            self.lblDocumentation.setText(f'<a href="{doc_url}">Documentation</a>')
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.update_ctrl_state()
        self.update_step_tab_ui()
        self.update_show_hints_label()
        self.minimize_dialog_height()

    def closeEvent(self, event):
        self.finishing = True
        if self.wait_for_confirmation_timer_id is not None:
            self.killTimer(self.wait_for_confirmation_timer_id)
        self.save_cache_settings()

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)
        self.show_field_hinds = app_cache.get_value(CACHE_ITEM_SHOW_FIELD_HINTS, True, bool)

    def save_cache_settings(self):
        app_cache.save_window_size(self)
        app_cache.set_value(CACHE_ITEM_SHOW_FIELD_HINTS, self.show_field_hinds)

    def minimize_dialog_height(self):
        def set():
            self.adjustSize()

        self.tm_resize_dlg = QTimer(self)
        self.tm_resize_dlg.setSingleShot(True)
        self.tm_resize_dlg.singleShot(100, set)

    def update_dynamic_labels(self):

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
            return f'<table style="float:right;{style_to_color(style)}"><tr><td><b>{lbl}</b></td><td>{change_mode}</td></tr></table>'

        if self.masternode:

            if self.dmn_owner_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter the owner private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the owner Dash address')
                style = 'hl1'
            self.lblOwnerKey.setText(get_label_text('Owner', key_type, tooltip_anchor, style))
            self.edtOwnerKey.setPlaceholderText(placeholder_text)

            if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'pubkey', 'Enter the operator private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('pubkey', 'privkey', 'Enter the operator public key')
                style = 'hl1'
            self.lblOperatorKey.setText(get_label_text('Operator', key_type, tooltip_anchor, style))
            self.edtOperatorKey.setPlaceholderText(placeholder_text)

            if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey','address', 'Enter the voting private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the voting Dash address')
                style = 'hl1'
            self.lblVotingKey.setText(get_label_text('Voting', key_type, tooltip_anchor, style))
            self.edtVotingKey.setPlaceholderText(placeholder_text)

    @pyqtSlot(str)
    def on_lblOwnerKey_linkActivated(self, link):
        if self.dmn_owner_key_type == InputKeyType.PRIVATE:
            self.dmn_owner_key_type = InputKeyType.PUBLIC
            self.dmn_owner_privkey = self.edtOwnerKey.text()
            self.edtOwnerKey.setText(self.dmn_owner_address)
        else:
            self.dmn_owner_key_type = InputKeyType.PRIVATE
            self.dmn_owner_address = self.edtOwnerKey.text()
            self.edtOwnerKey.setText(self.dmn_owner_privkey)
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_owner_key_info(False)

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        if self.dmn_operator_key_type == InputKeyType.PRIVATE:
            self.dmn_operator_key_type = InputKeyType.PUBLIC
            self.dmn_operator_privkey = self.edtOperatorKey.text()
            self.edtOperatorKey.setText(self.dmn_operator_pubkey)
        else:
            self.dmn_operator_key_type = InputKeyType.PRIVATE
            self.dmn_operator_pubkey = self.edtOperatorKey.text()
            self.edtOperatorKey.setText(self.dmn_operator_privkey)
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_operator_key_info(False)

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        if self.dmn_voting_key_type == InputKeyType.PRIVATE:
            self.dmn_voting_key_type = InputKeyType.PUBLIC
            self.dmn_voting_privkey = self.edtVotingKey.text()
            self.edtVotingKey.setText(self.dmn_voting_address)
        else:
            self.dmn_voting_key_type = InputKeyType.PRIVATE
            self.dmn_voting_address = self.edtVotingKey.text()
            self.edtVotingKey.setText(self.dmn_voting_privkey)
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_voting_key_info(False)

    @pyqtSlot(str)
    def on_lblOwnerKey_linkHovered(self, link):
        if link == 'address':
            tt = 'Change input type to Dash address'
        else:
            tt = 'Change input type to private key'
        self.lblOwnerKey.setToolTip(tt)

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

    def prepare_keys(self):
        gen_owner = False
        gen_operator = False
        gen_voting = False

        # if any of the owner/operator/voting key used in the configuration is the same as the corresponding
        # key shown in the blockchain, replace that key by a new one
        found_protx = False
        protx_state = {}
        try:
            for protx in self.dashd_intf.protx('list', 'registered', True):
                protx_state = protx.get('state')
                if (protx_state and protx_state.get('service') == self.masternode.ip + ':' + self.masternode.port) or \
                        (protx.get('collateralHash') == self.masternode.collateralTx and
                         str(protx.get('collateralIndex')) == str(self.masternode.collateralTxIndex)):
                    found_protx = True
                    break
        except Exception as e:
            pass

        if found_protx:
            if self.masternode.get_dmn_owner_public_address(self.app_config.dash_network) == \
                    protx_state.get('ownerAddress'):
                gen_owner = True

            if self.masternode.get_dmn_operator_pubkey() == protx_state.get('pubKeyOperator'):
                gen_operator = True

            if self.masternode.get_dmn_voting_public_address(self.app_config.dash_network) == \
                    protx_state.get('votingAddress'):
                gen_voting = True

        if (self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE and
             not self.masternode.dmn_owner_private_key) or \
                (self.masternode.dmn_owner_key_type == InputKeyType.PUBLIC and
                 not self.masternode.dmn_owner_address):
            gen_owner = True

        if (self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE and
            not self.masternode.dmn_operator_private_key) or \
                (self.masternode.dmn_operator_key_type == InputKeyType.PUBLIC and
                not self.masternode.dmn_operator_public_key):
            gen_operator = True

        if (self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE and
            not self.masternode.dmn_voting_private_key) or \
                (self.masternode.dmn_voting_key_type == InputKeyType.PUBLIC and
                 not self.masternode.dmn_voting_address):
            gen_voting = True

        if gen_owner:
            self.owner_pkey_generated =  generate_wif_privkey(self.app_config.dash_network, compressed=True)
            self.edtOwnerKey.setText(self.owner_pkey_generated)
        else:
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                self.edtOwnerKey.setText(self.masternode.dmn_owner_private_key)
            else:
                self.edtOwnerKey.setText(self.masternode.dmn_owner_address)
            self.dmn_owner_key_type = self.masternode.dmn_owner_key_type

        if gen_operator:
            try:
                self.operator_pkey_generated = generate_bls_privkey()
                self.edtOperatorKey.setText(self.operator_pkey_generated)
            except Exception as e:
                self.errorMsg(str(e))
        else:
            if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                self.edtOperatorKey.setText(self.masternode.dmn_operator_private_key)
            else:
                self.edtOperatorKey.setText(self.masternode.dmn_operator_public_key)
            self.dmn_operator_key_type = self.masternode.dmn_operator_key_type

        if self.deterministic_mns_spork_active:
            if gen_voting:
                self.voting_pkey_generated = generate_wif_privkey(self.app_config.dash_network, compressed=True)
                self.edtVotingKey.setText(self.voting_pkey_generated)
            else:
                if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                    self.edtVotingKey.setText(self.masternode.dmn_voting_private_key)
                else:
                    self.edtVotingKey.setText(self.masternode.dmn_voting_address)

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnGenerateOwnerKey_clicked(self, active):
        k = generate_wif_privkey(self.app_config.dash_network, compressed=True)
        self.edtOwnerKey.setText(k)
        self.edtOwnerKey.repaint()

    @pyqtSlot(bool)
    def on_btnGenerateOperatorKey_clicked(self, active):
        self.edtOperatorKey.setText(generate_bls_privkey())
        self.edtOperatorKey.repaint()  # qt 5.11.3 has issue with automatic repainting after setText on mac

    @pyqtSlot(bool)
    def on_btnGenerateVotingKey_clicked(self, active):
        k = generate_wif_privkey(self.app_config.dash_network, compressed=True)
        self.edtVotingKey.setText(k)
        self.edtVotingKey.repaint()

    def set_ctrl_message(self, control, message: str, style: str):
        if message:
            control.setText(f'{self.style}<span class="{style}">{message}</span>')
            control.setVisible(True)
            # control.repaint()
        else:
            control.setVisible(False)

    def update_ctrls_visibility(self):
        if not self.deterministic_mns_spork_active:
            # hide controls related to the voting key - if spork 15 is not active, voting key has to be the same
            # as the owner key
            self.lblVotingMsg.hide()
            self.lblVotingKey.hide()
            self.edtVotingKey.hide()
            self.btnGenerateVotingKey.hide()
        else:
            self.btnGenerateVotingKey.setVisible(self.dmn_voting_key_type == InputKeyType.PRIVATE)

        self.btnGenerateOwnerKey.setVisible(self.dmn_owner_key_type == InputKeyType.PRIVATE)
        self.btnGenerateOperatorKey.setVisible(self.dmn_operator_key_type == InputKeyType.PRIVATE)

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
        if show_invalid_data_msg and self.collateral_validation_err_msg:
            msg = self.collateral_validation_err_msg
            style = 'error'

        self.set_ctrl_message(self.lblCollateralTxMsg, msg, style)

    def upd_ip_info(self, show_invalid_data_msg: bool):
        """
        :param show_data_invalid_msg: if the argument is true and the data is invalid, an error message is shown
            below the control; the argument is set to True if before moving to the next step there are some errors
            found in the data provided by the user.
        """
        msg = ''
        style = ''
        if show_invalid_data_msg and self.ip_port_validation_err_msg:
            msg = self.ip_port_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                if self.edtIP.text().strip():
                    msg = 'You can leave the IP address and port fields empty if you want to delegate the operator ' \
                          'role to an external entity and you don\'t know their values in advance.'
                    style = 'info'
                else:
                    msg = 'If don\'t set the IP address and port fields, the masternode operator will ' \
                          'have to issue a ProUpServTx transaction using Dash wallet.'
                    style = 'warning'
        self.set_ctrl_message(self.lblIPMsg, msg, style)

    def upd_payout_addr_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if show_invalid_data_msg and self.payout_address_validation_err_msg:
            msg = self.payout_address_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                msg = 'The owner\'s payout address can be set to any valid Dash address - it no longer ' \
                      'has to be the same as the collateral address.'
                style = 'info'
        self.set_ctrl_message(self.lblPayoutMsg, msg, style)

    def upd_oper_reward_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if show_invalid_data_msg and self.operator_reward_validation_err_msg:
            msg = self.operator_reward_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
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
        if show_invalid_data_msg and self.owner_key_validation_err_msg:
            msg = self.owner_key_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                if self.dmn_owner_key_type == InputKeyType.PRIVATE:
                    if self.edtOwnerKey.text().strip() == self.owner_pkey_generated:
                        msg = 'This is an automatically generated owner private key. You can enter your own or ' \
                              'generate a new one by pressing the button on the right.'
                    elif not self.edtOwnerKey.text().strip():
                        msg = 'Enter the owner private key or generate a new one by clicking the button on the right.'
                    style = 'info'
                else:
                    msg = 'You can use Dash address if the related private key is stored elsewhere, eg in ' \
                          'the Dash Core wallet.<br><span class="warning">Note, that if you provide an address ' \
                          'instead of a private key, you will not be able to publish ProRegTx ' \
                          'transaction through public RPC nodes in the next steps.</span>'
                    style = 'info'

        self.set_ctrl_message(self.lblOwnerMsg, msg, style)

    def upd_operator_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if show_invalid_data_msg and self.operator_key_validation_err_msg:
            msg = self.operator_key_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                    if self.edtOperatorKey.text().strip() == self.operator_pkey_generated:
                        msg = 'This is an automatically generated operator BLS private key. You can enter your ' \
                              'own or generate a new one by pressing the button on the right.'
                    elif not self.edtOperatorKey.text().strip():
                        msg = 'Enter the operator private key or generate a new one by clicking the button on ' \
                              'the right.'
                    style = 'info'
                else:
                    msg = 'You can use public key if your masternode is managed by a separate entity (operator) ' \
                          'that controls the related private key or if you prefer to keep the private key outside ' \
                          'the program. If necessary, you can revoke this key by sending a new ProRegTx ' \
                          'transaction with a new operator key.'
                    style = 'info'

        self.set_ctrl_message(self.lblOperatorMsg, msg, style)

    def upd_voting_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if self.deterministic_mns_spork_active:
            if show_invalid_data_msg and self.voting_key_validation_err_msg:
                msg = self.voting_key_validation_err_msg
                style = 'error'
            else:
                if self.show_field_hinds:
                    if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                        if self.edtVotingKey.text().strip() == self.voting_pkey_generated:
                            msg = 'This is an automatically generated private key for voting. You can enter your own or ' \
                                  'generate a new one by pressing the button on the right.'
                        elif not self.edtVotingKey.text().strip():
                            msg = 'Enter the private key for voting or generate a new one by clicking the button on ' \
                                  'the right.'
                        style = 'info'
                    else:
                        msg = 'You can use Dash address if the related private key is stored elsewhere, eg in ' \
                              'the Dash Core wallet.<br><span class="warning">Note, that providing an address instead of ' \
                              'a private key will prevent you from voting on proposals in this program.</span>'
                        style = 'info'

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
        msg = ''
        if nt is None:
            msg = 'DIP-3 masternode registration involves sending a special transaction via the v0.13 Dash node ' \
                  '(eg Dash-Qt). <b>Note, that this requires incurring a certain transaction fee, as with any ' \
                  'other ("normal") transaction.</b>'
        elif nt == NODE_TYPE_PUBLIC_RPC:
            msg = 'The ProRegTx transaction will be processed via the remote RPC node stored in the app configuration.' \
                  '<br><br>' \
                  '<b>Note 1:</b> this operation will involve signing transaction data with your <span style="color:red">owner key on the remote node</span>, ' \
                  'so use this method only if you trust the operator of that node (nodes <i>alice(luna, suzy).dash-masternode-tool.org</i> are maintained by the author of this application).<br><br>' \
                  '<b>Note 2:</b> if the operation fails (e.g. due to a lack of funds), choose the manual method ' \
                  'using your own Dash wallet.'

        elif nt == NODE_TYPE_OWN:
            msg = 'A Dash Core wallet (v0.13) with sufficient funds to cover transaction fees is required to ' \
                  'complete the next steps.'
        self.lblDashNodeTypeMessage.setText(msg)

    def update_ctrl_state(self):
        self.edtOperatorReward.setDisabled(self.chbWholeMNReward.isChecked())

    @pyqtSlot(str)
    def on_edtCollateralTx_textChanged(self, text):
        self.upd_collateral_tx_info(False)

    @pyqtSlot(str)
    def on_edtCollateralIndex_textChanged(self, text):
        self.upd_collateral_tx_info(False)

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

    @pyqtSlot(str)
    def save_summary_info(self, link: str):
        file_name = WndUtils.save_file_query(self.main_dlg, self.app_config,
                                             'Enter the file name',
                                             filter="TXT files (*.txt);;All Files (*)")
        if file_name:
            with open(file_name, 'wt') as fptr:
                for l in self.summary_info:
                    lbl, val = l.split('\t')
                    fptr.write(f'{lbl}:\t{val}\n')

    def update_step_tab_ui(self):
        def show_hide_tabs(tab_idx_to_show: int):
            self.edtManualProtxPrepare.setVisible(tab_idx_to_show == 3)
            self.edtManualProtxPrepareResult.setVisible(tab_idx_to_show == 3)
            self.edtManualProtxSubmit.setVisible(tab_idx_to_show == 3)
            pass

        self.btnContinue.setEnabled(False)

        if self.current_step == STEP_MN_DATA:
            self.stackedWidget.setCurrentIndex(0)
            self.update_fields_info(False)
            self.btnContinue.show()
            self.btnContinue.setEnabled(True)
            self.btnCancel.setEnabled(True)

        elif self.current_step == STEP_DASHD_TYPE:
            self.stackedWidget.setCurrentIndex(1)
            self.upd_node_type_info()
            self.btnContinue.setEnabled(True)
            self.btnContinue.show()
            self.btnCancel.setEnabled(True)

        elif self.current_step == STEP_AUTOMATIC_RPC_NODE:
            self.stackedWidget.setCurrentIndex(2)
            self.upd_node_type_info()

        elif self.current_step == STEP_MANUAL_OWN_NODE:
            self.stackedWidget.setCurrentIndex(3)
            self.upd_node_type_info()
            self.btnContinue.setEnabled(True)

        elif self.current_step == STEP_SUMMARY:
            self.stackedWidget.setCurrentIndex(4)

            if self.dmn_owner_key_type == InputKeyType.PRIVATE:
                owner_privkey = self.dmn_owner_privkey
            else:
                owner_privkey = '&lt;not available&gt;'

            if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                operator_privkey = self.dmn_operator_privkey
            else:
                operator_privkey = '&lt;not available&gt;'

            if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                voting_privkey = self.dmn_voting_privkey
            else:
                voting_privkey = '&lt;not available&gt;'

            self.summary_info = \
                [f'Network address\t{self.dmn_ip}:{self.dmn_tcp_port}',
                 f'Payout address\t{self.dmn_owner_payout_addr}',
                 f'Owner private key\t{owner_privkey}',
                 f'Owner public address\t{self.dmn_owner_address}',
                 f'Operator private key\t{operator_privkey}',
                 f'Operator public key\t{self.dmn_operator_pubkey}',
                 f'Voting private key\t{voting_privkey}',
                 f'Voting public address\t{self.dmn_voting_address}',
                 f'Protx hash\t{self.dmn_reg_tx_hash}']

            text = '<table>'
            for l in self.summary_info:
                lbl, val = l.split('\t')
                text += f'<tr><td style="white-space: nowrap"><b>{lbl}:</b> </td><td>{val}</td></tr>'
            text += '</table>'
            self.edtProtxSummary.setText(text)
            self.edtProtxSummary.show()
            self.lblProtxSummary2.show()

            if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                operator_message = '<b><span style="color:red">One more thing... <span></b>copy the following ' \
                                   'line to the <code>dash.conf</code> file on your masternode server ' \
                                   '(and restart <i>dashd</i>) or pass it to the masternode operator:'
            else:
                operator_message = '<b><span style="color:red">One more thing... <span></b>copy the following ' \
                                   'line to the <code>dash.conf</code> file on your masternode server, replacing ' \
                                   '"&lt;your-operator-bls-private-key&gt;" with the appropriate value or ask the operator ' \
                                   'for it:'
            self.lblProtxSummary3.setText(operator_message)

            if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                operator_privkey = self.dmn_operator_privkey
            else:
                operator_privkey = '<your-operator-bls-private-key>'

            self.edtSummaryDMNOperatorKey.setText(f'masternodeblsprivkey={operator_privkey}')
            self.btnCancel.hide()
            self.btnBack.hide()
            self.btnContinue.hide()
            self.btnClose.show()
            self.btnClose.setEnabled(True)
            self.btnClose.repaint()
        else:
            raise Exception('Invalid step')

        show_hide_tabs(self.stackedWidget.currentIndex())
        self.lblFieldHints.setVisible(self.stackedWidget.currentIndex() == 0)
        self.btnBack.setEnabled(len(self.step_stack) > 0)
        self.btnContinue.repaint()
        self.btnCancel.repaint()
        self.btnBack.repaint()

    def validate_data(self):
        self.dmn_collateral_tx = self.edtCollateralTx.text().strip()
        self.collateral_validation_err_msg = ''
        error_count = 0
        try:
            if not self.dmn_collateral_tx:
                self.collateral_validation_err_msg = 'Collteral transaction ID is required.'
                self.edtCollateralTx.setFocus()
            else:
                self.dmn_collateral_tx_index = int(self.edtCollateralIndex.text())
                if self.dmn_collateral_tx_index < 0:
                     self.collateral_validation_err_msg = 'Invalid collateral transaction index.'
        except Exception:
            self.edtCollateralIndex.setFocus()
            self.collateral_validation_err_msg = 'Invalid collateral transaction index: should be an integer ' \
                                                 'value, greater or equal 0.'
        if self.collateral_validation_err_msg:
            self.upd_collateral_tx_info(True)
            error_count += 1

        self.ip_port_validation_err_msg = ''
        try:
            self.dmn_ip = self.edtIP.text().strip()
            if self.dmn_ip:
                ipaddress.ip_address(self.dmn_ip)
        except Exception as e:
            self.edtIP.setFocus()
            self.ip_port_validation_err_msg = 'Invalid masternode IP address: %s.' % str(e)
            self.upd_ip_info(True)
            error_count += 1

        try:
            if self.dmn_ip:
                self.dmn_tcp_port = int(self.edtPort.text())
            else:
                self.dmn_tcp_port = None
        except Exception:
            self.edtPort.setFocus()
            self.ip_port_validation_err_msg = 'Invalid TCP port: should be integer.'
            self.upd_ip_info(True)
            error_count += 1

        self.payout_address_validation_err_msg = ''
        addr = self.edtPayoutAddress.text().strip()
        if not addr:
            self.payout_address_validation_err_msg = 'Owner payout address is required.'
        else:
            self.dmn_owner_payout_addr = addr
            if not validate_address(self.dmn_owner_payout_addr, self.app_config.dash_network):
                self.payout_address_validation_err_msg = 'Invalid owner payout address.'
        if self.payout_address_validation_err_msg:
            self.edtPayoutAddress.setFocus()
            self.upd_payout_addr_info(True)
            error_count += 1

        self.operator_reward_validation_err_msg = ''
        if self.chbWholeMNReward.isChecked():
            self.dmn_operator_reward = 0
        else:
            self.dmn_operator_reward = self.edtOperatorReward.value()
            if self.dmn_operator_reward > 100 or self.dmn_operator_reward < 0:
                self.edtOperatorReward.setFocus()
                self.operator_reward_validation_err_msg = 'Invalid operator reward value: should be a value ' \
                                                          'between 0 and 100.'
        if self.operator_reward_validation_err_msg:
            self.upd_oper_reward_info(True)
            error_count += 1

        self.owner_key_validation_err_msg = ''
        key = self.edtOwnerKey.text().strip()
        if not key:
            self.owner_key_validation_err_msg = 'Owner key/address is required.'
        else:
            if self.dmn_owner_key_type == InputKeyType.PRIVATE:
                self.dmn_owner_privkey = key
                if not validate_wif_privkey(self.dmn_owner_privkey, self.app_config.dash_network):
                    self.edtOwnerKey.setFocus()
                    self.owner_key_validation_err_msg = 'Invalid owner private key.'
                else:
                    self.dmn_owner_address = wif_privkey_to_address(self.dmn_owner_privkey, self.app_config.dash_network)
            else:
                self.dmn_owner_address = key
                self.dmn_owner_privkey = ''
                if not validate_address(self.dmn_owner_address, self.app_config.dash_network):
                    self.edtOwnerKey.setFocus()
                    self.owner_key_validation_err_msg = 'Invalid owner Dash address.'
        if self.owner_key_validation_err_msg:
            self.upd_owner_key_info(True)
            error_count += 1

        self.operator_key_validation_err_msg = ''
        key = self.edtOperatorKey.text().strip()
        if not key:
            self.operator_key_validation_err_msg = 'Operator key is required.'
        else:
            if self.dmn_operator_key_type == InputKeyType.PRIVATE:
                try:
                    self.dmn_operator_privkey = key

                    try:
                        b = bytes.fromhex(self.dmn_operator_privkey)
                        if len(b) != 32:
                            raise Exception('invalid length (' + str(len(b)) + ')')
                    except Exception as e:
                        self.edtOperatorKey.setFocus()
                        self.operator_key_validation_err_msg = 'Invalid operator private key: ' + str(e)

                    self.dmn_operator_pubkey = bls_privkey_to_pubkey(self.dmn_operator_privkey)
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    self.operator_key_validation_err_msg = 'Invalid operator private key: ' + str(e)
            else:
                self.dmn_operator_pubkey = key
                self.dmn_operator_privkey = ''
                try:
                    b = bytes.fromhex(self.dmn_operator_pubkey)
                    if len(b) != 48:
                        raise Exception('invalid length (' + str(len(b)) + ')')
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    self.operator_key_validation_err_msg = 'Invalid operator public key: ' + str(e)
        if self.operator_key_validation_err_msg:
            self.upd_operator_key_info(True)
            error_count += 1

        self.voting_key_validation_err_msg = ''
        if self.deterministic_mns_spork_active:
            key = self.edtVotingKey.text().strip()
            if not key:
                self.voting_key_validation_err_msg = 'Voting key/address is required.'
            else:
                if self.dmn_voting_key_type == InputKeyType.PRIVATE:
                    self.dmn_voting_privkey = key
                    if not validate_wif_privkey(self.dmn_voting_privkey, self.app_config.dash_network):
                        self.edtVotingKey.setFocus()
                        self.voting_key_validation_err_msg = 'Invalid voting private key.'
                    else:
                        self.dmn_voting_address = wif_privkey_to_address(self.dmn_voting_privkey, self.app_config.dash_network)
                else:
                    self.dmn_voting_address = key
                    self.dmn_voting_privkey = ''
                    if not validate_address(self.dmn_voting_address, self.app_config.dash_network):
                        self.edtVotingKey.setFocus()
                        self.voting_key_validation_err_msg = 'Invalid voting Dash address.'
        else:
            # spork 15 not active - use the owner private key for voting
            self.dmn_voting_address = self.dmn_owner_address
            self.dmn_voting_privkey = self.dmn_owner_privkey
            self.dmn_voting_key_type = self.dmn_owner_key_type

        if self.voting_key_validation_err_msg:
            self.upd_voting_key_info(True)
            error_count += 1

        if error_count > 1:
            raise Exception('Errors were encountered in the input data. You must correct them before you can continue.')
        elif error_count == 1:
            raise Exception(max((self.collateral_validation_err_msg, self.ip_port_validation_err_msg,
                                 self.payout_address_validation_err_msg, self.operator_reward_validation_err_msg,
                                 self.owner_key_validation_err_msg, self.operator_key_validation_err_msg,
                                 self.voting_key_validation_err_msg)))

        break_scanning = False

        def check_break_scanning():
            nonlocal break_scanning
            return break_scanning

        def do_break_scanning():
            nonlocal break_scanning
            break_scanning = True
            return False

        self.btnContinue.setEnabled(False)
        try:
            ret = WndUtils.run_thread_dialog(self.get_collateral_tx_address_thread, (check_break_scanning,), True,
                                             force_close_dlg_callback=do_break_scanning)
        except Exception as e:
            log.exception(str(e))
            raise Exception(str(e))
        self.btnContinue.setEnabled(True)
        return ret

    def get_collateral_tx_address_thread(self, ctrl: CtrlObject, check_break_scanning_ext: Callable[[], bool]):
        txes_cnt = 0
        msg = ''
        break_scanning = False
        ctrl.dlg_config_fun(dlg_title="Validating collateral transaction.", show_progress_bar=False)
        ctrl.display_msg_fun('Verifying collateral transaction...')

        def check_break_scanning():
            nonlocal break_scanning
            if self.finishing or break_scanning:
                # stop the scanning process if the dialog finishes or the address/bip32path has been found
                raise BreakFetchTransactionsException()
            if check_break_scanning_ext is not None and check_break_scanning_ext():
                raise BreakFetchTransactionsException()

        def fetch_txes_feeback(tx_cnt: int):
            nonlocal msg, txes_cnt
            txes_cnt += tx_cnt
            ctrl.display_msg_fun(msg + '<br><br>' + 'Number of transactions fetched so far: ' + str(txes_cnt))

        def on_msg_link_activated(link: str):
            nonlocal break_scanning
            if link == 'break':
                break_scanning = True

        try:
            tx = self.dashd_intf.getrawtransaction(self.dmn_collateral_tx, 1, skip_cache=True)
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
                if vout.get('valueSat') != 1000e8:
                    raise Exception('The value of the collateral transaction output is not equal to 1000 Dash.')

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
            try:
                addr = hw_intf.get_address(self.main_dlg.hw_session, self.dmn_collateral_tx_address_path)
            except CancelException:
                return False

            msg = ''
            if addr != self.dmn_collateral_tx_address:
                log.warning(
                    f'The address returned by the hardware wallet ({addr}) for the BIP32 path '
                    f'{self.dmn_collateral_tx_address_path} differs from the address stored the mn configuration '
                    f'(self.dmn_collateral_tx_address). Need to scan wallet for a correct BIP32 path.')

                msg = '<span style="color:red">The BIP32 path of the collateral address from your mn config is incorret.<br></span>' \
                      f'Trying to find the BIP32 path of the address {self.dmn_collateral_tx_address} in your wallet.' \
                      f'<br>This may take a while (<a href="break">break</a>)...'
                self.dmn_collateral_tx_address_path = ''
        else:
            msg = 'Looking for a BIP32 path of the Dash address related to the masternode collateral.<br>' \
                  'This may take a while (<a href="break">break</a>)....'

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
                                                             fetch_txes_feeback)
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
            if self.validate_data():
                cs = STEP_DASHD_TYPE
            else:
                return
            self.step_stack.append(self.current_step)

        elif self.current_step == STEP_DASHD_TYPE:
            if self.get_dash_node_type() == NODE_TYPE_PUBLIC_RPC:
                cs = STEP_AUTOMATIC_RPC_NODE
            elif self.get_dash_node_type() == NODE_TYPE_OWN:
                cs = STEP_MANUAL_OWN_NODE
            else:
                self.errorMsg('You have to choose one of the two options.')
                return
            self.step_stack.append(self.current_step)

        elif self.current_step == STEP_AUTOMATIC_RPC_NODE:
            cs = STEP_SUMMARY
            # in this case don't allow to start the automatic process again when the user clicks <Back>

        elif self.current_step == STEP_MANUAL_OWN_NODE:
            # check if the user passed tge protx transaction hash
            if not self.manual_signed_message:
                self.errorMsg('It looks like you have not signed a "protx register_prepare" result.')
                return

            self.dmn_reg_tx_hash = self.edtManualTxHash.text().strip()
            if not self.dmn_reg_tx_hash:
                self.edtManualTxHash.setFocus()
                self.errorMsg('Invalid transaction hash.')
                return
            try:
                bytes.fromhex(self.dmn_reg_tx_hash)
            except Exception:
                log.warning('Invalid transaction hash.')
                self.edtManualTxHash.setFocus()
                self.errorMsg('Invalid transaction hash.')
                return
            cs = STEP_SUMMARY
        else:
            self.errorMsg('Invalid step')
            return

        prev_step = self.current_step
        self.current_step = cs
        self.update_step_tab_ui()

        try:
            if self.current_step == STEP_AUTOMATIC_RPC_NODE:
                self.start_automatic_process()
            elif self.current_step == STEP_MANUAL_OWN_NODE:
                self.start_manual_process()
            elif self.current_step == STEP_SUMMARY:
                self.lblProtxSummary1.setText('<b><span style="color:green">Congratultions! The transaction for your DIP-3 '
                                              'masternode has been submitted and is currently awaiting confirmations.'
                                              '</b></span>')
                if self.on_proregtx_success_callback:
                    self.on_proregtx_success_callback(self.masternode)
                if not self.check_tx_confirmation():
                    self.wait_for_confirmation_timer_id = self.startTimer(5000)
        except Exception:
            self.current_step = prev_step
            self.update_step_tab_ui()
            raise

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
        if active:
            self.upd_node_type_info()

    @pyqtSlot(bool)
    def on_rbOwnDashNodeType_toggled(self, active):
        if active:
            self.upd_node_type_info()

    def sign_protx_message_with_hw(self, msg_to_sign) -> str:
        sig = WndUtils.call_in_main_thread(
            hw_intf.hw_sign_message, self.main_dlg.hw_session, self.dmn_collateral_tx_address_path,
            msg_to_sign, 'Click the confirmation button on your hardware wallet to sign the ProTx payload message.')

        if sig.address != self.dmn_collateral_tx_address:
            log.error(f'Protx payload signature address mismatch. Is: {sig.address}, should be: '
                      f'{self.dmn_collateral_tx_address}.')
            raise Exception(f'Protx payload signature address mismatch. Is: {sig.address}, should be: '
                            f'{self.dmn_collateral_tx_address}.')
        else:
            sig_bin = base64.b64encode(sig.signature)
            payload_sig_str = sig_bin.decode('ascii')
            return payload_sig_str

    def start_automatic_process(self):
        self.lblProtxTransaction1.hide()
        self.lblProtxTransaction2.hide()
        self.lblProtxTransaction3.hide()
        self.lblProtxTransaction4.hide()
        self.btnContinue.setEnabled(False)
        self.btnContinue.repaint()
        self.run_thread(self, self.proregtx_automatic_thread, (), on_thread_finish=self.finished_automatic_process)

    def finished_automatic_process(self):
        self.btnCancel.setEnabled(True)
        self.btnCancel.repaint()
        self.update_step_tab_ui()

    def proregtx_automatic_thread(self, ctrl):
        log.debug('Starting proregtx_prepare_thread')
        def set_text(widget, text: str):
            def call(widget, text):
                widget.setText(text)
                widget.repaint()
                widget.setVisible(True)
            WndUtils.call_in_main_thread(call, widget, text)

        def finished_with_success():
            def call():
                self.next_step()
            WndUtils.call_in_main_thread(call)


        try:
            try:
                mn_reg_support = self.dashd_intf.checkfeaturesupport('protx_register', self.app_config.app_version)
                # is the "registration" feature enabled on the current rpc node?
                if not mn_reg_support.get('enabled'):
                    if mn_reg_support.get('message'):
                        raise Exception(mn_reg_support.get('message'))
                    else:
                        raise Exception('The \'protx_register\' function is not supported by the RPC node '
                                        'you are connected to.')

                public_proxy_node = True

                active = self.app_config.feature_register_dmn_automatic.get_value()
                if not active:
                    msg = self.app_config.feature_register_dmn_automatic.get_message()
                    if not msg:
                        msg = 'The functionality of the automatic execution of the ProRegTx command on the ' \
                              '"public" RPC nodes is inactive. Use the manual method or contact the program author ' \
                              'for details.'
                    raise Exception(msg)

            except JSONRPCException as e:
                public_proxy_node = False  # it's not a "public" rpc node

            # preparing protx message
            try:
                funding_address = ''
                if not public_proxy_node:
                    try:
                        # find an address to be used as the source of the transaction fees
                        min_fee = round(1024 * FEE_DUFF_PER_BYTE / 1e8, 8)
                        balances = self.dashd_intf.listaddressbalances(min_fee)
                        bal_list = []
                        for addr in balances:
                            bal_list.append({'address': addr, 'amount': balances[addr]})
                        bal_list.sort(key = lambda x: x['amount'])
                        if not bal_list:
                            raise Exception("No address can be found in the node's wallet with sufficient funds to "
                                            "cover the transaction fees.")
                        funding_address = bal_list[0]['address']
                    except JSONRPCException as e:
                        log.info("Couldn't list the node address balances. We assume you are using a public RPC node and "
                                 "the funding address for the transaction fees will be estimated during the "
                                 "`register_prepare` call")

                set_text(self.lblProtxTransaction1, '<b>1. Preparing a ProRegTx transaction on a remote node...</b>')

                if self.dmn_owner_key_type == InputKeyType.PRIVATE:
                    owner_key = self.dmn_owner_privkey
                else:
                    owner_key = self.dmn_owner_address

                params = ['register_prepare', self.dmn_collateral_tx, self.dmn_collateral_tx_index,
                          self.dmn_ip + ':' + str(self.dmn_tcp_port) if self.dmn_ip else '0', owner_key,
                          self.dmn_operator_pubkey, self.dmn_voting_address, str(round(self.dmn_operator_reward, 2)),
                          self.dmn_owner_payout_addr]
                if funding_address:
                    params.append(funding_address)

                call_ret = self.dashd_intf.rpc_call(True, False, 'protx', *tuple(params))

                call_ret_str = json.dumps(call_ret, default=EncodeDecimal)
                msg_to_sign = call_ret.get('signMessage', '')
                protx_tx = call_ret.get('tx')

                log.debug('register_prepare returned: ' + call_ret_str)
                set_text(self.lblProtxTransaction1,
                         '<b>1. Preparing a ProRegTx transaction on a remote node.</b> <span style="color:green">'
                         'Success.</span>')
            except Exception as e:
                set_text(
                    self.lblProtxTransaction1,
                    '<b>1. Preparing a ProRegTx transaction on a remote node.</b> <span style="color:red">Failed '
                    f'with the following error: {str(e)}</span>')
                return

            set_text(self.lblProtxTransaction2, '<b>Message to be signed:</b><br><code>' + msg_to_sign + '</code>')

            # signing message:
            set_text(self.lblProtxTransaction3, '<b>2. Signing message with hardware wallet...</b>')
            try:
                payload_sig_str = self.sign_protx_message_with_hw(msg_to_sign)

                set_text(self.lblProtxTransaction3, '<b>2. Signing message with hardware wallet.</b> '
                                                    '<span style="color:green">Success.</span>')
            except CancelException:
                set_text(self.lblProtxTransaction3,
                         '<b>2. Signing message with hardware wallet.</b> <span style="color:red">Cancelled.</span>')
                return
            except Exception as e:
                log.exception('Signature failed.')
                set_text(self.lblProtxTransaction3,
                         '<b>2. Signing message with hardware wallet.</b> <span style="color:red">Failed with the '
                         f'following error: {str(e)}.</span>')
                return

            # submitting signed transaction
            set_text(self.lblProtxTransaction4, '<b>3. Submitting the signed protx transaction to the remote node...</b>')
            try:
                self.dmn_reg_tx_hash = self.dashd_intf.rpc_call(True, False, 'protx', 'register_submit', protx_tx,
                                                                payload_sig_str)

                log.debug('protx register_submit returned: ' + str(self.dmn_reg_tx_hash))
                set_text(self.lblProtxTransaction4,
                         '<b>3. Submitting the signed protx transaction to the remote node.</b> <span style="'
                         'color:green">Success.</span>')
                finished_with_success()
            except Exception as e:
                log.exception('protx register_submit failed')
                set_text(self.lblProtxTransaction4,
                         '<b>3. Submitting the signed protx transaction to the remote node.</b> '
                         f'<span style="color:red">Failed with the following error: {str(e)}</span>')

        except Exception as e:
            log.exception('Exception occurred')
            set_text(self.lblProtxTransaction1, f'<span style="color:red">{str(e)}</span>')

    @pyqtSlot(bool)
    def on_btnManualSignProtx_clicked(self):
        prepare_result = self.edtManualProtxPrepareResult.toPlainText().strip()
        if not prepare_result:
            self.errorMsg('You need to enter a result of the "protx register_prepare" command.')
            self.edtManualProtxPrepareResult.setFocus()
            return

        try:
            prepare_result_dict = json.loads(prepare_result)
            msg_to_sign = prepare_result_dict.get('signMessage', '')
            protx_tx = prepare_result_dict.get('tx')

            try:
                payload_sig_str = self.sign_protx_message_with_hw(msg_to_sign)
                protx_submit = f'protx register_submit "{protx_tx}" "{payload_sig_str}"'
                self.edtManualProtxSubmit.setPlainText(protx_submit)
                self.btnContinue.setEnabled(True)
                self.btnContinue.repaint()
                self.manual_signed_message = True
            except CancelException:
                return
            except Exception as e:
                log.exception('Signature failed.')
                self.errorMsg(str(e))
                return

        except Exception as e:
            self.errorMsg('Invalid "protx register_prepare" result. Note that the text must be copied along '
                          'with curly braces.')
            return

    def start_manual_process(self):
        self.edtManualFundingAddress.setFocus()
        self.update_manual_protx_prepare_command()

    def update_manual_protx_prepare_command(self):
        addr = self.edtManualFundingAddress.text().strip()
        if addr:
            valid = validate_address(addr, self.app_config.dash_network)
            if valid:
                if self.dmn_owner_key_type == InputKeyType.PRIVATE:
                    owner_key = self.dmn_owner_privkey
                else:
                    owner_key = self.dmn_owner_address

                cmd = f'protx register_prepare "{self.dmn_collateral_tx}" "{self.dmn_collateral_tx_index}" ' \
                    f'"{self.dmn_ip + ":" + str(self.dmn_tcp_port) if self.dmn_ip else "0"}" ' \
                    f'"{owner_key}" "{self.dmn_operator_pubkey}" "{self.dmn_voting_address}" ' \
                    f'"{str(round(self.dmn_operator_reward, 2))}" "{self.dmn_owner_payout_addr}" "{addr}"'
            else:
                cmd = 'Enter the valid funding address in the exit box above'
        else:
            cmd = ''

        self.edtManualProtxPrepare.setPlainText(cmd)
        if cmd != self.last_manual_prepare_string:
            self.last_manual_prepare_string = cmd
            self.edtManualProtxSubmit.clear()
            self.edtManualProtxPrepareResult.clear()
            self.edtManualTxHash.clear()
            self.dmn_reg_tx_hash = ''
            self.manual_signed_message = False

    def timerEvent(self, event: QTimerEvent):
        """ Timer controlling the confirmation of the proreg transaction. """
        if self.check_tx_confirmation():
            self.killTimer(event.timerId())

    def check_tx_confirmation(self):
        try:
            tx = self.dashd_intf.getrawtransaction(self.dmn_reg_tx_hash, 1, skip_cache=True)
            conf = tx.get('confirmations')
            if conf:
                h = tx.get('height')
                self.lblProtxSummary1.setText(
                    '<b><span style="color:green">Congratultions! The transaction for your DIP-3 masternode has been '
                    f'confirmed in block {h}.</b></span> ')
                return True
        except Exception:
            pass
        return False

    def update_show_hints_label(self):
        if self.show_field_hinds:
            lbl = '<a href="hide">Hide field descriptions</a>'
        else:
            lbl = '<a href="show">Show field descriptions</a>'
        self.lblFieldHints.setText(lbl)

    @pyqtSlot(str)
    def on_lblFieldHints_linkActivated(self, link):
        if link == 'show':
            self.show_field_hinds = True
        else:
            self.show_field_hinds = False
        self.update_show_hints_label()
        self.update_fields_info(False)
        self.minimize_dialog_height()

    @pyqtSlot(str)
    def on_edtManualFundingAddress_textChanged(self, text):
        self.update_manual_protx_prepare_command()

    @pyqtSlot(bool)
    def on_btnManualFundingAddressPaste_clicked(self, checked):
        cl = QApplication.clipboard()
        self.edtManualFundingAddress.setText(cl.text())

    @pyqtSlot(bool)
    def on_btnManualProtxPrepareCopy_clicked(self, checked):
        text = self.edtManualProtxPrepare.toPlainText()
        cl = QApplication.clipboard()
        cl.setText(text)

    @pyqtSlot(bool)
    def on_btnManualProtxPrepareResultPaste_clicked(self, checked):
        cl = QApplication.clipboard()
        self.edtManualProtxPrepareResult.setPlainText(cl.text())

    @pyqtSlot(bool)
    def on_btnManualProtxSubmitCopy_clicked(self, checked):
        text = self.edtManualProtxSubmit.toPlainText()
        cl = QApplication.clipboard()
        cl.setText(text)

    @pyqtSlot(bool)
    def on_btnManualTxHashPaste_clicked(self, checked):
        cl = QApplication.clipboard()
        self.edtManualTxHash.setText(cl.text())

    @pyqtSlot(bool)
    def on_btnSummaryDMNOperatorKeyCopy_clicked(self, checked):
        text = self.edtSummaryDMNOperatorKey.text()
        cl = QApplication.clipboard()
        cl.setText(text)