import base64
from typing import Callable, Optional, Literal, cast

import bitcoin
from PyQt5 import QtCore
from PyQt5.QtCore import pyqtSlot, Qt, QTimer
from PyQt5.QtGui import QTextDocument
from PyQt5.QtWidgets import QWidget, QLineEdit, QInputDialog, QMessageBox, QAction, QApplication, QActionGroup
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import cryptography.hazmat.primitives.serialization

import dash_utils
import hw_intf
from app_config import MasternodeConfig, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, DMN_ROLE_VOTING, InputKeyType, AppConfig, \
    MasternodeType
from app_defs import DispMessage, AppTextMessageType
from bip44_wallet import Bip44Wallet, BreakFetchTransactionsException
from common import CancelException
from dashd_intf import DashdInterface
from find_coll_tx_dlg import WalletUtxosListDlg
from thread_fun_dlg import CtrlObject
from ui import ui_masternode_details_wdg
from wnd_utils import WndUtils


class WdgMasternodeDetails(QWidget, ui_masternode_details_wdg.Ui_WdgMasternodeDetails):
    name_modified = QtCore.pyqtSignal(object, str)
    data_changed = QtCore.pyqtSignal(object)
    role_modified = QtCore.pyqtSignal()
    label_width_changed = QtCore.pyqtSignal(int)
    app_text_message_sent = QtCore.pyqtSignal(int, str, object)

    def __init__(self, parent, app_config: AppConfig, dashd_intf: DashdInterface, hw_session: hw_intf.HwSessionInfo):
        QWidget.__init__(self, parent)
        ui_masternode_details_wdg.Ui_WdgMasternodeDetails.__init__(self)
        self.parent = parent
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.hw_session = hw_session
        self.masternode = MasternodeConfig()  # temporary object to avoid changing attributes of the global
        # mn object, since user has the ability to cancel editing
        self.updating_ui = False
        self.edit_mode = False
        self.owner_key_invalid = False
        self.operator_key_invalid = False
        self.voting_key_invalid = False
        self.setupUi(self)

    def setupUi(self, widget: QWidget):
        ui_masternode_details_wdg.Ui_WdgMasternodeDetails.setupUi(self, self)
        WndUtils.set_icon(self.parent, self.btnShowOwnerPrivateKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnShowOperatorPrivateKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnShowVotingPrivateKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyOwnerKey, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyOperatorKey, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyVotingKey, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyProtxHash, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyPlatformId, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnShowCollateralPathAddress, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnPlatformP2PPortSetDefault, 'restore@16px.png')
        WndUtils.set_icon(self.parent, self.btnPlatformHTTPPortSetDefault, 'restore@16px.png')

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

        # Copy Platform Node Id as ...:
        self.act_copy_platform_node_as_pkcs8_base64 = QAction('Copy Ed25519 private key as PKCS8 / base64', self)
        self.act_copy_platform_node_as_pkcs8_pem = QAction('Copy Ed25519 private key as PKCS8 / PEM', self)
        self.act_copy_platform_node_as_pkcs8_der = QAction('Copy Ed25519 private key as PKCS8 / DER_HEX', self)
        self.act_copy_platform_node_as_raw_hex = QAction('Copy Ed25519 private key as RAW / HEX', self)
        self.act_copy_platform_node_as_pkcs8_base64.triggered.connect(
            self.on_copy_platform_node_as_pkcs8_base64_triggered)
        self.act_copy_platform_node_as_pkcs8_pem.triggered.connect(self.on_copy_platform_node_as_pkcs8_pem_triggered)
        self.act_copy_platform_node_as_pkcs8_der.triggered.connect(self.on_copy_platform_node_as_pkcs8_der_triggered)
        self.act_copy_platform_node_as_raw_hex.triggered.connect(self.on_copy_platform_node_as_raw_hex_triggered)
        self.btnCopyPlatformId.addActions((self.act_copy_platform_node_as_pkcs8_base64,
                                           self.act_copy_platform_node_as_raw_hex,
                                           self.act_copy_platform_node_as_pkcs8_der,
                                           self.act_copy_platform_node_as_pkcs8_pem))
        self.update_ui_controls_state()

    def showEvent(self, QShowEvent):
        def apply():
            self.update_key_controls_state()
            self.lblOwnerKey.fontMetrics()
            self.set_buttons_height()

        QTimer.singleShot(100, apply)

    def set_buttons_height(self):
        h = self.edtName.height()
        self.btnCopyOwnerKey.setFixedHeight(h)
        self.btnShowOwnerPrivateKey.setFixedHeight(h)
        self.btnGenerateOwnerPrivateKey.setFixedHeight(h)

        self.btnCopyOperatorKey.setFixedHeight(h)
        self.btnShowOperatorPrivateKey.setFixedHeight(h)
        self.btnGenerateOperatorPrivateKey.setFixedHeight(h)

        self.btnCopyVotingKey.setFixedHeight(h)
        self.btnShowVotingPrivateKey.setFixedHeight(h)
        self.btnGenerateVotingPrivateKey.setFixedHeight(h)
        self.btnCopyProtxHash.setFixedHeight(h)

        self.btnGetMNDataByIP.setFixedHeight(h)
        self.btnShowCollateralPathAddress.setFixedHeight(h)
        self.btnBip32PathToAddress.setFixedHeight(h)
        self.btnLocateCollateral.setFixedHeight(h)
        self.btnCopyPlatformId.setFixedHeight(h)
        self.btnPlatformP2PPortSetDefault.setFixedHeight(h)
        self.btnPlatformHTTPPortSetDefault.setFixedHeight(h)

    def update_ui_controls_state(self):
        """Update visibility and enabled/disabled state of the UI controls.
        """
        self.lblDMNTxHash.setVisible(self.masternode is not None)
        self.edtDMNTxHash.setVisible(self.masternode is not None)
        self.btnGetMNDataByIP.setVisible(self.masternode is not None and self.edit_mode)

        self.lblCollateral.setVisible(self.masternode is not None and
                                      (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnLocateCollateral.setVisible(self.masternode is not None and self.edit_mode and
                                            (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnBip32PathToAddress.setVisible(self.masternode is not None and self.edit_mode and
                                              (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnShowCollateralPathAddress.setVisible(self.masternode is not None and
                                                     (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.edtCollateralAddress.setVisible(self.masternode is not None and
                                             (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.lblCollateralPath.setVisible(self.masternode is not None and
                                          (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.edtCollateralPath.setVisible(self.masternode is not None and
                                          (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))

        self.lblOwnerKey.setVisible(self.masternode is not None and
                                    (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.edtOwnerKey.setVisible(self.masternode is not None and
                                    (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnShowOwnerPrivateKey.setVisible(self.masternode is not None and
                                               self.edit_mode is False and
                                               (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnCopyOwnerKey.setVisible(self.masternode is not None and
                                        (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.lblOperatorKey.setVisible(self.masternode is not None and
                                       (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.edtOperatorKey.setVisible(self.masternode is not None and
                                       (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.btnShowOperatorPrivateKey.setVisible(self.masternode is not None and
                                                  self.edit_mode is False and
                                                  (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.btnCopyOperatorKey.setVisible(self.masternode is not None and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.lblVotingKey.setVisible(self.masternode is not None and
                                     (self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0))
        self.edtVotingKey.setVisible(self.masternode is not None and
                                     (self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0))
        self.btnShowVotingPrivateKey.setVisible(self.masternode is not None and
                                                self.edit_mode is False and
                                                (self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0))
        self.btnCopyVotingKey.setVisible(self.masternode is not None and
                                         (self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0))

        self.act_view_as_owner_private_key.setVisible(self.masternode is not None and
                                                      self.masternode.owner_key_type == InputKeyType.PRIVATE)
        self.act_view_as_owner_public_key.setVisible(self.masternode is not None and
                                                     self.masternode.owner_key_type == InputKeyType.PRIVATE)
        self.act_view_as_operator_private_key.setVisible(self.masternode is not None and
                                                         self.masternode.operator_key_type == InputKeyType.PRIVATE)
        self.act_view_as_voting_private_key.setVisible(self.masternode is not None and
                                                       self.masternode.voting_key_type == InputKeyType.PRIVATE)
        self.act_view_as_voting_public_key.setVisible(self.masternode is not None and
                                                      self.masternode.voting_key_type == InputKeyType.PRIVATE)

        # Platform Node ID
        self.lblPlatformNodeId.setVisible(self.masternode is not None and
                                          (self.masternode.masternode_type == MasternodeType.HPMN))
        self.edtPlatformNodeId.setVisible(self.masternode is not None and
                                          (self.masternode.masternode_type == MasternodeType.HPMN))
        self.btnCopyPlatformId.setVisible(self.masternode is not None and
                                          (self.masternode.masternode_type == MasternodeType.HPMN))

        # Platform P2P port
        self.lblPlatformP2PPort.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.HPMN))
        self.edtPlatformP2PPort.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.HPMN))

        # Platform HTTP port
        self.lblPlatformHTTPPort.setVisible(self.masternode is not None and
                                            (self.masternode.masternode_type == MasternodeType.HPMN))
        self.edtPlatformHTTPPort.setVisible(self.masternode is not None and
                                            (self.masternode.masternode_type == MasternodeType.HPMN))

        self.btnGenerateOwnerPrivateKey.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.owner_key_type == InputKeyType.PRIVATE and
            self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0)

        self.btnGenerateOperatorPrivateKey.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.operator_key_type == InputKeyType.PRIVATE and
            self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0)

        self.btnGenerateVotingPrivateKey.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.voting_key_type == InputKeyType.PRIVATE and
            self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0)

        self.btnGetPlatformNodeIdFromPrivate.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.masternode_type == MasternodeType.HPMN and
            self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0)

        self.btnPlatformP2PPortSetDefault.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.masternode_type == MasternodeType.HPMN and
            self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0)

        self.btnPlatformHTTPPortSetDefault.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.masternode_type == MasternodeType.HPMN and
            self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0)

        self.lblUserRole.setVisible(self.masternode is not None)
        self.chbRoleOwner.setVisible(self.masternode is not None)
        self.chbRoleOperator.setVisible(self.masternode is not None)
        self.chbRoleVoting.setVisible(self.masternode is not None)

        self.btnCopyProtxHash.setVisible(self.masternode is not None)

        # self.btnFindCollateral.setVisible(self.masternode is not None)
        self.lblIP.setVisible(self.masternode is not None)
        self.edtIP.setVisible(self.masternode is not None)
        self.lblPort.setVisible(self.masternode is not None)
        self.edtPort.setVisible(self.masternode is not None)
        self.lblName.setVisible(self.masternode is not None)
        self.edtName.setVisible(self.masternode is not None)
        self.lblCollateralTxHash.setVisible(self.masternode is not None)
        self.edtCollateralTxHash.setVisible(self.masternode is not None)
        self.lblCollateralTxIndex.setVisible(self.masternode is not None)
        self.edtCollateralTxIndex.setVisible(self.masternode is not None)

        self.chbRoleVoting.setEnabled(self.edit_mode)
        self.chbRoleOperator.setEnabled(self.edit_mode)
        self.chbRoleOwner.setEnabled(self.edit_mode)
        self.rbMNTypeRegular.setEnabled(self.edit_mode)
        self.rbMNTypeHPMN.setEnabled(self.edit_mode)
        self.edtName.setReadOnly(self.edit_mode is False)
        self.edtIP.setReadOnly(self.edit_mode is False)
        self.edtPort.setReadOnly(self.edit_mode is False)
        self.edtCollateralAddress.setReadOnly(self.edit_mode is False)
        self.edtCollateralPath.setReadOnly(self.edit_mode is False)
        self.edtCollateralTxHash.setReadOnly(self.edit_mode is False)
        self.edtCollateralTxIndex.setReadOnly(self.edit_mode is False)
        self.edtDMNTxHash.setReadOnly(self.edit_mode is False)
        self.edtOwnerKey.setReadOnly(self.edit_mode is False)
        self.edtOperatorKey.setReadOnly(self.edit_mode is False)
        self.edtVotingKey.setReadOnly(self.edit_mode is False)
        self.edtPlatformNodeId.setReadOnly(self.edit_mode is False)
        self.edtPlatformP2PPort.setReadOnly(self.edit_mode is False)
        self.edtPlatformHTTPPort.setReadOnly(self.edit_mode is False)
        self.btnGenerateOwnerPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateOperatorPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateVotingPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGetPlatformNodeIdFromPrivate.setEnabled(self.edit_mode is True)
        self.btnPlatformP2PPortSetDefault.setEnabled(self.edit_mode is True)
        self.btnPlatformHTTPPortSetDefault.setEnabled(self.edit_mode is True)
        self.btnLocateCollateral.setEnabled(self.edit_mode)
        col_btn_visible = self.masternode is not None and (not self.masternode.collateral_tx or
                                                           not self.masternode.collateral_address or
                                                           not self.masternode.collateral_bip32_path)
        self.update_key_controls_state()

    def update_dynamic_labels(self):
        def style_to_color(style: str) -> str:
            if style == 'hl1':
                color = 'color:#00802b'
            elif style == 'hl2':
                color = 'color:#0047b3'
            else:
                color = ''
            return color

        def get_label_text(prefix: str, cur_key_type: str, tooltip_anchor: str, group: QActionGroup, style: str,
                           error_msg: Optional[str] = None):
            lbl = '???'
            if self.edit_mode:
                change_mode = f'<td>(<a href="{tooltip_anchor}">use {tooltip_anchor}</a>)</td>'
            else:
                a = group.checkedAction()
                if a:
                    cur_key_type = a.data()
                change_mode = ''

            if cur_key_type == 'privkey':
                lbl = prefix + ' private key'
            elif cur_key_type == 'address':
                lbl = prefix + ' Dash address'
            elif cur_key_type == 'pubkey':
                lbl = prefix + ' public key'
            elif cur_key_type == 'pubkeyhash':
                lbl = prefix + ' public key hash'

            if error_msg:
                err = '<td style="color:red">' + error_msg + '</td>'
            else:
                err = ''
            return f'<table style="float:right;{style_to_color(style)}"><tr><td>{lbl}</td>{change_mode}{err}</tr></table>'

        if self.masternode:
            style = ''
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter the owner private key')
                if not self.edit_mode and not self.act_view_as_owner_private_key.isChecked():
                    style = 'hl2'
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the owner Dash address')
                if not self.edit_mode:
                    style = 'hl1' if self.act_view_as_owner_public_address.isChecked() else 'hl2'
            self.lblOwnerKey.setText(get_label_text(
                'Owner', key_type, tooltip_anchor, self.ag_owner_key, style,
                '[invalid key format]' if self.owner_key_invalid else ''))
            self.edtOwnerKey.setPlaceholderText(placeholder_text)

            style = ''
            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'pubkey', 'Enter the operator private key')
                if not self.edit_mode and not self.act_view_as_operator_private_key.isChecked():
                    style = 'hl2'
            else:
                key_type, tooltip_anchor, placeholder_text = ('pubkey', 'privkey', 'Enter the operator public key')
                if not self.edit_mode:
                    style = 'hl1' if self.act_view_as_operator_public_key.isChecked() else 'hl2'
            self.lblOperatorKey.setText(get_label_text(
                'Operator', key_type, tooltip_anchor, self.ag_operator_key,
                style, '[invalid key format]' if self.operator_key_invalid else ''))
            self.edtOperatorKey.setPlaceholderText(placeholder_text)

            style = ''
            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter the voting private key')
                if not self.edit_mode and not self.act_view_as_voting_private_key.isChecked():
                    style = 'hl2'
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the voting Dash address')
                if not self.edit_mode:
                    style = 'hl1' if self.act_view_as_voting_public_address.isChecked() else 'hl2'
            self.lblVotingKey.setText(get_label_text(
                'Voting', key_type, tooltip_anchor, self.ag_voting_key, style,
                '[invalid key format]' if self.voting_key_invalid else ''))
            self.edtVotingKey.setPlaceholderText(placeholder_text)

            self.set_left_label_width(self.get_max_left_label_width())

    def update_key_controls_state(self):
        self.edtOwnerKey.setEchoMode(QLineEdit.Normal if self.btnShowOwnerPrivateKey.isChecked() or
                                                         self.edit_mode else QLineEdit.Password)

        self.edtOperatorKey.setEchoMode(QLineEdit.Normal if self.btnShowOperatorPrivateKey.isChecked() or
                                                            self.edit_mode else QLineEdit.Password)

        self.edtVotingKey.setEchoMode(QLineEdit.Normal if self.btnShowVotingPrivateKey.isChecked() or
                                                          self.edit_mode else QLineEdit.Password)

        self.update_dynamic_labels()

    def masternode_data_to_ui(self, reset_key_view_type: bool = False):
        if self.masternode:
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                self.act_view_as_owner_private_key.setChecked(True)
            else:
                self.act_view_as_owner_public_address.setChecked(True)

            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                self.act_view_as_operator_private_key.setChecked(True)
            else:
                self.act_view_as_operator_public_key.setChecked(True)

            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                self.act_view_as_voting_private_key.setChecked(True)
            else:
                self.act_view_as_voting_public_address.setChecked(True)
            if reset_key_view_type:
                self.btnShowOwnerPrivateKey.setChecked(False)
                self.btnShowOperatorPrivateKey.setChecked(False)
                self.btnShowVotingPrivateKey.setChecked(False)

            self.chbRoleOwner.setChecked(self.masternode.dmn_user_roles & DMN_ROLE_OWNER)
            self.chbRoleOperator.setChecked(self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR)
            self.chbRoleVoting.setChecked(self.masternode.dmn_user_roles & DMN_ROLE_VOTING)
            self.rbMNTypeRegular.setChecked(self.masternode.masternode_type == MasternodeType.REGULAR)
            self.rbMNTypeHPMN.setChecked(self.masternode.masternode_type == MasternodeType.HPMN)
            self.edtName.setText(self.masternode.name)
            self.edtIP.setText(self.masternode.ip)
            self.edtPort.setText(str(self.masternode.tcp_port))
            self.edtCollateralAddress.setText(self.masternode.collateral_address)
            self.edtCollateralPath.setText(self.masternode.collateral_bip32_path)
            self.edtCollateralTxHash.setText(self.masternode.collateral_tx)
            self.edtCollateralTxIndex.setText(str(self.masternode.collateral_tx_index))
            self.edtDMNTxHash.setText(self.masternode.protx_hash)
            self.edtOwnerKey.setText(self.get_owner_key_to_display())
            self.edtVotingKey.setText(self.get_voting_key_to_display())
            self.edtOperatorKey.setText(self.get_operator_key_to_display())
            self.edtPlatformNodeId.setText(self.masternode.platform_node_id)
            self.edtPlatformP2PPort.setText(str(self.masternode.platform_p2p_port)
                                            if self.masternode.platform_p2p_port is not None else None)
            self.edtPlatformHTTPPort.setText(str(self.masternode.platform_http_port)
                                             if self.masternode.platform_http_port is not None else None)
            self.updating_ui = False
            self.set_buttons_height()
        else:
            for e in self.findChildren(QLineEdit):
                e.setText('')
        self.update_ui_controls_state()

    def get_owner_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.owner_private_key
                else:
                    ret = self.masternode.owner_address
            else:
                try:
                    if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                        if self.act_view_as_owner_private_key.isChecked():
                            ret = self.masternode.owner_private_key
                        elif self.act_view_as_owner_public_address.isChecked():
                            if self.masternode.owner_private_key:
                                ret = dash_utils.wif_privkey_to_address(self.masternode.owner_private_key,
                                                                        self.app_config.dash_network)
                        elif self.act_view_as_owner_public_key.isChecked():
                            if self.masternode.owner_private_key:
                                ret = dash_utils.wif_privkey_to_pubkey(self.masternode.owner_private_key)
                        elif self.act_view_as_owner_public_key_hash.isChecked():
                            if self.masternode.owner_private_key:
                                pubkey = dash_utils.wif_privkey_to_pubkey(self.masternode.owner_private_key)
                                pubkey_bin = bytes.fromhex(pubkey)
                                pub_hash = bitcoin.bin_hash160(pubkey_bin)
                                ret = pub_hash.hex()
                        else:
                            ret = '???'
                    else:
                        if self.act_view_as_owner_public_address.isChecked():
                            ret = self.masternode.owner_address
                        elif self.act_view_as_owner_public_key_hash.isChecked():
                            ret = self.masternode.get_owner_pubkey_hash()
                        else:
                            ret = '???'
                except Exception as e:
                    msg = str(e)
                    if not msg:
                        msg = 'Key conversion error.'
                    WndUtils.error_msg(msg)

        return ret

    def get_voting_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.voting_private_key
                else:
                    ret = self.masternode.voting_address
            else:
                try:
                    if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                        if self.act_view_as_voting_private_key.isChecked():
                            ret = self.masternode.voting_private_key
                        elif self.act_view_as_voting_public_address.isChecked():
                            if self.masternode.voting_private_key:
                                ret = dash_utils.wif_privkey_to_address(self.masternode.voting_private_key,
                                                                        self.app_config.dash_network)
                        elif self.act_view_as_voting_public_key.isChecked():
                            if self.masternode.voting_private_key:
                                ret = dash_utils.wif_privkey_to_pubkey(self.masternode.voting_private_key)
                        elif self.act_view_as_voting_public_key_hash.isChecked():
                            if self.masternode.voting_private_key:
                                pubkey = dash_utils.wif_privkey_to_pubkey(self.masternode.voting_private_key)
                                pubkey_bin = bytes.fromhex(pubkey)
                                pub_hash = bitcoin.bin_hash160(pubkey_bin)
                                ret = pub_hash.hex()
                        else:
                            ret = '???'
                    else:
                        if self.act_view_as_voting_public_address.isChecked():
                            ret = self.masternode.voting_address
                        elif self.act_view_as_voting_public_key_hash.isChecked():
                            ret = self.masternode.get_voting_pubkey_hash()
                        else:
                            ret = '???'
                except Exception as e:
                    msg = str(e)
                    if not msg:
                        msg = 'Key conversion error.'
                    WndUtils.error_msg(msg)
        return ret

    def get_operator_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.operator_private_key
                else:
                    ret = self.masternode.operator_public_key
            else:
                try:
                    if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                        if self.act_view_as_operator_private_key.isChecked():
                            ret = self.masternode.operator_private_key
                        elif self.act_view_as_operator_public_key.isChecked():
                            ret = self.masternode.get_operator_pubkey()
                        else:
                            ret = '???'
                    else:
                        if self.act_view_as_operator_public_key.isChecked():
                            ret = self.masternode.operator_public_key
                        else:
                            ret = '???'
                except Exception as e:
                    msg = str(e)
                    if not msg:
                        msg = 'Key conversion error.'
                    WndUtils.error_msg(msg)
        return ret

    @pyqtSlot(str)
    def on_lblOwnerKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                self.masternode.owner_key_type = InputKeyType.PUBLIC
                self.edtOwnerKey.setText(self.masternode.owner_address)
                self.act_view_as_owner_private_key.setChecked(True)
            else:
                self.masternode.owner_key_type = InputKeyType.PRIVATE
                self.edtOwnerKey.setText(self.masternode.owner_private_key)
                self.act_view_as_owner_public_address.setChecked(True)
            self.on_mn_data_modified()
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                self.masternode.operator_key_type = InputKeyType.PUBLIC
                self.edtOperatorKey.setText(self.masternode.operator_public_key)
                self.act_view_as_operator_private_key.setChecked(True)
            else:
                self.masternode.operator_key_type = InputKeyType.PRIVATE
                self.edtOperatorKey.setText(self.masternode.operator_private_key)
                self.act_view_as_operator_public_key.setChecked(True)
            self.on_mn_data_modified()
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        if self.masternode and self.edit_mode:
            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                self.masternode.voting_key_type = InputKeyType.PUBLIC
                self.edtVotingKey.setText(self.masternode.voting_address)
                self.act_view_as_voting_private_key.setChecked(True)
            else:
                self.masternode.voting_key_type = InputKeyType.PRIVATE
                self.edtVotingKey.setText(self.masternode.voting_private_key)
                self.act_view_as_voting_public_address.setChecked(True)
            self.on_mn_data_modified()
            self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_lblOwnerKey_linkHovered(self, link):
        if link == 'address':
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
        if link == 'address':
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
                get_lbl_text_width(self.lblOwnerKey),
                get_lbl_text_width(self.lblOperatorKey),
                get_lbl_text_width(self.lblVotingKey))

        return w

    def set_left_label_width(self, width):
        if self.lblName.width() != width:
            self.label_width_changed.emit(width)

        self.lblUserRole.setFixedWidth(width)
        self.lblName.setFixedWidth(width)
        self.lblMasternodeType.setFixedWidth(width)
        self.lblIP.setFixedWidth(width)
        self.lblCollateral.setFixedWidth(width)
        self.lblCollateralTxHash.setFixedWidth(width)
        self.lblDMNTxHash.setFixedWidth(width)
        self.lblOwnerKey.setFixedWidth(width)
        self.lblOperatorKey.setFixedWidth(width)
        self.lblVotingKey.setFixedWidth(width)
        self.lblPlatformNodeId.setFixedWidth(width)
        self.lblPlatformP2PPort.setFixedWidth(width)

    def set_masternode(self, src_masternode: Optional[MasternodeConfig]):
        self.updating_ui = True
        if src_masternode:
            self.masternode.copy_from(src_masternode)
            self.masternode.modified = False
            self.validate_keys()
            self.masternode_data_to_ui(True)

    def get_masternode_data(self, dest_masternode: MasternodeConfig):
        """Copies masternode data from the internal MasternodeConfig object to dest_masternode.
          Used to get modified data and pass it to the global MasternodeConfig object.
        """
        dest_masternode.copy_from(self.masternode)

    def set_edit_mode(self, enabled: bool):
        if self.edit_mode != enabled:
            self.edit_mode = enabled
            self.masternode_data_to_ui(True if enabled else False)
            if not self.edit_mode:
                self.lblOwnerKey.setToolTip('')
                self.lblOperatorKey.setToolTip('')
                self.lblVotingKey.setToolTip('')

    def is_modified(self) -> bool:
        return self.masternode and self.masternode.modified

    def on_mn_data_modified(self):
        if self.masternode and not self.updating_ui:
            self.masternode.set_modified()
            self.data_changed.emit(self.masternode)

    @pyqtSlot(bool)
    def on_chbRoleOwner_toggled(self, checked):
        if not self.updating_ui:
            if checked:
                self.masternode.dmn_user_roles |= DMN_ROLE_OWNER
            else:
                self.masternode.dmn_user_roles &= ~DMN_ROLE_OWNER
            self.update_ui_controls_state()
            self.on_mn_data_modified()
            self.role_modified.emit()

    @pyqtSlot(bool)
    def on_chbRoleOperator_toggled(self, checked):
        if not self.updating_ui:
            if checked:
                self.masternode.dmn_user_roles |= DMN_ROLE_OPERATOR
            else:
                self.masternode.dmn_user_roles &= ~DMN_ROLE_OPERATOR
            self.update_ui_controls_state()
            self.on_mn_data_modified()
            self.role_modified.emit()

    @pyqtSlot(bool)
    def on_chbRoleVoting_toggled(self, checked):
        if not self.updating_ui:
            if checked:
                self.masternode.dmn_user_roles |= DMN_ROLE_VOTING
            else:
                self.masternode.dmn_user_roles &= ~DMN_ROLE_VOTING
            self.update_ui_controls_state()
            self.on_mn_data_modified()
            self.role_modified.emit()

    @pyqtSlot(bool)
    def on_rbMNTypeRegular_toggled(self, checked):
        if not self.updating_ui:
            if checked:
                self.masternode.masternode_type = MasternodeType.REGULAR
            self.update_ui_controls_state()
            self.on_mn_data_modified()
            self.role_modified.emit()

    @pyqtSlot(bool)
    def on_rbMNTypeHPMN_toggled(self, checked):
        if not self.updating_ui:
            if checked:
                self.masternode.masternode_type = MasternodeType.HPMN
            self.update_ui_controls_state()
            self.on_mn_data_modified()
            self.role_modified.emit()

    @pyqtSlot(str)
    def on_edtName_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.on_mn_data_modified()
            self.masternode.name = text.strip()
            self.name_modified.emit(self.masternode, text)

    @pyqtSlot(str)
    def on_edtIP_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.on_mn_data_modified()
            self.masternode.ip = text.strip()

    @pyqtSlot(str)
    def on_edtPort_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.on_mn_data_modified()
            self.masternode.tcp_port = int(text.strip()) if text.strip() else None

    @pyqtSlot(str)
    def on_edtCollateralAddress_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateral_address))
            self.on_mn_data_modified()
            self.masternode.collateral_address = text.strip()
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralPath_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateral_bip32_path))
            self.on_mn_data_modified()
            self.masternode.collateral_bip32_path = text.strip()
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralTxHash_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            update_ui = ((not text) != (not self.masternode.collateral_tx))
            self.on_mn_data_modified()
            self.masternode.collateral_tx = text.strip()
            if update_ui:
                self.update_ui_controls_state()

    @pyqtSlot(str)
    def on_edtCollateralTxIndex_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.on_mn_data_modified()
            self.masternode.collateral_tx_index = text.strip()

    @pyqtSlot(str)
    def on_edtDMNTxHash_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            self.on_mn_data_modified()
            self.masternode.protx_hash = text.strip()

    @pyqtSlot(bool)
    def on_btnGetMNDataByIP_clicked(self, _):
        if self.masternode and not self.updating_ui:
            if not (self.masternode.ip and self.masternode.tcp_port):
                WndUtils.error_msg('Enter the masternode IP address and TCP port number.')
                return

            cache_max_age = 500
            self.dashd_intf.get_masternodelist('json', data_max_age=cache_max_age, protx_data_max_age=cache_max_age)
            mn = self.masternode
            updated_fields = []

            ip_port = mn.ip + ':' + str(mn.tcp_port)
            mn_info = self.dashd_intf.masternodes_by_ip_port.get(ip_port)
            modified = False
            keys_modified = []
            if mn_info:
                if mn_info.protx:
                    protx = mn_info.protx
                    if mn.collateral_address != protx.collateral_address:
                        updated_fields.append('collateral address')
                        # self.edtCollateralAddress.setText(protx.collateral_address)
                        mn.collateral_address = protx.collateral_address
                        modified = True

                    if mn.protx_hash != protx.protx_hash:
                        updated_fields.append('protx hash')
                        # self.edtDMNTxHash.setText(protx.protx_hash)
                        self.masternode.protx_hash = protx.protx_hash
                        modified = True

                    if mn.collateral_tx != protx.collateral_hash or str(mn.collateral_tx_index) != \
                            str(protx.collateral_index):
                        updated_fields.append('collateral hash/index')
                        # self.edtCollateralTxHash.setVisible(protx.collateral_hash)
                        mn.collateral_tx = protx.collateral_hash
                        # self.edtCollateralTxIndex.setText(str(protx.collateral_index))
                        mn.collateral_tx_index = str(protx.collateral_index)
                        modified = True

                    if mn.dmn_user_roles & DMN_ROLE_OWNER > 0 and \
                            ((not mn.owner_private_key and mn.owner_key_type == InputKeyType.PRIVATE) or
                             (not mn.owner_address and mn.owner_key_type == InputKeyType.PUBLIC)):
                        mn.owner_key_type = InputKeyType.PUBLIC
                        mn.owner_address = protx.owner_address
                        modified = True
                        keys_modified.append('owner')

                    if mn.dmn_user_roles & DMN_ROLE_OPERATOR > 0 and \
                            ((not mn.operator_private_key and mn.operator_key_type == InputKeyType.PRIVATE) or
                             (not mn.operator_public_key and mn.operator_key_type == InputKeyType.PUBLIC)):
                        mn.operator_key_type = InputKeyType.PUBLIC
                        mn.operator_public_key = protx.pubkey_operator
                        modified = True
                        keys_modified.append('operator')

                    if mn.dmn_user_roles & DMN_ROLE_VOTING > 0 and \
                            ((not mn.voting_private_key and mn.voting_key_type == InputKeyType.PRIVATE) or
                             (not mn.voting_address and mn.voting_key_type == InputKeyType.PUBLIC)):
                        mn.voting_key_type = InputKeyType.PUBLIC
                        mn.voting_address = protx.voting_address
                        modified = True
                        keys_modified.append('voting')

                if modified:
                    self.masternode_data_to_ui()
                    self.on_mn_data_modified()
                    self.app_text_message_sent.emit(
                        DispMessage.OTHER_1, 'The following mn data has been set: ' + ', '.join(updated_fields),
                        AppTextMessageType.INFO)

                    if keys_modified:
                        self.app_text_message_sent.emit(
                            DispMessage.OTHER_2,
                            'We\'ve set <b>public</b> keys for ' + ', '.join(keys_modified) +
                            '. You need to enter <b>private</b> keys instead, to have access to some of the features.',
                            AppTextMessageType.WARN)
            else:
                WndUtils.warn_msg(
                    'Couldn\'t find this masternode in the list of registered deterministic masternodes.')

    @pyqtSlot(bool)
    def on_btnBip32PathToAddress_clicked(self, checked):
        if self.masternode.collateral_bip32_path:
            if self.hw_session.connect_hardware_wallet():
                try:
                    addr = hw_intf.get_address(self.hw_session, self.masternode.collateral_bip32_path,
                                               show_display=True)
                    if addr:
                        self.masternode.collateral_address = addr.strip()
                        self.edtCollateralAddress.setText(addr.strip())
                        self.on_mn_data_modified()
                        self.update_ui_controls_state()
                except CancelException:
                    pass

    @pyqtSlot(bool)
    def on_btnShowCollateralPathAddress_clicked(self, checked):
        if self.masternode.collateral_bip32_path:
            try:
                if self.hw_session.connect_hardware_wallet():
                    addr = hw_intf.get_address(
                        self.hw_session, self.masternode.collateral_bip32_path, True,
                        f'Displaying address for the BIP32 path <b>{self.masternode.collateral_bip32_path}</b>.'
                        f'<br>Click the confirmation button on your device.')
            except CancelException:
                pass

    @pyqtSlot(str)
    def on_edtOwnerKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                self.masternode.owner_private_key = text.strip()
            else:
                self.masternode.owner_address = text.strip()
            self.validate_keys()
            self.update_dynamic_labels()
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtOperatorKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                self.masternode.operator_private_key = text.strip()
            else:
                self.masternode.operator_public_key = text.strip()
            self.validate_keys()
            self.update_dynamic_labels()
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtVotingKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                self.masternode.voting_private_key = text.strip()
            else:
                self.masternode.voting_address = text.strip()
            self.validate_keys()
            self.update_dynamic_labels()
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtPlatformNodeId_textChanged(self, text):
        if self.masternode and not self.updating_ui:
            self.masternode.platform_node_id = text.strip()
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtPlatformP2PPort_textChanged(self, text):
        if self.masternode and not self.updating_ui:
            _t = text.strip()
            self.masternode.platform_p2p_port = int(_t) if _t else None
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtPlatformHTTPPort_textChanged(self, text):
        if self.masternode and not self.updating_ui:
            _t = text.strip()
            self.masternode.platform_http_port = int(_t) if _t else None
            self.on_mn_data_modified()

    def validate_keys(self):
        self.owner_key_invalid = False
        self.operator_key_invalid = False
        self.voting_key_invalid = False

        if self.masternode:
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                if self.masternode.owner_private_key:
                    self.owner_key_invalid = not dash_utils.validate_wif_privkey(self.masternode.owner_private_key,
                                                                                 self.app_config.dash_network)
            else:
                if self.masternode.owner_address:
                    self.owner_key_invalid = not dash_utils.validate_address(self.masternode.owner_address,
                                                                             self.app_config.dash_network)

            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                if self.masternode.operator_private_key:
                    self.operator_key_invalid = not dash_utils.validate_bls_privkey(
                        self.masternode.operator_private_key)
            else:
                if self.masternode.operator_public_key:
                    self.operator_key_invalid = not dash_utils.validate_bls_pubkey(
                        self.masternode.operator_public_key)

            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                if self.masternode.voting_private_key:
                    self.voting_key_invalid = not dash_utils.validate_wif_privkey(
                        self.masternode.voting_private_key,
                        self.app_config.dash_network)
            else:
                if self.masternode.voting_address:
                    self.voting_key_invalid = not dash_utils.validate_address(self.masternode.voting_address,
                                                                              self.app_config.dash_network)

    def generate_priv_key(self, pk_type: str, edit_control: QLineEdit, compressed: bool):
        if edit_control.text():
            if WndUtils.query_dlg(
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
    def on_btnGenerateOwnerPrivateKey_clicked(self, checked):
        if self.masternode:
            pk = self.generate_priv_key('owner', self.edtOwnerKey, True)
            if pk:
                self.masternode.owner_private_key = pk
                self.btnShowOwnerPrivateKey.setChecked(True)
                self.on_mn_data_modified()

    @pyqtSlot(bool)
    def on_btnGenerateOperatorPrivateKey_clicked(self, checked):
        if self.masternode:

            pk = self.generate_priv_key('operator', self.edtOperatorKey, True)
            if pk:
                self.masternode.operator_private_key = pk
                self.btnShowOperatorPrivateKey.setChecked(True)
                self.on_mn_data_modified()

    @pyqtSlot(bool)
    def on_btnGenerateVotingPrivateKey_clicked(self, checked):
        if self.masternode:
            pk = self.generate_priv_key('voting', self.edtVotingKey, True)
            if pk:
                self.masternode.voting_private_key = pk
                self.btnShowVotingPrivateKey.setChecked(True)
                self.on_mn_data_modified()

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

                self.masternode.collateral_address = utxo.address
                self.edtCollateralAddress.setText(utxo.address)
                self.masternode.collateral_bip32_path = utxo.bip32_path
                self.edtCollateralPath.setText(utxo.bip32_path)
                self.masternode.collateral_tx = utxo.txid
                self.edtCollateralTxHash.setText(utxo.txid)
                self.masternode.collateral_tx_index = str(utxo.output_index)
                self.edtCollateralTxIndex.setText(str(utxo.output_index))
                self.update_ui_controls_state()
                self.on_mn_data_modified()

            if self.masternode.masternode_type == MasternodeType.REGULAR:
                dash_value_to_find = 1000
            else:
                dash_value_to_find = 4000

            address = self.edtCollateralAddress.text()
            if self.edtCollateralTxHash.text():
                # If there is any value in the collateral tx edit box, don't automatically apply the possible
                # result (if only one UTXO was found). We want to prevent the user from missing the fact, that
                # the value has been replaced with another
                auto_apply_result = False
            else:
                auto_apply_result = True

            found = WalletUtxosListDlg.select_utxo_from_wallet_dialog(
                self, dash_value_to_find, self.app_config, self.dashd_intf,
                address, self.hw_session, apply_utxo, auto_apply_result)

            if not found:
                msg = f'Could not find any UTXO of {dash_value_to_find} Dash value'
                if address:
                    msg += f' assigned to address {address}.'
                else:
                    msg += ' in your wallet.'
                WndUtils.warn_msg(msg)

        except Exception as e:
            WndUtils.error_msg(str(e))

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

    @pyqtSlot()
    def on_btnCopyOwnerKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtOwnerKey.text())

    @pyqtSlot()
    def on_btnCopyVotingKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtVotingKey.text())

    @pyqtSlot()
    def on_btnCopyOperatorKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtOperatorKey.text())

    @pyqtSlot()
    def on_btnCopyProtxHash_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtDMNTxHash.text())

    @pyqtSlot()
    def on_btnCopyPlatformId_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtPlatformNodeId.text())

    @pyqtSlot()
    def on_copy_platform_node_as_pkcs8_base64_triggered(self):
        try:
            if self.masternode and self.masternode.platform_node_id_private_key:
                priv: Ed25519PrivateKey = dash_utils.parse_ed25519_private_key(
                    self.masternode.platform_node_id_private_key)
                priv_bytes = priv.private_bytes(cryptography.hazmat.primitives.serialization.Encoding.DER,
                                                cryptography.hazmat.primitives.serialization.PrivateFormat.PKCS8,
                                                cryptography.hazmat.primitives.serialization.NoEncryption())
                priv_str = base64.b64encode(priv_bytes).decode('ascii')
                cl = QApplication.clipboard()
                cl.setText(priv_str)
            else:
                WndUtils.warn_msg('Your Platform Node Id has not been entered into the configuraions as an Ed25519 '
                                  'private key.')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot()
    def on_copy_platform_node_as_pkcs8_der_triggered(self):
        try:
            if self.masternode and self.masternode.platform_node_id_private_key:
                priv: Ed25519PrivateKey = dash_utils.parse_ed25519_private_key(
                    self.masternode.platform_node_id_private_key)
                priv_bytes = priv.private_bytes(cryptography.hazmat.primitives.serialization.Encoding.DER,
                                                cryptography.hazmat.primitives.serialization.PrivateFormat.PKCS8,
                                                cryptography.hazmat.primitives.serialization.NoEncryption())
                priv_str = priv_bytes.hex()
                cl = QApplication.clipboard()
                cl.setText(priv_str)
            else:
                WndUtils.warn_msg('Your Platform Node Id has not been entered into the configuraions as an Ed25519 '
                                  'private key.')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot()
    def on_copy_platform_node_as_pkcs8_pem_triggered(self):
        try:
            if self.masternode and self.masternode.platform_node_id_private_key:
                priv: Ed25519PrivateKey = dash_utils.parse_ed25519_private_key(
                    self.masternode.platform_node_id_private_key)
                priv_bytes = priv.private_bytes(cryptography.hazmat.primitives.serialization.Encoding.PEM,
                                                cryptography.hazmat.primitives.serialization.PrivateFormat.PKCS8,
                                                cryptography.hazmat.primitives.serialization.NoEncryption())
                priv_str = priv_bytes.decode('ascii')
                cl = QApplication.clipboard()
                cl.setText(priv_str)
            else:
                WndUtils.warn_msg('Your Platform Node Id has not been entered into the configuraions as an Ed25519 '
                                  'private key.')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot()
    def on_copy_platform_node_as_raw_hex_triggered(self):
        try:
            if self.masternode and self.masternode.platform_node_id_private_key:
                priv: Ed25519PrivateKey = dash_utils.parse_ed25519_private_key(
                    self.masternode.platform_node_id_private_key)
                priv_bytes = priv.private_bytes(cryptography.hazmat.primitives.serialization.Encoding.Raw,
                                                cryptography.hazmat.primitives.serialization.PrivateFormat.Raw,
                                                cryptography.hazmat.primitives.serialization.NoEncryption())
                priv_str = priv_bytes.hex()
                cl = QApplication.clipboard()
                cl.setText(priv_str)
            else:
                WndUtils.warn_msg('Your Platform Node Id has not been entered into the configuraions as an Ed25519 '
                                  'private key.')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnGetPlatformNodeIdFromPrivate_clicked(self, checked):
        if self.masternode:
            key_str, ok = QInputDialog.getMultiLineText(self, "Enter ED25519 private key",
                                                        "Enter ED25519 private key (PEM/DER/base64):")

            if ok:
                try:
                    public_key = dash_utils.ed25519_private_key_to_pubkey(key_str)
                    platform_id = dash_utils.ed25519_public_key_to_platform_id(public_key)
                except Exception as e:
                    WndUtils.error_msg(str(e))
                    return

                if self.edtPlatformNodeId.text() != platform_id:
                    if self.edtPlatformNodeId.text():
                        if WndUtils.query_dlg(
                                f'This will overwrite the current Platform Node Id value. Do you really want to proceed?',
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Yes, icon=QMessageBox.Warning) != QMessageBox.Yes:
                            return

                    self.edtPlatformNodeId.setText(platform_id)

    @pyqtSlot()
    def on_btnPlatformP2PPortSetDefault_clicked(self):
        if self.edtPlatformP2PPort.text() != str(dash_utils.DASH_PLATFORM_DEFAULT_P2P_PORT):
            self.edtPlatformP2PPort.setText(str(dash_utils.DASH_PLATFORM_DEFAULT_P2P_PORT))
            self.on_mn_data_modified()

    @pyqtSlot()
    def on_btnPlatformHTTPPortSetDefault_clicked(self):
        if self.edtPlatformHTTPPort.text() != str(dash_utils.DASH_PLATFORM_DEFAULT_HTTP_PORT):
            self.edtPlatformHTTPPort.setText(str(dash_utils.DASH_PLATFORM_DEFAULT_HTTP_PORT))
            self.on_mn_data_modified()
