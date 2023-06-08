#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-11
import base64
import json
import logging
from typing import List, Callable, Optional
import ipaddress

from PyQt5.QtCore import pyqtSlot, Qt, QTimerEvent, QTimer
from PyQt5.QtWidgets import QDialog, QMessageBox, QApplication, QWidget
from bitcoinrpc.authproxy import EncodeDecimal, JSONRPCException

import app_cache
import app_defs
import hw_intf
from app_config import MasternodeConfig, MasternodeType, AppConfig, InputKeyType
from app_defs import FEE_DUFF_PER_BYTE
from bip44_wallet import Bip44Wallet, BreakFetchTransactionsException
from common import CancelException
from dash_utils import generate_bls_privkey, generate_wif_privkey, validate_address, wif_privkey_to_address, \
    validate_wif_privkey, bls_privkey_to_pubkey, MASTERNODE_TX_MINIMUM_CONFIRMATIONS, DASH_PLATFORM_DEFAULT_P2P_PORT, \
    DASH_PLATFORM_DEFAULT_HTTP_PORT, generate_ed25519_private_key, \
    parse_ed25519_private_key, DASH_PLATFORM_DEFAULT_P2P_PORT, \
    DASH_PLATFORM_DEFAULT_HTTP_PORT, ed25519_private_key_to_tenderdash, validate_platform_node_id, \
    validate_ed25519_privkey, ed25519_private_key_to_platform_node_id, ed25519_private_key_to_raw_hex
from dashd_intf import DashdInterface
from thread_fun_dlg import CtrlObject
from ui import ui_reg_masternode_dlg
from wnd_utils import WndUtils, QDetectThemeChange, get_widget_font_color_blue, \
    get_widget_font_color_green
from find_coll_tx_dlg import WalletUtxosListDlg
from wallet_dlg import WalletDlg, WalletDisplayMode

STEP_MN_DATA = 1
STEP_DASHD_TYPE = 2
STEP_AUTOMATIC_RPC_NODE = 3
STEP_MANUAL_OWN_NODE = 4
STEP_SUMMARY = 5

NODE_TYPE_PUBLIC_RPC = 1
NODE_TYPE_OWN = 2

CACHE_ITEM_SHOW_FIELD_HINTS = 'RegMasternodeDlg_ShowFieldHints'

log = logging.getLogger('dmt.reg_masternode')


