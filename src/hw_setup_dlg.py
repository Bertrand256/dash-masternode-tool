#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

from PyQt5.QtWidgets import QMessageBox, QDialog, QLayout
import hw_intf as hw_intf
import wnd_utils as wnd_utils
from ui import ui_hw_setup_dlg


class HwSetupDlg(QDialog, ui_hw_setup_dlg.Ui_HwSetupDlg, wnd_utils.WndUtils):
    def __init__(self, main_ui):
        QDialog.__init__(self)
        wnd_utils.WndUtils.__init__(self, main_ui.config)
        self.main_ui = main_ui
        self.main_ui.connectHardwareWallet()
        self.hw_client = self.main_ui.hw_client
        self.features = None
        self.version = '?'
        if self.hw_client:
            self.features = self.hw_client.features
            self.version = str(self.features.major_version) + '.' + str(self.features.minor_version) + '.' + \
                           str(self.features.patch_version)
        self.setupUi()

    def setupUi(self):
        ui_hw_setup_dlg.Ui_HwSetupDlg.setupUi(self, self)
        self.setWindowTitle('Hardware Wallet Setup')
        self.lblVersion.setText(self.version)
        self.btnClose.clicked.connect(self.close)
        self.btnEnDisPin.clicked.connect(self.btnEnDisPinClick)
        self.btnChangePin.clicked.connect(self.btnChangePinClick)
        self.btnEnDisPass.clicked.connect(self.btnEnDisPassClick)
        self.updateControlsState()
        self.layout().setSizeConstraint(QLayout.SetFixedSize)

    def updateControlsState(self):
        if self.hw_client:
            if self.features.pin_protection:
                self.lblPinStatus.setText('enabled')
                self.btnEnDisPin.setText('Disable')
                self.btnChangePin.setEnabled(True)
                self.lblPinStatus.setStyleSheet('QLabel{color: green}')
            else:
                self.lblPinStatus.setText('disabled')
                self.btnEnDisPin.setText('Enable')
                self.btnChangePin.setEnabled(False)
                self.lblPinStatus.setStyleSheet('QLabel{color: red}')

            if self.features.passphrase_protection:
                self.lblPassStatus.setText('enabled')
                self.lblPassStatus.setStyleSheet('QLabel{color: green}')
                self.btnEnDisPass.setText('Disable')
            else:
                self.lblPassStatus.setText('disabled')
                self.lblPassStatus.setStyleSheet('QLabel{color: red}')
                self.btnEnDisPass.setText('Enable')

    def btnEnDisPinClick(self):
        try:
            if self.hw_client:
                if self.features.pin_protection:
                    # disable
                    if self.queryDlg('Do you really want to disable PIN protection of your %s?' % self.main_ui.getHwName(),
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                     icon=QMessageBox.Warning) == QMessageBox.Yes:
                        hw_intf.change_pin(self.main_ui, remove=True)
                        self.features = self.hw_client.features
                        self.updateControlsState()
                else:
                    # enable PIN
                    hw_intf.change_pin(self.main_ui, remove=False)
                    self.features = self.hw_client.features
                    self.updateControlsState()

        except Exception as e:
            self.errorMsg(str(e))

    def btnChangePinClick(self):
        try:
            if self.hw_client and self.features.pin_protection:
                hw_intf.change_pin(self.main_ui, remove=False)
                self.features = self.hw_client.features
                self.updateControlsState()

        except Exception as e:
            self.errorMsg(str(e))

    def btnEnDisPassClick(self):
        try:
            if self.hw_client:
                if self.features.passphrase_protection:
                    # disable passphrase
                    if self.queryDlg('Do you really want to disable passphrase protection of your %s?' % self.main_ui.getHwName(),
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                     icon=QMessageBox.Warning) == QMessageBox.Yes:
                        self.hw_client.apply_settings(use_passphrase=False)
                        self.features = self.hw_client.features
                        self.updateControlsState()
                else:
                    # enable passphrase
                    if self.queryDlg('Do you really want to enable passphrase protection of your %s?' % self.main_ui.getHwName(),
                                     buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                                     icon=QMessageBox.Warning) == QMessageBox.Yes:
                        self.hw_client.apply_settings(use_passphrase=True)
                        self.features = self.hw_client.features
                        self.updateControlsState()

        except Exception as e:
            self.errorMsg(str(e))
