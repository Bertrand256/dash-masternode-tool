import os
import sys
from enum import Enum
from functools import partial

import bitcoin
from PyQt5 import QtCore
from PyQt5.QtCore import QSize, pyqtSlot, Qt
from PyQt5.QtGui import QPixmap, QTextDocument
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
    role_modified = QtCore.pyqtSignal()

    def __init__(self, main_dlg, app_config, dashd_intf):
        QWidget.__init__(self, main_dlg)
        ui_masternode_details.Ui_WdgMasternodeDetails.__init__(self)
        self.main_dlg = main_dlg
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.masternode: MasternodeConfig = None
        self.updating_ui = False
        self.edit_mode = False
        self.style_sheet = 'QLineEdit[hightlight="true"]{color:#0047b3} QLabel[hightlight="true"]{color:#0047b3}'
        self.setStyleSheet(self.style_sheet)
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

        self.act_view_as_mn_private_key = QAction('View as private key', self)
        self.act_view_as_mn_private_key.setData('privkey')
        self.act_view_as_mn_private_key.triggered.connect(self.on_masternode_view_key_type_changed)
        self.act_view_as_mn_public_address = QAction('View as Dash address', self)
        self.act_view_as_mn_public_address.setData('address')
        self.act_view_as_mn_public_address.triggered.connect(self.on_masternode_view_key_type_changed)
        self.act_view_as_mn_public_key = QAction('View as public key', self)
        self.act_view_as_mn_public_key.setData('pubkey')
        self.act_view_as_mn_public_key.triggered.connect(self.on_masternode_view_key_type_changed)
        self.act_view_as_mn_public_key_hash = QAction('View as public key hash', self)
        self.act_view_as_mn_public_key_hash.setData('pubkeyhash')
        self.act_view_as_mn_public_key_hash.triggered.connect(self.on_masternode_view_key_type_changed)
        self.ag_mn_key = QActionGroup(self)
        self.act_view_as_mn_private_key.setCheckable(True)
        self.act_view_as_mn_public_address.setCheckable(True)
        self.act_view_as_mn_public_key.setCheckable(True)
        self.act_view_as_mn_public_key_hash.setCheckable(True)
        self.act_view_as_mn_private_key.setActionGroup(self.ag_mn_key)
        self.act_view_as_mn_public_address.setActionGroup(self.ag_mn_key)
        self.act_view_as_mn_public_key.setActionGroup(self.ag_mn_key)
        self.act_view_as_mn_public_key_hash.setActionGroup(self.ag_mn_key)
        self.btnShowMnPrivateKey.addActions((self.act_view_as_mn_private_key, self.act_view_as_mn_public_address,
                                            self.act_view_as_mn_public_key, self.act_view_as_mn_public_key_hash))

        self.act_view_as_owner_private_key = QAction('View as private key', self)
        self.act_view_as_owner_private_key.setData('privkey')
        self.act_view_as_owner_private_key.triggered.connect(self.on_owner_view_key_type_changed)
        self.act_view_as_owner_public_address = QAction('View as Dash address', self)
        self.act_view_as_owner_public_address.setData('address')
        self.act_view_as_owner_public_address.triggered.connect(self.on_owner_view_key_type_changed)
        self.act_view_as_owner_public_key = QAction('View as public key', self)
        self.act_view_as_owner_public_key.setData('pubkey')
        self.act_view_as_owner_public_key.triggered.connect(self.on_owner_view_key_type_changed)
        self.act_view_as_owner_public_key_hash = QAction('View as public key hash', self)
        self.act_view_as_owner_public_key_hash.setData('pubkeyhash')
        self.act_view_as_owner_public_key_hash.triggered.connect(self.on_owner_view_key_type_changed)
        self.ag_owner_key = QActionGroup(self)
        self.act_view_as_owner_private_key.setCheckable(True)
        self.act_view_as_owner_public_address.setCheckable(True)
        self.act_view_as_owner_public_key.setCheckable(True)
        self.act_view_as_owner_public_key_hash.setCheckable(True)
        self.act_view_as_owner_private_key.setActionGroup(self.ag_owner_key)
        self.act_view_as_owner_public_address.setActionGroup(self.ag_owner_key)
        self.act_view_as_owner_public_key.setActionGroup(self.ag_owner_key)
        self.act_view_as_owner_public_key_hash.setActionGroup(self.ag_owner_key)
        self.btnShowOwnerPrivateKey.addActions(
            (self.act_view_as_owner_private_key, self.act_view_as_owner_public_address,
             self.act_view_as_owner_public_key, self.act_view_as_owner_public_key_hash))

        self.act_view_as_voting_private_key = QAction('View as private key', self)
        self.act_view_as_voting_private_key.setData('privkey')
        self.act_view_as_voting_private_key.triggered.connect(self.on_voting_view_key_type_changed)
        self.act_view_as_voting_public_address = QAction('View as Dash address', self)
        self.act_view_as_voting_public_address.setData('address')
        self.act_view_as_voting_public_address.triggered.connect(self.on_voting_view_key_type_changed)
        self.act_view_as_voting_public_key = QAction('View as public key', self)
        self.act_view_as_voting_public_key.setData('pubkey')
        self.act_view_as_voting_public_key.triggered.connect(self.on_voting_view_key_type_changed)
        self.act_view_as_voting_public_key_hash = QAction('View as public key hash', self)
        self.act_view_as_voting_public_key_hash.setData('pubkeyhash')
        self.act_view_as_voting_public_key_hash.triggered.connect(self.on_voting_view_key_type_changed)
        self.ag_voting_key = QActionGroup(self)
        self.act_view_as_voting_private_key.setCheckable(True)
        self.act_view_as_voting_public_address.setCheckable(True)
        self.act_view_as_voting_public_key.setCheckable(True)
        self.act_view_as_voting_public_key_hash.setCheckable(True)
        self.act_view_as_voting_private_key.setActionGroup(self.ag_voting_key)
        self.act_view_as_voting_public_address.setActionGroup(self.ag_voting_key)
        self.act_view_as_voting_public_key.setActionGroup(self.ag_voting_key)
        self.act_view_as_voting_public_key_hash.setActionGroup(self.ag_voting_key)
        self.btnShowVotingPrivateKey.addActions((self.act_view_as_voting_private_key,
                                                 self.act_view_as_voting_public_address,
                                                 self.act_view_as_voting_public_key,
                                                 self.act_view_as_voting_public_key_hash))

        self.act_view_as_operator_private_key = QAction('View as private key', self)
        self.act_view_as_operator_private_key.setData('privkey')
        self.act_view_as_operator_private_key.triggered.connect(self.on_operator_view_key_type_changed)
        self.act_view_as_operator_public_key = QAction('View as public key', self)
        self.act_view_as_operator_public_key.setData('pubkey')
        self.act_view_as_operator_public_key.triggered.connect(self.on_operator_view_key_type_changed)
        self.ag_operator_key = QActionGroup(self)
        self.act_view_as_operator_private_key.setCheckable(True)
        self.act_view_as_operator_public_key.setCheckable(True)
        self.act_view_as_operator_private_key.setActionGroup(self.ag_operator_key)
        self.act_view_as_operator_public_key.setActionGroup(self.ag_operator_key)
        self.btnShowOperatorPrivateKey.addActions((self.act_view_as_operator_private_key,
                                          self.act_view_as_operator_public_key))

        self.update_ui_controls_state()

    def showEvent(self, QShowEvent):
        self.update_key_controls_state()  # qt 0.9.2: control styles aren't updated properly without reapplying
                                          # them here

        self.lblOwnerKey.fontMetrics()

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
                                               self.edit_mode is False and
                                               self.masternode.dmn_user_role == DMN_ROLE_OWNER)
        self.btnCopyOwnerKey.setVisible(self.masternode is not None and is_deterministic and
                                                   self.masternode.dmn_user_role == DMN_ROLE_OWNER)
        self.lblOperatorKey.setVisible(self.masternode is not None and is_deterministic and
                                              self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.edtOperatorKey.setVisible(self.masternode is not None and is_deterministic and
                                              self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.btnShowOperatorPrivateKey.setVisible(self.masternode is not None and is_deterministic and
                                                  self.edit_mode is False and
                                                  self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.btnCopyOperatorKey.setVisible(self.masternode is not None and is_deterministic and
                                                      self.masternode.dmn_user_role != DMN_ROLE_VOTING)
        self.lblVotingKey.setVisible(self.masternode is not None and is_deterministic and
                                            self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)
        self.edtVotingKey.setVisible(self.masternode is not None and is_deterministic and
                                            self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)
        self.btnShowVotingPrivateKey.setVisible(self.masternode is not None and is_deterministic and
                                                self.edit_mode is False and
                                                self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)
        self.btnCopyVotingKey.setVisible(self.masternode is not None and is_deterministic and
                                                    self.masternode.dmn_user_role != DMN_ROLE_OPERATOR)

        self.act_view_as_owner_private_key.setVisible(self.masternode is not None and
                                                      self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE)
        self.act_view_as_owner_public_key.setVisible(self.masternode is not None and
                                                     self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE)
        self.act_view_as_operator_private_key.setVisible(self.masternode is not None and
                                                         self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE)
        self.act_view_as_voting_private_key.setVisible(self.masternode is not None and
                                                       self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE)
        self.act_view_as_voting_public_key.setVisible(self.masternode is not None and
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
        self.btnShowMnPrivateKey.setVisible(self.masternode is not None and self.edit_mode is False and
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
        self.update_key_controls_state()

    def update_dynamic_labels(self):
        # doc = QTextDocument(self)
        # doc.setDocumentMargin(0)
        # doc.setDefaultFont(self.lblOwnerKey.font())
        # doc.setHtml('Test')
        # h = int(doc.size().height())

        def get_label_text(prefix:str, group: QActionGroup, tooltip_anchor: str):
            lbl = '???'
            a = group.checkedAction()
            if a:
                if a.data() == 'privkey':
                    lbl = lbl = prefix + ' private key'
                elif a.data() == 'address':
                    lbl = prefix + ' Dash address'
                elif a.data() == 'pubkey':
                    lbl = prefix + ' public key'
                elif a.data() == 'pubkeyhash':
                    lbl = prefix + ' public key hash'

            if self.edit_mode:
                change_lbl = {'addr': 'address', 'priv': 'privkey', 'pub': 'pubkey'}.get(tooltip_anchor)

                # change_mode = f'<a href="{tooltip_anchor}"><img width="{h}" height="{h}" ' \
                #                'src="img/swap-horiz@24px.png"></img></a>'
                change_mode = f'(<a href="{tooltip_anchor}">use {change_lbl}</a>)'
            else:
                change_mode = ''
            return f'<table style="float:right"><tr><td>{lbl}</td><td>{change_mode}</td></tr></table>'

        if self.masternode:

            tooltip_anchor = 'addr' if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE else 'priv'
            self.lblOwnerKey.setText(get_label_text('Owner', self.ag_owner_key, tooltip_anchor))

            tooltip_anchor = 'pub' if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE else 'priv'
            self.lblOperatorKey.setText(get_label_text('Operator', self.ag_operator_key, tooltip_anchor))

            tooltip_anchor = 'addr' if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE else 'priv'
            self.lblVotingKey.setText(get_label_text('Voting', self.ag_voting_key, tooltip_anchor))

            self.set_left_label_width(self.get_max_left_label_width())

    def update_key_controls_state(self):
        self.edtMasternodePrivateKey.setEchoMode(QLineEdit.Normal if self.btnShowMnPrivateKey.isChecked() or
                                                                     self.edit_mode else QLineEdit.Password)

        hl = not self.act_view_as_mn_private_key.isChecked() and not self.edit_mode
        self.edtMasternodePrivateKey.setProperty('hightlight', hl)
        self.lblMasternodePrivateKey.setProperty('hightlight', hl)

        self.edtOwnerKey.setEchoMode(QLineEdit.Normal if self.btnShowOwnerPrivateKey.isChecked() or
                                                         self.edit_mode else QLineEdit.Password)

        hl = self.masternode is not None and not self.edit_mode and \
             not ((self.act_view_as_owner_private_key.isChecked() and
                   self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE) or
                  (self.act_view_as_owner_public_address.isChecked() and
                   self.masternode.dmn_owner_key_type == InputKeyType.PUBLIC))
        self.edtOwnerKey.setProperty('hightlight', hl )
        self.lblOwnerKey.setProperty('hightlight', hl )

        self.edtOperatorKey.setEchoMode(QLineEdit.Normal if self.btnShowOperatorPrivateKey.isChecked() or
                                        self.edit_mode else QLineEdit.Password)

        hl = self.masternode is not None and not self.edit_mode and \
             not ((self.act_view_as_operator_private_key.isChecked() and
                   self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE) or
                  (self.masternode.dmn_operator_key_type == InputKeyType.PUBLIC))
        self.edtOperatorKey.setProperty('hightlight', hl)
        self.lblOperatorKey.setProperty('hightlight', hl )

        self.edtVotingKey.setEchoMode(QLineEdit.Normal if self.btnShowVotingPrivateKey.isChecked() or
                                      self.edit_mode else QLineEdit.Password)

        hl = self.masternode is not None and not self.edit_mode and \
             not ((self.act_view_as_voting_private_key.isChecked() and
                   self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE) or
                  (self.act_view_as_voting_public_address.isChecked() and
                   self.masternode.dmn_voting_key_type == InputKeyType.PUBLIC))
        self.edtVotingKey.setProperty('hightlight', hl)
        self.lblVotingKey.setProperty('hightlight', hl)

        self.update_dynamic_labels()
        self.apply_stylesheet()

    def masternode_data_to_ui(self):
        if self.masternode:
            self.act_view_as_mn_private_key.setChecked(True)
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                self.act_view_as_owner_private_key.setChecked(True)
            else:
                self.act_view_as_owner_public_address.setChecked(True)

            if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                self.act_view_as_operator_private_key.setChecked(True)
            else:
                self.act_view_as_operator_public_key.setChecked(True)

            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                self.act_view_as_voting_private_key.setChecked(True)
            else:
                self.act_view_as_voting_public_address.setChecked(True)
            self.btnShowMnPrivateKey.setChecked(False)
            self.btnShowOwnerPrivateKey.setChecked(False)
            self.btnShowOperatorPrivateKey.setChecked(False)
            self.btnShowVotingPrivateKey.setChecked(False)

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
            self.edtMasternodePrivateKey.setText(self.get_masternode_key_to_display())
            self.edtOwnerKey.setText(self.get_owner_key_to_display())
            self.edtVotingKey.setText(self.get_voting_key_to_display())
            self.edtOperatorKey.setText(self.get_operator_key_to_display())
            self.updating_ui = False
        else:
            for e in self.findChildren(QLineEdit):
                e.setText('')
        self.update_ui_controls_state()

    def get_masternode_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                ret = self.masternode.privateKey
            else:
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
                    ret = '???'
        return ret

    def get_owner_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.dmn_owner_private_key
                else:
                    ret = self.masternode.dmn_owner_address
            else:
                if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                    if self.act_view_as_owner_private_key.isChecked():
                        ret = self.masternode.dmn_owner_private_key
                    elif self.act_view_as_owner_public_address.isChecked():
                        ret = dash_utils.wif_privkey_to_address(self.masternode.dmn_owner_private_key,
                                                                self.app_config.dash_network)
                    elif self.act_view_as_owner_public_key.isChecked():
                        ret = dash_utils.wif_privkey_to_pubkey(self.masternode.dmn_owner_private_key)
                    elif self.act_view_as_owner_public_key_hash.isChecked():
                        pubkey = dash_utils.wif_privkey_to_pubkey(self.masternode.dmn_owner_private_key)
                        pubkey_bin = bytes.fromhex(pubkey)
                        pub_hash = bitcoin.bin_hash160(pubkey_bin)
                        ret = pub_hash.hex()
                    else:
                        ret = '???'
                else:
                    if self.act_view_as_owner_public_address.isChecked():
                        ret = self.masternode.dmn_owner_address
                    elif self.act_view_as_owner_public_key_hash.isChecked():
                        ret = self.masternode.get_dmn_owner_pubkey_hash()
                    else:
                        ret = '???'
        return ret

    def get_voting_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.dmn_voting_private_key
                else:
                    ret = self.masternode.dmn_voting_address
            else:
                if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                    if self.act_view_as_voting_private_key.isChecked():
                        ret = self.masternode.dmn_voting_private_key
                    elif self.act_view_as_voting_public_address.isChecked():
                        ret = dash_utils.wif_privkey_to_address(self.masternode.dmn_voting_private_key,
                                                                self.app_config.dash_network)
                    elif self.act_view_as_voting_public_key.isChecked():
                        ret = dash_utils.wif_privkey_to_pubkey(self.masternode.dmn_voting_private_key)
                    elif self.act_view_as_voting_public_key_hash.isChecked():
                        pubkey = dash_utils.wif_privkey_to_pubkey(self.masternode.dmn_voting_private_key)
                        pubkey_bin = bytes.fromhex(pubkey)
                        pub_hash = bitcoin.bin_hash160(pubkey_bin)
                        ret = pub_hash.hex()
                    else:
                        ret = '???'
                else:
                    if self.act_view_as_voting_public_address.isChecked():
                        ret = self.masternode.dmn_voting_address
                    elif self.act_view_as_voting_public_key_hash.isChecked():
                        ret = self.masternode.get_dmn_voting_pubkey_hash()
                    else:
                        ret = '???'
        return ret

    def get_operator_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.dmn_operator_private_key
                else:
                    ret = self.masternode.dmn_operator_public_key
            else:
                if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                    if self.act_view_as_operator_private_key.isChecked():
                        ret = self.masternode.dmn_operator_private_key
                    elif self.act_view_as_operator_public_key.isChecked():
                        ret = self.masternode.get_dmn_operator_pubkey()
                    else:
                        ret = '???'
                else:
                    if self.act_view_as_operator_public_key_hash.isChecked():
                        ret = self.masternode.dmn_operator_public_key
                    else:
                        ret = '???'
        return ret

    @pyqtSlot(str)
    def on_lblOwnerKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_owner_key_type = InputKeyType.PUBLIC
                self.edtOwnerKey.setText(self.masternode.dmn_owner_address)
                self.act_view_as_owner_private_key.setChecked(True)
            else:
                self.masternode.dmn_owner_key_type = InputKeyType.PRIVATE
                self.edtOwnerKey.setText(self.masternode.dmn_owner_private_key)
                self.act_view_as_owner_public_address.setChecked(True)
            self.set_modified()
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_operator_key_type = InputKeyType.PUBLIC
                self.edtOperatorKey.setText(self.masternode.dmn_operator_public_key)
                self.act_view_as_operator_private_key.setChecked(True)
            else:
                self.masternode.dmn_operator_key_type = InputKeyType.PRIVATE
                self.edtOperatorKey.setText(self.masternode.dmn_operator_private_key)
                self.act_view_as_operator_public_key.setChecked(True)
            self.set_modified()
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_voting_key_type = InputKeyType.PUBLIC
                self.edtVotingKey.setText(self.masternode.dmn_voting_address)
                self.act_view_as_voting_private_key.setChecked(True)
            else:
                self.masternode.dmn_voting_key_type = InputKeyType.PRIVATE
                self.edtVotingKey.setText(self.masternode.dmn_voting_private_key)
                self.act_view_as_voting_public_address.setChecked(True)
            self.set_modified()
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblOwnerKey_linkHovered(self, link):
        if link == 'addr':
            tt = 'Change input type to Dash address'
        else:
            tt = 'Change input type to private key'
        self.lblOwnerKey.setToolTip(tt)

    @pyqtSlot(str)
    def on_lblOperatorKey_linkHovered(self, link):
        if link == 'pub':
            tt = 'Change input type to public key'
        else:
            tt = 'Change input type to private key'
        self.lblOperatorKey.setToolTip(tt)

    @pyqtSlot(str)
    def on_lblVotingKey_linkHovered(self, link):
        if link == 'addr':
            tt = 'Change input type to Dash address'
        else:
            tt = 'Change input type to private key'
        self.lblVotingKey.setToolTip(tt)

    def get_max_left_label_width(self):
        doc = QTextDocument(self)
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.lblOwnerKey.font())
        doc.setHtml('Test')

        def get_lbl_text_width(lbl):
            nonlocal doc
            doc.setHtml(lbl.text())
            return int(doc.size().width() + 5)

        w = max(get_lbl_text_width(self.lblName),
                get_lbl_text_width(self.lblIP),
                get_lbl_text_width(self.lblCollateral),
                get_lbl_text_width(self.lblCollateralTxHash),
                get_lbl_text_width(self.lblDMNTxHash),
                get_lbl_text_width(self.lblMasternodePrivateKey),
                get_lbl_text_width(self.lblOwnerKey),
                get_lbl_text_width(self.lblOperatorKey),
                get_lbl_text_width(self.lblVotingKey))

        return w

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
            self.masternode_data_to_ui()
            self.apply_stylesheet()

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
            self.role_modified.emit()

    @pyqtSlot(bool)
    def on_rbRoleOperator_toggled(self, checked):
        if not self.updating_ui and checked:
            self.masternode.dmn_user_role = DMN_ROLE_OPERATOR
            self.update_ui_controls_state()
            self.set_modified()
            self.role_modified.emit()

    @pyqtSlot(bool)
    def on_rbRoleVoting_toggled(self, checked):
        if not self.updating_ui and checked:
            self.masternode.dmn_user_role = DMN_ROLE_VOTING
            self.update_ui_controls_state()
            self.set_modified()
            self.role_modified.emit()

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

    @pyqtSlot(str)
    def on_edtPort_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.port = text.strip()

    @pyqtSlot(str)
    def on_edtProtocolVersion_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.protocol_version = text.strip()
            if not self.masternode.protocol_version:
                self.masternode.use_default_protocol_version = True
            else:
                self.masternode.use_default_protocol_version = False

    @pyqtSlot(str)
    def on_edtCollateralAddress_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateralAddress))
            self.set_modified()
            self.masternode.collateralAddress = text.strip()
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralPath_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateralBip32Path))
            self.set_modified()
            self.masternode.collateralBip32Path = text.strip()
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralTxHash_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateralTx))
            self.set_modified()
            self.masternode.collateralTx = text.strip()
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralTxIndex_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.collateralTxIndex = text.strip()

    @pyqtSlot(str)
    def on_edtDMNTxHash_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.set_modified()
            self.masternode.dmn_tx_hash = text.strip()

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

    @pyqtSlot(str)
    def on_edtOwnerKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_owner_private_key = text.strip()
            else:
                self.masternode.dmn_owner_address = text.strip()
            self.set_modified()

    @pyqtSlot(str)
    def on_edtOperatorKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_operator_private_key = text.strip()
            else:
                self.masternode.dmn_operator_public_key = text.strip()
            self.set_modified()

    @pyqtSlot(str)
    def on_edtVotingKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                self.masternode.dmn_voting_private_key = text.strip()
            else:
                self.masternode.dmn_voting_address = text.strip()
            self.set_modified()

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
        self.update_key_controls_state()

    @pyqtSlot(bool)
    def on_btnShowOwnerPrivateKey_toggled(self, checked):
        self.edtOwnerKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.update_key_controls_state()

    @pyqtSlot(bool)
    def on_btnShowOperatorPrivateKey_toggled(self, checked):
        self.edtOperatorKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.update_key_controls_state()

    @pyqtSlot(bool)
    def on_btnShowVotingPrivateKey_toggled(self, checked):
        self.edtVotingKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.update_key_controls_state()

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

    def apply_stylesheet(self):
        self.setStyleSheet(self.style_sheet)

    def on_masternode_view_key_type_changed(self):
        self.btnShowMnPrivateKey.setChecked(True)
        self.update_key_controls_state()
        self.edtMasternodePrivateKey.setText(self.get_masternode_key_to_display())

    def on_owner_view_key_type_changed(self):
        self.btnShowOwnerPrivateKey.setChecked(True)
        self.update_key_controls_state()
        self.edtOwnerKey.setText(self.get_owner_key_to_display())

    def on_voting_view_key_type_changed(self):
        self.btnShowVotingPrivateKey.setChecked(True)
        self.update_key_controls_state()
        self.edtVotingKey.setText(self.get_voting_key_to_display())

    def on_operator_view_key_type_changed(self):
        self.btnShowOperatorPrivateKey.setChecked(True)
        self.update_key_controls_state()
        self.edtOperatorKey.setText(self.get_operator_key_to_display())

    def on_btnCopyMnKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtMasternodePrivateKey.text())

    def on_btnCopyOwnerKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtOwnerKey.text())

    def on_btnCopyVotingKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtVotingKey.text())

    def on_btnCopyOperatorKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtOperatorKey.text())