class RegMasternodeDlg(QDialog, QDetectThemeChange, ui_reg_masternode_dlg.Ui_RegMasternodeDlg, WndUtils):
    def __init__(self, main_dlg, config: AppConfig, dashd_intf: DashdInterface, masternode: MasternodeConfig,
                 on_proregtx_success_callback: Callable):
        QDialog.__init__(self, main_dlg)
        QDetectThemeChange.__init__(self)
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.__init__(self)
        WndUtils.__init__(self, main_dlg.app_config)
        self.main_dlg = main_dlg
        self.masternode = masternode
        self.app_config = config
        self.dashd_intf: DashdInterface = dashd_intf
        self.on_proregtx_success_callback = on_proregtx_success_callback
        self.style = ''
        self.styled_widgets: List[QWidget] = []
        self.operator_reward_saved = None
        self.owner_pkey_generated: Optional[str] = None
        self.operator_pkey_generated: Optional[str] = None
        self.voting_pkey_generated: Optional[str] = None
        self.current_step = STEP_MN_DATA
        self.step_stack: List[int] = []
        self.proregtx_prepare_thread_ref = None
        self.masternode_type: MasternodeType = self.masternode.masternode_type
        self.collateral_tx: Optional[str] = None
        self.collateral_tx_index: Optional[int] = None
        self.collateral_tx_address: Optional[str] = None
        self.collateral_tx_address_path: Optional[str] = None
        self.ip: Optional[str] = None
        self.tcp_port: Optional[int] = None
        self.owner_payout_addr: Optional[str] = None
        self.operator_reward: int = 0
        self.owner_privkey: Optional[str] = None
        self.owner_address: Optional[str] = None
        self.operator_privkey: Optional[str] = None
        self.operator_pubkey: Optional[str] = None
        self.voting_privkey: Optional[str] = None
        self.voting_address: Optional[str] = None
        self.owner_key_type = InputKeyType.PRIVATE
        self.operator_key_type = InputKeyType.PRIVATE
        self.voting_key_type = InputKeyType.PRIVATE
        self.platform_node_key_type = InputKeyType.PRIVATE
        self.platform_node_private_key: Optional[str] = None  # In this dialog, we are operating on Tenderdash pk format
        self.platform_node_id: Optional[str] = None
        self.platform_node_key_generated = False
        self.platform_p2p_port: Optional[int] = self.masternode.platform_p2p_port if \
            self.masternode.platform_p2p_port else DASH_PLATFORM_DEFAULT_P2P_PORT
        self.platform_http_port: Optional[int] = self.masternode.platform_http_port if \
            self.masternode.platform_http_port else DASH_PLATFORM_DEFAULT_HTTP_PORT

        self.collateral_validation_err_msg = ''
        self.ip_port_validation_err_msg = ''
        self.payout_address_validation_err_msg = ''
        self.operator_reward_validation_err_msg = ''
        self.owner_key_validation_err_msg = ''
        self.operator_key_validation_err_msg = ''
        self.voting_key_validation_err_msg = ''
        self.platform_node_id_validation_err_msg = ''
        self.platform_ports_validation_err_msg = ''

        self.dmn_reg_tx_hash = ''
        self.manual_signed_message = False
        self.last_manual_prepare_string: Optional[str] = None
        self.wait_for_confirmation_timer_id = None
        self.show_field_hinds = True
        self.summary_info = []
        self.register_prepare_command_name = 'register_prepare'  # register_prepare or register_prepare_hpmn, depending
        # on self.masternode_type
        if self.masternode:
            self.collateral_tx_address_path = self.masternode.collateral_bip32_path
        self.bip44_wallet = Bip44Wallet(self.app_config.hw_coin_name, self.main_dlg.hw_session,
                                        self.app_config.db_intf, self.dashd_intf, self.app_config.dash_network)
        self.finishing = False
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.setupUi(self, self)
        self.restore_cache_settings()
        self.edtCollateralTx.setText(self.masternode.collateral_tx)
        if self.masternode.collateral_tx:
            sz = self.edtCollateralTx.fontMetrics().size(0, self.masternode.collateral_tx + '000')
            self.edtCollateralTx.setMinimumWidth(sz.width())
        self.edtCollateralIndex.setText(str(self.masternode.collateral_tx_index))
        self.edtIP.setText(self.masternode.ip)
        self.edtPort.setText(str(self.masternode.tcp_port))
        self.edtPayoutAddress.setText(self.masternode.collateral_address)
        self.chbWholeMNReward.setChecked(True)
        self.lblProtxSummary2.linkActivated.connect(self.save_summary_info)
        self.lblCollateralTxMsg.sizePolicy().setHeightForWidth(True)
        self.edtPlatformP2PPort.setText(str(self.platform_p2p_port) if self.platform_p2p_port else '')
        self.edtPlatformHTTPPort.setText(str(self.platform_http_port) if self.platform_http_port else '')
        self.prepare_keys()
        self.btnClose.hide()
        WndUtils.set_icon(self, self.btnManualFundingAddressPaste, 'content-paste@16px.png')
        WndUtils.set_icon(self, self.btnManualProtxPrepareCopy, 'content-copy@16px.png')
        WndUtils.set_icon(self, self.btnManualProtxPrepareResultPaste, 'content-paste@16px.png')
        WndUtils.set_icon(self, self.btnManualProtxSubmitCopy, 'content-copy@16px.png')
        WndUtils.set_icon(self, self.btnManualTxHashPaste, 'content-paste@16px.png')
        WndUtils.set_icon(self, self.btnSummaryDMNOperatorKeyCopy, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnPlatformP2PPortSetDefault, 'restore@16px.png')
        WndUtils.set_icon(self.parent, self.btnPlatformHTTPPortSetDefault, 'restore@16px.png')
        doc_url = app_defs.get_doc_url('README.md#setting-up-a-masternode', use_doc_subdir=False)
        if doc_url:
            self.lblDocumentation.setText(f'<a href="{doc_url}">Documentation</a>')
        self.rbMNTypeRegular.blockSignals(True)
        self.rbMNTypeHPMN.blockSignals(True)
        if self.masternode_type == MasternodeType.REGULAR:
            self.rbMNTypeRegular.setChecked(True)
        else:
            self.rbMNTypeHPMN.setChecked(True)
        self.rbMNTypeRegular.blockSignals(False)
        self.rbMNTypeHPMN.blockSignals(False)
        self.update_styles()
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

    def showEvent(self, QShowEvent):
        def apply():
            self.set_buttons_height()

        QTimer.singleShot(100, apply)

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

    def set_buttons_height(self):
        h = self.edtCollateralTx.height()
        for btn in (self.btnGenerateOwnerKey, self.btnSelectCollateralUtxo, self.btnGenerateOperatorKey,
                    self.btnGenerateVotingKey, self.btnGeneratePlatformNodeKey, self.btnManualFundingAddressPaste,
                    self.btnManualProtxPrepareCopy, self.btnManualProtxPrepareResultPaste,
                    self.btnManualProtxSubmitCopy, self.btnManualTxHashPaste, self.btnSummaryDMNOperatorKeyCopy,
                    self.btnPlatformHTTPPortSetDefault, self.btnPlatformP2PPortSetDefault,
                    self.btnChooseAddressFromWallet):
            btn.setFixedHeight(h)

    def onThemeChanged(self):
        self.update_styles()

    def update_styles(self):
        blue_color = get_widget_font_color_blue(self.lblIPMsg)
        green_color = get_widget_font_color_green(self.lblIPMsg)

        self.style = f'QLabel[level="info"]{{color:{blue_color}}} \n QLabel[level="warning"]{{color:#ff6600}} \n ' \
                     f'QLabel[level="error"]{{background-color:red;color:white}}'
        self.setStyleSheet(self.style)

        # Stylesheet using custom properties (i.e. "level") needs to be applied to particular descendant widgets,
        # otherwise it doens't work
        for w in self.styled_widgets:
            w.setStyleSheet(self.style)

        self.lblProtxSummary1.setStyleSheet(f'QLabel{{color:{green_color};font-weight: bold}}')

    def update_dynamic_labels(self):

        def style_to_color(style: str) -> str:
            if style == 'hl1':
                color = 'color:#00802b'
            else:
                color = ''
            return color

        def get_label_text(prefix: str, key_type: str, tooltip_anchor: str, style: str):
            lbl = prefix + ' ' + \
                  {'privkey': 'private key',
                   'pubkey': 'public key',
                   'address': 'Dash address',
                   'platform_node_id': 'Node Id'}.get(key_type, '???')

            change_mode = f'(<a href="{tooltip_anchor}">use {tooltip_anchor}</a>)'
            ret = f'<table style="float:right;{style_to_color(style)}"><tr><td><b>{lbl}</b></td><td>{change_mode}' \
                  f'</td></tr></table>'
            return ret

        if self.masternode:
            if self.owner_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter the owner private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the owner Dash address')
                style = 'hl1'
            self.lblOwnerKey.setText(get_label_text('Owner', key_type, tooltip_anchor, style))
            self.edtOwnerKey.setPlaceholderText(placeholder_text)

            if self.operator_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'pubkey', 'Enter the operator private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('pubkey', 'privkey', 'Enter the operator public key')
                style = 'hl1'
            self.lblOperatorKey.setText(get_label_text('Operator', key_type, tooltip_anchor, style))
            self.edtOperatorKey.setPlaceholderText(placeholder_text)

            if self.voting_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter the voting private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the voting Dash address')
                style = 'hl1'
            self.lblVotingKey.setText(get_label_text('Voting', key_type, tooltip_anchor, style))
            self.edtVotingKey.setPlaceholderText(placeholder_text)

            if self.platform_node_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'node id',
                                                              'Enter the Platform Node private key')
                style = ''
            else:
                key_type, tooltip_anchor, placeholder_text = ('platform_node_id', 'privkey',
                                                              'Enter the Platform Node Id')
                style = 'hl1'
            self.lblPlatformNodeKey.setText(get_label_text('Platform Node', key_type, tooltip_anchor, style))
            self.edtPlatformNodeKey.setPlaceholderText(placeholder_text)

    @pyqtSlot(str)
    def on_lblOwnerKey_linkActivated(self, _):
        if self.owner_key_type == InputKeyType.PRIVATE:
            self.owner_key_type = InputKeyType.PUBLIC
            self.owner_privkey = self.edtOwnerKey.text()
            self.edtOwnerKey.setText(self.owner_address)
        else:
            self.owner_key_type = InputKeyType.PRIVATE
            self.owner_address = self.edtOwnerKey.text()
            self.edtOwnerKey.setText(self.owner_privkey)
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_owner_key_info(False)

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, _):
        if self.operator_key_type == InputKeyType.PRIVATE:
            self.operator_key_type = InputKeyType.PUBLIC
            self.operator_privkey = self.edtOperatorKey.text()
            self.edtOperatorKey.setText(self.operator_pubkey)
        else:
            self.operator_key_type = InputKeyType.PRIVATE
            self.operator_pubkey = self.edtOperatorKey.text()
            self.edtOperatorKey.setText(self.operator_privkey)
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_operator_key_info(False)

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, _):
        if self.voting_key_type == InputKeyType.PRIVATE:
            self.voting_key_type = InputKeyType.PUBLIC
            self.voting_privkey = self.edtVotingKey.text()
            self.edtVotingKey.setText(self.voting_address)
        else:
            self.voting_key_type = InputKeyType.PRIVATE
            self.voting_address = self.edtVotingKey.text()
            self.edtVotingKey.setText(self.voting_privkey)
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_voting_key_info(False)

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
        self.update_dynamic_labels()
        self.update_ctrls_visibility()
        self.upd_platform_node_key_info(False)

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

    @pyqtSlot(str)
    def on_lblPlatformNodeKey_linkHovered(self, link):
        if link == 'node id':
            tt = 'Change input type to Platform Node Id'
        else:
            tt = 'Change input type to Ed25519 private key'
        self.lblPlatformNodeKey.setToolTip(tt)

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
                if (protx_state and protx_state.get('service') == self.masternode.ip + ':' +
                    str(self.masternode.tcp_port)) or (protx.get('collateralHash') == self.masternode.collateral_tx and
                                                       str(protx.get('collateralIndex')) == str(
                            self.masternode.collateral_tx_index)):
                    found_protx = True
                    break
        except Exception as e:
            pass

        if found_protx:
            if self.masternode.get_owner_public_address(self.app_config.dash_network) == \
                    protx_state.get('ownerAddress'):
                gen_owner = True

            if self.masternode.get_operator_pubkey(self.app_config.feature_new_bls_scheme.get_value()) == \
                    protx_state.get('pubKeyOperator'):
                gen_operator = True

            if self.masternode.get_voting_public_address(self.app_config.dash_network) == \
                    protx_state.get('votingAddress'):
                gen_voting = True

        if (self.masternode.owner_key_type == InputKeyType.PRIVATE and
            not self.masternode.owner_private_key) or \
                (self.masternode.owner_key_type == InputKeyType.PUBLIC and
                 not self.masternode.owner_address):
            gen_owner = True

        if (self.masternode.operator_key_type == InputKeyType.PRIVATE and
            not self.masternode.operator_private_key) or \
                (self.masternode.operator_key_type == InputKeyType.PUBLIC and
                 not self.masternode.operator_public_key):
            gen_operator = True

        if (self.masternode.voting_key_type == InputKeyType.PRIVATE and
            not self.masternode.voting_private_key) or \
                (self.masternode.voting_key_type == InputKeyType.PUBLIC and
                 not self.masternode.voting_address):
            gen_voting = True

        if gen_owner:
            self.owner_pkey_generated = generate_wif_privkey(self.app_config.dash_network, compressed=True)
            self.edtOwnerKey.setText(self.owner_pkey_generated)
        else:
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                self.edtOwnerKey.setText(self.masternode.owner_private_key)
            else:
                self.edtOwnerKey.setText(self.masternode.owner_address)
            self.owner_key_type = self.masternode.owner_key_type

        if gen_operator:
            try:
                self.operator_pkey_generated = generate_bls_privkey()
                self.edtOperatorKey.setText(self.operator_pkey_generated)
            except Exception as e:
                self.error_msg(str(e), True)
        else:
            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                self.edtOperatorKey.setText(self.masternode.operator_private_key)
            else:
                self.edtOperatorKey.setText(self.masternode.operator_public_key)
            self.operator_key_type = self.masternode.operator_key_type

        if gen_voting:
            self.voting_pkey_generated = generate_wif_privkey(self.app_config.dash_network, compressed=True)
            self.edtVotingKey.setText(self.voting_pkey_generated)
        else:
            if self.voting_key_type == InputKeyType.PRIVATE:
                self.edtVotingKey.setText(self.masternode.voting_private_key)
            else:
                self.edtVotingKey.setText(self.masternode.voting_address)

        self.platform_node_key_type = self.masternode.platform_node_key_type
        if self.platform_node_key_type == InputKeyType.PRIVATE:
            pk = self.masternode.get_platform_node_private_key_for_editing()
            self.edtPlatformNodeKey.setText(pk)
        else:
            self.edtPlatformNodeKey.setText(self.masternode.platform_node_id)

    @pyqtSlot(bool)
    def on_rbMNTypeRegular_toggled(self, checked):
        if checked:
            self.masternode_type = MasternodeType.REGULAR
            self.update_fields_info(True)
            self.update_ctrls_visibility()

    @pyqtSlot(bool)
    def on_rbMNTypeHPMN_toggled(self, checked):
        if checked:
            self.masternode_type = MasternodeType.HPMN
            self.update_fields_info(True)
            self.update_ctrls_visibility()

    @pyqtSlot(bool)
    def on_btnSelectCollateralUtxo_clicked(self):
        try:
            def apply_utxo(utxo):
                if utxo.masternode:
                    if utxo.masternode.name != self.masternode.name:
                        if WndUtils.query_dlg(
                                "Do you really want to use the UTXO that is already assigned to another masternode "
                                "configuration?",
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                            return False

                self.edtCollateralTx.setText(utxo.txid)
                self.edtCollateralIndex.setText(str(utxo.output_index))
                self.collateral_tx = utxo.txid
                self.collateral_tx_index = utxo.output_index
                self.collateral_tx_address = utxo.address
                self.collateral_tx_address_path = utxo.bip32_path

            if self.masternode_type == MasternodeType.REGULAR:
                dash_value_to_find = 1000
            else:
                dash_value_to_find = 4000

            if self.edtCollateralTx.text():
                # If there is any value in the collateral tx edit box, don't automatically apply the possible
                # result (if only one UTXO was found); We want to prevent the user from missing the fact, that
                # the value has been replaced with another
                auto_apply_result = False
            else:
                auto_apply_result = True

            found = WalletUtxosListDlg.select_utxo_from_wallet_dialog(
                self, dash_value_to_find, self.app_config, self.dashd_intf,
                None, self.main_dlg.hw_session, apply_utxo, auto_apply_result)

            if not found:
                # WndUtils.warn_msg(f'Could not find any UTXO of {dash_value_to_find} Dash value in your wallet.')
                if WndUtils.query_dlg(
                        f"Could not find any UTXO of {dash_value_to_find} Dash value in your wallet.\n\n"
                        f"To continue you must have an unspent {dash_value_to_find} Dash transaction output. "
                        f"Should I open a wallet window so you can create one? ",
                        buttons=QMessageBox.Yes | QMessageBox.No,
                        icon=QMessageBox.Warning) == QMessageBox.Yes:
                    try:
                        self.main_dlg.main_view.stop_threads()
                        ui = WalletDlg(self, self.main_dlg.hw_session, initial_mn_sel=None)
                        ui.subscribe_for_a_new_utxo(dash_value_to_find)
                        ui.exec_()

                        utxos_created = ui.get_new_utxos_subscribed()
                        if utxos_created and len(utxos_created) == 1:
                            utxo = utxos_created[0]
                            self.edtCollateralTx.setText(utxo.txid)
                            self.edtCollateralIndex.setText(str(utxo.output_index))
                    except Exception as e:
                        self.error_msg(str(e), True)
                    finally:
                        self.main_dlg.main_view.resume_threads()

        except Exception as e:
            WndUtils.error_msg(str(e))

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        self.close()

    @pyqtSlot(bool)
    def on_btnChooseAddressFromWallet_clicked(self, active):
        try:
            self.main_dlg.main_view.stop_threads()
            ui = WalletDlg(self, self.main_dlg.hw_session, initial_mn_sel=None,
                           display_mode=WalletDisplayMode.SELECT_ADDRESS)
            if ui.exec_():
                addr = ui.get_selected_wallet_address()
                if addr:
                    self.edtPayoutAddress.setText(addr)
        except Exception as e:
            self.error_msg(str(e), True)
        finally:
            self.main_dlg.main_view.resume_threads()

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

    def set_ctrl_message(self, control, message: str, style: str):
        control.setText(message)
        if message:
            control.setProperty('level', style)
            control.setStyleSheet(self.style)
            control.show()
        else:
            control.hide()
        if control not in self.styled_widgets:
            self.styled_widgets.append(control)

    def update_ctrls_visibility(self):
        self.btnGenerateVotingKey.setVisible(self.voting_key_type == InputKeyType.PRIVATE)
        self.btnGenerateOwnerKey.setVisible(self.owner_key_type == InputKeyType.PRIVATE)
        self.btnGenerateOperatorKey.setVisible(self.operator_key_type == InputKeyType.PRIVATE)
        self.btnGeneratePlatformNodeKey.setVisible(self.platform_node_key_type == InputKeyType.PRIVATE)

        if self.masternode_type == MasternodeType.REGULAR:
            self.lblPlatformNodeKey.hide()
            self.lblPlatformP2PPort.hide()
            self.lblPlatformHTTPPort.hide()
            self.lblPlatformPortsMsg.hide()
            self.edtPlatformNodeKey.hide()
            self.edtPlatformP2PPort.hide()
            self.edtPlatformHTTPPort.hide()
            self.lblPlatformNodeKeyMsg.hide()
            self.btnPlatformP2PPortSetDefault.hide()
            self.btnPlatformHTTPPortSetDefault.hide()
            self.linePlatformNodeId.hide()
            self.btnGeneratePlatformNodeKey.hide()
        else:
            self.lblPlatformNodeKey.show()
            self.lblPlatformP2PPort.show()
            self.lblPlatformHTTPPort.show()
            self.lblPlatformPortsMsg.show()
            self.edtPlatformNodeKey.show()
            self.edtPlatformP2PPort.show()
            self.edtPlatformHTTPPort.show()
            self.lblPlatformNodeKeyMsg.show()
            self.btnPlatformP2PPortSetDefault.show()
            self.btnPlatformHTTPPortSetDefault.show()
            self.linePlatformNodeId.show()
            self.btnGeneratePlatformNodeKey.show()

    def update_fields_info(self, show_invalid_data_msg: bool):
        """
        :param show_invalid_data_msg: if the argument is true and the data is invalid, an error message is shown
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
        self.upd_platform_node_key_info(show_invalid_data_msg)
        self.upd_platform_ports_info(show_invalid_data_msg)

    def upd_collateral_tx_info(self, show_invalid_data_msg: bool):
        """
        :param show_invalid_data_msg: if the argument is true and the data is invalid, an error message is shown
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
        :param show_invalid_data_msg: if the argument is true and the data is invalid, an error message is shown
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
                    msg = "You can leave the IP address and port fields empty if you want to delegate the operator " \
                          "role to an external entity and you don't know their values in advance."
                    style = 'info'
                else:
                    msg = "If you do not set the IP address and TCP port fields, the masternode operator will " \
                          "have to send a ProUpServTx transaction, e.g. by using the DMT 'Update Service' feature."
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
                if self.owner_key_type == InputKeyType.PRIVATE:
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

    def upd_platform_node_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if self.masternode_type == MasternodeType.HPMN:
            if show_invalid_data_msg and self.platform_node_id_validation_err_msg:
                msg = self.platform_node_id_validation_err_msg
                style = 'error'
            else:
                if self.show_field_hinds:
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

        self.set_ctrl_message(self.lblPlatformNodeKeyMsg, msg, style)

    def upd_platform_ports_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if show_invalid_data_msg and self.platform_ports_validation_err_msg:
            msg = self.platform_ports_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                msg = ''
                style = 'info'

        self.set_ctrl_message(self.lblPlatformPortsMsg, msg, style)

    def upd_operator_key_info(self, show_invalid_data_msg: bool):
        msg = ''
        style = ''
        if show_invalid_data_msg and self.operator_key_validation_err_msg:
            msg = self.operator_key_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                if self.operator_key_type == InputKeyType.PRIVATE:
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
        if show_invalid_data_msg and self.voting_key_validation_err_msg:
            msg = self.voting_key_validation_err_msg
            style = 'error'
        else:
            if self.show_field_hinds:
                if self.voting_key_type == InputKeyType.PRIVATE:
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
            msg = 'DIP-3 masternode registration involves sending a special transaction via the Dash node ' \
                  '(eg Dash-Qt). <b>Note, that this requires incurring a certain transaction fee, as with any ' \
                  'other ("normal") transaction.</b>'
        elif nt == NODE_TYPE_PUBLIC_RPC:
            msg = 'The ProRegTx transaction will be processed via the remote RPC node stored in the app configuration.' \
                  '<br><br>' \
                  '<b>Note 1:</b> this operation will involve signing transaction data with your <span style="color:red">owner key on the remote node</span>, ' \
                  'so use this method only if you trust the operator of that node (nodes <i>alice(suzy).dash-masternode-tool.org</i> are maintained by the author of this application).<br><br>' \
                  '<b>Note 2:</b> if the operation fails (e.g. due to a lack of funds), choose the manual method ' \
                  'using your own Dash wallet.'

        elif nt == NODE_TYPE_OWN:
            msg = 'A Dash Core wallet with sufficient funds to cover transaction fees is required to ' \
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
    def on_edtPlatformNodeKey_textChanged(self, text):
        self.upd_platform_node_key_info(False)

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

            if self.owner_key_type == InputKeyType.PRIVATE:
                owner_privkey = self.owner_privkey
            else:
                owner_privkey = '&lt;not available&gt;'

            if self.operator_key_type == InputKeyType.PRIVATE:
                operator_privkey = self.operator_privkey
            else:
                operator_privkey = '&lt;not available&gt;'

            if self.voting_key_type == InputKeyType.PRIVATE:
                voting_privkey = self.voting_privkey
            else:
                voting_privkey = '&lt;not available&gt;'

            self.summary_info = \
                [f'Network address\t{self.ip}:{self.tcp_port}',
                 f'Payout address\t{self.owner_payout_addr}',
                 f'Owner private key\t{owner_privkey}',
                 f'Owner public address\t{self.owner_address}',
                 f'Operator private key\t{operator_privkey}',
                 f'Operator public key\t{self.operator_pubkey}',
                 f'Voting private key\t{voting_privkey}',
                 f'Voting public address\t{self.voting_address}',
                 f'Protx hash\t{self.dmn_reg_tx_hash}']

            if self.masternode_type == MasternodeType.HPMN:
                self.summary_info.extend(
                    [f'Platform Node Id\t{self.platform_node_id}',
                     f'Platform P2P port\t{self.platform_p2p_port}',
                     f'Platform HTTP port\t{self.platform_http_port}'])

                if self.platform_node_key_type == InputKeyType.PRIVATE:
                    if self.platform_node_private_key:
                        priv_tenderdash = ed25519_private_key_to_tenderdash(self.platform_node_private_key)
                        priv_hex = ed25519_private_key_to_raw_hex(self.platform_node_private_key)
                        self.summary_info.append(f'Platform Node private key (Tenderdash)\t{priv_tenderdash}')
                        self.summary_info.append(f'Platform Node private key (raw)\t{priv_hex}')
                else:
                    if self.platform_node_id:
                        self.summary_info.append(f'Platform Node Id\t{self.platform_node_id}')

            text = '<table>'
            for l in self.summary_info:
                lbl, val = l.split('\t')
                text += f'<tr><td style="white-space: nowrap"><b>{lbl}:</b> </td><td>{val}</td></tr>'
            text += '</table>'
            self.edtProtxSummary.setText(text)
            self.edtProtxSummary.show()
            self.lblProtxSummary2.show()

            if self.operator_key_type == InputKeyType.PRIVATE:
                operator_message = '<b><span style="color:red">One more thing... <span></b>copy the following ' \
                                   'line to the <code>dash.conf</code> file on your masternode server ' \
                                   '(and restart <i>dashd</i>) or pass it to the masternode operator:'
            else:
                operator_message = '<b><span style="color:red">One more thing... <span></b>copy the following ' \
                                   'line to the <code>dash.conf</code> file on your masternode server, replacing ' \
                                   '"&lt;your-operator-bls-private-key&gt;" with the appropriate value or ask the ' \
                                   'operator for it:'
            self.lblProtxSummary3.setText(operator_message)

            if self.operator_key_type == InputKeyType.PRIVATE:
                operator_privkey = self.operator_privkey
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
        self.collateral_tx = self.edtCollateralTx.text().strip()
        self.collateral_validation_err_msg = ''
        error_count = 0
        try:
            if not self.collateral_tx:
                self.collateral_validation_err_msg = 'Collteral transaction ID is required.'
                self.edtCollateralTx.setFocus()
            else:
                self.collateral_tx_index = int(self.edtCollateralIndex.text())
                if self.collateral_tx_index < 0:
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
            self.ip = self.edtIP.text().strip()
            if self.ip:
                ipaddress.ip_address(self.ip)
        except Exception as e:
            self.edtIP.setFocus()
            self.ip_port_validation_err_msg = 'Invalid masternode IP address: %s.' % str(e)
            self.upd_ip_info(True)
            error_count += 1

        try:
            if self.ip:
                self.tcp_port = int(self.edtPort.text())
            else:
                self.tcp_port = None
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
            self.owner_payout_addr = addr
            if not validate_address(self.owner_payout_addr, self.app_config.dash_network):
                self.payout_address_validation_err_msg = 'Invalid owner payout address.'
        if self.payout_address_validation_err_msg:
            self.edtPayoutAddress.setFocus()
            self.upd_payout_addr_info(True)
            error_count += 1

        self.operator_reward_validation_err_msg = ''
        if self.chbWholeMNReward.isChecked():
            self.operator_reward = 0
        else:
            self.operator_reward = self.edtOperatorReward.value()
            if self.operator_reward > 100 or self.operator_reward < 0:
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
            if self.owner_key_type == InputKeyType.PRIVATE:
                self.owner_privkey = key
                if not validate_wif_privkey(self.owner_privkey, self.app_config.dash_network):
                    self.edtOwnerKey.setFocus()
                    self.owner_key_validation_err_msg = 'Invalid owner private key.'
                else:
                    self.owner_address = wif_privkey_to_address(self.owner_privkey,
                                                                self.app_config.dash_network)
            else:
                self.owner_address = key
                self.owner_privkey = ''
                if not validate_address(self.owner_address, self.app_config.dash_network):
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
            if self.operator_key_type == InputKeyType.PRIVATE:
                try:
                    self.operator_privkey = key

                    try:
                        b = bytes.fromhex(self.operator_privkey)
                        if len(b) != 32:
                            raise Exception('invalid length (' + str(len(b)) + ')')
                    except Exception as e:
                        self.edtOperatorKey.setFocus()
                        self.operator_key_validation_err_msg = 'Invalid operator private key: ' + str(e)

                    new_scheme = self.app_config.feature_new_bls_scheme.get_value()
                    self.operator_pubkey = bls_privkey_to_pubkey(self.operator_privkey, new_scheme)
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    self.operator_key_validation_err_msg = 'Invalid operator private key: ' + str(e)
            else:
                self.operator_pubkey = key
                self.operator_privkey = ''
                try:
                    b = bytes.fromhex(self.operator_pubkey)
                    if len(b) != 48:
                        raise Exception('invalid length (' + str(len(b)) + ')')
                except Exception as e:
                    self.edtOperatorKey.setFocus()
                    self.operator_key_validation_err_msg = 'Invalid operator public key: ' + str(e)
        if self.operator_key_validation_err_msg:
            self.upd_operator_key_info(True)
            error_count += 1

        self.voting_key_validation_err_msg = ''
        key = self.edtVotingKey.text().strip()
        if not key:
            self.voting_key_validation_err_msg = 'Voting key/address is required.'
        else:
            if self.voting_key_type == InputKeyType.PRIVATE:
                self.voting_privkey = key
                if not validate_wif_privkey(self.voting_privkey, self.app_config.dash_network):
                    self.edtVotingKey.setFocus()
                    self.voting_key_validation_err_msg = 'Invalid voting private key.'
                else:
                    self.voting_address = wif_privkey_to_address(self.voting_privkey,
                                                                 self.app_config.dash_network)
            else:
                self.voting_address = key
                self.voting_privkey = ''
                if not validate_address(self.voting_address, self.app_config.dash_network):
                    self.edtVotingKey.setFocus()
                    self.voting_key_validation_err_msg = 'Invalid voting Dash address.'

        if self.voting_key_validation_err_msg:
            self.upd_voting_key_info(True)
            error_count += 1

        if self.masternode_type == MasternodeType.REGULAR:
            self.register_prepare_command_name = 'register_prepare'
        else:
            self.register_prepare_command_name = 'register_prepare_hpmn'

        self.platform_node_id_validation_err_msg = ''
        if self.masternode_type == MasternodeType.HPMN:
            node_key = self.edtPlatformNodeKey.text().strip()
            if self.platform_node_key_type == InputKeyType.PRIVATE:
                if not node_key:
                    self.platform_node_id_validation_err_msg = 'Platform node private key or node id is required.'
                else:
                    if not validate_ed25519_privkey(node_key):
                        self.platform_node_id_validation_err_msg = \
                            'The Platform private key is invalid. It should be an Ed25519 private key.'
                    else:
                        self.platform_node_id = ed25519_private_key_to_platform_node_id(node_key)
                        self.platform_node_private_key = node_key
            else:
                if not node_key:
                    self.platform_node_id_validation_err_msg = 'Platform node id is required.'
                else:
                    if not validate_platform_node_id(node_key):
                        self.platform_node_id_validation_err_msg = 'Platform node id should be a 20-byte hexadecimal ' \
                                                                   'string.'
                    else:
                        self.platform_node_id = node_key

            if self.platform_node_id_validation_err_msg:
                self.upd_platform_node_key_info(True)
                error_count += 1

            self.platform_ports_validation_err_msg = ''
            p2p_port = self.edtPlatformP2PPort.text().strip()
            if not p2p_port:
                self.platform_ports_validation_err_msg = 'Platform P2P port is required.'
            else:
                try:
                    p2p_port = int(p2p_port)
                    if not (1 <= p2p_port <= 65535):
                        raise Exception('Platform P2P port is invalid')
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
                        raise Exception('Platform HTTP port is invalid')
                    self.platform_http_port = http_port
                except Exception:
                    if self.platform_ports_validation_err_msg:
                        self.platform_ports_validation_err_msg += ' '
                    self.platform_ports_validation_err_msg += 'Platform HTTP port must be a valid TCP port [1-65535].'

            if self.platform_ports_validation_err_msg:
                self.upd_platform_ports_info(True)
                error_count += 1

        if error_count > 1:
            raise Exception('Errors were encountered in the input data. You must correct them before you can continue.')
        elif error_count == 1:
            raise Exception(max((self.collateral_validation_err_msg, self.ip_port_validation_err_msg,
                                 self.payout_address_validation_err_msg, self.operator_reward_validation_err_msg,
                                 self.owner_key_validation_err_msg, self.operator_key_validation_err_msg,
                                 self.voting_key_validation_err_msg, self.platform_node_id_validation_err_msg,
                                 self.platform_ports_validation_err_msg)))

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
            WndUtils.error_msg(str(e), True)
            ret = False

        self.btnContinue.setEnabled(True)
        return ret

    def get_collateral_tx_address_thread(self, ctrl: CtrlObject, check_break_scanning_ext: Callable[[], bool]):
        if self.masternode_type == MasternodeType.REGULAR:
            collateral_value_needed = 1e11
        else:
            collateral_value_needed = 4e11

        txes_cnt = 0
        msg = ''
        break_scanning = False
        ctrl.dlg_config(dlg_title="Validating collateral transaction.", show_progress_bar=False)
        ctrl.display_msg('Verifying collateral transaction...')

        def check_break_scanning():
            nonlocal break_scanning
            if self.finishing or break_scanning:
                # stop the scanning process if the dialog finishes or the address/bip32path has been found
                raise BreakFetchTransactionsException()
            if check_break_scanning_ext is not None and check_break_scanning_ext():
                raise BreakFetchTransactionsException()

        def fetch_txes_feedback(tx_cnt: int):
            nonlocal msg, txes_cnt
            txes_cnt += tx_cnt
            ctrl.display_msg(msg + '<br><br>' + 'Number of transactions fetched so far: ' + str(txes_cnt))

        def on_msg_link_activated(link: str):
            nonlocal break_scanning
            if link == 'break':
                break_scanning = True

        try:
            tx = self.dashd_intf.getrawtransaction(self.collateral_tx, 1, skip_cache=True)
        except Exception as e:
            raise Exception('Cannot get the collateral transaction due to the following error: ' + str(e))

        confirmations = tx.get('confirmations', 0)
        if confirmations < MASTERNODE_TX_MINIMUM_CONFIRMATIONS:
            raise Exception(f'The collateral transaction does not yet have '
                            f'the required number of {MASTERNODE_TX_MINIMUM_CONFIRMATIONS} confirmations. '
                            f'You must wait for {MASTERNODE_TX_MINIMUM_CONFIRMATIONS - confirmations} more '
                            f'confirmation(s) before continuing.')

        vouts = tx.get('vout')
        if vouts:
            if self.collateral_tx_index < len(vouts):
                vout = vouts[self.collateral_tx_index]
                spk = vout.get('scriptPubKey')
                if not spk:
                    raise Exception(f'The collateral transaction ({self.collateral_tx}) output '
                                    f'({self.collateral_tx_index}) doesn\'t have value in the scriptPubKey '
                                    f'field.')
                ads = spk.get('addresses')
                if not ads or len(ads) < 0:
                    raise Exception('The collateral transaction output doesn\'t have the Dash address assigned.')
                if vout.get('valueSat') != collateral_value_needed:
                    raise Exception(f'The value of the collateral transaction output is not equal to '
                                    f'{round(collateral_value_needed / 1e8)} Dash, which it should be '
                                    f'for this type of masternode.\n\nSelect another tx output.')

                self.collateral_tx_address = ads[0]
            else:
                raise Exception(f'Transaction {self.collateral_tx} doesn\'t have output with index: '
                                f'{self.collateral_tx_index}')
        else:
            raise Exception('Invalid collateral transaction')

        ctrl.display_msg('Verifying the collateral transaction address on your hardware wallet.')
        if not self.main_dlg.connect_hardware_wallet():
            return False

        if self.collateral_tx_address_path:
            try:
                addr = hw_intf.get_address(self.main_dlg.hw_session, self.collateral_tx_address_path)
            except CancelException:
                return False

            msg = ''
            if addr != self.collateral_tx_address:
                log.warning(
                    f'The address returned by the hardware wallet ({addr}) for the BIP32 path '
                    f'{self.collateral_tx_address_path} differs from the address stored the mn configuration '
                    f'(self.collateral_tx_address). Need to scan wallet for a correct BIP32 path.')

                msg = '<span style="color:red">The BIP32 path of the collateral address from your mn config is ' \
                      'incorrect.<br></span>' \
                      f'Trying to find the BIP32 path of the address {self.collateral_tx_address} in your wallet.' \
                      f'<br>This may take a while (<a href="break">break</a>)...'
                self.collateral_tx_address_path = ''
        else:
            msg = 'Looking for a BIP32 path of the Dash address related to the masternode collateral.<br>' \
                  'This may take a while (<a href="break">break</a>)....'

        if not self.collateral_tx_address_path and not self.finishing:
            lbl = ctrl.get_msg_label_control()
            if lbl:
                def set():
                    lbl.setOpenExternalLinks(False)
                    lbl.setTextInteractionFlags(lbl.textInteractionFlags() & ~Qt.TextSelectableByMouse)
                    lbl.linkActivated.connect(on_msg_link_activated)
                    lbl.repaint()

                WndUtils.call_in_main_thread(set)

            ctrl.display_msg(msg)

            # fetch the transactions that involved the addresses stored in the wallet - during this
            # all the used addresses are revealed
            addr = self.bip44_wallet.scan_wallet_for_address(self.collateral_tx_address, check_break_scanning,
                                                             fetch_txes_feedback)
            if not addr:
                if not break_scanning:
                    WndUtils.error_msg(
                        f'Couldn\'t find a BIP32 path of the collateral address ({self.collateral_tx_address}).')
                return False
            else:
                self.collateral_tx_address_path = addr.bip32_path

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
                self.error_msg('You have to choose one of the two options.')
                return
            self.step_stack.append(self.current_step)

        elif self.current_step == STEP_AUTOMATIC_RPC_NODE:
            cs = STEP_SUMMARY
            # in this case, don't allow starting the automatic process again when the user clicks <Back>

        elif self.current_step == STEP_MANUAL_OWN_NODE:
            # check if the user passed the protx transaction hash
            if not self.manual_signed_message:
                self.error_msg(f'It looks like you have not signed a "protx {self.register_prepare_command_name}" '
                               f'result.')
                return

            self.dmn_reg_tx_hash = self.edtManualTxHash.text().strip()
            if not self.dmn_reg_tx_hash:
                self.edtManualTxHash.setFocus()
                self.error_msg('Invalid transaction hash.')
                return
            try:
                bytes.fromhex(self.dmn_reg_tx_hash)
            except Exception:
                log.warning('Invalid transaction hash.')
                self.edtManualTxHash.setFocus()
                self.error_msg('Invalid transaction hash.')
                return
            cs = STEP_SUMMARY
        else:
            self.error_msg('Invalid step')
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
                self.lblProtxSummary1.setText('Congratulations! The transaction for your DIP-3 '
                                              'masternode has been submitted and is currently awaiting confirmations.')
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
        try:
            self.next_step()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnBack_clicked(self, active):
        try:
            self.previous_step()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_rbDMTDashNodeType_toggled(self, active):
        try:
            if active:
                self.upd_node_type_info()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_rbOwnDashNodeType_toggled(self, active):
        try:
            if active:
                self.upd_node_type_info()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def sign_protx_message_with_hw(self, msg_to_sign) -> str:
        sig = WndUtils.call_in_main_thread(
            hw_intf.hw_sign_message, self.main_dlg.hw_session, self.main_dlg.app_rt_data.hw_coin_name,
            self.collateral_tx_address_path, msg_to_sign,
            'Click the confirmation button on your hardware wallet to sign the ProTx payload message.')

        if sig:
            if sig.address != self.collateral_tx_address:
                log.error(f'Protx payload signature address mismatch. Is: {sig.address}, should be: '
                          f'{self.collateral_tx_address}.')
                raise Exception(f'Protx payload signature address mismatch. Is: {sig.address}, should be: '
                                f'{self.collateral_tx_address}.')
            else:
                sig_bin = base64.b64encode(sig.signature)
                payload_sig_str = sig_bin.decode('ascii')
                return payload_sig_str
        else:
            raise Exception('Signing of protx transaction failed!')

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
            green_color = get_widget_font_color_green(self)
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
                        bal_list.sort(key=lambda x: x['amount'])
                        if not bal_list:
                            raise Exception("No address can be found in the node's wallet with sufficient funds to "
                                            "cover the transaction fees.")
                        funding_address = bal_list[0]['address']
                    except JSONRPCException as e:
                        log.info(
                            "Couldn't list the node address balances. We assume you are using a public RPC node and "
                            "the funding address for the transaction fees will be estimated during the "
                            f"`{self.register_prepare_command_name}` call")

                set_text(self.lblProtxTransaction1, '<b>1. Preparing a ProRegTx transaction on a remote node...</b>')

                if self.owner_key_type == InputKeyType.PRIVATE:
                    owner_address = wif_privkey_to_address(self.owner_privkey, self.app_config.dash_network)
                else:
                    owner_address = self.owner_address

                params = [self.register_prepare_command_name, self.collateral_tx, self.collateral_tx_index,
                          self.ip + ':' + str(self.tcp_port) if self.ip else '0', owner_address,
                          self.operator_pubkey, self.voting_address,
                          str(round(self.operator_reward, 2)),
                          self.owner_payout_addr]

                if self.masternode_type == MasternodeType.HPMN:
                    params.extend([self.platform_node_id, str(self.platform_p2p_port), str(self.platform_http_port)])

                if funding_address:
                    params.append(funding_address)

                call_ret = self.dashd_intf.rpc_call(True, False, 'protx', *tuple(params))

                call_ret_str = json.dumps(call_ret, default=EncodeDecimal)
                msg_to_sign = call_ret.get('signMessage', '')
                protx_tx = call_ret.get('tx')

                log.debug(f'{self.register_prepare_command_name} returned: ' + call_ret_str)
                set_text(self.lblProtxTransaction1,
                         '<b>1. Preparing a ProRegTx transaction on a remote node.</b> <span style="color:green">'
                         'Success.</span>')
            except Exception as e:
                set_text(
                    self.lblProtxTransaction1,
                    '<b>1. Preparing a ProRegTx transaction on a remote node.</b> <span style="color:red">Failed '
                    f'with the following error: {str(e)}</span>')
                log.exception(str(e))
                return

            set_text(self.lblProtxTransaction2, '<b>Message to be signed:</b><br><code>' + msg_to_sign + '</code>')

            # signing message:
            set_text(self.lblProtxTransaction3, '<b>2. Signing message with hardware wallet...</b>')
            try:
                payload_sig_str = self.sign_protx_message_with_hw(msg_to_sign)

                set_text(self.lblProtxTransaction3, '<b>2. Signing message with hardware wallet.</b> '
                                                    f'<span style="color:{green_color}">Success.</span>')
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
            set_text(self.lblProtxTransaction4,
                     '<b>3. Submitting the signed protx transaction to the remote node...</b>')
            try:
                self.dmn_reg_tx_hash = self.dashd_intf.rpc_call(True, False, 'protx', 'register_submit', protx_tx,
                                                                payload_sig_str)

                log.debug('protx register_submit returned: ' + str(self.dmn_reg_tx_hash))
                set_text(self.lblProtxTransaction4,
                         '<b>3. Submitting the signed protx transaction to the remote node.</b> <span style="'
                         f'color:{green_color}">Success.</span>')
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
            self.error_msg(f'You need to enter a result of the "protx {self.register_prepare_command_name}" command.')
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
                self.error_msg(str(e))
                return

        except Exception as e:
            self.error_msg(f'Invalid "protx {self.register_prepare_command_name}" result. Note that the text must '
                           'be copied along with curly braces.')
            return

    def start_manual_process(self):
        self.edtManualFundingAddress.setFocus()
        self.update_manual_protx_prepare_command()

    def update_manual_protx_prepare_command(self):
        addr = self.edtManualFundingAddress.text().strip()
        if addr:
            valid = validate_address(addr, self.app_config.dash_network)
            if valid:
                if self.owner_key_type == InputKeyType.PRIVATE:
                    owner_key = wif_privkey_to_address(self.owner_privkey, self.app_config.dash_network)
                else:
                    owner_key = self.owner_address

                cmd = f'protx {self.register_prepare_command_name} "{self.collateral_tx}" ' \
                      f'"{self.collateral_tx_index}" ' \
                      f'"{self.ip + ":" + str(self.tcp_port) if self.ip else "0"}" ' \
                      f'"{owner_key}" "{self.operator_pubkey}" "{self.voting_address}" ' \
                      f'"{str(round(self.operator_reward, 2))}" "{self.owner_payout_addr}" '

                if self.masternode_type == MasternodeType.HPMN:
                    cmd += f'"{self.platform_node_id}" "{str(self.platform_p2p_port)}" "{str(self.platform_http_port)}"'

                cmd += f' "{addr}"'
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
                    'Congratulations! The transaction for your DIP-3 masternode has been '
                    f'confirmed in block {h}. ')
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
