import base64
import logging
from typing import Callable, Optional, Literal, cast

import bitcoin
from PyQt5 import QtCore
from PyQt5.QtCore import pyqtSlot, Qt, QTimer
from PyQt5.QtGui import QTextDocument
from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QInputDialog, QMessageBox, QAction, QApplication, QActionGroup
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import cryptography.hazmat.primitives.serialization

import dash_utils
import hw_intf
from app_config import MasternodeConfig, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, DMN_ROLE_VOTING, InputKeyType, AppConfig, \
    MasternodeType, MasternodeTypeMap
from app_defs import DispMessage, AppTextMessageType
from bip44_wallet import Bip44Wallet, BreakFetchTransactionsException
from common import CancelException
from dashd_intf import DashdInterface, Masternode
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
        self.masternode: MasternodeConfig = MasternodeConfig()  # temporary object to avoid changing attributes of the global
        # mn object, since user has the ability to cancel editing
        self.updating_ui = False
        self.edit_mode = False
        self.owner_key_invalid = False
        self.operator_key_invalid = False
        self.operator_pubkey_is_legacy = False
        self.voting_key_invalid = False
        self.platform_node_key_invalid = False
        self.setupUi(self)

    def setupUi(self, widget: QWidget):
        ui_masternode_details_wdg.Ui_WdgMasternodeDetails.setupUi(self, self)
        WndUtils.set_icon(self.parent, self.btnShowOwnerPrivateKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnShowOperatorPrivateKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnShowVotingPrivateKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnShowPlatformNodeKey, 'eye@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyOwnerKey, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyOperatorKey, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyVotingKey, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyProtxHash, 'content-copy@16px.png')
        WndUtils.set_icon(self.parent, self.btnCopyPlatformNodeKey, 'content-copy@16px.png')
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

        # # Copy Platform Node Id as ...:
        self.act_view_as_platform_node_private_key_tenderdash = QAction('View as Tenderdash private key', self)
        self.act_view_as_platform_node_private_key_tenderdash.setData('privkey_tenderdash')
        self.act_view_as_platform_node_private_key_tenderdash.triggered.connect(
            self.on_platform_node_view_key_type_changed)
        self.act_view_as_platform_node_id = QAction('View as Platform Node Id', self)
        self.act_view_as_platform_node_id.setData('platform_node_id')
        self.act_view_as_platform_node_id.triggered.connect(self.on_platform_node_view_key_type_changed)
        self.act_view_as_platform_node_private_key_pkcs8_base64 = QAction('View as PKCS8/base64 private key', self)
        self.act_view_as_platform_node_private_key_pkcs8_base64.setData('privkey_pkcs8_base64')
        self.act_view_as_platform_node_private_key_pkcs8_base64.triggered.connect(
            self.on_platform_node_view_key_type_changed)
        self.act_view_as_platform_node_private_key_pkcs8_pem = QAction('View as PKCS8/PEM private key', self)
        self.act_view_as_platform_node_private_key_pkcs8_pem.setData('privkey_pkcs8_pem')
        self.act_view_as_platform_node_private_key_pkcs8_pem.triggered.connect(
            self.on_platform_node_view_key_type_changed)
        self.act_view_as_platform_node_private_key_pkcs8_der = QAction('View as PKCS8/DER private key', self)
        self.act_view_as_platform_node_private_key_pkcs8_der.setData('privkey_pkcs8_der')
        self.act_view_as_platform_node_private_key_pkcs8_der.triggered.connect(
            self.on_platform_node_view_key_type_changed)
        self.act_view_as_platform_node_private_key_raw = QAction('View as RAW/HEX private key', self)
        self.act_view_as_platform_node_private_key_raw.setData('privkey_raw')
        self.act_view_as_platform_node_private_key_raw.triggered.connect(
            self.on_platform_node_view_key_type_changed)

        self.ag_platform_node_key = QActionGroup(self)
        self.act_view_as_platform_node_private_key_tenderdash.setCheckable(True)
        self.act_view_as_platform_node_id.setCheckable(True)
        self.act_view_as_platform_node_private_key_pkcs8_base64.setCheckable(True)
        self.act_view_as_platform_node_private_key_pkcs8_pem.setCheckable(True)
        self.act_view_as_platform_node_private_key_pkcs8_der.setCheckable(True)
        self.act_view_as_platform_node_private_key_raw.setCheckable(True)
        self.act_view_as_platform_node_private_key_tenderdash.setActionGroup(self.ag_platform_node_key)
        self.act_view_as_platform_node_id.setActionGroup(self.ag_platform_node_key)
        self.act_view_as_platform_node_private_key_pkcs8_base64.setActionGroup(self.ag_platform_node_key)
        self.act_view_as_platform_node_private_key_pkcs8_pem.setActionGroup(self.ag_platform_node_key)
        self.act_view_as_platform_node_private_key_pkcs8_der.setActionGroup(self.ag_platform_node_key)
        self.act_view_as_platform_node_private_key_raw.setActionGroup(self.ag_platform_node_key)
        self.btnShowPlatformNodeKey.addActions((self.act_view_as_platform_node_private_key_tenderdash,
                                                self.act_view_as_platform_node_id,
                                                self.act_view_as_platform_node_private_key_pkcs8_base64,
                                                self.act_view_as_platform_node_private_key_pkcs8_pem,
                                                self.act_view_as_platform_node_private_key_pkcs8_der,
                                                self.act_view_as_platform_node_private_key_raw))

        self.update_ui_controls_state()

    def showEvent(self, QShowEvent):
        def apply():
            self.update_key_controls_state()
            self.lblOwnerKey.fontMetrics()
            self.set_buttons_height()

        QTimer.singleShot(100, apply)

    def set_buttons_height(self):
        h = self.edtName.height()
        self.btnCopyProtxHash.setFixedHeight(h)
        self.btnCopyOwnerKey.setFixedHeight(h)
        self.btnShowOwnerPrivateKey.setFixedHeight(h)
        self.btnGenerateOwnerPrivateKey.setFixedHeight(h)
        self.btnCopyOperatorKey.setFixedHeight(h)
        self.btnShowOperatorPrivateKey.setFixedHeight(h)
        self.btnShowPlatformNodeKey.setFixedHeight(h)
        self.btnGenerateOperatorPrivateKey.setFixedHeight(h)
        self.btnCopyVotingKey.setFixedHeight(h)
        self.btnShowVotingPrivateKey.setFixedHeight(h)
        self.btnGenerateVotingPrivateKey.setFixedHeight(h)
        self.btnGetMNDataByIP.setFixedHeight(h)
        self.btnShowCollateralPathAddress.setFixedHeight(h)
        self.btnBip32PathToAddress.setFixedHeight(h)
        self.btnLocateCollateral.setFixedHeight(h)
        self.btnCopyPlatformNodeKey.setFixedHeight(h)
        self.btnGeneratePlatformNodePrivateKey.setFixedHeight(h)
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
        self.lblOwnerKeyMsg.setVisible(self.masternode is not None and
                                       (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0) and
                                       self.owner_key_invalid)
        self.edtOwnerKey.setVisible(self.masternode is not None and
                                    (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnShowOwnerPrivateKey.setVisible(self.masternode is not None and
                                               self.edit_mode is False and
                                               (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.btnCopyOwnerKey.setVisible(self.masternode is not None and
                                        (self.masternode.dmn_user_roles & DMN_ROLE_OWNER > 0))
        self.lblOperatorKey.setVisible(self.masternode is not None and
                                       (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.lblOperatorKeyMsg.setVisible(self.masternode is not None and
                                         (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0) and
                                          (self.operator_key_invalid or self.operator_pubkey_is_legacy))
        self.edtOperatorKey.setVisible(self.masternode is not None and
                                       (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.btnShowOperatorPrivateKey.setVisible(self.masternode is not None and
                                                  self.edit_mode is False and
                                                  (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.btnCopyOperatorKey.setVisible(self.masternode is not None and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.lblVotingKey.setVisible(self.masternode is not None and
                                     (self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0))
        self.lblVotingKeyMsg.setVisible(self.masternode is not None and
                                        (self.masternode.dmn_user_roles & DMN_ROLE_VOTING > 0) and
                                        self.voting_key_invalid)
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
        self.lblPlatformNodeKey.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.EVO) and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.edtPlatformNodeKey.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.EVO) and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.btnCopyPlatformNodeKey.setVisible(self.masternode is not None and
                                               (self.masternode.masternode_type == MasternodeType.EVO) and
                                               (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.btnShowPlatformNodeKey.setVisible(self.masternode is not None and
                                               self.edit_mode is False and
                                               (self.masternode.masternode_type == MasternodeType.EVO) and
                                               (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.lblPlatformNodeMsg.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.EVO) and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0) and
                                           self.platform_node_key_invalid)

        # Platform P2P port
        self.lblPlatformP2PPort.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.EVO) and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.edtPlatformP2PPort.setVisible(self.masternode is not None and
                                           (self.masternode.masternode_type == MasternodeType.EVO) and
                                           (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))

        # Platform HTTP port
        self.lblPlatformHTTPPort.setVisible(self.masternode is not None and
                                            (self.masternode.masternode_type == MasternodeType.EVO) and
                                            (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))
        self.edtPlatformHTTPPort.setVisible(self.masternode is not None and
                                            (self.masternode.masternode_type == MasternodeType.EVO) and
                                            (self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0))

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

        self.btnGeneratePlatformNodePrivateKey.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.platform_node_key_type == InputKeyType.PRIVATE and
            self.masternode.masternode_type == MasternodeType.EVO and
            self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0)

        self.btnPlatformP2PPortSetDefault.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.masternode_type == MasternodeType.EVO and
            self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0)

        self.btnPlatformHTTPPortSetDefault.setVisible(
            self.masternode is not None and self.edit_mode and
            self.masternode.masternode_type == MasternodeType.EVO and
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
        self.edtPlatformNodeKey.setReadOnly(self.edit_mode is False)
        self.edtPlatformP2PPort.setReadOnly(self.edit_mode is False)
        self.edtPlatformHTTPPort.setReadOnly(self.edit_mode is False)
        self.btnGenerateOwnerPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateOperatorPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGenerateVotingPrivateKey.setEnabled(self.edit_mode is True)
        self.btnGeneratePlatformNodePrivateKey.setEnabled(self.edit_mode is True)
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
            elif style == 'error':
                color = 'color:red'
            elif style == 'warning':
                color = 'background-color:#ff9900'
            else:
                color = ''
            return color

        def set_label_text(lbl_control: QLabel, msg_control: QLabel, key_desc_prefix: str, cur_key_type: str,
                           tooltip_anchor: str, menu_group: Optional[QActionGroup], style: str,
                           error_msg: Optional[str] = None, error_msg_style: Optional[str] = 'error'):
            change_mode = ''
            if self.edit_mode and tooltip_anchor:
                change_mode = f'<td>(<a href="{tooltip_anchor}">use {tooltip_anchor}</a>)</td>'
            elif menu_group:
                a = menu_group.checkedAction()
                if a:
                    cur_key_type = a.data()
                change_mode = ''

            if cur_key_type == 'privkey':
                lbl = key_desc_prefix + ' private key'
            elif cur_key_type == 'address':
                lbl = key_desc_prefix + ' Dash address'
            elif cur_key_type == 'pubkey':
                lbl = key_desc_prefix + ' public key'
            elif cur_key_type == 'pubkeyhash':
                lbl = key_desc_prefix + ' public key hash'
            elif cur_key_type in ('privkey_tenderdash', 'privkey_pkcs8_base64', 'privkey_pkcs8_pem',
                                  'privkey_pkcs8_der', 'privkey_raw'):
                lbl = key_desc_prefix + ' key'
            elif cur_key_type == 'platform_node_id':
                lbl = key_desc_prefix + ' id'
            else:
                lbl = key_desc_prefix

            if error_msg:
                err_text = f'<span style="{style_to_color(error_msg_style)}">' + error_msg + '</span>'
            else:
                err_text = ''

            lbl_text = f'<table style="float:right;{style_to_color(style)}"><tr><td>{lbl}</td>{change_mode}' \
                       f'</tr></table>'
            lbl_control.setText(lbl_text)

            if msg_control:
                msg_control.setText(err_text)

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

            err_msg = ''
            if self.owner_key_invalid:
                if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                    err_msg = 'Invalid owner private key format'
                else:
                    err_msg = 'Invalid owner Dash address format'
            set_label_text(self.lblOwnerKey, self.lblOwnerKeyMsg, 'Owner', key_type, tooltip_anchor,
                           self.ag_owner_key, style, err_msg)
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

            err_msg = ''
            if self.operator_key_invalid:
                if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                    err_msg = 'Invalid operator private key format'
                else:
                    err_msg = 'Invalid operator public key format'
            set_label_text(self.lblOperatorKey, self.lblOperatorKeyMsg, 'Operator', key_type, tooltip_anchor,
                           self.ag_operator_key, style, err_msg)
            self.edtOperatorKey.setPlaceholderText(placeholder_text)

            if not err_msg and self.masternode.operator_key_type == InputKeyType.PUBLIC and \
                    self.operator_pubkey_is_legacy:
                err_msg = 'Legacy operator public key'
                set_label_text(self.lblOperatorKey, self.lblOperatorKeyMsg, 'Operator', key_type, tooltip_anchor,
                               self.ag_operator_key, style, err_msg, error_msg_style='warning')

            style = ''
            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey', 'address', 'Enter the voting private key')
                if not self.edit_mode and not self.act_view_as_voting_private_key.isChecked():
                    style = 'hl2'
            else:
                key_type, tooltip_anchor, placeholder_text = ('address', 'privkey', 'Enter the voting Dash address')
                if not self.edit_mode:
                    style = 'hl1' if self.act_view_as_voting_public_address.isChecked() else 'hl2'

            err_msg = ''
            if self.voting_key_invalid:
                if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                    err_msg = 'Invalid voting private key format'
                else:
                    err_msg = 'Invalid voting Dash address format'
            set_label_text(self.lblVotingKey, self.lblVotingKeyMsg, 'Voting', key_type, tooltip_anchor,
                           self.ag_voting_key, style, err_msg)
            self.edtVotingKey.setPlaceholderText(placeholder_text)

            style = ''
            if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                key_type, tooltip_anchor, placeholder_text = ('privkey_tenderdash', 'node id',
                                                              'Enter the Platform Node key')
                if not self.edit_mode and not self.act_view_as_platform_node_private_key_tenderdash.isChecked():
                    style = 'hl2'
            else:
                key_type, tooltip_anchor, placeholder_text = ('platform_node_id', 'privkey',
                                                              'Enter the Platform Node id')
                if not self.edit_mode:
                    style = 'hl1' if self.act_view_as_platform_node_id.isChecked() else 'hl2'

            err_msg = ''
            if self.platform_node_key_invalid:
                if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                    err_msg = 'Invalid Platform Node key format (sould be Ed25519)'
                else:
                    err_msg = 'Invalid Plarform Node Id format'
            set_label_text(self.lblPlatformNodeKey, self.lblPlatformNodeMsg, 'Platform Node', key_type,
                           tooltip_anchor, self.ag_platform_node_key, style, err_msg)
            self.edtPlatformNodeKey.setPlaceholderText(placeholder_text)

            self.set_left_label_width(self.get_max_left_label_width())

    def update_key_controls_state(self):
        self.edtOwnerKey.setEchoMode(QLineEdit.Normal if self.btnShowOwnerPrivateKey.isChecked() or
                                                         self.edit_mode else QLineEdit.Password)

        self.edtOperatorKey.setEchoMode(QLineEdit.Normal if self.btnShowOperatorPrivateKey.isChecked() or
                                                            self.edit_mode else QLineEdit.Password)

        self.edtVotingKey.setEchoMode(QLineEdit.Normal if self.btnShowVotingPrivateKey.isChecked() or
                                                          self.edit_mode else QLineEdit.Password)

        self.edtPlatformNodeKey.setEchoMode(QLineEdit.Normal if self.btnShowPlatformNodeKey.isChecked() or
                                                                self.edit_mode else QLineEdit.Password)
        self.update_dynamic_labels()

    def masternode_data_to_ui(self, reset_key_view_type: bool = False):
        if self.masternode:
            self.updating_ui = True
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

            if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                self.act_view_as_platform_node_private_key_tenderdash.setChecked(True)
            else:
                self.act_view_as_platform_node_id.setChecked(True)

            if reset_key_view_type:
                self.btnShowOwnerPrivateKey.setChecked(False)
                self.btnShowOperatorPrivateKey.setChecked(False)
                self.btnShowVotingPrivateKey.setChecked(False)
                self.btnShowPlatformNodeKey.setChecked(False)
                self.btnShowPlatformNodeKey.setChecked(False)

            self.chbRoleOwner.setChecked(self.masternode.dmn_user_roles & DMN_ROLE_OWNER)
            self.chbRoleOperator.setChecked(self.masternode.dmn_user_roles & DMN_ROLE_OPERATOR)
            self.chbRoleVoting.setChecked(self.masternode.dmn_user_roles & DMN_ROLE_VOTING)
            self.rbMNTypeRegular.setChecked(self.masternode.masternode_type == MasternodeType.REGULAR)
            self.rbMNTypeHPMN.setChecked(self.masternode.masternode_type == MasternodeType.EVO)
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
            platform_key = self.get_platform_key_to_display()
            self.edtPlatformNodeKey.setText(platform_key)
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
                            ret = self.masternode.get_operator_pubkey(
                                self.app_config.feature_new_bls_scheme.get_value())
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

    def get_platform_key_to_display(self) -> str:
        ret = ''
        if self.masternode:
            if self.edit_mode:
                if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                    ret = self.masternode.get_platform_node_private_key_for_editing()
                else:
                    ret = self.masternode.voting_address
            else:
                try:
                    if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                        if self.masternode.platform_node_private_key:
                            if self.act_view_as_platform_node_private_key_tenderdash.isChecked():
                                ret = dash_utils.ed25519_private_key_to_tenderdash(
                                    self.masternode.platform_node_private_key)
                            elif self.act_view_as_platform_node_id.isChecked():
                                ret = dash_utils.ed25519_private_key_to_platform_node_id(
                                    self.masternode.platform_node_private_key)
                            elif self.act_view_as_platform_node_private_key_raw.isChecked():
                                ret = dash_utils.ed25519_private_key_to_raw_hex(
                                    self.masternode.platform_node_private_key)
                            elif self.act_view_as_platform_node_private_key_pkcs8_pem.isChecked():
                                ret = dash_utils.ed25519_private_key_to_pkcs8_pem(
                                    self.masternode.platform_node_private_key)
                            elif self.act_view_as_platform_node_private_key_pkcs8_der.isChecked():
                                ret = dash_utils.ed25519_private_key_to_pkcs8_der(
                                    self.masternode.platform_node_private_key)
                            elif self.act_view_as_platform_node_private_key_pkcs8_base64.isChecked():
                                ret = dash_utils.ed25519_private_key_to_pkcs8_base64(
                                    self.masternode.platform_node_private_key)
                            else:
                                ret = '???'
                        else:
                            ret = ''
                    else:
                        if self.act_view_as_platform_node_id.isChecked():
                            ret = self.masternode.platform_node_id
                        else:
                            ret = '<Platform Node Id cannot be converted to a private key>'
                except Exception as e:
                    msg = str(e)
                    if not msg:
                        msg = 'Key conversion error.'
                    WndUtils.error_msg(msg, True)
        return ret

    @pyqtSlot(str)
    def on_lblOwnerKey_linkActivated(self, link):
        try:
            if self.masternode and self.edit_mode:
                state = self.edtOwnerKey.blockSignals(True)
                try:
                    if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                        self.masternode.owner_key_type = InputKeyType.PUBLIC
                        self.edtOwnerKey.setText(self.masternode.owner_address)
                        self.act_view_as_owner_private_key.setChecked(True)
                    else:
                        self.masternode.owner_key_type = InputKeyType.PRIVATE
                        self.edtOwnerKey.setText(self.masternode.owner_private_key)
                        self.act_view_as_owner_public_address.setChecked(True)
                    self.on_mn_data_modified()
                    self.validate_keys()
                    self.update_ui_controls_state()
                finally:
                    self.edtOwnerKey.blockSignals(state)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(str)
    def on_lblOperatorKey_linkActivated(self, link):
        try:
            if self.masternode and self.edit_mode:
                state = self.edtOperatorKey.blockSignals(True)
                try:
                    if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                        self.masternode.operator_key_type = InputKeyType.PUBLIC
                        self.edtOperatorKey.setText(self.masternode.operator_public_key)
                        self.act_view_as_operator_private_key.setChecked(True)
                    else:
                        self.masternode.operator_key_type = InputKeyType.PRIVATE
                        self.edtOperatorKey.setText(self.masternode.operator_private_key)
                        self.act_view_as_operator_public_key.setChecked(True)
                    self.on_mn_data_modified()
                    self.validate_keys()
                    self.update_ui_controls_state()
                finally:
                    self.edtOperatorKey.blockSignals(state)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(str)
    def on_lblVotingKey_linkActivated(self, link):
        try:
            if self.masternode and self.edit_mode:
                state = self.edtVotingKey.blockSignals(True)
                try:
                    if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                        self.masternode.voting_key_type = InputKeyType.PUBLIC
                        self.edtVotingKey.setText(self.masternode.voting_address)
                        self.act_view_as_voting_private_key.setChecked(True)
                    else:
                        self.masternode.voting_key_type = InputKeyType.PRIVATE
                        self.edtVotingKey.setText(self.masternode.voting_private_key)
                        self.act_view_as_voting_public_address.setChecked(True)
                    self.on_mn_data_modified()
                    self.validate_keys()
                    self.update_ui_controls_state()
                finally:
                    self.edtVotingKey.blockSignals(state)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(str)
    def on_lblPlatformNodeKey_linkActivated(self, link):
        try:
            if self.masternode and self.edit_mode:
                state = self.edtPlatformNodeKey.blockSignals(True)
                try:
                    if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                        self.masternode.platform_node_key_type = InputKeyType.PUBLIC
                        self.edtPlatformNodeKey.setText(self.masternode.platform_node_id)
                        self.act_view_as_platform_node_private_key_tenderdash.setChecked(True)
                    else:
                        self.masternode.platform_node_key_type = InputKeyType.PRIVATE
                        try:
                            self.edtPlatformNodeKey.setText(self.masternode.get_platform_node_private_key_for_editing())
                        except Exception as e:
                            logging.exception(str(e))
                        self.act_view_as_platform_node_id.setChecked(True)
                    self.on_mn_data_modified()
                    self.validate_keys()
                    self.update_ui_controls_state()
                finally:
                    self.edtPlatformNodeKey.blockSignals(state)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

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

    @pyqtSlot(str)
    def on_lblPlatformNodeKey_linkHovered(self, link):
        if link == 'platform node id':
            tt = 'Change input type to Platform Node id'
        else:
            tt = 'Change input type to private key'
        self.lblPlatformNodeKey.setToolTip(tt)

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
                get_lbl_text_width(self.lblVotingKey),
                get_lbl_text_width(self.lblPlatformNodeKey),
                get_lbl_text_width(self.lblPlatformP2PPort),
                get_lbl_text_width(self.lblMasternodeType))

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
        self.lblPlatformNodeKey.setFixedWidth(width)
        self.lblPlatformP2PPort.setFixedWidth(width)

    def set_masternode(self, src_masternode: Optional[MasternodeConfig]):
        self.updating_ui = True
        if src_masternode:
            self.masternode.copy_from(src_masternode)
            self.validate_keys()
            self.masternode_data_to_ui(True)

    def get_masternode_data(self, dest_masternode: MasternodeConfig):
        """Copies masternode data from the internal MasternodeConfig object to dest_masternode.
          Used to get modified data and pass it to the global MasternodeConfig object.
        """
        self.masternode.update_data_hash()
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
        return self.masternode and self.masternode.is_modified()

    def on_mn_data_modified(self):
        if self.masternode and not self.updating_ui:
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
                self.masternode.masternode_type = MasternodeType.EVO
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
        try:
            if self.masternode and not self.updating_ui:
                self.on_mn_data_modified()
                self.masternode.tcp_port = int(text.strip()) if text.strip() else None
        except Exception as e:
            WndUtils.error_msg('Invalid TCP port number.')

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
        try:
            if self.masternode and not self.updating_ui:
                if not (self.masternode.ip and self.masternode.tcp_port):
                    WndUtils.error_msg('Enter the masternode IP address and TCP port number.')
                    return

                cache_max_age = 500
                self.dashd_intf.get_masternodelist('json', data_max_age=cache_max_age)
                mn_cfg = self.masternode
                updated_fields = []

                ip_port = mn_cfg.ip + ':' + str(mn_cfg.tcp_port)
                mn_info: Masternode = self.dashd_intf.masternodes_by_ip_port.get(ip_port)
                modified = False
                keys_modified = []
                if mn_info:
                    if mn_cfg.collateral_address != mn_info.collateral_address:
                        updated_fields.append('collateral address')
                        mn_cfg.collateral_address = mn_info.collateral_address
                        modified = True

                    if mn_cfg.protx_hash != mn_info.protx_hash:
                        updated_fields.append('protx hash')
                        self.masternode.protx_hash = mn_info.protx_hash
                        modified = True

                    mn_type = MasternodeTypeMap.get(mn_info.type, MasternodeType.REGULAR)
                    if mn_cfg.masternode_type != mn_type:
                        updated_fields.append('mn type')
                        self.masternode.masternode_type = mn_type
                        modified = True

                    if mn_cfg.collateral_tx != mn_info.collateral_hash or str(mn_cfg.collateral_tx_index) != \
                            str(mn_info.collateral_index):
                        updated_fields.append('collateral hash/index')
                        mn_cfg.collateral_tx = mn_info.collateral_hash
                        mn_cfg.collateral_tx_index = str(mn_info.collateral_index)
                        modified = True

                    if mn_cfg.dmn_user_roles & DMN_ROLE_OWNER > 0 and \
                            ((not mn_cfg.owner_private_key and mn_cfg.owner_key_type == InputKeyType.PRIVATE) or
                             (not mn_cfg.owner_address and mn_cfg.owner_key_type == InputKeyType.PUBLIC)):
                        mn_cfg.owner_key_type = InputKeyType.PUBLIC
                        mn_cfg.owner_address = mn_info.owner_address
                        modified = True
                        keys_modified.append('owner')

                    if mn_cfg.dmn_user_roles & DMN_ROLE_OPERATOR > 0 and \
                            ((not mn_cfg.operator_private_key and mn_cfg.operator_key_type == InputKeyType.PRIVATE) or
                             (not mn_cfg.operator_public_key and mn_cfg.operator_key_type == InputKeyType.PUBLIC)):
                        mn_cfg.operator_key_type = InputKeyType.PUBLIC
                        mn_cfg.operator_public_key = mn_info.pubkey_operator
                        modified = True
                        keys_modified.append('operator')

                    if mn_cfg.dmn_user_roles & DMN_ROLE_VOTING > 0 and \
                            ((not mn_cfg.voting_private_key and mn_cfg.voting_key_type == InputKeyType.PRIVATE) or
                             (not mn_cfg.voting_address and mn_cfg.voting_key_type == InputKeyType.PUBLIC)):
                        mn_cfg.voting_key_type = InputKeyType.PUBLIC
                        mn_cfg.voting_address = mn_info.voting_address
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
                                '. You need to enter <b>private</b> keys instead, to have access to some of '
                                'the features.',
                                AppTextMessageType.WARN)
                else:
                    WndUtils.warn_msg(
                        'Couldn\'t find this masternode in the list of registered deterministic masternodes.')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

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
            self.update_ui_controls_state()
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
            self.update_ui_controls_state()
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
            self.update_ui_controls_state()
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtPlatformNodeKey_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                self.masternode.platform_node_private_key = text.strip()
            else:
                self.masternode.platform_node_id = text.strip()
            self.validate_keys()
            self.update_dynamic_labels()
            self.update_ui_controls_state()
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtPlatformP2PPort_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            _t = text.strip()
            self.masternode.platform_p2p_port = int(_t) if _t else None
            self.on_mn_data_modified()

    @pyqtSlot(str)
    def on_edtPlatformHTTPPort_textEdited(self, text):
        if self.masternode and not self.updating_ui:
            _t = text.strip()
            self.masternode.platform_http_port = int(_t) if _t else None
            self.on_mn_data_modified()

    def validate_keys(self):
        self.owner_key_invalid = False
        self.operator_key_invalid = False
        self.operator_pubkey_is_legacy = False
        self.voting_key_invalid = False
        self.platform_node_key_invalid = False

        if self.masternode:
            if self.masternode.owner_key_type == InputKeyType.PRIVATE:
                if self.masternode.owner_private_key:
                    self.owner_key_invalid = not dash_utils.validate_wif_privkey(self.masternode.owner_private_key,
                                                                                 self.app_config.dash_network)
            else:
                if self.masternode.owner_address:
                    self.owner_key_invalid = not dash_utils.validate_address(self.masternode.owner_address,
                                                                             self.app_config.dash_network)

            new_bls_scheme = self.app_config.feature_new_bls_scheme.get_value()
            if self.masternode.operator_key_type == InputKeyType.PRIVATE:
                if self.masternode.operator_private_key:
                    self.operator_key_invalid = not dash_utils.validate_bls_privkey(
                        self.masternode.operator_private_key, new_bls_scheme)
            else:
                if self.masternode.operator_public_key:
                    self.operator_key_invalid = not dash_utils.validate_bls_pubkey(
                        self.masternode.operator_public_key, new_bls_scheme)

                    if self.operator_key_invalid and new_bls_scheme:
                        if dash_utils.validate_bls_pubkey_legacy(self.masternode.operator_public_key):
                            self.operator_key_invalid = False
                            self.operator_pubkey_is_legacy = True

            if self.masternode.voting_key_type == InputKeyType.PRIVATE:
                if self.masternode.voting_private_key:
                    self.voting_key_invalid = not dash_utils.validate_wif_privkey(
                        self.masternode.voting_private_key,
                        self.app_config.dash_network)
            else:
                if self.masternode.voting_address:
                    self.voting_key_invalid = not dash_utils.validate_address(self.masternode.voting_address,
                                                                              self.app_config.dash_network)

            if self.masternode.platform_node_key_type == InputKeyType.PRIVATE:
                if self.masternode.platform_node_private_key:
                    self.platform_node_key_invalid = not dash_utils.validate_ed25519_privkey(
                        self.masternode.platform_node_private_key)
            else:
                if self.masternode.platform_node_id:
                    self.platform_node_key_invalid = not dash_utils.validate_platform_node_id(
                        self.masternode.platform_node_id)

    def generate_priv_key(self, pk_type: Literal['operator', 'owner', 'voting', 'platform_node'],
                          edit_control: QLineEdit, compressed: bool):
        if edit_control.text():
            if WndUtils.query_dlg(
                    f'This will overwrite the current {pk_type} private key value. Do you really want to proceed?',
                    buttons=QMessageBox.Yes | QMessageBox.Cancel,
                    default_button=QMessageBox.Yes, icon=QMessageBox.Warning) != QMessageBox.Yes:
                return None

        if pk_type == 'operator':
            pk = dash_utils.generate_bls_privkey()
        elif pk_type == 'platform_node':
            pk = dash_utils.generate_ed25519_private_key()
            pk = dash_utils.ed25519_private_key_to_tenderdash(pk)
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
    def on_btnGeneratePlatformNodePrivateKey_clicked(self, checked):
        if self.masternode:
            pk = self.generate_priv_key('platform_node', self.edtPlatformNodeKey, True)
            if pk:
                self.masternode.platform_node_private_key = pk
                self.btnShowPlatformNodeKey.setChecked(True)
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
    def on_btnShowPlatformNodeKey_toggled(self, checked):
        self.edtPlatformNodeKey.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
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

    def on_platform_node_view_key_type_changed(self):
        self.btnShowPlatformNodeKey.setChecked(True)
        self.update_key_controls_state()
        self.edtPlatformNodeKey.setText(self.get_platform_key_to_display())

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
    def on_btnCopyPlatformNodeKey_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtPlatformNodeKey.text())

    @pyqtSlot()
    def on_btnCopyProtxHash_clicked(self):
        cl = QApplication.clipboard()
        cl.setText(self.edtDMNTxHash.text())

    @pyqtSlot()
    def on_btnPlatformP2PPortSetDefault_clicked(self):
        if self.edtPlatformP2PPort.text() != str(dash_utils.DASH_PLATFORM_DEFAULT_P2P_PORT):
            self.edtPlatformP2PPort.setText(str(dash_utils.DASH_PLATFORM_DEFAULT_P2P_PORT))
            self.masternode.platform_p2p_port = dash_utils.DASH_PLATFORM_DEFAULT_P2P_PORT
            self.on_mn_data_modified()

    @pyqtSlot()
    def on_btnPlatformHTTPPortSetDefault_clicked(self):
        if self.edtPlatformHTTPPort.text() != str(dash_utils.DASH_PLATFORM_DEFAULT_HTTP_PORT):
            self.edtPlatformHTTPPort.setText(str(dash_utils.DASH_PLATFORM_DEFAULT_HTTP_PORT))
            self.masternode.platform_http_port = dash_utils.DASH_PLATFORM_DEFAULT_HTTP_PORT
            self.on_mn_data_modified()
