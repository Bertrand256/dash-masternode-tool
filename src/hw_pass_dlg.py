#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from PyQt5.QtWidgets import QDialog, QLayout
from wnd_utils import WndUtils
from ui import ui_hw_pass_dlg


class HardwareWalletPassDlg(QDialog, ui_hw_pass_dlg.Ui_HardwareWalletPassDlg, WndUtils):
    def __init__(self, pass_available_on_device: bool):
        QDialog.__init__(self)
        WndUtils.__init__(self, app_config=None)
        ui_hw_pass_dlg.Ui_HardwareWalletPassDlg.__init__(self)
        self.passphrase = ''
        self.enter_on_device = False
        self.pass_available_on_device = pass_available_on_device
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        ui_hw_pass_dlg.Ui_HardwareWalletPassDlg.setupUi(self, self)
        self.btnEnterPass.clicked.connect(self.btnEnterClick)
        self.btnEnterOnDevice.clicked.connect(self.btnEnterOnDeviceClick)
        self.edtPass.textChanged.connect(self.onPassChanged)
        self.edtPassConfirm.textChanged.connect(self.onPassChanged)
        self.setWindowTitle('')
        self.btnEnterPass.setEnabled(True)
        self.setWindowTitle('Hardware wallet passphrase')
        self.layout().setSizeConstraint(QLayout.SetFixedSize)
        if not self.pass_available_on_device:
            self.btnEnterOnDevice.hide()

    def onPassChanged(self):
        self.btnEnterPass.setEnabled(self.edtPass.text() == self.edtPassConfirm.text())

    def btnEnterClick(self):
        self.accept()

    def btnEnterOnDeviceClick(self):
        self.enter_on_device = True
        self.accept()

    def getPassphrase(self):
        if self.enter_on_device:
            raise Exception('Enter on device clicked')
        else:
            return self.edtPass.text()

    def getEnterOnDevice(self):
        return self.enter_on_device