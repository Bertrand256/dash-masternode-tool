#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QMessageBox, QDialog, QLayout
import hw_intf as hw_intf
import wnd_utils as wnd_utils
from app_defs import HWType
from ui import ui_hw_setup_dlg


class HwSetupDlg(QDialog, ui_hw_setup_dlg.Ui_HwSetupDlg, wnd_utils.WndUtils):
    def __init__(self, main_ui):
        QDialog.__init__(self)
        wnd_utils.WndUtils.__init__(self, main_ui.app_config)
        self.main_ui = main_ui
        self.main_ui.connect_hardware_wallet()
        self.hw_session = self.main_ui.hw_session
        self.version = '?'
        self.pin_protection = None
        self.passphrase_protection = None
        if self.hw_session and  self.hw_session.hw_client:
            self.version = hw_intf.get_hw_firmware_version(self.main_ui.hw_session)
            self.read_hw_features()
        self.setupUi()

    def setupUi(self):
        ui_hw_setup_dlg.Ui_HwSetupDlg.setupUi(self, self)
        self.setWindowTitle('Hardware Wallet Setup')
        self.lblVersion.setText(self.version)
        self.updateControlsState()
        if self.main_ui.app_config.hw_type == HWType.ledger_nano_s:
            self.lblMessage.setVisible(True)
        else:
            self.lblMessage.setVisible(False)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)

    def updateControlsState(self):
        if self.hw_session and self.hw_session.hw_client:
            if self.pin_protection is True:
                self.lblPinStatus.setText('enabled')
                self.btnEnDisPin.setText('Disable')
                self.btnChangePin.setEnabled(True)
                self.lblPinStatus.setStyleSheet('QLabel{color: green}')
            elif self.pin_protection is False:
                self.lblPinStatus.setText('disabled')
                self.btnEnDisPin.setText('Enable')
                self.btnChangePin.setEnabled(False)
                self.lblPinStatus.setStyleSheet('QLabel{color: red}')
            else:
                self.lblPinStatus.setVisible(False)
                self.lblPinStatusLabel.setVisible(False)
                self.btnEnDisPin.setVisible(False)
                self.btnChangePin.setVisible(False)

            if self.passphrase_protection is True:
                self.lblPassStatus.setText('enabled')
                self.lblPassStatus.setStyleSheet('QLabel{color: green}')
                self.btnEnDisPass.setText('Disable')
            elif self.passphrase_protection is False:
                self.lblPassStatus.setText('disabled')
                self.lblPassStatus.setStyleSheet('QLabel{color: red}')
                self.btnEnDisPass.setText('Enable')
            else:
                self.lblPassStatus.setVisible(False)
                self.lblPassStatusLabel.setVisible(False)
                self.lblPassStatus.setVisible(False)
                self.btnEnDisPass.setVisible(False)

    def read_hw_features(self):
        if self.main_ui.app_config.hw_type in (HWType.trezor, HWType.keepkey):
            features = self.hw_session.hw_client.features
            self.pin_protection = features.pin_protection
            self.passphrase_protection = features.passphrase_protection

    @pyqtSlot()
    def on_btnEnDisPin_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client:
                if self.pin_protection is True:
                    # disable
                    if self.queryDlg('Do you really want to disable PIN protection of your %s?' % self.main_ui.getHwName(),
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                     icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.change_pin(self.main_ui.hw_session, remove=True)
                        self.read_hw_features()
                        self.updateControlsState()
                elif self.pin_protection is False:
                    # enable PIN
                    hw_intf.change_pin(self.main_ui.hw_session, remove=False)
                    self.read_hw_features()
                    self.updateControlsState()

        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot()
    def on_btnChangePin_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client and self.pin_protection is True:
                hw_intf.change_pin(self.main_ui.hw_session, remove=False)
                self.read_hw_features()
                self.updateControlsState()

        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot()
    def on_btnEnDisPass_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client:
                if self.passphrase_protection is True:
                    # disable passphrase
                    if self.queryDlg('Do you really want to disable passphrase protection of your %s?' % self.main_ui.getHwName(),
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                     icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.enable_passphrase(self.hw_session, passphrase_enabled=False)
                        self.read_hw_features()
                        self.updateControlsState()
                elif self.passphrase_protection is False:
                    # enable passphrase
                    if self.queryDlg('Do you really want to enable passphrase protection of your %s?' % self.main_ui.getHwName(),
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                     icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.enable_passphrase(self.hw_session, passphrase_enabled=True)
                        self.read_hw_features()
                        self.updateControlsState()

        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()
