#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import base64
from PyQt5.QtWidgets import QDialog
import wnd_utils as wnd_utils
import hw_intf
from app_defs import HWType
from ui import ui_sign_message_dlg
import logging
from hw_common import HardwareWalletCancelException


class SignMessageDlg(QDialog, ui_sign_message_dlg.Ui_SignMessageDlg, wnd_utils.WndUtils):
    def __init__(self, main_ui, bip32path, address):
        QDialog.__init__(self, parent=main_ui)
        wnd_utils.WndUtils.__init__(self, main_ui.config)
        self.main_ui = main_ui
        self.bip32path = bip32path
        self.address = address
        self.setupUi()

    def setupUi(self):
        ui_sign_message_dlg.Ui_SignMessageDlg.setupUi(self, self)
        self.setWindowTitle('Sign message')
        self.btnSignMessage.clicked.connect(self.btnSignMessageClick)
        self.btnClose.clicked.connect(self.close)
        self.lblSigningAddress.setText(self.address)

    def btnSignMessageClick(self):
        try:
            msg_to_sign = self.edtMessageToSign.toPlainText()
            if msg_to_sign:
                # for ledger HW check if the message contains non-ascii characters
                if self.main_ui.config.hw_type == HWType.ledger_nano_s:
                    try:
                        msg_to_sign.encode('ascii')
                    except UnicodeEncodeError:
                        self.warnMsg('Ledger wallets cannot sign non-ASCII and non-printable characters. Please '
                                     'remove them from your message and try again.')
                        return
                    if len(msg_to_sign) > 140:
                        self.warnMsg('Ledger wallets cannot sign messages longer than 140 characters. Please '
                                     'remove any extra characters and try again.')
                        return

                sig = hw_intf.hw_sign_message(self.main_ui.hw_session, self.bip32path, msg_to_sign)
                signed = base64.b64encode(sig.signature)
                # hex_message = binascii.hexlify(sig.signature).decode('base64')
                self.edtSignedMessage.setPlainText(signed.decode('ascii'))
                if sig.address != self.address:
                    self.warnMsg('Message signed but signing address (%s) for BIP32 path (%s) differs from '
                                 'required one: %s\n\nDid you enter correct passphrase?' % (sig.address, self.bip32path, self.address))
            else:
                self.errorMsg('Empty message cannot be signed.')

        except HardwareWalletCancelException:
            logging.warning('HardwareWalletCancelException')

        except Exception as e:
            logging.exception('Sign message exception:')
            self.errorMsg(str(e))

