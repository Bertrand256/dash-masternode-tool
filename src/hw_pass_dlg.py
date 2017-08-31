#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from PyQt5.QtWidgets import QDialog, QLayout
from wnd_utils import WndUtils
from ui import ui_hw_pass_dlg


class HardwareWalletPassDlg(QDialog, ui_hw_pass_dlg.Ui_HardwareWalletPassDlg, WndUtils):
    def __init__(self):
        QDialog.__init__(self)
        WndUtils.__init__(self, app_config=None)
        ui_hw_pass_dlg.Ui_HardwareWalletPassDlg.__init__(self)
        self.passphrase = ''
        self.setupUi()

    def setupUi(self):
        ui_hw_pass_dlg.Ui_HardwareWalletPassDlg.setupUi(self, self)
        self.btnEnterPass.clicked.connect(self.btnEnterClick)
        self.edtPass.textChanged.connect(self.onPassChanged)
        self.edtPassConfirm.textChanged.connect(self.onPassChanged)
        self.setWindowTitle('')
        self.btnEnterPass.setEnabled(True)
        self.setWindowTitle('Hardware wallet passphrase')
        self.layout().setSizeConstraint(QLayout.SetFixedSize)

    def onPassChanged(self):
        self.btnEnterPass.setEnabled(self.edtPass.text() == self.edtPassConfirm.text())

    def btnEnterClick(self):
        self.accept()

    def getPassphrase(self):
        return self.edtPass.text()
