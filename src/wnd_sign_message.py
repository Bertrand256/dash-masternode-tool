#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import base64
from src import wnd_sign_message_base
from src.hw_intf import sign_message
import src.wnd_utils as wnd_utils


class Ui_DialogSignMessage(wnd_sign_message_base.Ui_DialogSignMessage, wnd_utils.WndUtils):
    def __init__(self, main_ui, bip32path, address):
        wnd_utils.WndUtils.__init__(self)
        self.main_ui = main_ui
        self.bip32path = bip32path
        self.address = address

    def setupUi(self, DialogSignMessage):
        wnd_sign_message_base.Ui_DialogSignMessage.setupUi(self, DialogSignMessage)
        self.window = DialogSignMessage
        self.window.setWindowTitle('Sign message')
        self.btnSignMessage.clicked.connect(self.btnSignMessageClick)
        self.btnClose.clicked.connect(self.window.close)
        self.lblSigningAddress.setText(self.address)

    def btnSignMessageClick(self):
        try:
            msg_to_sign = self.edtMessageToSign.toPlainText()
            if msg_to_sign:
                sig = sign_message(self.main_ui, self.bip32path, msg_to_sign)
                signed = base64.b64encode(sig.signature)
                # hex_message = binascii.hexlify(sig.signature).decode('base64')
                self.edtSignedMessage.setPlainText(signed.decode('ascii'))
                if sig.address != self.address:
                    self.warnMsg('Message signed but signing address (%s) for BIP32 path (%s) differs from '
                                 'required one: %s\n\nDid you enter correct passphrase?' % (sig.address, self.bip32path, self.address))
            else:
                self.errorMsg('Empty message to sign.')

        except Exception as e:
            self.errorMsg(str(e))

