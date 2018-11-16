#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-11
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QDialog

from app_config import MasternodeConfig, AppConfig
from dash_utils import generate_bls_privkey, generate_privkey
from ui import ui_reg_masternode_dlg
from wnd_utils import WndUtils


class RegMasternodeDlg(QDialog, ui_reg_masternode_dlg.Ui_RegMasternodeDlg, WndUtils):
    def __init__(self, parent, config: AppConfig, masternode: MasternodeConfig):
        QDialog.__init__(self, parent)
        ui_reg_masternode_dlg.Ui_RegMasternodeDlg.__init__(self)
        WndUtils.__init__(self, parent.config)
        self.masternode = masternode
        self.app_config = config
        self.style = '<style>.info{color:darkblue} .warning{color:red} .error{background-color:red;color:white}</style>'
        self.operator_reward_saved = None
        self.operator_pkey_old: str = None
        self.voting_pkey_old: str = None
        self.operator_pkey_generated: str = None
        self.voting_pkey_generated: str = None
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
        self.update_ctrl_state()
        self.update_messages()

    def generate_keys(self):
        """ Generate new operator and voting keys if were not provided before."""
        if not self.operator_pkey_old:
            k = generate_bls_privkey()
            k_bin = k.serialize()
            self.operator_pkey_generated = k_bin.hex()
            self.edtOperatorKey.setText(self.operator_pkey_generated)

        if not self.voting_pkey_old:
            self.voting_pkey_generated = generate_privkey(self.app_config.dash_network, compressed=True)
            self.edtVotingKey.setText(self.voting_pkey_generated)

    @pyqtSlot(bool)
    def on_btnGenerateOperatorKey_clicked(self, active):
        k = generate_bls_privkey()
        pk_hex = k.serialize().hex()
        self.edtOperatorKey.setText(pk_hex)
        self.edtOperatorKey.repaint()  # qt 5.11.3 has issue with automatic repainting after setText on mac

    def set_ctrl_message(self, control, message: str, style: str):
        if message:
            control.setText(f'{self.style}<span class="{style}">{message}</span>')
            control.adjustSize()
        else:
            control.setVisible(False)

    def update_messages(self):
        self.lblIPMsg.setStyleSheet('')
        if self.edtIP.text():
            self.lblIPMsg.setText(
                f'{self.style}'
                '<span class="info">You can leave the IP address and port fields empty if you want to delegate the operator '
                'role to a hosting service and you don\'t know the IP address and port in advance (<a href=\"https\">read more</a>).'
                '</span>')
        else:
            self.lblIPMsg.setText(
                f'{self.style}'
                '<span class="warning">If don\'t set the IP address and port fields, the masternode operator will '
                'have to issue a ProUpServTx transaction using Dash wallet (<a href=\"https\">read more</a>).</span>'
                '')
        self.lblIPMsg.adjustSize()

        if self.edtPayoutAddress.text():
            msg = f'{self.style}' \
                   '<span class="info">Your owner\'s payout address can now be set to any valid Dash address - it don\'t have to be ' \
                  'the same as the address of the collateral.</span>'
        else:
            msg = f'{self.style}' \
                   '<span class="error">You have to set a valid payout address.</span>'
        self.lblPayoutMsg.setText(msg)
        self.lblPayoutMsg.adjustSize()

        if self.chbWholeMNReward.isChecked():
            msg = f'{self.style}' \
                  f'<span class="info">Here you can specify how much of the masternode earnings will go to the ' \
                  f'masternode operator.</span>'
        else:
            msg = f'{self.style}<span class="warning">The masternode operator will have to specify his ' \
                  f'reward payee address in a ProUpServTx transaction, otherwise the full reward will go to the masternode ' \
                  f'owner.</span>'
        self.lblOperatorRewardMsg.setText(msg)
        self.lblOperatorRewardMsg.adjustSize()

        if self.edtOwnerKey.text():
            if self.masternode and self.masternode.privateKey.strip() == self.edtOwnerKey.text().strip():
                msg = 'This is your old masternode private key that can be used as the owner key. Despite this, now ' \
                      'is a good opportunity to generate a new one by clicking the button on the right. ' \
                      'If you are sure that the old key has not been disclosed, you can keep it unchanged.'
            else:
                msg = 'The owner key has the highest authority to control your masternode, so keep it safe and secret.'
            style = 'info'
        else:
            msg = 'The owner key value is required.'
            style = 'error'
        self.set_ctrl_message(self.lblOwnerMsg, msg, style)

        if self.edtOperatorKey.text():
            if not self.operator_pkey_old and self.edtOperatorKey.text().strip() == self.operator_pkey_generated:
                msg = 'This is a newly generated operator BLS private key. You can generate a new one (by clicking ' \
                      'the button on the right) or you can enter your own one.'
            else:
                msg = ''
            style = 'info'
        else:
            msg = 'The operator key value is required.'
            style = 'error'
        self.set_ctrl_message(self.lblOperatorMsg, msg, style)

        if self.edtVotingKey.text():
            if not self.voting_pkey_old and self.edtVotingKey.text().strip() == self.voting_pkey_generated:
                msg = 'This is a newly generated private key for voting. You can generate a new one ' \
                      '(by pressing the button on the right) or you can enter your own one. You can also use the ' \
                      'owner key, although it is not recommended.'
            else:
                msg = ''
            style = 'info'
        else:
            msg = 'The voting key value is required.'
            style = 'error'
        self.set_ctrl_message(self.lblVotingMsg, msg, style)

    def update_ctrl_state(self):
        self.edtOperatorReward.setDisabled(self.chbWholeMNReward.isChecked())

    @pyqtSlot(str)
    def on_edtIP_textChanged(self, text):
        self.update_messages()

    @pyqtSlot(str)
    def on_edtPayoutAddress_textChanged(self, text):
        self.update_messages()

    @pyqtSlot(bool)
    def on_chbWholeMNReward_toggled(self, checked):
        if checked:
            self.operator_reward_saved = self.edtOperatorReward.value()
            self.edtOperatorReward.setValue(0.0)
        else:
            if not self.operator_reward_saved is None:
                self.edtOperatorReward.setValue(self.operator_reward_saved)
        self.update_ctrl_state()
        self.update_messages()

    @pyqtSlot(str)
    def on_edtOwnerKey_textChanged(self, text):
        self.update_messages()

    @pyqtSlot(str)
    def on_edtOperatorKey_textChanged(self, text):
        self.update_messages()

    @pyqtSlot(str)
    def on_edtVotingKey_textChanged(self, text):
        self.update_messages()