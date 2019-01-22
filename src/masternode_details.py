import os
import sys
from enum import Enum
from functools import partial

import bitcoin
from PyQt5 import QtCore
from PyQt5.QtCore import QSize, pyqtSlot, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QWidget, QLineEdit, QMessageBox, QAction, QApplication, QActionGroup

import dash_utils
from app_config import MasternodeConfig, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, DMN_ROLE_VOTING, InputKeyType
from bip44_wallet import Bip44Wallet, BreakFetchTransactionsException
from find_coll_tx_dlg import ListCollateralTxsDlg
from thread_fun_dlg import CtrlObject
from ui import ui_masternode_details
from wnd_utils import WndUtils


class WdgMasternodeDetails(QWidget, ui_masternode_details.Ui_WdgMasternodeDetails):
    name_modified = QtCore.pyqtSignal(str)
    data_changed = QtCore.pyqtSignal(object)

    def __init__(self, main_dlg, app_config, dashd_intf):
        QWidget.__init__(self, main_dlg)
        ui_masternode_details.Ui_WdgMasternodeDetails.__init__(self)
        self.main_dlg = main_dlg
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.masternode: MasternodeConfig = None
        self.updating_ui = False
        self.edit_mode = False
        self.setupUi()

    def setupUi(self):
        ui_masternode_details.Ui_WdgMasternodeDetails.setupUi(self, self)
        self.main_dlg.setIcon(self.btnShowMnPrivateKey, 'eye@16px.png')
        self.main_dlg.setIcon(self.btnShowOwnerPrivateKey, 'eye@16px.png')
        self.main_dlg.setIcon(self.btnShowOperatorPrivateKey, 'eye@16px.png')
        self.main_dlg.setIcon(self.btnShowVotingPrivateKey, 'eye@16px.png')
        self.main_dlg.setIcon(self.btnCopyMnKey, 'content-copy@16px.png')
        self.main_dlg.setIcon(self.btnCopyOwnerKey, 'content-copy@16px.png')
        self.main_dlg.setIcon(self.btnCopyOperatorKey, 'content-copy@16px.png')
        self.main_dlg.setIcon(self.btnCopyVotingKey, 'content-copy@16px.png')

        self.ag_mn_key = QActionGroup(self)
        self.act_view_as_mn_private_key = QAction('View as private key', self)
        self.act_view_as_mn_private_key.triggered.connect(self.on_act_view_as_mn_private_key_triggered)
        self.act_view_as_mn_public_address = QAction('View as Dash address', self)
        self.act_view_as_mn_public_address.triggered.connect(self.on_act_view_as_mn_public_address_triggered)
        self.act_view_as_mn_public_key = QAction('View as public key', self)
        self.act_view_as_mn_public_key.triggered.connect(self.on_act_view_as_mn_public_key_triggered)
        self.act_view_as_mn_public_key_hash = QAction('View as public key hash', self)
        self.act_view_as_mn_public_key_hash.triggered.connect(self.on_act_view_as_mn_public_key_hash_triggered)
        self.act_view_as_mn_private_key.setCheckable(True)
        self.act_view_as_mn_public_address.setCheckable(True)
        self.act_view_as_mn_public_key.setCheckable(True)
        self.act_view_as_mn_public_key_hash.setCheckable(True)
        self.act_view_as_mn_private_key.setActionGroup(self.ag_mn_key)
        self.act_view_as_mn_public_address.setActionGroup(self.ag_mn_key)
        self.act_view_as_mn_public_key.setActionGroup(self.ag_mn_key)
        self.act_view_as_mn_public_key_hash.setActionGroup(self.ag_mn_key)

        self.btnCopyMnKey.addActions((self.act_view_as_mn_private_key, self.act_view_as_mn_public_address,
                                            self.act_view_as_mn_public_key, self.act_view_as_mn_public_key_hash))
        self.btnShowMnPrivateKey.addActions((self.act_view_as_mn_private_key, self.act_view_as_mn_public_address,
                                            self.act_view_as_mn_public_key, self.act_view_as_mn_public_key_hash))

        self.act_copy_as_owner_private_key = QAction('Copy as private key', self)
        self.act_copy_as_owner_private_key.triggered.connect(self.on_act_copy_as_owner_private_key_triggered)
        self.act_copy_as_owner_public_address = QAction('Copy as Dash address', self)
        self.act_copy_as_owner_public_address.triggered.connect(self.on_act_copy_as_owner_public_address_triggered)
        self.act_copy_as_owner_public_key = QAction('Copy as public key', self)
        self.act_copy_as_owner_public_key.triggered.connect(self.on_act_copy_as_owner_public_key_triggered)
        self.act_copy_as_owner_public_key_hash = QAction('Copy as public key hash', self)
        self.act_copy_as_owner_public_key_hash.triggered.connect(self.on_act_copy_as_owner_public_key_hash_triggered)
        self.btnCopyOwnerKey.addActions((self.act_copy_as_owner_private_key, self.act_copy_as_owner_public_address,
                                            self.act_copy_as_owner_public_key, self.act_copy_as_owner_public_key_hash))

        self.act_copy_as_voting_private_key = QAction('Copy as private key', self)
        self.act_copy_as_voting_private_key.triggered.connect(self.on_act_copy_as_voting_private_key_triggered)
        self.act_copy_as_voting_public_address = QAction('Copy as Dash address', self)
        self.act_copy_as_voting_public_address.triggered.connect(self.on_act_copy_as_voting_public_address_triggered)
        self.act_copy_as_voting_public_key = QAction('Copy as public key', self)
        self.act_copy_as_voting_public_key.triggered.connect(self.on_act_copy_as_voting_public_key_triggered)
        self.act_copy_as_voting_public_key_hash = QAction('Copy as public key hash', self)
        self.act_copy_as_voting_public_key_hash.triggered.connect(self.on_act_copy_as_voting_public_key_hash_triggered)
        self.btnCopyVotingKey.addActions((self.act_copy_as_voting_private_key, self.act_copy_as_voting_public_address,
                                          self.act_copy_as_voting_public_key, self.act_copy_as_voting_public_key_hash))

        self.act_copy_as_operator_private_key = QAction('Copy as private key', self)
        self.act_copy_as_operator_private_key.triggered.connect(self.on_act_copy_as_operator_private_key_triggered)
        self.act_copy_as_operator_public_key = QAction('Copy as public key', self)
        self.act_copy_as_operator_public_key.triggered.connect(self.on_act_copy_as_operator_public_key_triggered)
        self.btnCopyOperatorKey.addActions((self.act_copy_as_operator_private_key,
                                          self.act_copy_as_operator_public_key))

        self.update_dynamic_labels()
        self.update_ui_controls_state()

    def update_ui_controls_state(self):
        """Update visibility and enabled/disabled state of the UI controls.
        """
        if self.masternode:
            is_deterministic = self.masternode.is_deterministic
        else:
            is_deterministic = False

        if self.masternode:
            self.lblTitle.setVisible(True)
            self.lblAction.setVisible(self.edit_mode is True)
            if is_deterministic:
                lbl = '<span>Deterministic masternode</span>'
                lbl_action = '<a href="change-to-non-dmn">Alter configuration to non-deterministic</a>'
                color = '#2eb82e'
            else:
                lbl = '<span>Non-deterministic masternode</span>'
                lbl_action = '<a href="change-to-dmn">Alter configuration to deterministic</a>'
                color = 'navy'
            self.lblTitle.setText(lbl)
            self.lblTitle.setStyleSheet(
                f'QLabel{{background-color:{color};color:white;padding:3px 5px 3px 5px; border-radius:3px}}')
            self.lblAction.setText(lbl_action)
        else:
            self.lblTitle.setVisible(False)
            self.lblAction.setVisible(False)

        self.lblDMNTxHash.setVisible(self.masternode is not None and is_deterministic)
        self.edtDMNTxHash.setVisible(self.masternode is not None and is_deterministic)
        self.btnFindDMNTxHash.setVisible(self.masternode is not None and is_deterministic and self.edit_mode)
        self.lblOwnerKey.setVisible(self.masternode is not None and is_deterministic and
                                           self.masternode.dmn_user_role == DMN_ROLE_OWNER)
        self.edtOwnerKey.setVisible(self.masternode is not None and is_deterministic and
                                           self.masternode.dmn_user_role == DMN_ROLE_OWNER)
        self.btnShowOwnerPrivateKey.setVisible(self.masternode is not None and is_deterministic and
                                                   self.masternode.dmn_user_role == DMN_ROLE_OWNER)
        self.btnCopyOwnerKey.setVisible(self.masternode is not None and is_deterministic and
                                                   self.masternode.dmn_user_role == DMN_ROLE_OWNER)
        self.lblOperatorKey.setVisible(self.masternode is not None and is_deterministic and
                                              self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.edtOperatorKey.setVisible(self.masternode is not None and is_deterministic and
                                              self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.btnShowOperatorPrivateKey.setVisible(self.masternode is not None and is_deterministic and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.btnCopyOperatorKey.setVisible(self.masternode is not None and is_deterministic and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.lblVotingKey.setVisible(self.masternode is not None and is_deterministic and
                                            self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)
        self.edtVotingKey.setVisible(self.masternode is not None and is_deterministic and
                                            self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)
        self.btnShowVotingPrivateKey.setVisible(self.masternode is not None and is_deterministic and
                                                    self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)
        self.btnCopyVotingKey.setVisible(self.masternode is not None and is_deterministic and
                                                    self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)

        self.act_copy_as_owner_private_key.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE)
        self.act_copy_as_owner_public_key.setVisible(self.masternode is not None and
                                                     self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE)
        self.act_copy_as_operator_private_key.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE)
        self.act_copy_as_voting_private_key.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE)
        self.act_copy_as_voting_public_key.setVisible(self.masternode is not None and
                                                     self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE)

        self.btnGenerateMnPrivateKey.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.dmn_user_role != DMN_ROLE_VOTING)

        self.btnGenerateOwnerPrivateKey.setVisible(
            self.masternode is not None and is_deterministic and self.edit_mode and
            self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE and
            self.masternode.dmn_user_role == DMN_ROLE_OWNER)

        self.btnGenerateOperatorPrivateKey.setVisible(
            self.masternode is not None and is_deterministic and self.edit_mode and
            self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE and
            self.masternode.dmn_user_role != DMN_ROLE_VOTING)

        self.btnGenerateVotingPrivateKey.setVisible(
            self.masternode is not None and is_deterministic and self.edit_mode and
            self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE and
            self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)

        self.lblUserRole.setVisible(self.masternode is not None and is_deterministic)
        self.rbRoleOwner.setVisible(self.masternode is not None and is_deterministic)
        self.rbRoleOperator.setVisible(self.masternode is not None and is_deterministic)
        self.rbRoleVoting.setVisible(self.masternode is not None and is_deterministic)

        self.lblMasternodePrivateKey.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.edtMasternodePrivateKey.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.btnShowMnPrivateKey.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.btnCopyMnKey.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)

        # self.btnFindCollateral.setVisible(self.masternode is not None)
        self.lblIP.setVisible(self.masternode is not None)
        self.edtIP.setVisible(self.masternode is not None)
        self.lblPort.setVisible(self.masternode is not None)
        self.edtPort.setVisible(self.masternode is not None)
        self.lblProtocolVersion.setVisible(self.masternode is not None and not is_deterministic)
        self.edtProtocolVersion.setVisible(self.masternode is not None and not is_deterministic)
        self.lblName.setVisible(self.masternode is not None)
        self.edtName.setVisible(self.masternode is not None)
        self.lblCollateral.setVisible(self.masternode is not None)
        self.edtCollateralAddress.setVisible(self.masternode is not None)
        self.lblCollateralPath.setVisible(self.masternode is not None)
        self.edtCollateralPath.setVisible(self.masternode is not None)
        self.lblCollateralTxHash.setVisible(self.masternode is not None)
        self.edtCollateralTxHash.setVisible(self.masternode is not None)
        self.lblCollateralTxIndex.setVisible(self.masternode is not None)
        self.edtCollateralTxIndex.setVisible(self.masternode is not None)

        self.rbRoleVoting.setEnabled(self.edit_mode)
        self.rbRoleOperator.setEnabled(self.edit_mode)
        self.rbRoleOwner.setEnabled(self.edit_mode)
        self.edtName.setReadOnly(self.edit_mode is False)
        self.edtIP.setReadOnly(self.edit_mode is False)
        self.edtPort.setReadOnly(self.edit_mode is False)
        self.edtProtocolVersion.setReadOnly(self.edit_mode is False)
        self.edtCollateralAddress.setReadOnly(self.edit_mode is False)
        self.edtCollateralPath.setReadOnly(self.edit_mode is False)
        self.edtCollateralTxHash.setReadOnly(self.edit_mode is False)
        self.edtCollateralTxIndex.setReadOnly(self.edit_mode is False)
        self.edtDMNTxHash.setReadOnly(self.edit_mode is False)
        self.edtMasternodePrivateKey.setReadOnly(self.edit_mode is False)
        self.edtOwnerKey.setReadOnly(self.edit_mode is False)
        self.edtOperatorKey.setReadOnly(self.edit_mode is False)
        self.edtVotingKey.setReadOnly(self.edit_mode is False)
        self.btnGenerateMnPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateOwnerPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateOperatorPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateVotingPrivateKey.setEnabled(self.edit_mode is True)
        self.btnLocateCollateral.setEnabled(self.edit_mode)
        col_btn_visible = self.masternode is not None and (not self.masternode.collateralTx or
                                               not self.masternode.collateralAddress or
                                               not self.masternode.collateralBip32Path)
        self.btnLocateCollateral.setVisible(col_btn_visible and self.edit_mode)
        self.btnLocateCollateral.repaint()
        self.update_dynamic_labels()

    def update_dynamic_labels(self):
        if self.masternode:
            if self.edit_mode:
                pref = '<a href="key">'
                suf = '</a>'
            else:
                pref = ''
                suf = ''

            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                lbl = f'Owner {pref}private key{suf}'
                tt = 'Change input to public address' if self.edit_mode else ''
            else:
                lbl = f'Owner {pref}public address{suf}'
                tt = 'Change input to private key' if self.edit_mode else ''
            self.lblOwnerKey.setText(lbl)
            self.lblOwnerKey.setToolTip(tt)

            if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                lbl = f'Operator {pref}private key{suf}'
                tt = 'Change input to public key' if self.edit_mode else ''
            else:
                lbl = f'Operator {pref}public key{suf}'
                tt = 'Change input to private key' if self.edit_mode else ''
            self.lblOperatorKey.setText(lbl)
            self.lblOperatorKey.setToolTip(tt)

            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                lbl = f'Voting {pref}private key{suf}'
                tt = 'Change input to public address' if self.edit_mode else ''
            else:
                lbl = f'Voting {pref}public address{suf}'
                tt = 'Change input to private key' if self.edit_mode else ''
            self.lblVotingKey.setText(lbl)
            self.lblVotingKey.setToolTip(tt)

    def masternode_data_to_ui(self):
        if self.masternode:
            self.rbRoleOwner.setChecked(self.masternode.dmn_user_role == DMN_ROLE_OWNER)
            self.rbRoleOperator.setChecked(self.masternode.dmn_user_role == DMN_ROLE_OPERATOR)
            self.rbRoleVoting.setChecked(self.masternode.dmn_user_role == DMN_ROLE_VOTING)
            self.edtName.setText(self.masternode.name)
            self.edtIP.setText(self.masternode.ip)
            self.edtProtocolVersion.setText(self.masternode.protocol_version if
                                            self.masternode.use_default_protocol_version is False else '')
            self.edtPort.setText(self.masternode.port)
            self.edtCollateralAddress.setText(self.masternode.collateralAddress)
            self.edtCollateralPath.setText(self.masternode.collateralBip32Path)
            self.edtCollateralTxHash.setText(self.masternode.collateralTx)
            self.edtCollateralTxIndex.setText(self.masternode.collateralTxIndex)
            self.edtDMNTxHash.setText(self.masternode.dmn_tx_hash)
            self.edtMasternodePrivateKey.setText(self.get_masternode_key_string())
            if self.edit_mode:

                if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                    self.edtOwnerKey.setText(self.masternode.dmn_owner_private_key)
                else:
                    self.edtOwnerKey.setText(self.masternode.dmn_owner_address)

                if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                    self.edtOperatorKey.setText(self.masternode.dmn_operator_private_key)
                else:
                    self.edtOperatorKey.setText(self.masternode.dmn_operator_public_key)

                if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                    self.edtVotingKey.setText(self.masternode.dmn_voting_private_key)
                else:
                    self.edtVotingKey.setText(self.masternode.dmn_voting_address)

            self.edtMasternodePrivateKey.setEchoMode(QLineEdit.Password if self.btnShowMnPrivateKey.isChecked()
                                                     else QLineEdit.Normal)
            self.edtOwnerKey.setEchoMode(QLineEdit.Password if self.btnShowOwnerPrivateKey.isChecked()
                                         else QLineEdit.Normal)
            self.edtOperatorKey.setEchoMode(QLineEdit.Password if self.btnShowOperatorPrivateKey.isChecked()
                                            else QLineEdit.Normal)
            self.edtVotingKey.setEchoMode(QLineEdit.Password if self.btnShowVotingPrivateKey.isChecked()
                                          else QLineEdit.Normal)

            self.updating_ui = False
        else:
            for e in self.findChildren(QLineEdit):
                e.setText('')
        self.update_ui_controls_state()

    def get_masternode_key_string(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.act_view_as_mn_private_key.isChecked():
                    ret = self.masternode.privateKey
                elif self.act_view_as_mn_public_address.isChecked():
                    ret = dash_utils.wif_privkey_to_address(self.masternode.privateKey, self.app_config.dash_network)
                elif self.act_view_as_mn_public_key.isChecked():
                    ret = dash_utils.wif_privkey_to_pubkey(self.masternode.privateKey)
                elif self.act_view_as_mn_public_key_hash.isChecked():
                    pubkey = dash_utils.wif_privkey_to_pubkey(self.masternode.privateKey)
                    pubkey_bin = bytes.fromhex(pubkey)
                    pub_hash = bitcoin.bin_hash160(pubkey_bin)
                    ret = pub_hash.hex()
            else:
                ret = self.masternode.privateKey
        return ret

    @pyqtSlot(str)
    def on_lblOwnerKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_owner_key_type = InputKeyType.PUBLIC
                self.edtOwnerKey.setText(self.masternode.dmn_owner_address)
            else:
                self.masternode.dmn_owner_key_type = InputKeyType.PRIVATE
                self.edtOwnerKey.setText(self.masternode.dmn_owner_private_key)
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_operator_key_type = InputKeyType.PUBLIC
                self.edtOperatorKey.setText(self.masternode.dmn_operator_public_key)
            else:
                self.masternode.dmn_operator_key_type = InputKeyType.PRIVATE
                self.edtOperatorKey.setText(self.masternode.dmn_operator_private_key)
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_voting_key_type = InputKeyType.PUBLIC
                self.edtVotingKey.setText(self.masternode.dmn_voting_address)
            else:
                self.masternode.dmn_voting_key_type = InputKeyType.PRIVATE
                self.edtVotingKey.setText(self.masternode.dmn_voting_private_key)
            self.update_ui_controls_state()

    def get_max_left_label_width(self):
        return max(self.lblName.width(), self.lblIP.width(), self.lblCollateral.width(),
                   self.lblCollateralTxHash.width(), self.lblDMNTxHash.width(), self.lblMasternodePrivateKey.width(),
                   self.lblOwnerKey.width(), self.lblOperatorKey.width(),
                   self.lblVotingKey.width())

    def set_left_label_width(self, width):
        self.lblName.setFixedWidth(width)
        self.lblIP.setFixedWidth(width)
        self.lblCollateral.setFixedWidth(width)
        self.lblCollateralTxHash.setFixedWidth(width)
        self.lblDMNTxHash.setFixedWidth(width)
        self.lblMasternodePrivateKey.setFixedWidth(width)
        self.lblOwnerKey.setFixedWidth(width)
        self.lblOperatorKey.setFixedWidth(width)
        self.lblVotingKey.setFixedWidth(width)

    def set_masternode(self, masternode: MasternodeConfig):
        self.updating_ui = True
        self.masternode = masternode
        self.masternode_data_to_ui()

    def set_edit_mode(self, enabled: bool):
        if self.edit_mode != enabled:
            self.edit_mode = enabled
            if not self.edit_mode:
                self.act_view_as_mn_private_key.setChecked(True)

            if self.btnShowMnPrivateKey.isChecked() != enabled:
                self.btnShowMnPrivateKey.setChecked(enabled)

            if self.btnShowOwnerPrivateKey.isChecked() != enabled:
                self.btnShowOwnerPrivateKey.setChecked(enabled)

            if self.btnShowOperatorPrivateKey.isChecked() != enabled:
                self.btnShowOperatorPrivateKey.setChecked(enabled)

            if self.btnShowVotingPrivateKey.isChecked() != enabled:
                self.btnShowVotingPrivateKey.setChecked(enabled)

            self.update_ui_controls_state()

    def set_modified(self):
        if self.masternode and not self.updating_ui:
            self.masternode.set_modified()
            self.data_changed.emit(self.masternode)

    @pyqtSlot(str)
    def on_lblAction_linkActivated(self, str):
        if self.masternode:
            determ = None
            if str == 'change-to-dmn' and self.masternode.is_deterministic is False:
                determ = True
            elif str == 'change-to-non-dmn' and self.masternode.is_deterministic:
                determ = False

            if determ is not None:
                self.set_deterministic(determ)

    def set_deterministic(self, deterministic: bool):
        self.masternode.is_deterministic = deterministic
        self.update_ui_controls_state()
        self.set_modified()

    @pyqtSlot(bool)
    def on_rbRoleOwner_toggled(self, checked):
        if not self.updating_ui and checked:
            self.masternode.dmn_user_role = DMN_ROLE_OWNER
            self.update_ui_controls_state()
            self.set_modified()

    @pyqtSlot(bool)
    def on_rbRoleOperator_toggled(self, checked):
        if not self.updating_ui and checked:
            self.masternode.dmn_user_role = DMN_ROLE_OPERATOR
            self.update_ui_controls_state()
            self.set_modified()

    @pyqtSlot(bool)
    def on_rbRoleVoting_toggled(self, checked):
        if not self.updating_ui and checked:
            self.masternode.dmn_user_role = DMN_ROLE_VOTING
            self.update_ui_controls_state()
            self.set_modified()

    @pyqtSlot(str)
    def on_edtName_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.name = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtIP_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.ip = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtPort_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.port = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtProtocolVersion_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.protocol_version = text.strip()
            if not self.masternode.protocol_version:
                self.masternode.use_default_protocol_version = True
            else:
                self.masternode.use_default_protocol_version = False
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtCollateralAddress_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateralAddress))
            self.set_modified()
            self.masternode.collateralAddress = text.strip()
            self.name_modified.emit(text)
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralPath_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateralBip32Path))
            self.set_modified()
            self.masternode.collateralBip32Path = text.strip()
            self.name_modified.emit(text)
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralTxHash_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateralTx))
            self.set_modified()
            self.masternode.collateralTx = text.strip()
            self.name_modified.emit(text)
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralTxIndex_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.collateralTxIndex = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtDMNTxHash_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.dmn_tx_hash = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(bool)
    def on_btnFindDMNTxHash_clicked(self, checked):
        if self.masternode and not self.updating_ui:
            found_protx = None
            if not ((self.masternode.ip and self.masternode.port) or
                    (self.masternode.collateralTx and self.masternode.collateralTxIndex)):
                WndUtils.errorMsg('To be able to locate the deterministic masternode transaction you need to '
                                  'provide the masternode ip + port or collateral tx + tx index.')
                return

            try:
                txes = self.dashd_intf.protx('list', 'registered', True)
                for protx in txes:
                    state = protx.get('state')
                    if state:
                        if (state.get('addr') == self.masternode.ip + ':' + self.masternode.port) or \
                           (protx.get('collateralHash') == self.masternode.collateralTx and
                            str(protx.get('collateralIndex', '')) == self.masternode.collateralTxIndex):
                            found_protx = protx
                            break
            except Exception as e:
                pass

            if found_protx:
                if self.masternode.dmn_tx_hash == protx.get('proTxHash'):
                    WndUtils.infoMsg('You have te correct DMN TX hash in the masternode configuration.')
                else:
                    self.edtDMNTxHash.setText(protx.get('proTxHash'))
                    self.masternode.dmn_tx_hash = protx.get('proTxHash')
                    self.set_modified()
            else:
                WndUtils.warnMsg('Couldn\'t find this masternode in the list of registered deterministic masternodes.')
            self.set_modified()


    @pyqtSlot(str)
    def on_edtMasternodePrivateKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.privateKey = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtOwnerKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.dmn_owner_private_key = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtOperatorKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.dmn_operator_private_key = text.strip()
            self.name_modified.emit(text)

    @pyqtSlot(str)
    def on_edtVotingKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.dmn_voting_private_key = text.strip()
            self.name_modified.emit(text)

    def generate_priv_key(self, pk_type:str, edit_control: QLineEdit, compressed: bool):
        if edit_control.text():
            if WndUtils.queryDlg(
                    f'This will overwrite the current {pk_type} private key value. Do you really want to proceed?',
                     buttons=QMessageBox.Yes | QMessageBox.Cancel,
                     default_button=QMessageBox.Yes, icon=QMessageBox.Warning) != QMessageBox.Yes:
                return None

        if pk_type == 'operator':
            pk = dash_utils.generate_bls_privkey()
        else:
            pk = dash_utils.generate_wif_privkey(self.app_config.dash_network, compressed=compressed)
        edit_control.setText(pk)
        return pk

    @pyqtSlot(bool)
    def on_btnGenerateMnPrivateKey_clicked(self, checked):
        if self.masternode:
            pk = self.generate_priv_key('masternode', self.edtMasternodePrivateKey, True)
            if pk:
                self.masternode.privateKey = pk
                self.btnShowMnPrivateKey.setChecked(True)
                self.set_modified()

    @pyqtSlot(bool)
    def on_btnGenerateOwnerPrivateKey_clicked(self, checked):
        if self.masternode:
            pk = self.generate_priv_key('owner', self.edtOwnerKey, True)
            if pk:
                self.masternode.dmn_owner_private_key = pk
                self.btnShowOwnerPrivateKey.setChecked(True)
                self.set_modified()

    @pyqtSlot(bool)
    def on_btnGenerateOperatorPrivateKey_clicked(self, checked):
        if self.masternode:

            pk = self.generate_priv_key('operator', self.edtOperatorKey, True)
            if pk:
                self.masternode.dmn_operator_private_key = pk
                self.btnShowOperatorPrivateKey.setChecked(True)
                self.set_modified()

    @pyqtSlot(bool)
    def on_btnGenerateVotingPrivateKey_clicked(self, checked):
        if self.masternode:
            pk = self.generate_priv_key('voting', self.edtVotingKey, True)
            if pk:
                self.masternode.dmn_voting_private_key = pk
                self.btnShowVotingPrivateKey.setChecked(True)
                self.set_modified()

    @pyqtSlot(bool)
    def on_btnShowMnPrivateKey_toggled(self, checked):
        self.edtMasternodePrivateKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    @pyqtSlot(bool)
    def on_btnShowOwnerPrivateKey_toggled(self, checked):
        self.edtOwnerKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    @pyqtSlot(bool)
    def on_btnShowOperatorPrivateKey_toggled(self, checked):
        self.edtOperatorKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    @pyqtSlot(bool)
    def on_btnShowVotingPrivateKey_toggled(self, checked):
        self.edtVotingKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    @pyqtSlot(bool)
    def on_btnLocateCollateral_clicked(self, checked):
        if not self.main_dlg.connect_hardware_wallet():
            return

        def apply_utxo(utxo):
            self.masternode.collateralAddress = utxo.address
            self.edtCollateralAddress.setText(utxo.address)
            self.masternode.collateralBip32Path = utxo.bip32_path
            self.edtCollateralPath.setText(utxo.bip32_path)
            self.masternode.collateralTx = utxo.txid
            self.edtCollateralTxHash.setText(utxo.txid)
            self.masternode.collateralTxIndex = str(utxo.output_index)
            self.edtCollateralTxIndex.setText(str(utxo.output_index))
            self.update_ui_controls_state()
            self.set_modified()

        bip44_wallet = Bip44Wallet(self.app_config.hw_coin_name, self.main_dlg.hw_session,
                                   self.app_config.db_intf, self.dashd_intf, self.app_config.dash_network)

        utxos = WndUtils.run_thread_dialog(self.get_collateral_tx_address_thread, (bip44_wallet,), True)
        if utxos:
            if len(utxos) == 1 and not self.masternode.collateralAddress and not self.masternode.collateralTx:
                used = False
                for mn in self.app_config.masternodes:
                    if utxos[0].address == mn.collateralAddress or mn.collateralTx + '-' + str(mn.collateralTxIndex) == \
                       utxos[0].txid + '-' + str(utxos[0].output_index):
                        used = True
                        break
                if not used:
                    apply_utxo(utxos[0])
                    return

            dlg = ListCollateralTxsDlg(self, self.masternode, self.app_config, False, utxos)
            if dlg.exec_():
                utxo = dlg.get_selected_utxo()
                if utxo:
                    apply_utxo(utxo)
        else:
            if utxos is not None:
                WndUtils.warnMsg('Couldn\'t find any 1000 Dash UTXO in your wallet.')

    def get_collateral_tx_address_thread(self, ctrl: CtrlObject, bip44_wallet: Bip44Wallet):
        utxos = []
        break_scanning = False
        txes_cnt = 0
        msg = 'Scanning wallet transactions for 1000 Dash UTXOs.<br>' \
              'This may take a while (<a href="break">break</a>)....'
        ctrl.dlg_config_fun(dlg_title="Scanning wallet", show_progress_bar=False)
        ctrl.display_msg_fun(msg)

        def check_break_scanning():
            nonlocal break_scanning
            if break_scanning:
                # stop the scanning process if the dialog finishes or the address/bip32path has been found
                raise BreakFetchTransactionsException()

        def fetch_txes_feeback(tx_cnt: int):
            nonlocal msg, txes_cnt
            txes_cnt += tx_cnt
            ctrl.display_msg_fun(msg + '<br><br>' + 'Number of transactions fetched so far: ' + str(txes_cnt))

        def on_msg_link_activated(link: str):
            nonlocal break_scanning
            if link == 'break':
                break_scanning = True

        lbl = ctrl.get_msg_label_control()
        if lbl:
            def set():
                lbl.setOpenExternalLinks(False)
                lbl.setTextInteractionFlags(lbl.textInteractionFlags() & ~Qt.TextSelectableByMouse)
                lbl.linkActivated.connect(on_msg_link_activated)
                lbl.repaint()

            WndUtils.call_in_main_thread(set)

        try:
            bip44_wallet.on_fetch_account_txs_feedback = fetch_txes_feeback
            bip44_wallet.fetch_all_accounts_txs(check_break_scanning)

            for utxo in bip44_wallet.list_utxos_for_account(account_id=None, filter_by_satoshis=1e11):
                utxos.append(utxo)

        except BreakFetchTransactionsException:
            return None
        return utxos

    def on_act_view_as_mn_private_key_triggered(self):
        if self.masternode and not self.edit_mode:
            self.edtMasternodePrivateKey.setText(self.masternode.privateKey)

    def on_act_view_as_mn_public_address_triggered(self):
        if self.masternode and not self.edit_mode:
            ret = dash_utils.wif_privkey_to_address(self.masternode.privateKey, self.app_config.dash_network)
            self.edtMasternodePrivateKey.setText(ret)

    def on_act_view_as_mn_public_key_triggered(self):
        if self.masternode:
            ret = dash_utils.wif_privkey_to_pubkey(self.masternode.privateKey)
            cl = QApplication.clipboard()
            cl.setText(ret)

    def on_act_view_as_mn_public_key_hash_triggered(self):
        if self.masternode:
            pubkey = dash_utils.wif_privkey_to_pubkey(self.masternode.privateKey)
            pubkey_bin = bytes.fromhex(pubkey)
            pub_hash = bitcoin.bin_hash160(pubkey_bin)
            ret = pub_hash.hex()
            cl = QApplication.clipboard()
            cl.setText(ret)

    def on_act_copy_as_owner_private_key_triggered(self):
        if self.masternode:
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                cl = QApplication.clipboard()
                cl.setText(self.masternode.dmn_owner_private_key)
            else:
                raise Exception('Cannot convert a Dash address to a public key.')

    def on_act_copy_as_owner_public_address_triggered(self):
        if self.masternode:
            cl = QApplication.clipboard()
            cl.setText(self.masternode.get_dmn_owner_public_address(self.app_config.dash_network))

    def on_act_copy_as_owner_public_key_triggered(self):
        if self.masternode:
            ret = ''
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                if self.masternode.dmn_owner_private_key:
                    ret = dash_utils.wif_privkey_to_pubkey(self.masternode.dmn_owner_private_key)
            else:
                raise Exception('Cannot convert an address to a public key.')
            cl = QApplication.clipboard()
            cl.setText(ret)

    def on_act_copy_as_owner_public_key_hash_triggered(self):
        if self.masternode:
            cl = QApplication.clipboard()
            cl.setText(self.masternode.get_dmn_owner_pubkey_hash())

    def on_act_copy_as_voting_private_key_triggered(self):
        if self.masternode:
            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                cl = QApplication.clipboard()
                cl.setText(self.masternode.dmn_voting_private_key)
            else:
                raise Exception('Cannot convert a Dash address to a public key.')

    def on_act_copy_as_voting_public_address_triggered(self):
        if self.masternode:
            cl = QApplication.clipboard()
            cl.setText(self.masternode.get_dmn_voting_public_address(self.app_config.dash_network))

    def on_act_copy_as_voting_public_key_triggered(self):
        if self.masternode:
            ret = ''
            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                if self.masternode.dmn_voting_private_key:
                    ret = dash_utils.wif_privkey_to_pubkey(self.masternode.dmn_voting_private_key)
            else:
                raise Exception('Cannot convert a Dash address to a public key.')

            cl = QApplication.clipboard()
            cl.setText(ret)

    def on_act_copy_as_voting_public_key_hash_triggered(self):
        if self.masternode:
            ret = self.masternode.get_dmn_voting_pubkey_hash()
            cl = QApplication.clipboard()
            cl.setText(ret)

    def on_act_copy_as_operator_private_key_triggered(self):
        if self.masternode:
            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                ret = self.masternode.dmn_operator_private_key
            else:
                raise Exception('Cannot convert a public key to a private key.')
            cl = QApplication.clipboard()
            cl.setText(ret)

    def on_act_copy_as_operator_public_key_triggered(self):
        if self.masternode:
            cl = QApplication.clipboard()
            cl.setText(self.masternode.get_dmn_operator_pubkey())
