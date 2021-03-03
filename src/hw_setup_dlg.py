#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QMessageBox, QDialog, QLayout
import hw_intf as hw_intf
import wnd_utils as wnd_utils
from hw_common import HWType
from ui import ui_hw_setup_dlg


class HwSetupDlg(QDialog, ui_hw_setup_dlg.Ui_HwSetupDlg, wnd_utils.WndUtils):
    def __init__(self, main_ui):
        QDialog.__init__(self)
        wnd_utils.WndUtils.__init__(self, main_ui.app_config)
        self.main_ui = main_ui
        self.main_ui.connect_hardware_wallet()
        self.hw_session: hw_intf.HwSessionInfo = self.main_ui.hw_session
        self.version = '?'
        self.pin_protection = None
        self.passphrase_protection = None
        self.passphrase_always_on_device = None
        self.wipe_code_protection = None  # https://wiki.trezor.io/User_manual:Wipe_code
        self.sd_protection = None  # https://wiki.trezor.io/User_manual:SD_card_protection
        self.auto_lock_delay_ms = None
        if self.hw_session and self.hw_session.hw_device:
            self.version = self.hw_session.hw_device.firmware_version
            self.read_hw_features()
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        ui_hw_setup_dlg.Ui_HwSetupDlg.setupUi(self, self)
        self.setWindowTitle('Hardware Wallet Setup')
        self.lblFirmwareVersion.setText(self.version)
        self.updateControlsState()
        if self.main_ui.app_config.hw_type == HWType.ledger_nano:
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

            if self.passphrase_always_on_device is True:
                self.lblPassAlwaysOnDeviceStatus.setText('enabled')
                self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: green}')
                self.btnEnDisPassAlwaysOnDevice.setText('Disable')
                self.btnEnDisPassAlwaysOnDevice.setEnabled(True)
            elif self.passphrase_always_on_device is False:
                self.lblPassAlwaysOnDeviceStatus.setText('disabled')
                self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: red}')
                self.btnEnDisPassAlwaysOnDevice.setText('Enable')
                self.btnEnDisPassAlwaysOnDevice.setEnabled(True)
            else:
                self.lblPassAlwaysOnDeviceStatus.setText('not available')
                self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: orange}')
                self.btnEnDisPassAlwaysOnDevice.setText('Enable')
                self.btnEnDisPassAlwaysOnDevice.setDisabled(True)

            if self.wipe_code_protection is True:
                self.lblWipeCodeStatus.setText('enabled')
                self.lblWipeCodeStatus.setStyleSheet('QLabel{color: green}')
                self.btnEnDisWipeCode.setText('Disable')
                self.btnEnDisWipeCode.setEnabled(True)
            elif self.wipe_code_protection is False:
                self.lblWipeCodeStatus.setText('disabled')
                self.lblWipeCodeStatus.setStyleSheet('QLabel{color: red}')
                self.btnEnDisWipeCode.setText('Enable')
                self.btnEnDisWipeCode.setEnabled(True)
            else:
                self.lblWipeCodeStatus.setText('not available')
                self.lblWipeCodeStatus.setStyleSheet('QLabel{color: orange}')
                self.btnEnDisWipeCode.setText('Enable')
                self.btnEnDisWipeCode.setDisabled(True)

    def read_hw_features(self):
        if self.main_ui.app_config.hw_type in (HWType.trezor, HWType.keepkey):
            features = self.hw_session.hw_client.features
            feature_names = [k for k in features.keys()]
            self.pin_protection = features.pin_protection
            self.passphrase_protection = features.passphrase_protection
            if 'passphrase_always_on_device' in feature_names:
                self.passphrase_always_on_device = features.passphrase_always_on_device
            if 'wipe_code_protection' in feature_names:
                self.wipe_code_protection = features.wipe_code_protection
            if 'sd_protection' in feature_names:
                self.sd_protection = features.sd_protection

    @pyqtSlot()
    def on_btnEnDisPin_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client:
                if self.pin_protection is True:
                    # disable
                    if self.query_dlg('Do you really want to disable PIN protection for your %s?' % self.main_ui.getHwName(),
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.change_pin(self.main_ui.hw_session.hw_client, remove=True)
                        self.read_hw_features()
                        self.updateControlsState()
                elif self.pin_protection is False:
                    # enable PIN
                    hw_intf.change_pin(self.main_ui.hw_session.hw_client, remove=False)
                    self.read_hw_features()
                    self.updateControlsState()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_btnChangePin_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client and self.pin_protection is True:
                hw_intf.change_pin(self.main_ui.hw_session.hw_client, remove=False)
                self.read_hw_features()
                self.updateControlsState()

        except Exception as e:
            self.error_msg(str(e))

    @pyqtSlot()
    def on_btnEnDisPass_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client:
                if self.passphrase_protection is True:
                    # disable passphrase
                    if self.query_dlg('Do you really want to disable passphrase protection for your %s?' % self.main_ui.getHwName(),
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.enable_passphrase(self.hw_session.hw_client, passphrase_enabled=False)
                        self.read_hw_features()
                        self.updateControlsState()
                elif self.passphrase_protection is False:
                    # enable passphrase
                    if self.query_dlg('Do you really want to enable passphrase protection for your %s?' % self.main_ui.getHwName(),
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.enable_passphrase(self.hw_session.hw_client, passphrase_enabled=True)
                        self.read_hw_features()
                        self.updateControlsState()
        except Exception as e:
            self.error_msg(str(e))

    @pyqtSlot()
    def on_btnEnDisPassAlwaysOnDevice_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client:
                if self.passphrase_always_on_device is True:
                    message = 'Do you really want to disable the "Passphrase always on device" option for your %s?'
                    new_enabled = False
                elif self.passphrase_always_on_device is False:
                    message = 'Do you really want to enable the "Passphrase always on device" option for your %s?'
                    new_enabled = True
                else:
                    return

                if self.query_dlg(message % self.main_ui.getHwName(),
                                  buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                  icon=QMessageBox.Warning) == QMessageBox.Yes:
                    hw_intf.set_passphrase_always_on_device(self.main_ui.hw_session, enabled=new_enabled)
                    self.read_hw_features()
                    self.updateControlsState()
        except Exception as e:
            self.error_msg(str(e))

    @pyqtSlot()
    def on_btnEnDisWipeCode_clicked(self):
        try:
            if self.hw_session and self.hw_session.hw_client:
                if self.wipe_code_protection is True:
                    message = 'Do you really want to disable wipe code protection for your %s?'
                    new_enabled = False
                elif self.wipe_code_protection is False:
                    message = 'Do you really want to enable wipe code protection for your %s?'
                    new_enabled = True
                else:
                    return

                if self.query_dlg(message % self.main_ui.getHwName(),
                                  buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                  icon=QMessageBox.Warning) == QMessageBox.Yes:
                    hw_intf.set_wipe_code(self.main_ui.hw_session, enabled=new_enabled)
                    self.read_hw_features()
                    self.updateControlsState()
        except Exception as e:
            self.error_msg(str(e))

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()
