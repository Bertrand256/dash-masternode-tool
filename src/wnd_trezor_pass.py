#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from src.wnd_utils import WndUtils
from src import wnd_trezor_pass_base


class Ui_DialogTrezorPin(wnd_trezor_pass_base.Ui_DialogTrezorPass, WndUtils):
    def __init__(self, message):
        super().__init__()
        self.passphrase = ''

    def setupUi(self, Window):
        self.window = Window
        wnd_trezor_pass_base.Ui_DialogTrezorPass.setupUi(self, Window)
        self.btnEnterPass.clicked.connect(self.btnEnterClick)
        self.edtPass.textChanged.connect(self.onPassChanged)
        self.edtPassConfirm.textChanged.connect(self.onPassChanged)
        self.window.setWindowTitle('')
        self.btnEnterPass.setEnabled(False)

    def onPassChanged(self):
        self.btnEnterPass.setEnabled(self.edtPass.text() == self.edtPassConfirm.text())

    def btnEnterClick(self):
        self.window.accept()

    def getPassphrase(self):
        return self.edtPass.text()
